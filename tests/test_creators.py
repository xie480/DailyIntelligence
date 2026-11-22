"""创作者 URL、时间窗口和账号管理的行为测试。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest

from daily_intelligence.creator_service import (
    CreatorAccountService,
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


if __name__ == "__main__":
    unittest.main()
