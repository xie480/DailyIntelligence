"""URL、内容指纹和相似文本去重工具。"""

from __future__ import annotations

import hashlib
import re
from difflib import SequenceMatcher
from html import unescape
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from typing import Iterable


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

