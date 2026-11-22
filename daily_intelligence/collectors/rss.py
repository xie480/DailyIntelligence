"""RSS/Atom 标准库采集器。"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from typing import Any, Callable, Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from xml.etree import ElementTree

from ..deduplication import deduplicate_items
from ..models import Item


class _TextExtractor(HTMLParser):
    """提取 HTML 文本并丢弃标签。"""

    def __init__(self) -> None:
        """初始化文本片段列表。"""
        super().__init__()
        self.parts: list[str] = []

    def handle_data(
        self,
        data: str,
    ) -> None:
        """保存标签中的可见文本。"""
        self.parts.append(data)

    def text(self) -> str:
        """返回拼接后的纯文本。"""
        return " ".join(
            part.strip()
            for part in self.parts
            if part.strip()
        ).strip()


@dataclass(frozen=True, slots=True)
class RSSFeedFailure:
    """记录单个 Feed 的脱敏失败来源和异常类型。"""

    source: str
    url: str
    reason: str


@dataclass(frozen=True, slots=True)
class RSSCollectionResult:
    """保存 RSS 批次结果及成功、失败 Feed 明细。"""

    items: list[Item]
    successful_feeds: tuple[str, ...]
    failures: tuple[RSSFeedFailure, ...]

    @property
    def success_count(self) -> int:
        """返回成功 Feed 数量。"""
        return len(self.successful_feeds)

    @property
    def failure_count(self) -> int:
        """返回失败 Feed 数量。"""
        return len(self.failures)


class RSSCollector:
    """读取 RSS/Atom feed 并应用最近时间窗口。"""

    def __init__(
        self,
        timeout: int = 15,
        retries: int = 2,
        opener: Callable[..., Any] | None = None,
        sleep_fn: Callable[[float], None] | None = None,
    ) -> None:
        """初始化可注入网络客户端和重试策略。"""
        self.timeout = timeout
        self.retries = max(0, retries)
        self.opener = opener or urlopen
        self.sleep_fn = sleep_fn or time.sleep

    def collect(
        self,
        feeds: Iterable[dict[str, Any]],
        now: datetime | None = None,
        window_hours: int = 24,
        supplement_days: int = 7,
    ) -> list[Item]:
        """采集主窗口和补充窗口内的 RSS/Atom 条目。"""
        return self.collect_with_report(
            feeds,
            now=now,
            window_hours=window_hours,
            supplement_days=supplement_days,
        ).items

    def collect_with_report(
        self,
        feeds: Iterable[dict[str, Any]],
        now: datetime | None = None,
        window_hours: int = 24,
        supplement_days: int = 7,
    ) -> RSSCollectionResult:
        """逐个采集 Feed，隔离失败并返回批次统计。"""
        current = now or datetime.now(timezone.utc)
        current = self._ensure_aware(current)
        primary_cutoff = current - timedelta(hours=window_hours)
        supplement_cutoff = current - timedelta(days=supplement_days)
        collected: list[Item] = []
        successful_feeds: list[str] = []
        failures: list[RSSFeedFailure] = []
        for feed in feeds:
            source = str(
                feed.get("name")
                or "RSS Feed"
            )
            url = str(feed.get("url") or "")
            try:
                xml_content = self._fetch(url)
                root = ElementTree.fromstring(xml_content)
                for entry in self._entry_nodes(root):
                    item = self._entry_to_item(
                        entry,
                        feed,
                        current,
                        primary_cutoff,
                        supplement_cutoff,
                    )
                    if item:
                        collected.append(item)
                successful_feeds.append(source)
            except Exception as error:
                failures.append(
                    RSSFeedFailure(
                        source=source,
                        url=url,
                        reason=self._error_reason(error),
                    )
                )
        return RSSCollectionResult(
            items=deduplicate_items(collected),
            successful_feeds=tuple(successful_feeds),
            failures=tuple(failures),
        )

    def _fetch(
        self,
        url: str,
    ) -> bytes:
        """读取 feed 内容并对网络临时错误进行重试。"""
        request = Request(
            url,
            headers={
                "User-Agent": "Daily-Intelligence/1.0",
                "Accept": "application/rss+xml, application/atom+xml, application/xml",
            },
            method="GET",
        )
        for attempt in range(self.retries + 1):
            try:
                with self.opener(
                    request,
                    timeout=self.timeout,
                ) as response:
                    return response.read()
            except HTTPError:
                raise
            except (
                URLError,
                TimeoutError,
                ConnectionError,
                OSError,
            ):
                if attempt >= self.retries:
                    raise
                self.sleep_fn(float(2 ** attempt))
        raise RuntimeError("RSS 重试流程异常结束")

    @staticmethod
    def _error_reason(
        error: BaseException,
    ) -> str:
        """返回不包含 URL、请求体和凭证的异常类型摘要。"""
        reason = getattr(
            error,
            "reason",
            None,
        )
        if reason is None:
            return type(error).__name__
        return (
            f"{type(error).__name__}/"
            f"{type(reason).__name__}"
        )

    @staticmethod
    def _entry_nodes(
        root: ElementTree.Element,
    ) -> list[ElementTree.Element]:
        """兼容 RSS item 和 Atom entry 节点。"""
        root_name = RSSCollector._local_name(root.tag)
        if root_name == "feed":
            return [
                element
                for element in root.iter()
                if RSSCollector._local_name(element.tag) == "entry"
            ]
        return [
            element
            for element in root.iter()
            if RSSCollector._local_name(element.tag) == "item"
        ]

    def _entry_to_item(
        self,
        entry: ElementTree.Element,
        feed: dict[str, Any],
        current: datetime,
        primary_cutoff: datetime,
        supplement_cutoff: datetime,
    ) -> Item | None:
        """把 RSS/Atom 节点转换为项目模型。"""
        title = self._child_text(entry, "title")
        link = self._entry_link(entry)
        if not title or not link:
            return None
        published = self._parse_datetime(
            self._child_text(
                entry,
                "pubDate",
            )
            or self._child_text(entry, "published")
            or self._child_text(entry, "updated")
        )
        if published and published < supplement_cutoff:
            return None
        summary = self._strip_html(
            self._child_text(entry, "description")
            or self._child_text(entry, "summary")
            or self._child_text(entry, "content")
        )
        is_primary = bool(
            published
            and published >= primary_cutoff
        )
        return Item(
            item_type="news",
            title=title,
            url=link,
            source=str(feed.get("name") or feed.get("url") or "RSS"),
            published_at=published.isoformat() if published else None,
            summary=summary,
            content=summary,
            category=str(feed.get("category") or "software"),
            metadata={
                "feed_url": feed.get("url"),
                "is_primary": is_primary,
                "is_supplement": bool(published and not is_primary),
                "collected_at": current.isoformat(),
            },
        )

    @staticmethod
    def _local_name(
        tag: str,
    ) -> str:
        """去除 XML 命名空间前缀。"""
        return tag.rsplit(
            "}",
            1,
        )[-1]

    @classmethod
    def _child_text(
        cls,
        entry: ElementTree.Element,
        name: str,
    ) -> str:
        """读取指定本地名称的第一个子节点文本。"""
        for child in entry:
            if cls._local_name(child.tag) == name:
                return "".join(child.itertext()).strip()
        return ""

    @classmethod
    def _entry_link(
        cls,
        entry: ElementTree.Element,
    ) -> str:
        """兼容 RSS 文本链接和 Atom href 属性。"""
        for child in entry:
            if cls._local_name(child.tag) != "link":
                continue
            href = child.attrib.get("href")
            if href:
                return href.strip()
            text = "".join(child.itertext()).strip()
            if text:
                return text
        return ""

    @staticmethod
    def _strip_html(
        value: str,
    ) -> str:
        """用 HTMLParser 将摘要转换为纯文本。"""
        parser = _TextExtractor()
        parser.feed(value or "")
        parser.close()
        return parser.text()

    @staticmethod
    def _parse_datetime(
        value: str,
    ) -> datetime | None:
        """解析 ISO 8601 或 RFC 822 时间并统一为 UTC。"""
        if not value:
            return None
        parsed: datetime
        try:
            parsed = datetime.fromisoformat(
                value.replace(
                    "Z",
                    "+00:00",
                )
            )
        except ValueError:
            try:
                parsed = parsedate_to_datetime(value)
            except (TypeError, ValueError, OverflowError):
                return None
        parsed = RSSCollector._ensure_aware(parsed)
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _ensure_aware(
        value: datetime,
    ) -> datetime:
        """为无时区时间补 UTC，避免比较时抛出异常。"""
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value

