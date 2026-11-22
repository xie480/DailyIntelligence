"""基础配置、数据模型和 SQLite 行为测试。"""

from __future__ import annotations

import shutil
import sqlite3
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

    def test_database_initialization_repairs_partial_v1_schema(self) -> None:
        """schema_version 为 1 时仍应补齐缺失结构并保留已有数据。"""
        self.database.initialize()
        item_id = self.database.upsert_item(
            Item(
                item_type="news",
                title="Existing item",
                url="https://example.com/existing",
                source="example",
                summary="Must survive schema repair.",
            )
        )
        self.database.connection.execute(
            "DROP INDEX idx_items_fingerprint"
        )
        self.database.connection.execute(
            "DROP TABLE feedback"
        )
        self.database.connection.commit()

        self.database.initialize()

        stored = self.database.get_item(item_id)
        self.assertIsNotNone(stored)
        self.assertEqual(stored["title"], "Existing item")
        tables = {
            row["name"]
            for row in self.database.connection.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                """
            )
        }
        self.assertIn("feedback", tables)
        indexes = {
            row["name"]
            for row in self.database.connection.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'index'
                """
            )
        }
        self.assertIn("idx_items_fingerprint", indexes)

    def test_database_enforces_foreign_keys_on_each_connection(self) -> None:
        """每个数据库连接都应启用 SQLite 外键约束。"""
        self.database.initialize()

        pragma_value = self.database.connection.execute(
            "PRAGMA foreign_keys"
        ).fetchone()[0]
        self.assertEqual(pragma_value, 1)
        with self.assertRaises(sqlite3.IntegrityError):
            self.database.connection.execute(
                """
                INSERT INTO feedback(action, item_id, created_at)
                VALUES ('like', 999999, '2026-11-21T00:00:00+00:00')
                """
            )

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
        self.database.save_repo_snapshot("acme/demo", "2026-11-14", 100, 10)
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

    def test_snapshot_growth_returns_zero_without_cutoff_baseline(self) -> None:
        """窗口内没有 cutoff 前快照时不应伪造 Star 增长。"""
        self.database.initialize()
        self.database.save_repo_snapshot("acme/recent", "2026-11-20", 100, 10)
        self.database.save_repo_snapshot("acme/recent", "2026-11-21", 135, 12)

        self.assertEqual(
            self.database.star_growth("acme/recent", 7),
            0,
        )


if __name__ == "__main__":
    unittest.main()

