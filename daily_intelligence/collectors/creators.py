"""Bilibili 与 YouTube 创作者内容采集器。"""

from __future__ import annotations

from datetime import datetime, timezone
from html import unescape
import json
import random
import re
import time
from typing import Any, Callable, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, build_opener
import xml.etree.ElementTree as ElementTree

from ..creator_service import CreatorWindow
from ..creator_urls import extract_youtube_channel_id
from ..models import CreatorAccount, CreatorUpdate


BILIBILI_VIDEO_API = "https://api.bilibili.com/x/space/wbi/arc/search"
BILIBILI_DYNAMIC_API = (
    "https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/space"
)
BILIBILI_NAV_API = "https://api.bilibili.com/x/web-interface/nav"
BILIBILI_ACCOUNT_API = "https://api.bilibili.com/x/space/acc/info"
YOUTUBE_FEED_API = "https://www.youtube.com/feeds/videos.xml"
YOUTUBE_USER_AGENT = "DailyIntelligence/creator-updates"
DEFAULT_TIMEOUT_SECONDS = 15
DEFAULT_RETRIES = 2
MAX_BILIBILI_PAGES = 50
MAX_DYNAMIC_PAGES = 50


class CreatorHttpError(RuntimeError):
    """表示创作者平台请求失败或返回了不可解析的数据。"""


