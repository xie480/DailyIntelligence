"""创作者 URL、时间窗口和账号管理的行为测试。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest

from daily_intelligence.creator_service import (
    CreatorAccountService,
    CreatorUpdatesService,
    CreatorWindow,
    calculate_creator_window,
)
from daily_intelligence.creator_urls import (
    CreatorUrlError,
    parse_bilibili_url,
    parse_creator_url,
    parse_youtube_channel_url,
)
from daily_intelligence.database import Database
from daily_intelligence.collectors.creators import (
    BilibiliCollector,
    YouTubeCollector,
    parse_youtube_feed,
    sign_wbi,
)
from daily_intelligence.models import CreatorAccount, CreatorUpdate, Item
from tests.test_support import temporary_directory


UTC = timezone.utc


class CreatorFoundationTestCase(unittest.TestCase):
    """验证创作者功能的纯逻辑和 SQLite 基础行为。"""

    def setUp(self) -> None:
        """创建隔离数据库。"""
        self.runtime_tempdir = temporary_directory(
            prefix="daily-intelligence-creators-",
        )
        self.addCleanup(
            self.runtime_tempdir.cleanup,
        )
        self.database = Database(
            Path(self.runtime_tempdir.name)
            / "database"
            / "intelligence.db"
        )
        self.database.initialize()

    def tearDown(self) -> None:
        """关闭数据库连接。"""
        self.database.close()

    def test_bilibili_and_youtube_urls_are_parsed_to_stable_keys(self) -> None:
        """B 站 UID、频道 ID 和 handle 应被解析为稳定账号键。"""
        bilibili = parse_bilibili_url(
            "https://space.bilibili.com/123456?from=search"
        )
        channel = parse_youtube_channel_url(
            "https://www.youtube.com/channel/UC_example"
        )
        handle = parse_creator_url(
            "https://www.youtube.com/@ExampleChannel"
        )

        self.assertEqual(bilibili.account_key, "123456")
        self.assertEqual(bilibili.canonical_url, "https://space.bilibili.com/123456")
        self.assertEqual(channel.account_key, "UC_example")
        self.assertEqual(handle.account_key, "@ExampleChannel")
        self.assertTrue(handle.requires_resolution)

    def test_invalid_creator_url_is_rejected_without_guessing_account(self) -> None:
        """无法确认平台或账号 ID 的链接不得被错误添加。"""
        with self.assertRaises(CreatorUrlError):
            parse_creator_url("https://www.youtube.com/watch?v=video")
        with self.assertRaises(CreatorUrlError):
            parse_creator_url("https://space.bilibili.com/not-a-uid")

    def test_first_creator_window_is_limited_to_24_hours(self) -> None:
        """首次模块运行最多回溯 24 小时并使用带时区时间。"""
        end = datetime(
            2026,
            11,
            22,
            21,
            tzinfo=timezone(timedelta(hours=8)),
        )
        window = calculate_creator_window(
            window_end=end,
            global_last_success_end=None,
            account_created_at=None,
        )

        self.assertEqual(window.window_end, end.astimezone(UTC))
        self.assertEqual(
            window.window_start,
            (end - timedelta(hours=24)).astimezone(UTC),
        )

    def test_creator_window_uses_previous_success_and_account_creation(self) -> None:
        """普通运行从成功检查点开始，新账号从添加时间开始。"""
        end = datetime(
            2026,
            11,
            22,
            13,
            tzinfo=UTC,
        )
        previous = datetime(
            2026,
            11,
            21,
            13,
            tzinfo=UTC,
        )
        created = datetime(
            2026,
            11,
            22,
            8,
            tzinfo=UTC,
        )
        normal = calculate_creator_window(
            window_end=end,
            global_last_success_end=previous,
            account_created_at=created,
        )
        new_account = calculate_creator_window(
            window_end=end,
            global_last_success_end=previous,
            account_created_at=created,
            account_has_success=False,
        )

        self.assertEqual(normal.window_start, previous)
        self.assertEqual(new_account.window_start, created)
        self.assertFalse(
            CreatorWindow(
                window_start=previous,
                window_end=end,
            ).contains(previous)
        )
        self.assertTrue(
            CreatorWindow(
                window_start=previous,
                window_end=end,
            ).contains(end)
        )

    def test_creator_account_management_requires_authorization_and_is_idempotent(self) -> None:
        """账号管理只允许授权 owner，且同平台账号不能重复添加。"""
        self.database.authorize_creator_owner("qq:owner")
        service = CreatorAccountService(self.database)
        account = service.add_account(
            "https://space.bilibili.com/123456",
            owner_key="qq:owner",
            display_name="测试 UP 主",
        )

        self.assertEqual(account["account_key"], "123456")
        self.assertEqual(
            service.list_accounts("qq:owner")[0]["display_name"],
            "测试 UP 主",
        )
        with self.assertRaises(ValueError):
            service.add_account(
                "https://space.bilibili.com/123456",
                owner_key="qq:owner",
            )
        with self.assertRaises(PermissionError):
            service.list_accounts("qq:other")

        service.pause_account(
            "bilibili",
            "123456",
            owner_key="qq:owner",
        )
        self.assertEqual(
            service.list_accounts("qq:owner")[0]["status"],
            "paused",
        )
        service.resume_account(
            "bilibili",
            "123456",
            owner_key="qq:owner",
        )
        service.configure_account(
            "bilibili",
            "123456",
            owner_key="qq:owner",
            monitor_videos=True,
            monitor_dynamics=False,
        )
        self.assertFalse(
            bool(service.list_accounts("qq:owner")[0]["monitor_dynamics"])
        )

    def test_youtube_account_cannot_enable_dynamic_monitoring(self) -> None:
        """YouTube 账号只允许视频监控。"""
        self.database.authorize_creator_owner("qq:owner")
        service = CreatorAccountService(self.database)
        with self.assertRaises(ValueError):
            service.add_account(
                "https://www.youtube.com/channel/UC_example",
                owner_key="qq:owner",
                monitor_dynamics=True,
            )

    def test_v1_database_migrates_to_creator_schema_without_losing_items(self) -> None:
        """旧 v1 数据库升级后应保留项目并创建创作者表。"""
        migration_tempdir = temporary_directory(
            prefix="daily-intelligence-creator-migration-",
        )
        self.addCleanup(
            migration_tempdir.cleanup,
        )
        database_path = (
            Path(migration_tempdir.name)
            / "database"
            / "intelligence.db"
        )
        legacy = Database(database_path)
        legacy.connection.execute(
            "CREATE TABLE schema_version (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        legacy._apply_v1()
        legacy.connection.execute(
            "INSERT INTO schema_version(version, applied_at) VALUES (1, '2026-11-21T00:00:00+00:00')"
        )
        legacy.upsert_item(
            Item(
                item_type="news",
                title="Legacy item",
                url="https://example.com/legacy",
                source="legacy",
                summary="Must survive v2 migration.",
            )
        )
        legacy.close()

        upgraded = Database(database_path)
        upgraded.initialize()
        self.addCleanup(
            upgraded.close,
        )
        self.assertIsNotNone(
            upgraded.get_item(1)
        )
        tables = {
            row["name"]
            for row in upgraded.connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        self.assertIn("creator_accounts", tables)
        self.assertEqual(
            upgraded.connection.execute(
                "SELECT MAX(version) FROM schema_version"
            ).fetchone()[0],
            2,
        )


class FakeBilibiliClient:
    """为分页和动态分类测试提供可控的 Bilibili 响应。"""

    def __init__(self) -> None:
        """准备分页数据。"""
        self.video_pages = {
            1: {
                "data": {
                    "list": {
                        "vlist": [
                            {
                                "bvid": "BV_recent_1",
                                "title": "最近视频",
                                "created": 1795348800,
                                "author": "测试 UP 主",
                            },
                            {
                                "bvid": "BV_old",
                                "title": "旧视频",
                                "created": 1795000000,
                                "author": "测试 UP 主",
                            },
                        ]
                    },
                    "page": {
                        "count": 2,
                        "pages": 2,
                        "pn": 1,
                    },
                }
            },
            2: {
                "data": {
                    "list": {
                        "vlist": [
                            {
                                "bvid": "BV_recent_2",
                                "title": "第二个最近视频",
                                "created": 1795345200,
                                "author": "测试 UP 主",
                            }
                        ]
                    },
                    "page": {
                        "count": 2,
                        "pages": 2,
                        "pn": 2,
                    },
                }
            },
        }
        self.dynamic_pages = [
            {
                "data": {
                    "items": [
                        {
                            "id_str": "dynamic-forward",
                            "type": "DYNAMIC_TYPE_FORWARD",
                            "modules": {
                                "module_author": {
                                    "name": "测试 UP 主",
                                    "pub_ts": 1795347000,
                                },
                                "module_dynamic": {
                                    "desc": {
                                        "text": "转发一条消息"
                                    },
                                    "orig": {
                                        "desc": {
                                            "text": "原动态内容"
                                        }
                                    },
                                },
                            },
                        },
                        {
                            "id_str": "dynamic-draw",
                            "type": "DYNAMIC_TYPE_DRAW",
                            "modules": {
                                "module_author": {
                                    "name": "测试 UP 主",
                                    "pub_ts": 1795346000,
                                },
                                "module_dynamic": {
                                    "desc": {
                                        "text": "图片动态"
                                    },
                                    "major": {
                                        "draw": {
                                            "items": [
                                                {
                                                    "src": "https://img.example/1.jpg"
                                                }
                                            ]
                                        }
                                    },
                                },
                            },
                        },
                        {
                            "id_str": "dynamic-video",
                            "type": "DYNAMIC_TYPE_AV",
                            "modules": {
                                "module_author": {
                                    "name": "测试 UP 主",
                                    "pub_ts": 1795345000,
                                },
                                "module_dynamic": {
                                    "major": {
                                        "archive": {
                                            "bvid": "BV_recent_1"
                                        }
                                    }
                                },
                            },
                        },
                    ],
                    "has_more": False,
                }
            }
        ]

    def fetch_video_page(
        self,
        uid: str,
        page: int,
        page_size: int = 30,
    ) -> dict[str, object]:
        """返回指定页投稿。"""
        return self.video_pages.get(
            page,
            {
                "data": {
                    "list": {
                        "vlist": []
                    }
                }
            },
        )

    def fetch_dynamic_page(
        self,
        uid: str,
        offset: str = "",
    ) -> dict[str, object]:
        """返回一页动态。"""
        return self.dynamic_pages.pop(
            0
        )


class CreatorCollectorTestCase(unittest.TestCase):
    """验证平台响应解析、分页和去重。"""

    def setUp(self) -> None:
        """准备覆盖测试数据的时间窗口和账号。"""
        self.window = CreatorWindow(
            window_start=datetime(
                2026,
                11,
                21,
                0,
                tzinfo=UTC,
            ),
            window_end=datetime(
                2026,
                11,
                23,
                0,
                tzinfo=UTC,
            ),
        )
        self.account = CreatorAccount(
            platform="bilibili",
            account_key="123456",
            display_name="测试 UP 主",
            profile_url="https://space.bilibili.com/123456",
            owner_key="qq:owner",
        )

    def test_bilibili_collector_paginates_and_filters_old_videos(self) -> None:
        """投稿采集应继续翻页并只返回窗口内的 BV 号。"""
        client = FakeBilibiliClient()
        updates = BilibiliCollector(client).collect_videos(
            self.account,
            self.window,
        )

        self.assertEqual(
            [item.external_id for item in updates],
            ["BV_recent_1", "BV_recent_2"],
        )

    def test_bilibili_dynamic_collector_classifies_and_skips_video_cards(self) -> None:
        """文字、图片、转发动态应保留，视频卡片应交给视频板块。"""
        client = FakeBilibiliClient()
        updates = BilibiliCollector(client).collect_dynamics(
            self.account,
            self.window,
        )

        self.assertEqual(
            [item.external_id for item in updates],
            ["dynamic-forward", "dynamic-draw"],
        )
        self.assertEqual(updates[0].metadata["dynamic_type"], "转发动态")
        self.assertEqual(updates[1].metadata["dynamic_type"], "图片动态")
        self.assertEqual(
            updates[1].metadata["images"],
            ["https://img.example/1.jpg"],
        )

    def test_youtube_atom_feed_filters_window_and_deduplicates_video_id(self) -> None:
        """YouTube Feed 应按 Video ID 去重并过滤窗口外条目。"""
        feed = """
        <feed xmlns="http://www.w3.org/2005/Atom"
              xmlns:yt="http://www.youtube.com/xml/schemas/2015"
              xmlns:media="http://search.yahoo.com/mrss/">
          <title>Example Channel</title>
          <entry>
            <yt:videoId>video-1</yt:videoId>
            <title>New Video</title>
            <published>2026-11-21T08:00:00+00:00</published>
            <link rel="alternate" href="https://www.youtube.com/watch?v=video-1" />
            <author><name>Example Channel</name></author>
            <media:group><media:thumbnail url="https://img.example/video.jpg" /></media:group>
          </entry>
          <entry>
            <yt:videoId>video-1</yt:videoId>
            <title>Duplicate</title>
            <published>2026-11-21T08:01:00+00:00</published>
            <link rel="alternate" href="https://www.youtube.com/watch?v=video-1" />
          </entry>
          <entry>
            <yt:videoId>old-video</yt:videoId>
            <title>Old Video</title>
            <published>2026-11-20T08:00:00+00:00</published>
            <link rel="alternate" href="https://www.youtube.com/watch?v=old-video" />
          </entry>
        </feed>
        """
        updates = parse_youtube_feed(
            feed.encode("utf-8"),
            self.window,
        )

        self.assertEqual(
            [item.external_id for item in updates],
            ["video-1"],
        )
        self.assertEqual(
            updates[0].metadata["thumbnail"],
            "https://img.example/video.jpg",
        )

    def test_bilibili_wbi_signature_contains_stable_timestamp_and_digest(self) -> None:
        """WBI 签名应使用排序参数、wts 和 32 位 MD5。"""
        signed = sign_wbi(
            {
                "foo": "a b",
                "bar": "!",
            },
            "a" * 32,
            "b" * 32,
            now=1700000000,
        )

        self.assertEqual(signed["wts"], "1700000000")
        self.assertEqual(len(signed["w_rid"]), 32)
        self.assertNotIn("!", signed["w_rid"])


class FakeCreatorCollector:
    """为检查点测试提供可切换成功/失败的采集器。"""

    def __init__(self) -> None:
        """初始化动态采集失败开关。"""
        self.fail_dynamics = True

    def collect_videos(
        self,
        account: dict[str, object],
        window: CreatorWindow,
    ) -> list[CreatorUpdate]:
        """返回窗口内的一条视频。"""
        return [
            CreatorUpdate(
                platform=str(account["platform"]),
                content_type="video",
                external_id="video-1",
                creator_name=str(account["display_name"]),
                title="测试视频",
                url="https://example.com/video-1",
                published_at=(
                    window.window_end - timedelta(minutes=5)
                ).isoformat(),
            )
        ]

    def collect_dynamics(
        self,
        account: dict[str, object],
        window: CreatorWindow,
    ) -> list[CreatorUpdate]:
        """首次调用模拟接口失败，后续返回一条动态。"""
        if self.fail_dynamics:
            raise RuntimeError("dynamic endpoint unavailable")
        return [
            CreatorUpdate(
                platform="bilibili",
                content_type="dynamic",
                external_id="dynamic-1",
                creator_name=str(account["display_name"]),
                title="测试动态",
                url="https://t.bilibili.com/dynamic-1",
                published_at=(
                    window.window_end - timedelta(minutes=3)
                ).isoformat(),
                metadata={
                    "dynamic_type": "文字动态",
                },
            )
        ]


class CreatorCollectionTestCase(unittest.TestCase):
    """验证单来源失败隔离和报告保存后的检查点推进。"""

    def setUp(self) -> None:
        """创建账号和可控采集器。"""
        self.runtime_tempdir = temporary_directory(
            prefix="daily-intelligence-creator-collection-",
        )
        self.addCleanup(
            self.runtime_tempdir.cleanup,
        )
        self.database = Database(
            Path(self.runtime_tempdir.name)
            / "database"
            / "intelligence.db"
        )
        self.database.initialize()
        self.database.authorize_creator_owner("qq:owner")
        self.manager = CreatorAccountService(
            self.database
        )
        self.manager.add_account(
            "https://space.bilibili.com/123456",
            owner_key="qq:owner",
            display_name="测试 UP 主",
        )
        self.collector = FakeCreatorCollector()
        self.service = CreatorUpdatesService(
            self.database,
            bilibili_collector=self.collector,
            youtube_collector=self.collector,
        )

    def tearDown(self) -> None:
        """关闭数据库连接。"""
        self.database.close()

    def test_source_failure_does_not_advance_checkpoint_and_other_source_survives(self) -> None:
        """动态失败不能影响视频事件保存或视频来源进度。"""
        end = datetime(
            2026,
            11,
            23,
            0,
            tzinfo=UTC,
        )
        result = self.service.collect(
            window_end=end,
            run_key="creator:test-1",
        )
        account = self.database.get_creator_account(
            "bilibili",
            "123456",
        )
        assert account is not None
        video_checkpoint = self.database.get_creator_checkpoint(
            int(account["id"]),
            "video",
        )
        dynamic_checkpoint = self.database.get_creator_checkpoint(
            int(account["id"]),
            "dynamic",
        )

        self.assertEqual(result.status, "partial")
        self.assertEqual(len(result.successful), 1)
        self.assertEqual(len(result.failures), 1)
        self.assertIsNone(video_checkpoint["last_success_end"])
        self.assertEqual(dynamic_checkpoint["last_status"], "failed")
        self.assertEqual(
            len(
                self.service.report_updates(result)
            ),
            1,
        )

        self.service.finalize(
            result,
            report_saved=True,
        )
        video_checkpoint = self.database.get_creator_checkpoint(
            int(account["id"]),
            "video",
        )
        dynamic_checkpoint = self.database.get_creator_checkpoint(
            int(account["id"]),
            "dynamic",
        )
        self.assertEqual(
            video_checkpoint["last_success_end"],
            end.isoformat(),
        )
        self.assertIsNone(dynamic_checkpoint["last_success_end"])
        self.assertEqual(
            self.database.get_creator_global_last_success_end(),
            end.isoformat(),
        )

    def test_report_failure_keeps_checkpoint_and_retry_is_idempotent(self) -> None:
        """报告未落盘时不推进检查点，重试不会产生重复事件。"""
        end = datetime(
            2026,
            11,
            23,
            0,
            tzinfo=UTC,
        )
        first = self.service.collect(
            window_end=end,
            run_key="creator:test-2",
        )
        self.service.finalize(
            first,
            report_saved=False,
        )
        account = self.database.get_creator_account(
            "bilibili",
            "123456",
        )
        assert account is not None
        checkpoint = self.database.get_creator_checkpoint(
            int(account["id"]),
            "video",
        )
        self.assertIsNone(checkpoint["last_success_end"])

        self.collector.fail_dynamics = False
        second = self.service.collect(
            window_end=end,
            run_key="creator:test-3",
        )
        self.assertEqual(second.status, "success")
        self.assertEqual(
            self.database.connection.execute(
                "SELECT COUNT(*) FROM creator_events"
            ).fetchone()[0],
            2,
        )
        self.service.finalize(
            second,
            report_saved=True,
        )
        self.assertEqual(
            self.database.get_creator_global_last_success_end(),
            end.isoformat(),
        )


if __name__ == "__main__":
    unittest.main()
