"""日报 Markdown 渲染和文件落盘测试。"""

from __future__ import annotations

import unittest
from datetime import date, datetime, timezone
from pathlib import Path

from daily_intelligence.config import RuntimePaths
from daily_intelligence.report import (
    DailyReportRenderer,
    save_qq_report,
    save_report,
    split_qq_messages,
)
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

    def test_renderer_renders_project_metadata_analysis_and_collection_status(self) -> None:
        """日报应展示项目元数据、README 分析和各领域采集状态。"""
        markdown = DailyReportRenderer().render(
            [
                {
                    "id": 20,
                    "item_type": "github",
                    "title": "acme/deep-agent",
                    "url": "https://github.com/acme/deep-agent",
                    "source": "GitHub Search API",
                    "category": "AI Agent",
                    "summary": "A short description.",
                    "language": "Python",
                    "stars": 1250,
                    "forks": 120,
                    "metadata": {
                        "section": "github_hot",
                        "homepage": "https://deep-agent.example.com",
                        "created_at": "2026-10-01T00:00:00+00:00",
                        "updated_at": "2026-11-21T00:00:00+00:00",
                        "latest_release": {
                            "tag": "v2.0.0",
                            "published_at": "2026-11-20T00:00:00+00:00",
                        },
                        "readme": {
                            "status": "success",
                        },
                        "project_analysis": {
                            "summary": "A local agent runtime for developer workflows.",
                            "features": [
                                "Tool routing",
                                "MCP support",
                            ],
                            "use_cases": [
                                "Local automation",
                            ],
                            "recommendation_reason": "It is useful for repeatable local tasks.",
                            "evidence_urls": [
                                "https://github.com/acme/deep-agent",
                            ],
                        },
                    },
                    "recommendation_score": 90,
                    "match_reason": "匹配兴趣：AI Agent",
                }
            ],
            report_date=date(
                2026,
                11,
                22,
            ),
            collection_status={
                "generated_at": "2026-11-22T09:30:00+08:00",
                "search_status": {
                    "ai": "success",
                    "agent": "empty",
                    "software": "network_error",
                },
                "search_queries": {
                    "ai": ["model release", "coding tool"],
                    "agent": ["agent framework", "MCP"],
                    "software": ["developer tools", "security update"],
                },
            },
        )

        self.assertIn("## 今日情报速览", markdown)
        self.assertIn("★ 1,250 Stars", markdown)
        self.assertIn("120 Forks", markdown)
        self.assertIn("项目创建时间", markdown)
        self.assertIn("v2.0.0", markdown)
        self.assertIn("Tool routing", markdown)
        self.assertIn("Local automation", markdown)
        self.assertIn("## 数据来源与采集状态", markdown)
        self.assertIn("Agent：empty", markdown)
        self.assertIn("软件开发：network_error", markdown)

    def test_qq_markdown_keeps_complete_items_and_splits_by_boundaries(self) -> None:
        """QQ Markdown 应保留链接和完整条目，并按条目边界拆分。"""
        items = [
            {
                "id": index,
                "item_type": "news",
                "title": f"News {index}",
                "url": f"https://example.com/news-{index}",
                "source": "Official Blog",
                "category": "ai",
                "summary": "A source-backed summary.",
                "published_at": "2026-11-22T08:00:00+08:00",
                "metadata": {
                    "key_changes": ["A concrete change"],
                    "why_it_matters": "A clear developer impact.",
                    "source_verified": True,
                },
                "recommendation_score": 80 - index,
                "match_reason": "匹配兴趣：AI Agent",
            }
            for index in range(1, 4)
        ]

        qq_markdown = DailyReportRenderer().render_qq(
            items,
            report_date=date(
                2026,
                11,
                22,
            ),
            total_limit=3,
        )
        chunks = split_qq_messages(
            qq_markdown,
            max_chars=520,
        )

        self.assertIn("# 每日技术情报", qq_markdown)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(
            all(
                "[阅读原文](https://example.com/news-" in chunk
                for chunk in chunks
                if "### News" in chunk
            )
        )
        self.assertTrue(
            all(
                len(chunk) <= 520
                for chunk in chunks
            )
        )
        attachment = save_qq_report(
            self.paths,
            qq_markdown,
            date(
                2026,
                11,
                22,
            ),
        )
        self.assertTrue(attachment.is_file())


if __name__ == "__main__":
    unittest.main()

