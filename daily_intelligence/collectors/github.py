"""GitHub 官方 API 采集器。"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any, Callable, Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ..deduplication import deduplicate_items
from ..models import Item


GITHUB_API_URL = "https://api.github.com"
DEFAULT_USER_AGENT = "Daily-Intelligence/1.0"
DEFAULT_API_VERSION = "2022-11-28"


class _TrendingParser(HTMLParser):
    """解析 GitHub Trending 页面中的仓库卡片。"""

    def __init__(self) -> None:
        """初始化卡片和当前字段状态。"""
        super().__init__()
        self.cards: list[dict[str, Any]] = []
        self.current: dict[str, Any] | None = None
        self.active_field: str | None = None

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        """识别 article、仓库链接、描述、语言和统计字段。"""
        attributes = dict(attrs)
        classes = set(
            (attributes.get("class") or "").split()
        )
        if tag == "article" and "Box-row" in classes:
            self.current = {
                "href": "",
                "title": "",
                "description": "",
                "language": "",
                "stats": [],
            }
            self.active_field = None
            return
        if self.current is None:
            return
        if tag == "a" and attributes.get("href", "").startswith("/"):
            self.current["href"] = attributes["href"]
            self.active_field = "title"
        elif tag == "p":
            self.active_field = "description"
        elif tag == "span" and attributes.get("itemprop") == "programmingLanguage":
            self.active_field = "language"
        elif tag == "span":
            self.active_field = "stats"

    def handle_endtag(
        self,
        tag: str,
    ) -> None:
        """结束字段或保存完整仓库卡片。"""
        if tag in {
            "a",
            "p",
            "span",
        }:
            self.active_field = None
        if tag == "article" and self.current:
            self.cards.append(self.current)
            self.current = None

    def handle_data(
        self,
        data: str,
    ) -> None:
        """收集当前字段中的文本。"""
        if not self.current or not self.active_field:
            return
        value = data.strip()
        if not value:
            return
        if self.active_field == "stats":
            self.current["stats"].append(value)
        else:
            self.current[self.active_field] += f" {value}"


class GitHubClient:
    """封装 GitHub API 请求、鉴权和有限重试。"""

    def __init__(
        self,
        token: str | None = None,
        timeout: int = 15,
        retries: int = 2,
        opener: Callable[..., Any] | None = None,
        sleep_fn: Callable[[float], None] | None = None,
    ) -> None:
        """初始化可注入网络客户端，便于离线测试。"""
        self.token = token
        self.timeout = timeout
        self.retries = max(0, retries)
        self.opener = opener or urlopen
        self.sleep_fn = sleep_fn or time.sleep

    def get_json(
        self,
        path: str,
    ) -> dict[str, Any]:
        """请求一个 GitHub API 路径并解析 JSON 对象。"""
        request_url = (
            path
            if path.startswith("http")
            else f"{GITHUB_API_URL}{path}"
        )
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": DEFAULT_USER_AGENT,
            "X-GitHub-Api-Version": DEFAULT_API_VERSION,
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = Request(
            request_url,
            headers=headers,
            method="GET",
        )
        for attempt in range(self.retries + 1):
            try:
                with self.opener(
                    request,
                    timeout=self.timeout,
                ) as response:
                    payload = json.loads(
                        response.read().decode("utf-8")
                    )
                if not isinstance(payload, dict):
                    raise ValueError("GitHub API 返回值不是 JSON 对象")
                return payload
            except HTTPError as error:
                if not self._should_retry(error, attempt):
                    raise
                self.sleep_fn(self._retry_after(error))
            except (URLError, TimeoutError):
                if attempt >= self.retries:
                    raise
                self.sleep_fn(float(2 ** attempt))
        raise RuntimeError("GitHub API 重试流程异常结束")

    def _should_retry(
        self,
        error: HTTPError,
        attempt: int,
    ) -> bool:
        """判断限流或服务端错误是否允许重试。"""
        return (
            attempt < self.retries
            and error.code in {
                403,
                429,
                500,
                502,
                503,
                504,
            }
        )

    @staticmethod
    def _retry_after(
        error: HTTPError,
    ) -> float:
        """读取 Retry-After，缺省时使用短退避。"""
        header = error.headers.get("Retry-After") if error.headers else None
        try:
            return max(0.0, float(header))
        except (TypeError, ValueError):
            return 1.0


class GitHubCollector:
    """从 GitHub Search API 采集热点项目和 Release 信息。"""

    def __init__(
        self,
        client: GitHubClient,
    ) -> None:
        """保存 API 客户端。"""
        self.client = client

    def collect(
        self,
        queries: Iterable[dict[str, Any]] | None = None,
        per_page: int = 20,
        include_releases: bool = True,
    ) -> list[Item]:
        """执行查询并把仓库结果转换为去重后的项目列表。"""
        query_list = list(
            queries
            or [
                {
                    "name": "AI Agent",
                    "query": "topic:agent",
                }
            ]
        )
        collected: list[Item] = []
        for query_config in query_list:
            query_name = str(
                query_config.get("name")
                or query_config.get("query")
                or "github"
            )
            query = str(query_config.get("query") or query_name)
            payload = self.client.get_json(
                "/search/repositories"
                f"?q={self._quote_query(query)}"
                f"&sort=updated&order=desc&per_page={per_page}"
            )
            for repository in payload.get("items", []):
                item = self._repository_to_item(
                    repository,
                    query_name,
                    query_config.get("section"),
                    include_releases,
                )
                if item:
                    collected.append(item)
        return deduplicate_items(collected)

    @staticmethod
    def parse_trending_html(
        html: str,
    ) -> list[Item]:
        """解析 GitHub Trending HTML，作为官方 API 之外的补充来源。"""
        parser = _TrendingParser()
        parser.feed(html)
        parser.close()
        items: list[Item] = []
        for card in parser.cards:
            href = str(card.get("href") or "").strip()
            if not href.startswith("/"):
                continue
            full_name = href.strip("/").removesuffix(".git")
            if "/" not in full_name:
                continue
            stats = " ".join(card.get("stats") or [])
            total_stars = _parse_stat(
                stats,
                r"([\d,]+)\s+stars(?!\s+today)",
            )
            stars_today = _parse_stat(
                stats,
                r"([\d,]+)\s+stars\s+today",
            )
            metadata = {
                "section": "github_hot",
                "stars_today": stars_today,
                "source_type": "trending_html",
            }
            items.append(
                Item(
                    item_type="github",
                    title=full_name,
                    url=f"https://github.com/{full_name}",
                    source="GitHub Trending",
                    summary=str(
                        card.get("description") or ""
                    ).strip(),
                    content=str(
                        card.get("description") or ""
                    ).strip(),
                    category="trending",
                    language=str(
                        card.get("language") or ""
                    ).strip()
                    or None,
                    repo_full_name=full_name,
                    stars=total_stars,
                    metadata=metadata,
                )
            )
        return deduplicate_items(items)

    def _repository_to_item(
        self,
        repository: dict[str, Any],
        query_name: str,
        section: str | None,
        include_releases: bool,
    ) -> Item | None:
        """把 GitHub 仓库 JSON 转成统一项目模型。"""
        full_name = str(repository.get("full_name") or "").strip()
        html_url = str(repository.get("html_url") or "").strip()
        if not full_name or not html_url:
            return None
        latest_release: dict[str, Any] | None = None
        if include_releases:
            try:
                release = self.client.get_json(
                    f"/repos/{full_name}/releases/latest"
                )
                if release.get("tag_name"):
                    latest_release = {
                        "tag": release.get("tag_name"),
                        "name": release.get("name") or release.get("tag_name"),
                        "url": release.get("html_url"),
                        "published_at": release.get("published_at"),
                    }
            except HTTPError as error:
                if error.code != 404:
                    raise
        license_info = repository.get("license") or {}
        metadata: dict[str, Any] = {
            "query_name": query_name,
            "topics": repository.get("topics") or [],
            "license": license_info.get("spdx_id") or license_info.get("name"),
            "created_at": repository.get("created_at"),
            "updated_at": repository.get("updated_at"),
            "pushed_at": repository.get("pushed_at"),
        }
        if section:
            metadata["section"] = section
        if latest_release:
            metadata["latest_release"] = latest_release
        return Item(
            item_type="github",
            external_id=str(repository.get("id") or full_name),
            title=full_name,
            url=html_url,
            source="GitHub Search API",
            published_at=(
                repository.get("pushed_at")
                or repository.get("updated_at")
                or repository.get("created_at")
            ),
            summary=repository.get("description") or "",
            content=(
                f"{repository.get('description') or ''} "
                f"{' '.join(repository.get('topics') or [])}"
            ),
            category=query_name,
            language=repository.get("language"),
            repo_full_name=full_name,
            stars=int(repository.get("stargazers_count") or 0),
            forks=int(repository.get("forks_count") or 0),
            metadata=metadata,
        )

    @staticmethod
    def _quote_query(
        query: str,
    ) -> str:
        """对 GitHub 查询参数进行最小 URL 编码。"""
        from urllib.parse import quote

        return quote(
            query,
            safe="",
        )

    @staticmethod
    def snapshot_date(
        timezone_name: str = "UTC",
    ) -> str:
        """返回指定时区的当前日期，供 Star 快照使用。"""
        from zoneinfo import ZoneInfo

        return datetime.now(
            ZoneInfo(timezone_name)
        ).date().isoformat()


def _parse_stat(
    value: str,
    pattern: str,
) -> int:
    """从 Trending 统计文本中提取整数，缺失时返回零。"""
    match = re.search(
        pattern,
        value,
        flags=re.IGNORECASE,
    )
    if not match:
        return 0
    return int(
        match.group(1).replace(
            ",",
            "",
        )
    )

