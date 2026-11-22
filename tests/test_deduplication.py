"""去重工具的行为测试。"""

from __future__ import annotations

import unittest

from daily_intelligence.deduplication import (
    content_fingerprint,
    deduplicate_items,
    normalize_url,
    same_repository,
    text_similarity,
)
from daily_intelligence.models import Item


class DeduplicationTestCase(unittest.TestCase):
    """验证三层去重规则和仓库识别。"""

    def test_normalize_url_removes_tracking_parameters(self) -> None:
        """规范化 URL 应删除追踪参数、片段和默认端口。"""
        actual = normalize_url(
            "HTTPS://Example.com:443/news/?utm_source=x&b=2&a=1#section"
        )

        self.assertEqual(actual, "https://example.com/news?a=1&b=2")

    def test_content_fingerprint_ignores_html_and_whitespace(self) -> None:
        """相同内容的 HTML 与空白差异不应产生不同指纹。"""
        first = content_fingerprint(
            "A title",
            "<p>Hello</p>   world",
        )
        second = content_fingerprint(
            " A   title ",
            "Hello world",
        )

        self.assertEqual(first, second)

    def test_similarity_and_repository_identity(self) -> None:
        """相似新闻和同一 GitHub 仓库应被识别。"""
        self.assertGreater(
            text_similarity(
                "Open source agent runtime release",
                "Open-source agent runtime released",
            ),
            0.75,
        )
        self.assertTrue(
            same_repository(
                "https://github.com/acme/demo/",
                "acme/demo",
            )
        )

    def test_deduplicate_items_merges_related_sources(self) -> None:
        """重复 URL 或相似标题应保留一条并记录关联来源。"""
        first = Item(
            item_type="news",
            title="Agent runtime 1.0 released",
            url="https://example.com/news?utm_medium=rss",
            source="Official Blog",
            summary="A new agent runtime.",
            category="agent",
        )
        second = Item(
            item_type="news",
            title="Agent runtime 1.0 release",
            url="https://mirror.example.com/agent",
            source="Tech Media",
            summary="A new agent runtime.",
            category="agent",
        )

        result = deduplicate_items(
            [
                first,
                second,
            ],
            similarity_threshold=0.75,
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(
            result[0].metadata["related_sources"],
            ["Tech Media"],
        )

    def test_deduplicate_items_prefers_verified_official_source(self) -> None:
        """同一事件跨来源重复时应优先保留已核实的官方来源。"""
        media = Item(
            item_type="news",
            title="Agent runtime 1.0 released",
            url="https://media.example.com/agent-runtime",
            source="Tech Media",
            summary="Agent runtime 1.0 is released.",
            category="agent",
        )
        official = Item(
            item_type="news",
            title="Agent runtime 1.0 release",
            url="https://official.example.com/agent-runtime",
            source="Official Blog",
            summary="Agent runtime 1.0 is released.",
            category="agent",
            metadata={
                "source_verified": True,
            },
        )

        result = deduplicate_items(
            [
                media,
                official,
            ],
            similarity_threshold=0.75,
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].source, "Official Blog")
        self.assertEqual(
            result[0].url,
            "https://official.example.com/agent-runtime",
        )
        self.assertIn(
            "Tech Media",
            result[0].metadata["related_sources"],
        )


if __name__ == "__main__":
    unittest.main()