class _HttpClient:
    """提供可注入 opener、有限重试和退避的标准库 HTTP 基类。"""

    def __init__(
        self,
        opener: Any | None = None,
        retries: int = DEFAULT_RETRIES,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        """初始化可测试的 HTTP 客户端。"""
        self.opener = opener or build_opener()
        self.retries = max(
            0,
            retries,
        )
        self.timeout = timeout
        self.sleep = sleep or time.sleep

    def _request_bytes(
        self,
        url: str,
        headers: dict[str, str] | None = None,
    ) -> bytes:
        """发送 GET 请求并对临时失败执行有限指数退避。"""
        last_error: Exception | None = None
        for attempt in range(
            self.retries + 1
        ):
            request = Request(
                url,
                headers=headers or {},
                method="GET",
            )
            try:
                response = self.opener.open(
                    request,
                    timeout=self.timeout,
                )
                try:
                    return response.read()
                finally:
                    close = getattr(
                        response,
                        "close",
                        None,
                    )
                    if close:
                        close()
            except HTTPError as error:
                last_error = error
                retryable = error.code in {
                    408,
                    425,
                    429,
                } or error.code >= 500
                if not retryable or attempt >= self.retries:
                    raise CreatorHttpError(
                        f"HTTP {error.code} 请求失败: {url.split('?')[0]}"
                    ) from error
            except (
                OSError,
                TimeoutError,
                URLError,
            ) as error:
                last_error = error
                if attempt >= self.retries:
                    raise CreatorHttpError(
                        f"网络请求失败: {type(error).__name__}"
                    ) from error
            delay = min(
                8.0,
                0.5 * (2**attempt),
            ) + random.uniform(
                0.0,
                0.2,
            )
            self.sleep(delay)
        raise CreatorHttpError("请求失败") from last_error


class BilibiliClient(_HttpClient):
    """封装 Bilibili 账号、投稿和动态接口。"""

    def __init__(
        self,
        opener: Any | None = None,
        cookie: str | None = None,
        retries: int = DEFAULT_RETRIES,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        """初始化 Bilibili 客户端，Cookie 只保存在内存。"""
        super().__init__(
            opener=opener,
            retries=retries,
            timeout=timeout,
            sleep=sleep,
        )
        self.cookie = (cookie or "").strip() or None
        self._wbi_cache: tuple[str, str] | None = None

    def fetch_video_page(
        self,
        uid: str,
        page: int,
        page_size: int = 30,
    ) -> dict[str, Any]:
        """读取一页 UP 主投稿列表，使用 WBI 签名。"""
        params = {
            "mid": uid,
            "pn": str(page),
            "ps": str(page_size),
            "order": "pubdate",
        }
        keys = self._wbi_keys()
        if keys:
            params = sign_wbi(
                params,
                keys[0],
                keys[1],
            )
        return self._request_json(
            BILIBILI_VIDEO_API,
            params,
        )

    def fetch_dynamic_page(
        self,
        uid: str,
        offset: str = "",
    ) -> dict[str, Any]:
        """读取一页空间动态，offset 由接口响应返回。"""
        params = {
            "host_mid": uid,
            "offset": offset,
        }
        return self._request_json(
            BILIBILI_DYNAMIC_API,
            params,
        )

    def resolve_account_name(
        self,
        uid: str,
    ) -> str:
        """读取 Bilibili UID 对应的显示名称。"""
        payload = self._request_json(
            BILIBILI_ACCOUNT_API,
            {
                "mid": uid,
            },
        )
        name = str(
            ((payload.get("data") or {}).get("name") or "")
        ).strip()
        if not name:
            raise CreatorHttpError("Bilibili 账号响应缺少名称")
        return name

    def _wbi_keys(self) -> tuple[str, str] | None:
        """从 nav 接口读取并缓存 WBI 图片 key。"""
        if self._wbi_cache:
            return self._wbi_cache
        payload = self._request_json(
            BILIBILI_NAV_API,
            {},
            allowed_codes={
                -101,
            },
        )
        images = (
            ((payload.get("data") or {}).get("wbi_img") or {})
        )
        img_url = str(images.get("img_url") or "")
        sub_url = str(images.get("sub_url") or "")
        img_key = _wbi_key_from_url(img_url)
        sub_key = _wbi_key_from_url(sub_url)
        if not img_key or not sub_key:
            raise CreatorHttpError("Bilibili nav 响应缺少 WBI key")
        self._wbi_cache = (
            img_key,
            sub_key,
        )
        return self._wbi_cache

    def _request_json(
        self,
        endpoint: str,
        params: dict[str, str],
        allowed_codes: set[int] | None = None,
    ) -> dict[str, Any]:
        """请求 JSON 并验证 Bilibili code/data 结构。"""
        query = urlencode(
            params,
            doseq=True,
        )
        url = endpoint
        if query:
            url = f"{endpoint}?{query}"
        headers = {
            "Accept": "application/json",
            "User-Agent": YOUTUBE_USER_AGENT,
            "Referer": "https://www.bilibili.com/",
        }
        if self.cookie:
            headers["Cookie"] = self.cookie
        try:
            payload = json.loads(
                self._request_bytes(
                    url,
                    headers=headers,
                ).decode("utf-8")
            )
        except (
            UnicodeError,
            json.JSONDecodeError,
        ) as error:
            raise CreatorHttpError("Bilibili 响应不是有效 JSON") from error
        if not isinstance(payload, dict):
            raise CreatorHttpError("Bilibili 响应结构无效")
        code = payload.get("code")
        accepted_codes = {
            0,
            None,
        }
        accepted_codes.update(
            allowed_codes or set()
        )
        if code not in accepted_codes:
            message = str(payload.get("message") or "未知错误")
            raise CreatorHttpError(
                f"Bilibili 接口返回错误 {code}: {message[:120]}"
            )
        return payload


class BilibiliCollector:
    """把 Bilibili 投稿和空间动态转换为统一事件模型。"""

    def __init__(
        self,
        client: BilibiliClient,
    ) -> None:
        """绑定 Bilibili 客户端。"""
        self.client = client

    def collect_videos(
        self,
        account: CreatorAccount | dict[str, Any],
        window: CreatorWindow,
    ) -> list[CreatorUpdate]:
        """分页获取窗口内投稿，过早的页面会停止继续请求。"""
        uid = _account_value(
            account,
            "account_key",
        )
        creator_name = _account_value(
            account,
            "display_name",
        )
        result: list[CreatorUpdate] = []
        seen: set[str] = set()
        for page in range(
            1,
            MAX_BILIBILI_PAGES + 1,
        ):
            payload = self.client.fetch_video_page(
                uid,
                page,
            )
            records = _nested_list(
                payload,
                (
                    "data",
                    "list",
                    "vlist",
                ),
            )
            if not records:
                break
            page_info = data = payload.get("data") or {}
            page_meta = data.get("page") or {}
            try:
                current_page = int(page_meta.get("pn") or page)
                total_pages = int(page_meta.get("count") or 0)
            except (
                TypeError,
                ValueError,
            ):
                current_page = page
                total_pages = 0
            has_more = (
                current_page < total_pages
                if total_pages > 0
                else len(records) >= 30
            )
            page_times: list[datetime] = []
            for record in records:
                update = parse_bilibili_video(
                    record,
                    creator_name=creator_name,
                    window=window,
                )
                published = _parse_platform_datetime(
                    record.get("created")
                    or record.get("pubdate")
                    or record.get("ctime")
                )
                if published:
                    page_times.append(published)
                if update is None or update.external_id in seen:
                    continue
                seen.add(update.external_id)
                result.append(update)
            if page_times and all(
                value <= window.window_start
                for value in page_times
            ):
                break
            if not has_more:
                break
        result.sort(
            key=lambda item: item.published_at,
            reverse=True,
        )
        return result

    def collect_dynamics(
        self,
        account: CreatorAccount | dict[str, Any],
        window: CreatorWindow,
    ) -> list[CreatorUpdate]:
        """按 offset 游标读取动态，过滤视频投稿卡片。"""
        uid = _account_value(
            account,
            "account_key",
        )
        default_name = _account_value(
            account,
            "display_name",
        )
        result: list[CreatorUpdate] = []
        seen: set[str] = set()
        offset = ""
        for _ in range(
            MAX_DYNAMIC_PAGES
        ):
            payload = self.client.fetch_dynamic_page(
                uid,
                offset,
            )
            data = payload.get("data") or {}
            records = data.get("items") or []
            if not isinstance(records, list) or not records:
                break
            page_times: list[datetime] = []
            for record in records:
                update = parse_bilibili_dynamic(
                    record,
                    creator_name=default_name,
                    window=window,
                )
                published = _dynamic_datetime(record)
                if published:
                    page_times.append(published)
                if update is None or update.external_id in seen:
                    continue
                seen.add(update.external_id)
                result.append(update)
            next_offset = str(data.get("offset") or "")
            has_more = bool(data.get("has_more"))
            if not has_more or next_offset == offset:
                break
            if page_times and min(page_times) <= window.window_start:
                break
            offset = next_offset
        result.sort(
            key=lambda item: item.published_at,
            reverse=True,
        )
        return result


class YouTubeClient(_HttpClient):
    """读取公开 YouTube 频道页面和 Atom Feed。"""

    def fetch_feed(
        self,
        channel_id: str,
    ) -> bytes:
        """读取频道公开 Atom Feed，不需要 API Key。"""
        url = f"{YOUTUBE_FEED_API}?channel_id={channel_id}"
        return self._request_bytes(
            url,
            headers={
                "Accept": "application/atom+xml,application/xml",
                "User-Agent": YOUTUBE_USER_AGENT,
            },
        )

    def resolve_channel(
        self,
        url: str,
    ) -> tuple[str, str]:
        """从 handle 或旧式频道页解析真实 Channel ID 和名称。"""
        page = self._request_bytes(
            url,
            headers={
                "Accept": "text/html",
                "User-Agent": YOUTUBE_USER_AGENT,
            },
        ).decode("utf-8", errors="replace")
        channel_id = extract_youtube_channel_id(page)
        if not channel_id:
            raise CreatorHttpError(
                "无法从 YouTube 频道页解析真实 Channel ID，请提供 /channel/UC... 链接"
            )
        title_match = re.search(
            r"<title[^>]*>(.*?)</title>",
            page,
            flags=re.IGNORECASE | re.DOTALL,
        )
        name = unescape(
            re.sub(
                r"\s+",
                " ",
                title_match.group(1),
            ).strip()
            if title_match
            else channel_id
        )
        return channel_id, name.removesuffix(" - YouTube").strip()


class YouTubeCollector:
    """把公开 Atom Feed 转换为窗口内 YouTube 视频事件。"""

    def __init__(
        self,
        client: YouTubeClient,
    ) -> None:
        """绑定 YouTube 客户端。"""
        self.client = client

    def collect_videos(
        self,
        account: CreatorAccount | dict[str, Any],
        window: CreatorWindow,
    ) -> list[CreatorUpdate]:
        """读取频道 Feed 并按 Video ID 去重、过滤时间窗口。"""
        channel_id = _account_value(
            account,
            "account_key",
        )
        return parse_youtube_feed(
            self.client.fetch_feed(channel_id),
            window,
            default_creator_name=_account_value(
                account,
                "display_name",
            ),
            channel_id=channel_id,
        )


def parse_bilibili_video(
    record: dict[str, Any],
    creator_name: str,
    window: CreatorWindow,
) -> CreatorUpdate | None:
    """解析单条 Bilibili 投稿，发布时间不在窗口内时返回空值。"""
    external_id = str(
        record.get("bvid")
        or record.get("BV")
        or ""
    ).strip()
    published = _parse_platform_datetime(
        record.get("created")
        or record.get("pubdate")
        or record.get("ctime")
    )
    if not external_id or not published or not window.contains(published):
        return None
    title = _clean_text(
        record.get("title")
        or external_id
    )
    description = _clean_text(
        record.get("description")
        or record.get("desc")
        or ""
    )
    url = str(
        record.get("arcurl")
        or record.get("url")
        or f"https://www.bilibili.com/video/{external_id}"
    ).strip()
    metadata = {
        "video_id": external_id,
        "thumbnail": str(
            record.get("pic")
            or record.get("cover")
            or ""
        ).strip(),
    }
    return CreatorUpdate(
        platform="bilibili",
        content_type="video",
        external_id=external_id,
        creator_name=creator_name,
        title=title,
        url=url,
        published_at=published.isoformat(),
        summary=description[:500],
        content=description,
        metadata=metadata,
    )


def parse_bilibili_dynamic(
    record: dict[str, Any],
    creator_name: str,
    window: CreatorWindow,
) -> CreatorUpdate | None:
    """解析文字、图片、转发和专栏动态，跳过视频投稿卡片。"""
    if _dynamic_video_id(record):
        return None
    external_id = _dynamic_id(record)
    published = _dynamic_datetime(record)
    if not external_id or not published or not window.contains(published):
        return None
    modules = record.get("modules") or {}
    author = modules.get("module_author") or {}
    dynamic = modules.get("module_dynamic") or {}
    desc = dynamic.get("desc") or {}
    text = _clean_text(
        desc.get("text")
        or _rich_text(desc.get("rich_text_nodes"))
        or ""
    )
    dynamic_type = _dynamic_type(
        record,
    )
    if dynamic_type == "转发动态":
        original = dynamic.get("orig") or {}
        original_desc = original.get("desc") or {}
        original_text = _clean_text(
            original_desc.get("text")
            or _rich_text(original_desc.get("rich_text_nodes"))
            or ""
        )
        if original_text:
            text = f"{text} | 原动态：{original_text}"
    images = _dynamic_images(record)
    title = text[:80] or f"{dynamic_type}"
    return CreatorUpdate(
        platform="bilibili",
        content_type="dynamic",
        external_id=external_id,
        creator_name=_clean_text(
            author.get("name")
            or creator_name
        ),
        title=title,
        url=f"https://t.bilibili.com/{external_id}",
        published_at=published.isoformat(),
        summary=text[:500],
        content=text,
        metadata={
            "dynamic_type": dynamic_type,
            "images": images,
        },
    )


def parse_youtube_feed(
    payload: bytes,
    window: CreatorWindow,
    default_creator_name: str = "",
    channel_id: str = "",
) -> list[CreatorUpdate]:
    """解析 YouTube Atom XML，并拒绝重复或显式直播条目。"""
    try:
        root = ElementTree.fromstring(payload)
    except ElementTree.ParseError as error:
        raise CreatorHttpError("YouTube Atom Feed XML 解析失败") from error
    feed_title = _xml_child_text(
        root,
        "title",
    )
    result: list[CreatorUpdate] = []
    seen: set[str] = set()
    for entry in _xml_children(
        root,
        "entry",
    ):
        if _xml_has_live_marker(entry):
            continue
        video_id = _xml_child_text(
            entry,
            "videoId",
        )
        published_value = _xml_child_text(
            entry,
            "published",
        )
        published = _parse_platform_datetime(published_value)
        if not video_id or video_id in seen or not published:
            continue
        if not window.contains(published):
            continue
        seen.add(video_id)
        title = _xml_child_text(
            entry,
            "title",
        ) or video_id
        author = _xml_descendant_text(
            entry,
            "name",
        ) or default_creator_name or feed_title or channel_id
        link = _xml_link(entry)
        thumbnail = _xml_thumbnail(entry)
        result.append(
            CreatorUpdate(
                platform="youtube",
                content_type="video",
                external_id=video_id,
                creator_name=author,
                title=_clean_text(title),
                url=link
                or f"https://www.youtube.com/watch?v={video_id}",
                published_at=published.isoformat(),
                summary=_clean_text(title),
                metadata={
                    "video_id": video_id,
                    "channel_id": channel_id,
                    "thumbnail": thumbnail,
                },
            )
        )
    result.sort(
        key=lambda item: item.published_at,
        reverse=True,
    )
    return result


def sign_wbi(
    params: dict[str, str],
    img_key: str,
    sub_key: str,
    now: int | None = None,
) -> dict[str, str]:
    """按 Bilibili WBI 规则生成 wts 和 w_rid 参数。"""
    import hashlib

    mixin = _mixin_key(
        img_key + sub_key,
    )
    signed = {
        key: str(value)
        for key, value in params.items()
    }
    signed["wts"] = str(
        now
        if now is not None
        else int(time.time())
    )
    query = "&".join(
        f"{quote(str(key), safe='')}="
        f"{quote(str(value), safe='')}"
        for key, value in sorted(signed.items())
    )
    query = re.sub(
        r"[!'()*]",
        "",
        query,
    )
    signed["w_rid"] = hashlib.md5(
        (query + mixin).encode("utf-8")
    ).hexdigest()
    return signed


def _wbi_key_from_url(
    value: str,
) -> str:
    """从 WBI 图片 URL 提取文件名主干。"""
    name = value.rsplit(
        "/",
        1,
    )[-1]
    return name.split(
        ".",
        1,
    )[0]


def _mixin_key(
    value: str,
) -> str:
    """执行 Bilibili 官方 WBI 混淆表并截取 32 字符。"""
    table = (
        46,
        47,
        18,
        2,
        53,
        8,
        23,
        32,
        15,
        50,
        10,
        31,
        58,
        3,
        45,
        35,
        27,
        43,
        5,
        49,
        33,
        9,
        42,
        19,
        29,
        28,
        14,
        39,
        12,
        38,
        41,
        13,
        37,
        48,
        7,
        16,
        24,
        55,
        40,
        61,
        26,
        17,
        0,
        1,
        60,
        51,
        30,
        4,
        22,
        25,
        54,
        21,
        56,
        59,
        6,
        63,
        57,
        62,
        11,
        36,
        20,
        34,
        44,
        52,
    )
    return "".join(
        value[index]
        for index in table
        if index < len(value)
    )[:32]


def _account_value(
    account: CreatorAccount | dict[str, Any],
    key: str,
) -> str:
    """从 dataclass 或数据库字典读取必需的账号字段。"""
    if isinstance(account, dict):
        return str(account.get(key) or "").strip()
    return str(getattr(account, key, "") or "").strip()


def _nested_list(
    value: dict[str, Any],
    path: Iterable[str],
) -> list[dict[str, Any]]:
    """安全读取嵌套列表结构。"""
    current: Any = value
    for key in path:
        if not isinstance(current, dict):
            return []
        current = current.get(key)
    if not isinstance(current, list):
        return []
    return [
        item
        for item in current
        if isinstance(item, dict)
    ]


def _parse_platform_datetime(
    value: Any,
) -> datetime | None:
    """解析 epoch 秒或 ISO 时间为 UTC datetime。"""
    if value in {
        None,
        "",
    }:
        return None
    try:
        if isinstance(value, (int, float)) or str(value).isdigit():
            return datetime.fromtimestamp(
                float(value),
                tz=timezone.utc,
            )
        parsed = datetime.fromisoformat(
            str(value).replace(
                "Z",
                "+00:00",
            )
        )
        if parsed.tzinfo is None:
            parsed = parsed.replace(
                tzinfo=timezone.utc,
            )
        return parsed.astimezone(timezone.utc)
    except (
        TypeError,
        ValueError,
        OverflowError,
    ):
        return None


def _clean_text(
    value: Any,
) -> str:
    """清理 HTML 标签和连续空白，限制为外部文本内容。"""
    text = unescape(
        re.sub(
            r"<[^>]+>",
            " ",
            str(value or ""),
        )
    )
    return re.sub(
        r"\s+",
        " ",
        text,
    ).strip()


def _rich_text(
    nodes: Any,
) -> str:
    """把 Bilibili rich_text_nodes 安全拼接为纯文本。"""
    if not isinstance(nodes, list):
        return ""
    return "".join(
        str(node.get("text") or "")
        for node in nodes
        if isinstance(node, dict)
    )


def _dynamic_id(
    record: dict[str, Any],
) -> str:
    """从不同动态卡片结构提取 Dynamic ID。"""
    desc = record.get("desc") or {}
    return str(
        record.get("id_str")
        or record.get("dynamic_id_str")
        or record.get("dynamic_id")
        or desc.get("dynamic_id_str")
        or ""
    ).strip()


def _dynamic_datetime(
    record: dict[str, Any],
) -> datetime | None:
    """从动态作者模块或旧字段读取发布时间。"""
    modules = record.get("modules") or {}
    author = modules.get("module_author") or {}
    return _parse_platform_datetime(
        author.get("pub_ts")
        or author.get("pub_time")
        or record.get("pub_ts")
        or record.get("ctime")
    )


def _dynamic_video_id(
    record: dict[str, Any],
) -> str | None:
    """识别动态卡片中的视频 BV 号。"""
    modules = record.get("modules") or {}
    dynamic = modules.get("module_dynamic") or {}
    major = dynamic.get("major") or {}
    archive = major.get("archive") or {}
    bvid = str(
        archive.get("bvid")
        or archive.get("aid")
        or ""
    ).strip()
    return bvid or None


def _dynamic_type(
    record: dict[str, Any],
) -> str:
    """把 Bilibili 动态类型映射为日报中文标签。"""
    record_type = str(record.get("type") or "").upper()
    if "FORWARD" in record_type:
        return "转发动态"
    if "DRAW" in record_type:
        return "图片动态"
    if "ARTICLE" in record_type:
        return "专栏动态"
    return "文字动态"


def _dynamic_images(
    record: dict[str, Any],
) -> list[str]:
    """提取图片动态中的图片地址并去重。"""
    modules = record.get("modules") or {}
    dynamic = modules.get("module_dynamic") or {}
    major = dynamic.get("major") or {}
    draw = major.get("draw") or {}
    values: list[str] = []
    for item in draw.get("items") or []:
        if not isinstance(item, dict):
            continue
        src = str(
            item.get("src")
            or item.get("url")
            or ""
        ).strip()
        if src and src not in values:
            values.append(src)
    return values


def _xml_children(
    element: ElementTree.Element,
    local_name: str,
) -> list[ElementTree.Element]:
    """按本地标签名读取 XML 直接子节点。"""
    return [
        child
        for child in list(element)
        if child.tag.rsplit(
            "}",
            1,
        )[-1] == local_name
    ]


def _xml_descendants(
    element: ElementTree.Element,
    local_name: str,
) -> list[ElementTree.Element]:
    """按本地标签名读取 XML 后代节点。"""
    return [
        child
        for child in element.iter()
        if child.tag.rsplit(
            "}",
            1,
        )[-1] == local_name
    ]


def _xml_child_text(
    element: ElementTree.Element,
    local_name: str,
) -> str:
    """读取 XML 节点文本。"""
    values = _xml_children(
        element,
        local_name,
    )
    return _clean_text(
        values[0].text
        if values
        else ""
    )


def _xml_descendant_text(
    element: ElementTree.Element,
    local_name: str,
) -> str:
    """读取第一个后代节点文本。"""
    values = _xml_descendants(
        element,
        local_name,
    )
    return _clean_text(
        values[0].text
        if values
        else ""
    )


def _xml_link(
    entry: ElementTree.Element,
) -> str:
    """读取 Atom alternate 链接。"""
    for link in _xml_children(
        entry,
        "link",
    ):
        if link.attrib.get("rel") in {
            None,
            "alternate",
        }:
            return str(link.attrib.get("href") or "").strip()
    return ""


def _xml_thumbnail(
    entry: ElementTree.Element,
) -> str:
    """读取 media:thumbnail 图片地址。"""
    thumbnails = _xml_descendants(
        entry,
        "thumbnail",
    )
    return str(
        thumbnails[0].attrib.get("url")
        if thumbnails
        else ""
    ).strip()


def _xml_has_live_marker(
    entry: ElementTree.Element,
) -> bool:
    """识别 Atom 中明确标记为直播的条目，避免误采集直播。"""
    for node in entry.iter():
        local_name = node.tag.rsplit(
            "}",
            1,
        )[-1].lower()
        if "livebroadcast" in local_name or local_name == "livestream":
            return True
        value = (node.text or "").strip().lower()
        if value in {
            "live",
            "livestream",
        } and local_name in {
            "videotype",
            "broadcastcontent",
        }:
            return True
    return False
