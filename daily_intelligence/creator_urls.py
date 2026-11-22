"""Bilibili 与 YouTube 创作者主页链接解析。"""

from __future__ import annotations

from dataclasses import dataclass
import re
from urllib.parse import urlsplit


SUPPORTED_PLATFORMS = frozenset(
    {
        "bilibili",
        "youtube",
    }
)
_YOUTUBE_CHANNEL_ID_PATTERN = re.compile(
    r"^UC[0-9A-Za-z_-]{3,}$"
)
_YOUTUBE_HANDLE_PATTERN = re.compile(
    r"^@[A-Za-z0-9._-]{2,}$"
)
_BILIBILI_UID_PATTERN = re.compile(
    r"^[0-9]+$"
)
_YOUTUBE_RESOLVED_CHANNEL_PATTERN = re.compile(
    r"(?:youtube\.com/|\"channelId\"\s*:\s*\")"
    r"(UC[0-9A-Za-z_-]{3,})"
)


class CreatorUrlError(ValueError):
    """表示创作者主页链接缺少可确认的平台账号标识。"""


@dataclass(frozen=True, slots=True)
class ParsedCreatorUrl:
    """保存解析后的平台、账号键和规范化主页链接。"""

    platform: str
    account_key: str
    canonical_url: str
    requires_resolution: bool = False


def parse_creator_url(
    url: str,
) -> ParsedCreatorUrl:
    """根据域名解析 Bilibili 或 YouTube 创作者主页链接。"""
    cleaned = _clean_url(url)
    parsed = urlsplit(cleaned)
    hostname = (parsed.hostname or "").lower()
    if hostname in {
        "space.bilibili.com",
        "www.bilibili.com",
    }:
        return parse_bilibili_url(cleaned)
    if hostname in {
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
    }:
        return parse_youtube_channel_url(cleaned)
    raise CreatorUrlError(
        "只支持 space.bilibili.com 和 youtube.com 创作者主页链接"
    )


def parse_bilibili_url(
    url: str,
) -> ParsedCreatorUrl:
    """从 Bilibili 空间链接中提取数字 UID。"""
    cleaned = _clean_url(url)
    parsed = urlsplit(cleaned)
    hostname = (parsed.hostname or "").lower()
    if hostname not in {
        "space.bilibili.com",
        "www.bilibili.com",
    }:
        raise CreatorUrlError("不是受支持的 Bilibili 空间链接")
    segments = [
        value
        for value in parsed.path.split("/")
        if value
    ]
    uid = segments[0] if segments else ""
    if not _BILIBILI_UID_PATTERN.fullmatch(uid):
        raise CreatorUrlError("Bilibili 空间链接中没有可确认的 UID")
    return ParsedCreatorUrl(
        platform="bilibili",
        account_key=uid,
        canonical_url=f"https://space.bilibili.com/{uid}",
    )


def parse_youtube_channel_url(
    url: str,
) -> ParsedCreatorUrl:
    """解析 YouTube Channel ID、handle 和可尝试解析的旧式频道链接。"""
    cleaned = _clean_url(url)
    parsed = urlsplit(cleaned)
    hostname = (parsed.hostname or "").lower()
    if hostname not in {
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
    }:
        raise CreatorUrlError("不是受支持的 YouTube 频道链接")
    segments = [
        value
        for value in parsed.path.split("/")
        if value
    ]
    if len(segments) >= 2 and segments[0].lower() == "channel":
        channel_id = segments[1]
        if not _YOUTUBE_CHANNEL_ID_PATTERN.fullmatch(channel_id):
            raise CreatorUrlError("YouTube channel 链接中的 Channel ID 无效")
        return ParsedCreatorUrl(
            platform="youtube",
            account_key=channel_id,
            canonical_url=f"https://www.youtube.com/channel/{channel_id}",
        )
    if segments and _YOUTUBE_HANDLE_PATTERN.fullmatch(segments[0]):
        handle = segments[0]
        return ParsedCreatorUrl(
            platform="youtube",
            account_key=handle,
            canonical_url=f"https://www.youtube.com/{handle}",
            requires_resolution=True,
        )
    if len(segments) >= 2 and segments[0].lower() in {
        "c",
        "user",
    }:
        slug = segments[1]
        if not slug:
            raise CreatorUrlError("YouTube 旧式频道链接缺少频道标识")
        prefix = segments[0].lower()
        return ParsedCreatorUrl(
            platform="youtube",
            account_key=f"{prefix}:{slug}",
            canonical_url=f"https://www.youtube.com/{prefix}/{slug}",
            requires_resolution=True,
        )
    raise CreatorUrlError(
        "YouTube 链接必须是 /@handle 或 /channel/UC... 频道主页"
    )


def extract_youtube_channel_id(
    page_text: str,
) -> str | None:
    """从 YouTube 频道页 HTML 中提取真实 Channel ID。"""
    if not isinstance(page_text, str):
        return None
    match = _YOUTUBE_RESOLVED_CHANNEL_PATTERN.search(page_text)
    if not match:
        return None
    channel_id = match.group(1)
    if not _YOUTUBE_CHANNEL_ID_PATTERN.fullmatch(channel_id):
        return None
    return channel_id


def _clean_url(
    url: str,
) -> str:
    """清理自然语言消息中常见的结尾标点，不改变 URL 内部内容。"""
    if not isinstance(url, str):
        raise CreatorUrlError("创作者链接必须是文本")
    cleaned = url.strip().rstrip(
        " \t\r\n，。！？；：,.!?;:）)]}"
    )
    parsed = urlsplit(cleaned)
    if parsed.scheme.lower() not in {
        "http",
        "https",
    }:
        raise CreatorUrlError("创作者链接必须使用 HTTP 或 HTTPS")
    if not parsed.netloc:
        raise CreatorUrlError("创作者链接缺少域名")
    return cleaned
