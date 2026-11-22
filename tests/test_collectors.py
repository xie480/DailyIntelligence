"""GitHub 与 RSS 采集器的离线行为测试。"""

from __future__ import annotations

import json
import os
import unittest
from datetime import datetime, timezone
from email.utils import format_datetime
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.request import Request

from daily_intelligence.collectors.github import (
    GitHubAPIError,
    GitHubCollector,
    GitHubClient,
)
from daily_intelligence.collectors.rss import RSSCollector


class FakeResponse:
    """提供 urllib 响应对象所需的最小接口。"""

    def __init__(
        self,
        payload: bytes,
        headers: dict[str, str] | None = None,
        status: int = 200,
        url: str | None = None,
    ) -> None:
        """保存固定响应体。"""
        self.payload = payload
        self.headers = headers or {}
        self.status = status
        self.url = url

    def read(self) -> bytes:
        """返回响应体字节。"""
        return self.payload

    def getcode(self) -> int:
        """返回固定 HTTP 状态码。"""
        return self.status

    def geturl(self) -> str | None:
        """返回可选的最终响应 URL。"""
        return self.url

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


def request_header(
    request: Request,
    name: str,
) -> str | None:
    """大小写不敏感地读取测试请求头。"""
    for key, value in request.header_items():
        if key.lower() == name.lower():
            return value
    return None


class SequenceOpener:
    """按调用顺序返回响应或抛出预设异常。"""

    def __init__(
        self,
        outcomes: list[FakeResponse | BaseException],
    ) -> None:
        """保存离线响应序列。"""
        self.outcomes = outcomes
        self.requests: list[Request] = []

    def __call__(
        self,
        request: Request,
        timeout: int,
    ) -> FakeResponse:
        """记录请求并返回下一项离线结果。"""
        self.requests.append(request)
        if not self.outcomes:
            raise AssertionError("离线响应序列已耗尽")
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class FlakyOpener:
    """第一次返回限流错误，第二次返回成功响应。"""

    def __init__(self) -> None:
        """初始化调用计数。"""
        self.calls = 0

    def __call__(
        self,
        request: Request,
        timeout: int,
    ) -> FakeResponse:
        """模拟一次 429 后恢复。"""
        self.calls += 1
        if self.calls == 1:
            raise HTTPError(
                request.full_url,
                429,
                "rate limited",
                {
                    "Retry-After": "0",
                },
                None,
            )
        return FakeResponse(b"{}")


