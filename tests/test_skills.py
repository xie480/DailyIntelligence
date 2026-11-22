"""本地 Hermes Skill 目录和元数据检查。"""

from __future__ import annotations

import unittest
from pathlib import Path

from daily_intelligence.cli import build_parser


class SkillLayoutTestCase(unittest.TestCase):
    """验证本地 Skill 名称不会与 Hermes Hub 同名。"""

    def test_local_skill_uses_explicit_directory_and_metadata_name(self) -> None:
        """本地调度 Skill 应固定使用 daily-intelligence-local 名称。"""
        root = Path(__file__).resolve().parents[1]
        local_dir = root / "skills" / "daily-intelligence-local"
        old_dir = root / "skills" / "daily-intelligence"
        skill_path = local_dir / "SKILL.md"

        self.assertTrue(
            skill_path.is_file(),
        )
        self.assertFalse(
            old_dir.exists(),
        )
        text = skill_path.read_text(
            encoding="utf-8",
        )
        self.assertIn(
            "name: daily-intelligence-local",
            text,
        )
        self.assertIn(
            "E:\\YilenaCode\\DailyIntelligence\\skills\\daily-intelligence-local",
            text,
        )

    def test_all_project_skills_remain_present(self) -> None:
        """重命名调度 Skill 时其他三个 Skill 应保持可用。"""
        root = Path(__file__).resolve().parents[1]
        for name in (
            "daily-intelligence-local",
            "dailyintelligence-creators",
            "github-radar",
            "tech-news-radar",
            "interest-profile",
        ):
            with self.subTest(name=name):
                self.assertTrue(
                    (
                        root
                        / "skills"
                        / name
                        / "SKILL.md"
                    ).is_file()
                )

    def test_workflow_documents_native_search_and_json_handoff(self) -> None:
        """Skill 文档应写明真实 Web 工具、交接命令和失败状态。"""
        root = Path(__file__).resolve().parents[1]
        local_text = (
            root
            / "skills"
            / "daily-intelligence-local"
            / "SKILL.md"
        ).read_text(encoding="utf-8")
        news_text = (
            root
            / "skills"
            / "tech-news-radar"
            / "SKILL.md"
        ).read_text(encoding="utf-8")
        github_text = (
            root
            / "skills"
            / "github-radar"
            / "SKILL.md"
        ).read_text(encoding="utf-8")
        profile_text = (
            root
            / "skills"
            / "interest-profile"
            / "SKILL.md"
        ).read_text(encoding="utf-8")

        for phrase in (
            "web_search",
            "web_extract",
            "import-handoff",
            "search_status",
            "QQ 主动推送",
            "qq_report_path",
            "read-report",
            "完整日报正文",
            "不重新生成",
            "日报发送完成",
            "发送失败",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(
                    phrase,
                    local_text,
                )
        for phrase in (
            "至少两组",
            "published_at",
            "source_verified",
            "time_unverified",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(
                    phrase,
                    news_text,
                )
        for phrase in (
            "README",
            "project_analysis",
            "recommendation_reason",
            "evidence_urls",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(
                    phrase,
                    github_text,
                )
        for phrase in (
            "query",
            "不感兴趣",
            "想深入了解",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(
                    phrase,
                    profile_text,
                )

    def test_creator_skill_has_hermes_metadata_and_management_boundaries(self) -> None:
        """创作者 Skill 应包含 Hermes 元数据、权限规则和明确职责边界。"""
        root = Path(__file__).resolve().parents[1]
        skill_dir = root / "skills" / "dailyintelligence-creators"
        skill_path = skill_dir / "SKILL.md"
        reference_path = skill_dir / "references" / "commands.md"

        self.assertTrue(skill_path.is_file())
        self.assertTrue(reference_path.is_file())
        skill_text = skill_path.read_text(encoding="utf-8")
        reference_text = reference_path.read_text(encoding="utf-8")

        for phrase in (
            "name: dailyintelligence-creators",
            "description:",
            "metadata:",
            "hermes:",
            "terminal",
            "space.bilibili.com",
            "youtube.com/@",
            "/channel/UC",
            "CREATOR_ALREADY_EXISTS",
            "CREATOR_UNAUTHORIZED",
            "删除前必须确认",
            "不负责实际采集视频和动态",
            "不负责生成日报",
            "不负责启动后台监控服务",
            "不负责创建 Cron 任务",
            "不负责修改 DailyIntelligence 的采集时间窗口",
            "不修改 Hermes Profile",
            "不将账号数据写入 Hermes Memory",
            "不虚报操作成功",
            "sender ID",
            "owner-key",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, skill_text)

        for phrase in (
            "creator --json add",
            "creator --json list",
            "creator --json remove",
            "creator --json pause",
            "creator --json resume",
            "creator --json configure",
            "--data-dir",
            "--owner-key",
            "CREATOR_BACKEND_ERROR",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, reference_text)

        self.assertNotIn("E:\\HermesData", skill_text)
        self.assertNotIn("intelligence.db", skill_text)
        self.assertNotIn("SELECT ", skill_text.upper())

    def test_creator_skill_command_examples_match_cli_parser(self) -> None:
        """Skill 文档中的管理命令应被现有 CLI 参数解析器接受。"""
        parser = build_parser()
        data_dir = str(Path.cwd())
        command_cases = (
            [
                "--data-dir",
                data_dir,
                "creator",
                "--json",
                "add",
                "--owner-key",
                "qq:sender",
                "https://space.bilibili.com/123456",
            ],
            [
                "--data-dir",
                data_dir,
                "creator",
                "--json",
                "list",
                "--owner-key",
                "qq:sender",
            ],
            [
                "--data-dir",
                data_dir,
                "creator",
                "--json",
                "remove",
                "bilibili",
                "123456",
                "--owner-key",
                "qq:sender",
            ],
            [
                "--data-dir",
                data_dir,
                "creator",
                "--json",
                "pause",
                "youtube",
                "UC_example",
                "--owner-key",
                "qq:sender",
            ],
            [
                "--data-dir",
                data_dir,
                "creator",
                "--json",
                "resume",
                "youtube",
                "UC_example",
                "--owner-key",
                "qq:sender",
            ],
            [
                "--data-dir",
                data_dir,
                "creator",
                "--json",
                "configure",
                "bilibili",
                "123456",
                "--no-dynamics",
                "--owner-key",
                "qq:sender",
            ],
        )

        for command in command_cases:
            with self.subTest(command=command):
                args = parser.parse_args(command)
                self.assertEqual(args.command, "creator")
                self.assertTrue(args.creator_json)


if __name__ == "__main__":
    unittest.main()
