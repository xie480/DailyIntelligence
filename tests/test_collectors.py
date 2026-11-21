"""GitHub 与 RSS 采集器的离线行为测试。"""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from urllib.error import HTTPError
from urllib.request import Request

from daily_intelligence.collectors.github import GitHubCollector, GitHubClient
from daily_intelligence.collectors.rss import RSSCollector


class FakeResponse:
    """提供 urllib 响应对象所需的最小接口。"""

    def __init__(self, payload: bytes) -> None:
        """保存固定响应体。"""
        self.payload = payload

    def read(self) -> bytes:
        """返回响应体字节。"""
        return self.payload

    def __enter__(self) -> "FakeResponse":
        """支持 with 语句。"""
        return self

    def __exit__(self, *args: object) -> None:
        """结束响应上下文。"""


class FakeOpener:
    """按 URL 路径返回预设 JSON 或 XML。"""

    def __init__(self, responses: dict[str, bytes]) -> None:
        """保存路径到响应体的映射。"""
        self.responses = responses
        self.requests: list[Request] = []

    def __call__(
        self,
        request: Request,
        timeout: int,
    ) -> FakeResponse:
        """记录请求并返回匹配的响应。"""
        self.requests.append(request)
        for path, payload in self.responses.items():
            if path in request.full_url:
                return FakeResponse(payload)
        raise AssertionError(f"没有匹配的 URL: {request.full_url}")


class CollectorTestCase(unittest.TestCase):
    """验证外部采集器在不联网时的解析结果。"""

    def test_github_collector_parses_repository_and_release(self) -> None:
        """GitHub 搜索结果应转换为项目并携带最新 Release。"""
        opener = FakeOpener(
            {
                "/search/repositories": json.dumps(
                    {
                        "items": [
                            {
                                "id": 42,
                                "full_name": "acme/demo",
                                "html_url": "https://github.com/acme/demo",
                                "name": "demo",
                                "description": "Agent toolkit",
                                "language": "Python",
                                "stargazers_count": 120,
                                "forks_count": 12,
                                "created_at": "2026-11-01T00:00:00Z",
                                "updated_at": "2026-11-21T00:00:00Z",
                                "pushed_at": "2026-11-21T01:00:00Z",
                                "license": {"spdx_id": "MIT"},
                            }
                        ]
                    }
                ).encode(),
                "/repos/acme/demo/releases/latest": json.dumps(
                    {
                        "tag_name": "v1.0.0",
                        "html_url": "https://github.com/acme/demo/releases/tag/v1.0.0",
                        "published_at": "2026-11-20T00:00:00Z",
                        "name": "First release",
                    }
                ).encode(),
            }
        )
        client = GitHubClient(
            opener=opener,
            sleep_fn=lambda seconds: None,
        )
        collector = GitHubCollector(client)

        items = collector.collect(
            queries=[
                {
                    "name": "Agent",
                    "query": "topic:agent",
                }
            ],
            per_page=5,
        )

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].repo_full_name, "acme/demo")
        self.assertEqual(items[0].stars, 120)
        self.assertEqual(items[0].metadata["latest_release"]["tag"], "v1.0.0")
        self.assertTrue(
            any(
                "/search/repositories" in request.full_url
                for request in opener.requests
            )
        )

    def test_rss_collector_parses_recent_rss_and_atom(self) -> None:
        """RSS 和 Atom 条目应解析标题、链接、摘要及时间。"""
        rss = b"""
        <rss version="2.0">
          <channel>
            <title>Agent News</title>
            <item>
              <title>Agent update</title>
              <link>https://example.com/agent</link>
              <description><![CDATA[<p>Useful update</p>]]></description>
              <pubDate>Fri, 21 Nov 2026 08:00:00 GMT</pubDate>
            </item>
          </channel>
        </rss>
        """
        atom = b"""
        <feed xmlns="http://www.w3.org/2005/Atom">
          <title>Release Feed</title>
          <entry>
            <title>Tool release</title>
            <link href="https://example.com/release" />
            <summary>Release summary</summary>
            <updated>2026-11-20T08:00:00Z</updated>
          </entry>
        </feed>
        """
        opener = FakeOpener(
            {
                "rss.xml": rss,
                "atom.xml": atom,
            }
        )
        collector = RSSCollector(
            opener=opener,
            sleep_fn=lambda seconds: None,
        )

        items = collector.collect(
            feeds=[
                {
                    "name": "Agent RSS",
                    "url": "https://example.com/rss.xml",
                    "category": "agent",
                },
                {
                    "name": "Release Atom",
                    "url": "https://example.com/atom.xml",
                    "category": "software",
                },
            ],
            now=datetime(
                2026,
                11,
                21,
                12,
                tzinfo=timezone.utc,
            ),
            window_hours=24,
            supplement_days=7,
        )

        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].title, "Agent update")
        self.assertEqual(items[0].summary, "Useful update")
        self.assertTrue(items[0].metadata["is_primary"])
        self.assertFalse(items[1].metadata["is_primary"])


if __name__ == "__main__":
    unittest.main()

