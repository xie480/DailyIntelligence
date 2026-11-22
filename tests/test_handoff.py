"""Hermes Web Search 结构化交接的离线测试。"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from daily_intelligence.config import RuntimePaths
from daily_intelligence.database import Database
from daily_intelligence.handoff import (
    HandoffValidationError,
    import_handoff,
    load_handoff,
    news_items_from_handoff,
    write_handoff,
)
from daily_intelligence.models import Item
from tests.test_support import temporary_directory


class HandoffTestCase(unittest.TestCase):
    """验证搜索状态、新闻字段和项目分析的结构化交接。"""

    def setUp(self) -> None:
        """创建隔离的交接文件和 SQLite 数据库。"""
        self.tempdir = temporary_directory(
            prefix="daily-intelligence-handoff-",
        )
        self.addCleanup(
            self.tempdir.cleanup,
        )
        self.root = Path(
            self.tempdir.name
        )
        self.paths = RuntimePaths.from_data_dir(
            self.root
        )
        self.paths.ensure()
        self.database = Database(
            self.paths.database_path
        )
        self.database.initialize()
        self.addCleanup(
            self.database.close,
        )

    def _payload(self) -> dict[str, object]:
        """构造包含三领域状态、新闻和项目分析的最小交接数据。"""
        return {
            "schema_version": "1.0",
            "generated_at": "2026-11-22T09:30:00+08:00",
            "timezone": "Asia/Shanghai",
            "window_hours": 24,
            "search_status": {
                "ai": "success",
                "agent": "empty",
                "software": "network_error",
            },
            "search_queries": {
                "ai": [
                    "AI model release official announcement last 24 hours",
                    "AI coding tool release official blog last 24 hours",
                ],
                "agent": [
                    "agent framework release MCP official last 24 hours",
                    "multi-agent automation news official last 24 hours",
                ],
                "software": [
                    "developer tool release official blog last 24 hours",
                    "software security update official last 24 hours",
                ],
            },
            "news": [
                {
                    "title": "Example model release",
                    "category": "ai",
                    "source_name": "Example Official",
                    "published_at": "2026-11-22T08:00:00+08:00",
                    "url": "https://example.com/model-release",
                    "summary": "A verified model update.",
                    "key_changes": [
                        "Adds a new capability",
                    ],
                    "importance": 90,
                    "why_it_matters": "Developers can evaluate the new API.",
                    "source_verified": True,
                    "evidence_urls": [
                        "https://example.com/model-release",
                    ],
                }
            ],
            "projects": [
                {
                    "repository": "acme/demo",
                    "summary": "A local agent runtime.",
                    "features": [
                        "Tool routing",
                        "Local execution",
                    ],
                    "use_cases": [
                        "Developer automation",
                    ],
                    "recommendation_reason": "Useful for local workflows.",
                    "evidence_urls": [
                        "https://github.com/acme/demo",
                    ],
                }
            ],
        }

    def test_handoff_round_trip_keeps_status_and_news_fields(self) -> None:
        """交接文件应原子写入并保留搜索状态和新闻证据。"""
        source_path = self.root / "handoff.json"
        write_handoff(
            source_path,
            self._payload(),
        )

        loaded = load_handoff(source_path)
        self.assertEqual(
            loaded["search_status"]["software"],
            "network_error",
        )
        items = news_items_from_handoff(loaded)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].metadata["source_verified"], True)
        self.assertEqual(
            items[0].metadata["evidence_urls"],
            ["https://example.com/model-release"],
        )

    def test_handoff_import_deduplicates_news_and_applies_project_analysis(self) -> None:
        """导入应合并新闻来源并把项目分析写入已有仓库。"""
        self.database.upsert_item(
            Item(
                item_type="github",
                title="acme/demo",
                url="https://github.com/acme/demo",
                source="GitHub Search API",
                repo_full_name="acme/demo",
                summary="Short description",
                metadata={
                    "section": "github_hot",
                },
            )
        )
        self.database.upsert_item(
            Item(
                item_type="news",
                title="Example model release",
                url="https://rss.example.com/model-release",
                source="Example RSS",
                category="ai",
                summary="A verified model update.",
                published_at="2026-11-22T08:00:00+08:00",
            )
        )
        source_path = self.root / "handoff.json"
        write_handoff(
            source_path,
            self._payload(),
        )

        result = import_handoff(
            self.database,
            source_path,
            self.paths.handoff_path,
        )

        self.assertEqual(result["news_imported"], 1)
        self.assertEqual(result["projects_updated"], 1)
        self.assertEqual(
            len(
                self.database.list_items(
                    item_type="news",
                    limit=20,
                )
            ),
            2,
        )
        github = self.database.list_items(
            item_type="github",
            limit=20,
        )[0]
        self.assertEqual(
            github["metadata"]["project_analysis"]["features"],
            [
                "Tool routing",
                "Local execution",
            ],
        )
        self.assertTrue(self.paths.handoff_path.is_file())

    def test_handoff_rejects_news_without_https_source(self) -> None:
        """新闻缺少安全原始链接时应拒绝写入。"""
        payload = self._payload()
        payload["news"][0]["url"] = "javascript:alert(1)"

        with self.assertRaises(HandoffValidationError):
            write_handoff(
                self.root / "invalid.json",
                payload,
            )

    def test_handoff_rejects_malformed_json(self) -> None:
        """损坏的交接 JSON 应抛出可识别的校验错误。"""
        path = self.root / "malformed.json"
        path.write_text(
            "{not-json}",
            encoding="utf-8",
        )

        with self.assertRaises(HandoffValidationError):
            load_handoff(path)

    def test_repository_handoff_example_is_valid(self) -> None:
        """仓库提供的交接示例应能直接通过 schema 校验。"""
        example_path = (
            Path(__file__).resolve().parents[1]
            / "config"
            / "hermes-handoff.example.json"
        )
        payload = load_handoff(example_path)
        self.assertEqual(
            payload["schema_version"],
            "1.0",
        )
        self.assertEqual(
            len(payload["news"]),
            3,
        )
        self.assertEqual(
            payload["search_status"]["software"],
            "partial",
        )


if __name__ == "__main__":
    unittest.main()
