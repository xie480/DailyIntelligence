"""本地 Hermes Skill 目录和元数据检查。"""

from __future__ import annotations

import unittest
from pathlib import Path


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


if __name__ == "__main__":
    unittest.main()
