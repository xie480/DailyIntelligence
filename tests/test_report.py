"""日报 Markdown 渲染和文件落盘测试。"""

from __future__ import annotations

import unittest
from datetime import date, datetime, timezone
from pathlib import Path

from daily_intelligence.config import RuntimePaths
from daily_intelligence.report import DailyReportRenderer, save_report
from tests.test_support import temporary_directory


class ReportTestCase(unittest.TestCase):
    """验证日报分区、去重和日期文件名。"""

    def setUp(self) -> None:
        """创建隔离报告目录。"""
        self.runtime_tempdir = temporary_directory(
            prefix="daily-intelligence-report-",
        )
        self.addCleanup(
            self.runtime_tempdir.cleanup,
        )
        self.runtime_dir = Path(
            self.runtime_tempdir.name
        )
        self.paths = RuntimePaths.from_data_dir(self.runtime_dir)
        self.paths.ensure()

    def tearDown(self) -> None:
        """清理报告目录。"""

    def test_renderer_creates_sections_and_focus_without_duplicate_event(self) -> None:
        """日报应生成六个板块且重点推荐不重复展示同一 URL。"""
        items = [
            {
                "id": 1,
                "item_type": "github",
                "title": "acme/agent-runtime",
                "url": "https://github.com/acme/agent-runtime",
                "source": "GitHub",
                "category": "AI Agent",
                "summary": "MCP agent harness.",
                "published_at": "2026-11-21T08:00:00+00:00",
                "metadata": {
                    "section": "github_hot",
                },
                "recommendation_score": 100,
                "match_reason": "匹配兴趣：AI Agent、MCP",
            },
            {
                "id": 2,
                "item_type": "news",
                "title": "Agent update",
                "url": "https://example.com/agent",
                "source": "Official Blog",
                "category": "agent",
                "summary": "Agent engineering update.",
                "published_at": "2026-11-21T07:00:00+00:00",
                "metadata": {},
                "recommendation_score": 80,
                "match_reason": "匹配兴趣：Agent Harness",
            },
        ]

        markdown = DailyReportRenderer().render(
            items,
            report_date=date(
                2026,
                11,
                21,
            ),
        )
        path = save_report(
            self.paths,
            markdown,
            date(
                2026,
                11,
                21,
            ),
        )

        self.assertIn("# Daily Intelligence 日报 - 2026-11-21", markdown)
        self.assertIn("## GitHub 热点", markdown)
        self.assertIn("## Agent 新闻", markdown)
        self.assertIn("## 今日重点推荐", markdown)
        self.assertEqual(markdown.count("https://github.com/acme/agent-runtime"), 1)
        self.assertEqual(path.name, "2026-11-21.md")
        self.assertTrue(path.is_file())

    def test_renderer_respects_total_limit(self) -> None:
        """日报内容总条数应受 total_limit 控制。"""
        items = [
            {
                "id": index,
                "item_type": "news",
                "title": f"News {index}",
                "url": f"https://example.com/{index}",
                "source": "Example",
                "category": "software",
                "summary": "Summary",
                "published_at": "2026-11-21T08:00:00+00:00",
                "metadata": {},
                "recommendation_score": 10,
                "match_reason": "测试",
            }
            for index in range(1, 8)
        ]

        markdown = DailyReportRenderer().render(
            items,
            report_date=date(
                2026,
                11,
                21,
            ),
            total_limit=3,
        )

        self.assertEqual(markdown.count("### News "), 3)

    def test_renderer_default_date_uses_injected_timezone(self) -> None:
        """未显式传日期时，日报标题应使用注入时区的逻辑日期。"""
        markdown = DailyReportRenderer().render(
            [],
            timezone_name="Asia/Shanghai",
            now=datetime(
                2026,
                11,
                22,
                16,
                tzinfo=timezone.utc,
            ),
        )

        self.assertIn(
            "# Daily Intelligence 日报 - 2026-11-23",
            markdown,
        )

    def test_focus_only_contains_rendered_items_and_unique_urls(self) -> None:
        """重点推荐只能来自已渲染板块，且 URL 不应重复。"""
        items = [
            {
                "id": index,
                "item_type": "github",
                "title": f"Hot {index}",
                "url": f"https://github.com/acme/hot-{index}",
                "source": "GitHub",
                "category": "AI Agent",
                "summary": "Summary",
                "metadata": {
                    "section": "github_hot",
                },
                "recommendation_score": index,
                "match_reason": "测试",
            }
            for index in range(1, 7)
        ]
        items.append(
            {
                "id": 7,
                "item_type": "github",
                "title": "Overflow",
                "url": "https://github.com/acme/overflow",
                "source": "GitHub",
                "category": "AI Agent",
                "summary": "Summary",
                "metadata": {
                    "section": "github_hot",
                },
                "recommendation_score": 1000,
                "match_reason": "测试",
            }
        )
        items.append(
            {
                "id": 8,
                "item_type": "news",
                "title": "Duplicate URL",
                "url": "https://github.com/acme/hot-6/?utm_source=test",
                "source": "GitHub",
                "category": "software",
                "summary": "Duplicate",
                "metadata": {},
                "recommendation_score": 999,
                "match_reason": "测试",
            }
        )

        markdown = DailyReportRenderer().render(
            items,
            report_date=date(
                2026,
                11,
                21,
            ),
            total_limit=8,
        )

        focus_markdown = markdown.split(
            "## 今日重点推荐",
            1,
        )[1]
        self.assertNotIn(
            "**Overflow**",
            focus_markdown,
        )
        self.assertEqual(
            markdown.count("https://github.com/acme/hot-6"),
            1,
        )
        self.assertEqual(
            focus_markdown.count("**Hot 6**"),
            1,
        )
        self.assertNotIn(
            "**Duplicate URL**",
            focus_markdown,
        )


if __name__ == "__main__":
    unittest.main()

