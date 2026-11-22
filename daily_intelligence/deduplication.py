"""URL、内容指纹和相似文本去重工具。"""

from __future__ import annotations

import hashlib
import re
from difflib import SequenceMatcher
from html import unescape
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from typing import TYPE_CHECKING, Iterable

if TYPE_CHECKING:
    from .models import Item


TRACKING_QUERY_PREFIXES = (
    "utm_",
    "mc_",
)
TRACKING_QUERY_KEYS = frozenset(
    {
        "fbclid",
        "gclid",
        "ref",
        "source",
    }
)
WHITESPACE_PATTERN = re.compile(r"\s+")


def normalize_url(
    url: str,
) -> str:
    """去除追踪参数并统一 URL 大小写、端口和片段。"""
    raw_url = url.strip()
    parsed = urlsplit(raw_url)
    scheme = parsed.scheme.lower()
    hostname = (parsed.hostname or "").lower()
    port = parsed.port
    netloc = hostname
    if port and not (
        (scheme == "http" and port == 80)
        or (scheme == "https" and port == 443)
    ):
        netloc = f"{hostname}:{port}"
    filtered_query = [
        (key, value)
        for key, value in parse_qsl(
            parsed.query,
            keep_blank_values=True,
        )
        if not key.lower().startswith(TRACKING_QUERY_PREFIXES)
        and key.lower() not in TRACKING_QUERY_KEYS
    ]
    filtered_query.sort()
    path = parsed.path or "/"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    return urlunsplit(
        (
            scheme,
            netloc,
            path,
            urlencode(filtered_query),
            "",
        )
    )


def _normalized_text(
    value: str,
) -> str:
    """把 HTML、大小写和连续空白归一化。"""
    plain_text = unescape(re.sub(r"<[^>]+>", " ", value or ""))
    return WHITESPACE_PATTERN.sub(
        " ",
        plain_text,
    ).strip().lower()


def content_fingerprint(
    title: str,
    content: str,
) -> str:
    """基于规范化标题和正文生成稳定 SHA-256 指纹。"""
    normalized = "\n".join(
        (
            _normalized_text(title),
            _normalized_text(content),
        )
    )
    return hashlib.sha256(
        normalized.encode("utf-8")
    ).hexdigest()


def text_similarity(
    left: str,
    right: str,
) -> float:
    """返回两个文本的标准库相似度比例。"""
    return SequenceMatcher(
        None,
        _normalized_text(left),
        _normalized_text(right),
    ).ratio()


def same_repository(
    left: str,
    right: str,
) -> bool:
    """识别两个 GitHub URL 或仓库名是否指向同一仓库。"""
    def repository_key(value: str) -> str:
        """提取 owner/repository 形式的稳定仓库键。"""
        parsed = urlsplit(value.strip())
        path = parsed.path.strip("/")
        if parsed.netloc.lower().endswith("github.com"):
            path = path.removesuffix(".git")
        return "/".join(path.split("/")[:2]).lower()

    left_key = repository_key(left)
    right_key = repository_key(right)
    return bool(left_key and left_key == right_key)


def deduplicate_urls(
    urls: Iterable[str],
) -> list[str]:
    """按规范化 URL 保留输入顺序并删除重复链接。"""
    seen: set[str] = set()
    result: list[str] = []
    for url in urls:
        normalized = normalize_url(url)
        if normalized in seen:
            continue
        seen.add(normalized)
        result.append(url)
    return result


def deduplicate_items(
    items: Iterable["Item"],
    similarity_threshold: float = 0.86,
) -> list["Item"]:
    """合并 URL、指纹或标题相似的项目，并保留关联来源。"""
    result: list["Item"] = []
    seen_urls: dict[tuple[str, str], int] = {}
    seen_fingerprints: dict[tuple[str, str], int] = {}
    for item in items:
        item_key = (
            item.item_type,
            normalize_url(item.url),
        )
        fingerprint_key = (
            item.item_type,
            content_fingerprint(
                item.title,
                item.content or item.summary,
            ),
        )
        duplicate_index = seen_urls.get(item_key)
        if duplicate_index is None:
            duplicate_index = seen_fingerprints.get(fingerprint_key)
        if duplicate_index is None:
            duplicate_index = _find_similar_item(
                result,
                item,
                similarity_threshold,
            )
        if duplicate_index is None:
            seen_urls[item_key] = len(result)
            seen_fingerprints[fingerprint_key] = len(result)
            result.append(item)
            continue
        result[duplicate_index] = _merge_item_sources(
            result[duplicate_index],
            item,
        )
    return result


def _find_similar_item(
    items: list["Item"],
    candidate: "Item",
    threshold: float,
) -> int | None:
    """在同类型和同分类项目中寻找超过阈值的相似标题。"""
    candidate_text = f"{candidate.title} {candidate.summary}"
    for index, item in enumerate(items):
        if item.item_type != candidate.item_type:
            continue
        if item.category and candidate.category and item.category != candidate.category:
            continue
        current_text = f"{item.title} {item.summary}"
        if text_similarity(current_text, candidate_text) >= threshold:
            return index
    return None


def _merge_item_sources(
    current: "Item",
    duplicate: "Item",
) -> "Item":
    """把重复条目的来源和链接合并到主条目元数据。"""
    if _source_priority(duplicate) > _source_priority(current):
        primary = duplicate
        secondary = current
    else:
        primary = current
        secondary = duplicate
    metadata = dict(primary.metadata)
    for key, value in secondary.metadata.items():
        metadata.setdefault(key, value)
    related_sources = list(metadata.get("related_sources", []))
    if secondary.source != primary.source and secondary.source not in related_sources:
        related_sources.append(secondary.source)
    related_urls = list(metadata.get("related_urls", []))
    normalized_primary = normalize_url(primary.url)
    normalized_secondary = normalize_url(secondary.url)
    if normalized_secondary != normalized_primary and secondary.url not in related_urls:
        related_urls.append(secondary.url)
    if related_sources:
        metadata["related_sources"] = related_sources
    if related_urls:
        metadata["related_urls"] = related_urls
    return primary.with_updates(metadata=metadata)


def _source_priority(
    item: "Item",
) -> int:
    """计算新闻来源可信度，已核实官方来源优先于转载。"""
    metadata = item.metadata
    source = item.source.casefold()
    score = 0
    if metadata.get("source_verified") is True:
        score += 2
    if "official" in source or "官方" in source:
        score += 1
    return score

