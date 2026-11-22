"""项目级环境变量配置的离线测试。"""

from __future__ import annotations

import os
import shutil
import subprocess
import unittest
import uuid
from pathlib import Path

from daily_intelligence.config import (
    DotEnvError,
    load_project_settings,
    parse_env_file,
    resolve_project_root,
)


class ProjectConfigTestCase(unittest.TestCase):
    """验证项目 `.env` 解析、优先级和凭证安全边界。"""

    def setUp(self) -> None:
        """创建不依赖系统临时目录的隔离项目目录。"""
        self.project_root = (
            Path.cwd()
            / ".test-tmp"
            / f"config-{uuid.uuid4().hex}"
        )
        self.project_root.mkdir(
            parents=True,
            exist_ok=True,
        )

    def tearDown(self) -> None:
        """删除隔离项目目录。"""
        shutil.rmtree(
            self.project_root,
            ignore_errors=True,
        )

    def test_parse_env_supports_quotes_comments_blank_lines_and_crlf(
        self,
    ) -> None:
        """解析器应支持引号、注释、空行和 Windows 换行。"""
        env_path = self.project_root / ".env"
        env_path.write_bytes(
            b"\r\n"
            b"# ignored comment\r\n"
            b" GITHUB_TOKEN = 'single-quoted-token' # trailing comment\r\n"
            b"DOUBLE_QUOTED=\"double-quoted-value\"\r\n"
            b"PLAIN=value # inline comment\r\n"
        )

        values = parse_env_file(env_path)

        self.assertEqual(
            values,
            {
                "GITHUB_TOKEN": "single-quoted-token",
                "DOUBLE_QUOTED": "double-quoted-value",
                "PLAIN": "value",
            },
        )

    def test_process_environment_overrides_project_env(self) -> None:
        """当前进程变量应覆盖项目 `.env`，包括显式空值。"""
        (self.project_root / ".env").write_text(
            "GITHUB_TOKEN=file-token\n"
            "FILE_ONLY=file-value\n",
            encoding="utf-8",
        )

        settings = load_project_settings(
            self.project_root,
            {
                "GITHUB_TOKEN": "process-token",
                "PROCESS_ONLY": "process-value",
            },
        )
        self.assertEqual(
            settings.github_token,
            "process-token",
        )
        self.assertEqual(
            settings.variables["FILE_ONLY"],
            "file-value",
        )
        self.assertEqual(
            settings.variables["PROCESS_ONLY"],
            "process-value",
        )

        empty_process_token = load_project_settings(
            self.project_root,
            {
                "GITHUB_TOKEN": "",
            },
        )
        self.assertIsNone(
            empty_process_token.github_token,
        )

    def test_missing_env_file_falls_back_to_empty_settings(self) -> None:
        """项目 `.env` 缺失时应返回匿名配置而不是抛异常。"""
        settings = load_project_settings(
            self.project_root,
            {},
        )

        self.assertEqual(
            settings.env_path,
            self.project_root / ".env",
        )
        self.assertIsNone(
            settings.github_token,
        )

    def test_malformed_env_error_does_not_echo_secret_value(self) -> None:
        """格式错误提示应清晰但不得回显可能的敏感值。"""
        secret = "ephemeral-config-secret"
        (self.project_root / ".env").write_text(
            f"GITHUB_TOKEN {secret}\n",
            encoding="utf-8",
        )

        with self.assertRaises(DotEnvError) as context:
            load_project_settings(
                self.project_root,
                {},
            )

        self.assertIn(
            ".env",
            str(context.exception),
        )
        self.assertNotIn(
            secret,
            str(context.exception),
        )

    def test_default_project_root_is_based_on_config_module_location(self) -> None:
        """默认项目根目录应来自源码位置而不是当前工作目录。"""
        self.assertEqual(
            resolve_project_root(),
            Path(__file__).resolve().parents[1],
        )

    def test_env_files_are_ignored_except_example(self) -> None:
        """Git 应忽略本地 `.env` 并允许提交模板。"""
        repository_root = Path(__file__).resolve().parents[1]
        ignored = subprocess.run(
            [
                "git",
                "check-ignore",
                "--no-index",
                "-q",
                ".env",
            ],
            cwd=repository_root,
            env={
                key: value
                for key, value in os.environ.items()
                if not key.startswith("GIT_CONFIG_")
            },
            check=False,
        )
        self.assertEqual(
            ignored.returncode,
            0,
        )
        gitignore = (
            repository_root / ".gitignore"
        ).read_text(
            encoding="utf-8",
        ).splitlines()
        self.assertIn(
            ".env",
            gitignore,
        )
        self.assertIn(
            ".env.*",
            gitignore,
        )
        self.assertIn(
            "!.env.example",
            gitignore,
        )


if __name__ == "__main__":
    unittest.main()
