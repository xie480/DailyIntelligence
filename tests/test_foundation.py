"""基础配置、数据模型和 SQLite 行为测试。"""

from __future__ import annotations

import shutil
import unittest
import uuid
from pathlib import Path

from daily_intelligence.config import RuntimePaths
from daily_intelligence.database import Database
from daily_intelligence.models import Item


class FoundationTestCase(unittest.TestCase):
    """为基础设施测试提供隔离的临时运行目录。"""

    def setUp(self) -> None:
        """创建当前测试独占的临时目录。"""
        self.runtime_dir = (
            Path.cwd()
            / ".test-tmp"
            / f"foundation-{uuid.uuid4().hex}"
        )
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.paths = RuntimePaths.from_data_dir(self.runtime_dir)
        self.database = Database(self.paths.database_path)

    def tearDown(self) -> None:
        """关闭数据库并释放临时目录。"""
        self.database.close()
        shutil.rmtree(
            self.runtime_dir,
            ignore_errors=True,
        )

    def test_runtime_paths_create_separated_directories(self) -> None:
        """运行目录应把数据库、画像、日报和日志分开。"""
        self.paths.ensure()

        self.assertTrue(self.paths.database_path.parent.is_dir())
        self.assertTrue(self.paths.profile_path.parent.is_dir())
        self.assertTrue(self.paths.reports_dir.is_dir())
        self.assertTrue(self.paths.logs_dir.is_dir())
        self.assertNotEqual(self.paths.data_dir, Path.cwd())

    def test_database_migration_is_idempotent_and_upsert_is_stable(self) -> None:
        """数据库重复初始化和同 URL 写入都应保持幂等。"""
        self.database.initialize()
        self.database.initialize()
        item = Item(
            item_type="news",
            title="A release",
            url="https://example.com/a?utm_source=test",
            source="example",
            published_at="2026-11-21T08:00:00+00:00",
            summary="A useful release.",
            category="software",
        )

        first_id = self.database.upsert_item(item)
        second_id = self.database.upsert_item(
            item.with_updates(summary="Updated summary.")
        )

        self.assertEqual(first_id, second_id)
        stored = self.database.get_item(first_id)
        self.assertIsNotNone(stored)
        self.assertEqual(stored["summary"], "Updated summary.")
        self.assertEqual(self.database.count_items(), 1)

    def test_run_guard_allows_retry_after_failure(self) -> None:
        """成功运行不可重复执行，失败运行允许恢复重试。"""
        self.database.initialize()

        self.assertTrue(self.database.begin_run("rss", "rss:2026-11-21"))
        self.assertFalse(self.database.begin_run("rss", "rss:2026-11-21"))
        self.database.finish_run("rss:2026-11-21", "failed", "network error")
        self.assertTrue(self.database.begin_run("rss", "rss:2026-11-21"))
        self.database.finish_run("rss:2026-11-21", "success")
        self.assertFalse(self.database.begin_run("rss", "rss:2026-11-21"))

    def test_snapshot_growth_and_feedback_history(self) -> None:
        """Star 快照应返回增量，反馈应保留结构化记录。"""
        self.database.initialize()
        self.database.save_repo_snapshot("acme/demo", "2026-11-20", 100, 10)
        self.database.save_repo_snapshot("acme/demo", "2026-11-21", 135, 12)

        self.assertEqual(self.database.star_growth("acme/demo", 7), 35)
        feedback_id = self.database.save_feedback(
            action="like",
            target="acme/demo",
            note="用户明确喜欢项目",
            signal={"topic": "Agent"},
        )

        self.assertIsInstance(feedback_id, int)
        history = self.database.list_feedback(limit=5)
        self.assertEqual(history[0]["action"], "like")
        self.assertEqual(history[0]["signal"]["topic"], "Agent")


if __name__ == "__main__":
    unittest.main()

