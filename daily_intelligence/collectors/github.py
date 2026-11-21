"""GitHub 官方 API 采集器。"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any, Callable, Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ..deduplication import deduplicate_items
from ..models import Item


GITHUB_API_URL = "https://api.github.com"
DEFAULT_USER_AGENT = "Daily-Intelligence/1.0"
DEFAULT_API_VERSION = "2022-11-28"


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