class AlwaysRateLimitedOpener:
    """持续返回限流错误，用于验证重试上限。"""

    def __init__(
        self,
        status: int = 429,
        headers: dict[str, str] | None = None,
        reason: str = "rate limited",
    ) -> None:
        """保存固定限流响应参数。"""
        self.status = status
        self.headers = headers or {"Retry-After": "0"}
        self.reason = reason
        self.calls = 0

    def __call__(
        self,
        request: Request,
        timeout: int,
    ) -> FakeResponse:
        """每次调用都抛出同一限流错误。"""
        self.calls += 1
        raise HTTPError(
            request.full_url,
            self.status,
            self.reason,
            self.headers,
            None,
        )


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

    def test_github_client_retries_rate_limit(self) -> None:
        """GitHub 429 应按 Retry-After 重试并返回结果。"""
        opener = FlakyOpener()
        sleeps: list[float] = []
        client = GitHubClient(
            opener=opener,
            sleep_fn=sleeps.append,
        )

        self.assertEqual(
            client.get_json("/rate-limit"),
            {},
        )
        self.assertEqual(opener.calls, 2)
        self.assertEqual(sleeps, [0.0])

    def test_github_client_uses_exact_headers_and_anonymous_fallback(self) -> None:
        """请求应使用固定 GitHub 头，并在空环境变量时匿名访问。"""
        fake_token = "ephemeral-github-token"
        authenticated_opener = FakeOpener(
            {
                "/headers": b"{}",
            }
        )
        with patch.dict(
            os.environ,
            {
                "GITHUB_TOKEN": fake_token,
            },
        ):
            GitHubClient(
                opener=authenticated_opener,
            ).get_json("/headers")

        authenticated_request = authenticated_opener.requests[0]
        self.assertEqual(
            authenticated_request.full_url,
            "https://api.github.com/headers",
        )
        self.assertEqual(
            request_header(authenticated_request, "Accept"),
            "application/vnd.github+json",
        )
        self.assertEqual(
            request_header(
                authenticated_request,
                "X-GitHub-Api-Version",
            ),
            "2022-11-28",
        )
        self.assertEqual(
            request_header(authenticated_request, "User-Agent"),
            "DailyIntelligence",
        )
        self.assertEqual(
            request_header(authenticated_request, "Authorization"),
            f"Bearer {fake_token}",
        )
        self.assertNotIn(fake_token, authenticated_request.full_url)

        anonymous_opener = FakeOpener(
            {
                "/headers": b"{}",
            }
        )
        with patch.dict(
            os.environ,
            {
                "GITHUB_TOKEN": "",
            },
        ):
            GitHubClient(
                opener=anonymous_opener,
            ).get_json("/headers")

        self.assertIsNone(
            request_header(
                anonymous_opener.requests[0],
                "Authorization",
            )
        )

    def test_github_client_rejects_non_api_hosts_and_redirect_targets(self) -> None:
        """API URL 和最终响应主机必须固定为 HTTPS api.github.com。"""
        opener = FakeOpener(
            {
                "/safe": b"{}",
            }
        )
        client = GitHubClient(
            token="ephemeral-github-token",
            opener=opener,
        )

        with self.assertRaises(ValueError):
            client.get_json("https://github.com/acme/demo")
        with self.assertRaises(ValueError):
            client.get_json("http://api.github.com/safe")
        with self.assertRaises(ValueError):
            client.get_json("//evil.example/safe")
        self.assertEqual(opener.requests, [])

        redirect_opener = SequenceOpener(
            [
                FakeResponse(
                    b"{}",
                    url="https://evil.example/redirected",
                )
            ]
        )
        with self.assertRaises(GitHubAPIError):
            GitHubClient(
                token="ephemeral-github-token",
                opener=redirect_opener,
            ).get_json("/safe")

        status_redirect_opener = SequenceOpener(
            [
                FakeResponse(
                    b"",
                    headers={
                        "Location": "https://evil.example/redirected",
                    },
                    status=302,
                    url="https://api.github.com/safe",
                )
            ]
        )
        with self.assertRaises(GitHubAPIError):
            GitHubClient(
                token="ephemeral-github-token",
                opener=status_redirect_opener,
            ).get_json("/safe")
        self.assertEqual(len(status_redirect_opener.requests), 1)

    def test_github_client_redacts_token_from_errors(self) -> None:
        """异常文本和 URL 不得暴露注入的临时 Token。"""
        fake_token = "ephemeral-redaction-token"

        def opener(
            request: Request,
            timeout: int,
        ) -> FakeResponse:
            """抛出含临时 Token 的离线异常。"""
            raise HTTPError(
                f"{request.full_url}?debug={fake_token}",
                500,
                f"upstream failure {fake_token}",
                {},
                None,
            )

        with self.assertRaises(GitHubAPIError) as context:
            GitHubClient(
                token=fake_token,
                opener=opener,
                retries=0,
            ).get_json("/redaction")

        error = context.exception
        self.assertNotIn(fake_token, str(error))
        self.assertNotIn(fake_token, str(error.url))

    def test_github_client_honors_http_date_retry_after_with_cap(self) -> None:
        """HTTP-date Retry-After 应转换为有上限的等待秒数。"""
        now = 1_800_000_000.0
        retry_at = datetime.fromtimestamp(
            now + 4,
            tz=timezone.utc,
        )
        opener = SequenceOpener(
            [
                HTTPError(
                    "https://api.github.com/date",
                    403,
                    "rate limited",
                    {
                        "Retry-After": format_datetime(
                            retry_at,
                            usegmt=True,
                        )
                    },
                    None,
                ),
                FakeResponse(b"{}"),
            ]
        )
        sleeps: list[float] = []
        client = GitHubClient(
            opener=opener,
            retries=1,
            max_wait_seconds=5,
            sleep_fn=sleeps.append,
            time_fn=lambda: now,
        )

        self.assertEqual(client.get_json("/date"), {})
        self.assertEqual(sleeps, [4.0])

    def test_github_client_honors_rate_limit_reset_and_fails_fast_over_cap(
        self,
    ) -> None:
        """X-RateLimit-Reset 应等待或在超 cap 时立即失败。"""
        now = 1_800_000_000.0
        opener = SequenceOpener(
            [
                HTTPError(
                    "https://api.github.com/reset",
                    429,
                    "rate limited",
                    {
                        "X-RateLimit-Reset": str(int(now + 3)),
                    },
                    None,
                ),
                FakeResponse(b"{}"),
            ]
        )
        sleeps: list[float] = []
        client = GitHubClient(
            opener=opener,
            retries=1,
            max_wait_seconds=5,
            sleep_fn=sleeps.append,
            time_fn=lambda: now,
        )

        self.assertEqual(client.get_json("/reset"), {})
        self.assertEqual(sleeps, [3.0])

        capped_opener = AlwaysRateLimitedOpener(
            status=403,
            headers={
                "X-RateLimit-Reset": str(int(now + 100)),
            },
        )
        capped_sleeps: list[float] = []
        with self.assertRaises(GitHubAPIError) as context:
            GitHubClient(
                opener=capped_opener,
                retries=3,
                max_wait_seconds=10,
                sleep_fn=capped_sleeps.append,
                time_fn=lambda: now,
            ).get_json("/capped")

        self.assertEqual(capped_opener.calls, 1)
        self.assertEqual(capped_sleeps, [])
        self.assertIn("reset_at=", str(context.exception))
        self.assertIn("wait_seconds=100", str(context.exception))

    def test_github_client_stops_on_secondary_rate_limit(self) -> None:
        """Secondary rate limit 信号应停止重试，避免连续撞击 API。"""
        opener = AlwaysRateLimitedOpener(
            status=403,
            reason="You have exceeded a secondary rate limit.",
        )
        sleeps: list[float] = []

        with self.assertRaises(GitHubAPIError):
            GitHubClient(
                opener=opener,
                retries=3,
                sleep_fn=sleeps.append,
            ).get_json("/secondary")

        self.assertEqual(opener.calls, 1)
        self.assertEqual(sleeps, [])

    def test_github_client_retries_transient_network_error(self) -> None:
        """暂时性网络错误应使用有限指数退避。"""
        opener = SequenceOpener(
            [
                URLError("temporary network failure"),
                FakeResponse(b"{}"),
            ]
        )
        sleeps: list[float] = []

        self.assertEqual(
            GitHubClient(
                opener=opener,
                retries=1,
                sleep_fn=sleeps.append,
            ).get_json("/network"),
            {},
        )
        self.assertEqual(sleeps, [1.0])

    def test_github_client_bounds_rate_limit_retries(self) -> None:
        """最大重试次数应明确且不可因持续 429 无限增长。"""
        opener = AlwaysRateLimitedOpener()
        sleeps: list[float] = []

        with self.assertRaises(GitHubAPIError):
            GitHubClient(
                opener=opener,
                retries=2,
                sleep_fn=sleeps.append,
            ).get_json("/bounded")

        self.assertEqual(opener.calls, 3)
        self.assertEqual(sleeps, [0.0, 0.0])

    def test_github_client_uses_etag_and_handles_304_cache_hit(self) -> None:
        """重复请求应发送 ETag，并把 304 作为缓存命中。"""
        opener = SequenceOpener(
            [
                FakeResponse(
                    b'{"value": 1}',
                    headers={
                        "ETag": '"v1"',
                    },
                ),
                FakeResponse(
                    b"",
                    status=304,
                ),
            ]
        )
        client = GitHubClient(
            opener=opener,
        )

        first = client.get_json("/etag")
        second = client.get_json("/etag")

        self.assertEqual(first, {"value": 1})
        self.assertEqual(second, {"value": 1})
        self.assertEqual(
            request_header(
                opener.requests[1],
                "If-None-Match",
            ),
            '"v1"',
        )

    def test_github_collector_deduplicates_release_requests(self) -> None:
        """同一 collection 内重复仓库只应请求一次 Release。"""
        repository_payload = json.dumps(
            {
                "items": [
                    {
                        "id": 42,
                        "full_name": "acme/repeated",
                        "html_url": "https://github.com/acme/repeated",
                        "description": "Repeated agent toolkit",
                        "language": "Python",
                        "stargazers_count": 10,
                        "forks_count": 2,
                    }
                ]
            }
        ).encode()
        release_payload = json.dumps(
            {
                "tag_name": "v1.0.0",
                "html_url": "https://github.com/acme/repeated/releases/tag/v1.0.0",
                "published_at": "2026-11-20T00:00:00Z",
                "name": "First release",
            }
        ).encode()
        opener = SequenceOpener(
            [
                FakeResponse(repository_payload),
                FakeResponse(release_payload),
                FakeResponse(repository_payload),
            ]
        )

        items = GitHubCollector(
            GitHubClient(
                opener=opener,
            )
        ).collect(
            queries=[
                {
                    "name": "First",
                    "query": "topic:first",
                },
                {
                    "name": "Second",
                    "query": "topic:second",
                },
            ]
        )

        self.assertEqual(len(items), 1)
        self.assertEqual(
            sum(
                "/repos/acme/repeated/releases/latest" in request.full_url
                for request in opener.requests
            ),
            1,
        )

    def test_trending_html_parser_extracts_repository_fields(self) -> None:
        """Trending HTML 补充解析应提取仓库、语言、Star 和今日增长。"""
        html = b"""
        <article class="Box-row">
          <h2><a href="/acme/trending">acme / trending</a></h2>
          <p>Useful agent tool</p>
          <span itemprop="programmingLanguage">Python</span>
          <span>1,234 stars</span>
          <span>56 stars today</span>
        </article>
        """

        items = GitHubCollector.parse_trending_html(
            html.decode(),
        )

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].repo_full_name, "acme/trending")
        self.assertEqual(items[0].stars, 1234)
        self.assertEqual(items[0].metadata["stars_today"], 56)


if __name__ == "__main__":
    unittest.main()

