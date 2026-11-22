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


if __name__ == "__main__":
    unittest.main()
