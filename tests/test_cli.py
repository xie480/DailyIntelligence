"""Python CLI 参数和核心命令测试。"""

from __future__ import annotations

import io
import json
import shutil
import unittest
import uuid
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path

from daily_intelligence.cli import DEFAULT_SOURCES, build_parser, main
from daily_intelligence.config import RuntimePaths
from daily_intelligence.database import Database
from daily_intelligence.models import Item


class CLITestCase(unittest.TestCase):
    """验证 CLI 能在指定运行目录下完成基本操作。"""

    def setUp(self) -> None:
        """创建隔离 CLI 运行目录。"""
        self.runtime_dir = (
            Path.cwd()
            / ".test-tmp"
            / f"cli-{uuid.uuid4().hex}"
        )
        self.runtime_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        """删除隔离 CLI 运行目录。"""
        shutil.rmtree(
            self.runtime_dir,
            ignore_errors=True,
        )

    def test_parser_accepts_global_data_directory_and_timezone(self) -> None:
        """全局参数应在子命令前指定运行目录和时区。"""
        parser = build_parser()

        args = parser.parse_args(
            [
                "--data-dir",
                str(self.runtime_dir),
                "--timezone",
                "UTC",
                "init-db",
            ]
        )

        self.assertEqual(
            args.data_dir,
            str(self.runtime_dir),
        )
        self.assertEqual(args.timezone, "UTC")
        self.assertEqual(args.command, "init-db")

    def test_parser_accepts_data_directory_after_subcommand(self) -> None:
        """每个顶层命令也应支持在子命令后指定运行目录。"""
        parser = build_parser()

        args = parser.parse_args(
            [
                "init-db",
                "--data-dir",
                str(self.runtime_dir),
            ]
        )

        self.assertEqual(
            args.data_dir,
            str(self.runtime_dir),
        )

    def test_init_feedback_profile_and_report_commands(self) -> None:
        """初始化、反馈、查看画像和指定日期日报应可连续执行。"""
        common = [
            "--data-dir",
            str(self.runtime_dir),
        ]

        self.assertEqual(
            main(
                common
                + [
                    "init-db",
                ]
            ),
            0,
        )
        self.assertTrue(
            (
                self.runtime_dir
                / "logs"
                / "daily-intelligence.log"
            ).is_file()
        )
        self.assertEqual(
            main(
                common
                + [
                    "feedback",
                    "多关注 MCP",
                ]
            ),
            0,
        )
        output = io.StringIO()
        with redirect_stdout(output):
            result = main(
                common
                + [
                    "profile",
                    "show",
                    "--json",
                ]
            )
        self.assertEqual(result, 0)
        profile = json.loads(output.getvalue())
        self.assertGreaterEqual(
            profile["interests"]["MCP"],
            90,
        )
        self.assertEqual(
            main(
                common
                + [
                    "report",
                    "--date",
                    "2026-11-21",
                    "--no-record",
                ]
            ),
            0,
        )
        self.assertTrue(
            (
                self.runtime_dir
                / "reports"
                / "2026-11-21.md"
            ).is_file()
        )

    def test_dry_run_does_not_need_network(self) -> None:
        """dry-run 应使用内置样例并输出可读日报。"""
        output = io.StringIO()
        with redirect_stdout(output):
            result = main(
                [
                    "--data-dir",
                    str(self.runtime_dir),
                    "dry-run",
                ]
            )

        self.assertEqual(result, 0)
        self.assertIn(
            "Daily Intelligence 日报",
            output.getvalue(),
        )
        self.assertFalse(
            (
                self.runtime_dir
                / "database"
                / "intelligence.db"
            ).exists()
        )

    def test_default_sources_match_example_config(self) -> None:
        """CLI 默认采集源应与示例配置保持一致。"""
        example_path = (
            Path(__file__).resolve().parents[1]
            / "config"
            / "sources.example.json"
        )
        example = json.loads(
            example_path.read_text(
                encoding="utf-8"
            )
        )

        self.assertEqual(
            DEFAULT_SOURCES,
            example,
        )

    def test_report_same_date_is_idempotent_for_recommendation_history(
        self,
    ) -> None:
        """同一报告日期重复执行不应追加相同的推荐历史。"""
        paths = RuntimePaths.from_data_dir(self.runtime_dir)
        paths.ensure()
        database = Database(paths.database_path)
        database.initialize()
        database.upsert_item(
            Item(
                item_type="github",
                title="acme/report-runtime",
                url="https://github.com/acme/report-runtime",
                source="GitHub Search API",
                summary="Agent runtime used for report idempotency.",
                category="AI Agent",
                repo_full_name="acme/report-runtime",
                metadata={
                    "section": "github_hot",
                    "latest_release": {
                        "published_at": datetime.now(
                            timezone.utc,
                        ).isoformat(),
                    },
                },
            )
        )
        database.close()

        common = [
            "--data-dir",
            str(self.runtime_dir),
        ]
        report_arguments = [
            "report",
            "--date",
            "2026-11-22",
        ]
        self.assertEqual(
            main(common + report_arguments),
            0,
        )
        report_path = (
            self.runtime_dir
            / "reports"
            / "2026-11-22.md"
        )
        first_report = report_path.read_text(encoding="utf-8")
        database = Database(paths.database_path)
        database.initialize()
        first_feedback_count = len(
            database.list_feedback(
                action="recommended",
                limit=100,
            )
        )
        database.close()

        self.assertEqual(
            first_feedback_count,
            1,
        )
        self.assertEqual(
            main(common + report_arguments),
            0,
        )
        second_report = report_path.read_text(encoding="utf-8")
        database = Database(paths.database_path)
        database.initialize()
        second_feedback_count = len(
            database.list_feedback(
                action="recommended",
                limit=100,
            )
        )
        database.close()

        self.assertEqual(
            second_feedback_count,
            first_feedback_count,
        )
        self.assertEqual(
            second_report,
            first_report,
        )

    def test_report_does_not_record_filtered_rss_supplement(self) -> None:
        """被日报过滤的 RSS 补充项不应写入推荐历史。"""
        paths = RuntimePaths.from_data_dir(self.runtime_dir)
        paths.ensure()
        database = Database(paths.database_path)
        database.initialize()
        database.upsert_item(
            Item(
                item_type="news",
                title="Filtered RSS supplement",
                url="https://example.com/filtered-supplement",
                source="Example RSS",
                summary="A seven day supplement outside the report window.",
                category="ai",
                metadata={
                    "is_primary": False,
                    "is_supplement": True,
                    "is_major_supplement": False,
                },
            )
        )
        database.close()

        self.assertEqual(
            main(
                [
                    "--data-dir",
                    str(self.runtime_dir),
                    "report",
                    "--date",
                    "2026-11-22",
                ]
            ),
            0,
        )
        report_path = (
            self.runtime_dir
            / "reports"
            / "2026-11-22.md"
        )
        report = report_path.read_text(encoding="utf-8")
        database = Database(paths.database_path)
        database.initialize()
        feedback_count = len(
            database.list_feedback(
                action="recommended",
                limit=100,
            )
        )
        database.close()

        self.assertNotIn(
            "Filtered RSS supplement",
            report,
        )
        self.assertEqual(
            feedback_count,
            0,
        )


if __name__ == "__main__":
    unittest.main()

