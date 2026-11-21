"""Python CLI 参数和核心命令测试。"""

from __future__ import annotations

import io
import json
import shutil
import unittest
import uuid
from contextlib import redirect_stdout
from pathlib import Path

from daily_intelligence.cli import build_parser, main


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


if __name__ == "__main__":
    unittest.main()

