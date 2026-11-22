"""GitHub 官方 API 采集器。"""

from __future__ import annotations

import base64
import binascii
import json
import re
import socket
import ssl
import time
from collections import OrderedDict
from copy import deepcopy
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from math import isfinite
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, quote, unquote, urlsplit
from urllib.request import (
    HTTPRedirectHandler,
    ProxyHandler,
    Request,
    build_opener,
    getproxies,
    proxy_bypass,
)

from ..deduplication import deduplicate_items
from ..config import load_project_settings
from ..models import Item


GITHUB_API_URL = "https://api.github.com"
GITHUB_API_HOST = "api.github.com"
DEFAULT_USER_AGENT = "DailyIntelligence"
DEFAULT_API_VERSION = "2022-11-28"
DEFAULT_MAX_RETRIES = 2
DEFAULT_MAX_WAIT_SECONDS = 30.0
DEFAULT_ETAG_CACHE_SIZE = 128
MAX_RETRIES_HARD_LIMIT = 5
README_MAX_CHARS = 12000
DEFAULT_README_LIMIT = 15


def _redact_text(
    value: object,
    token: str | None,
) -> str:
    """将异常文本中的当前 Token 替换为固定占位符。"""
    text = str(value)
    if token:
        for secret in {
            token,
            quote(
                token,
                safe="",
            ),
        }:
            text = text.replace(
                secret,
                "[REDACTED]",
            )
    return text


class GitHubAPIError(HTTPError):
    """表示已清理敏感信息的 GitHub API 错误。"""

    def __init__(
        self,
        code: int,
        message: str,
        token: str | None = None,
    ) -> None:
        """创建不包含请求 URL 和 Token 的 HTTP 异常。"""
        super().__init__(
            GITHUB_API_URL,
            code,
            _redact_text(
                message,
                token,
            ),
            None,
            None,
        )


class GitHubNetworkError(URLError):
    """表示已清理敏感信息的 GitHub 网络错误。"""

    def __init__(
        self,
        category: str,
        reason_type: str,
        proxy_configured: bool,
        token: str | None = None,
    ) -> None:
        """创建只记录类别、底层异常类型和代理状态的网络异常。"""
        self.category = category
        self.reason_type = reason_type
        self.proxy_configured = proxy_configured
        super().__init__(
            _redact_text(
                "GitHub API network error: "
                f"category={category}; "
                f"reason_type={reason_type}; "
                "proxy="
                f"{'configured' if proxy_configured else 'not-configured'}",
                token,
            )
        )


class GitHubProxyConfigError(ValueError):
    """表示 GITHUB_PROXY 配置无效或会被 NO_PROXY 绕过。"""


class _RejectRedirectHandler(HTTPRedirectHandler):
    """拒绝所有重定向，避免 Authorization 被带到其他主机。"""

    def redirect_request(
        self,
        req: Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> Request:
        """在重定向请求创建前直接终止流程。"""
        raise GitHubAPIError(
            code,
            "GitHub API redirect rejected",
        )


def _validate_proxy_url(
    value: str,
) -> tuple[str, str, int | None]:
    """校验项目代理地址并返回安全元数据，不回显代理内容。"""
    candidate = value.strip()
    if not candidate or any(
        character.isspace()
        for character in candidate
    ):
        raise GitHubProxyConfigError(
            "GITHUB_PROXY 必须是有效的 http/https 代理地址"
        )
    try:
        parsed = urlsplit(candidate)
        scheme = parsed.scheme.casefold()
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        raise GitHubProxyConfigError(
            "GITHUB_PROXY 的 URL 或端口格式无效"
        ) from None
    if scheme not in {
        "http",
        "https",
    }:
        raise GitHubProxyConfigError(
            "GITHUB_PROXY 只支持 http 或 https scheme"
        )
    if not hostname:
        raise GitHubProxyConfigError(
            "GITHUB_PROXY 必须包含代理主机名"
        )
    if parsed.path not in {
        "",
        "/",
    } or parsed.query or parsed.fragment:
        raise GitHubProxyConfigError(
            "GITHUB_PROXY 不得包含路径、查询参数或片段"
        )
    if port is not None and not 1 <= port <= 65535:
        raise GitHubProxyConfigError(
            "GITHUB_PROXY 端口必须位于 1 到 65535 之间"
        )
    return candidate, scheme, port


def _build_safe_opener(
    proxy_url: str | None = None,
) -> Any:
    """创建 GitHub 专用 opener，不修改 urllib 全局状态。"""
    handlers: list[Any] = []
    if proxy_url:
        handlers.append(
            ProxyHandler(
                {
                    "http": proxy_url,
                    "https": proxy_url,
                }
            )
        )
    handlers.append(
        _RejectRedirectHandler()
    )
    return build_opener(
        *handlers,
    )


def _safe_urlopen(
    request: Request,
    timeout: int,
    proxy_url: str | None = None,
) -> Any:
    """使用 GitHub 专用 opener 发起请求。"""
    return _build_safe_opener(
        proxy_url,
    ).open(
        request,
        timeout=timeout,
    )


def _network_error_details(
    error: BaseException,
    proxy_configured: bool,
) -> tuple[str, str]:
    """根据 URLError.reason 识别脱敏的网络故障类别。"""
    reason = getattr(
        error,
        "reason",
        error,
    )
    reason_type = type(reason).__name__
    reason_text = str(reason).casefold()
    if (
        isinstance(reason, ssl.SSLError)
        or "ssl" in reason_type.casefold()
        or "certificate" in reason_text
        or "tls" in reason_text
    ):
        return "TLS", reason_type
    if (
        isinstance(reason, socket.gaierror)
        or "gaierror" in reason_type.casefold()
        or "name or service not known" in reason_text
        or "nodename nor servname" in reason_text
        or "temporary failure in name resolution" in reason_text
    ):
        return "DNS", reason_type
    if (
        isinstance(reason, (TimeoutError, socket.timeout))
        or "timed out" in reason_text
        or "timeout" in reason_text
    ):
        return "timeout", reason_type
    if proxy_configured and (
        "proxy" in reason_text
        or "tunnel" in reason_text
        or isinstance(
            reason,
            ConnectionError,
        )
    ):
        return "proxy", reason_type
    if isinstance(
        reason,
        (ConnectionError, OSError),
    ):
        return "connection", reason_type
    return "network", reason_type


def _header_value(
    headers: Any,
    name: str,
) -> str | None:
    """大小写不敏感地读取响应头。"""
    if headers is None:
        return None
    try:
        value = headers.get(name)
    except AttributeError:
        value = None
    if value is not None:
        return str(value)
    try:
        for key, candidate in headers.items():
            if str(key).lower() == name.lower():
                return str(candidate)
    except AttributeError:
        return None
    return None


def _response_status(
    response: Any,
) -> int | None:
    """读取 urllib 响应的状态码。"""
    status = getattr(
        response,
        "status",
        None,
    )
    if status is None:
        getcode = getattr(
            response,
            "getcode",
            None,
        )
        if callable(getcode):
            status = getcode()
    try:
        return int(status) if status is not None else None
    except (TypeError, ValueError):
        return None


def _response_url(
    response: Any,
) -> str | None:
    """读取响应最终 URL，缺失时返回空值。"""
    geturl = getattr(
        response,
        "geturl",
        None,
    )
    if not callable(geturl):
        return None
    value = geturl()
    return str(value) if value else None


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
    """封装 GitHub API 请求、鉴权、限流重试和进程内缓存。"""

    def __init__(
        self,
        token: str | None = None,
        timeout: int = 15,
        retries: int = DEFAULT_MAX_RETRIES,
        opener: Callable[..., Any] | None = None,
        sleep_fn: Callable[[float], None] | None = None,
        max_wait_seconds: float = DEFAULT_MAX_WAIT_SECONDS,
        time_fn: Callable[[], float] | None = None,
        etag_cache_size: int = DEFAULT_ETAG_CACHE_SIZE,
        project_root: Path | str | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        """初始化可注入网络客户端，便于离线测试。"""
        settings = load_project_settings(
            project_root=project_root,
            environ=environ,
        )
        runtime_token = (
            settings.github_token
            if token is None
            else token
        )
        self.token = (
            runtime_token.strip()
            if isinstance(runtime_token, str)
            and runtime_token.strip()
            else None
        )
        self.timeout = timeout
        self.max_retries = min(
            MAX_RETRIES_HARD_LIMIT,
            max(0, int(retries)),
        )
        self.retries = self.max_retries
        self.proxy_mode = "auto"
        self.proxy_source = settings.github_proxy_source
        self.proxy_scheme: str | None = None
        self.proxy_port: int | None = None
        self._proxy_url: str | None = None
        explicit_proxy = settings.github_proxy
        if explicit_proxy:
            (
                self._proxy_url,
                self.proxy_scheme,
                self.proxy_port,
            ) = _validate_proxy_url(
                explicit_proxy,
            )
            if proxy_bypass(
                GITHUB_API_HOST,
            ):
                raise GitHubProxyConfigError(
                    "GITHUB_PROXY 与 NO_PROXY 冲突，"
                    "api.github.com 将被自动绕过"
                )
            self.proxy_mode = "explicit"
            self.proxy_configured = True
        else:
            self.proxy_source = "auto"
            self.proxy_configured = bool(
                getproxies()
            ) and not proxy_bypass(
                GITHUB_API_HOST,
            )
        self.max_wait_seconds = float(max_wait_seconds)
        if (
            not isfinite(self.max_wait_seconds)
            or self.max_wait_seconds < 0
        ):
            raise ValueError(
                "max_wait_seconds 必须为有限非负数"
            )
        self._http_opener = None
        if opener is not None:
            self.opener = opener
        else:
            self._http_opener = _build_safe_opener(
                self._proxy_url,
            )
            self.opener = self._http_opener.open
        self.sleep_fn = sleep_fn or time.sleep
        self.time_fn = time_fn or time.time
        self.etag_cache_size = max(
            1,
            int(etag_cache_size),
        )
        self._etag_cache: OrderedDict[
            str,
            tuple[str | None, dict[str, Any]],
        ] = OrderedDict()

    def get_json(
        self,
        path: str,
    ) -> dict[str, Any]:
        """请求一个 GitHub API 路径并解析 JSON 对象。"""
        request_url = self._build_api_url(path)
        cached_entry = self._etag_cache.get(request_url)
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": DEFAULT_API_VERSION,
            "User-Agent": DEFAULT_USER_AGENT,
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if cached_entry and cached_entry[0]:
            headers["If-None-Match"] = cached_entry[0]

        for attempt in range(self.retries + 1):
            request = Request(
                request_url,
                headers=headers,
                method="GET",
            )
            try:
                with self._open_request(request) as response:
                    response_headers = getattr(
                        response,
                        "headers",
                        None,
                    )
                    status = _response_status(response)
                    if status == 304:
                        return self._cached_body(request_url)
                    if status is not None and 300 <= status < 400:
                        raise GitHubAPIError(
                            status,
                            "GitHub API redirect rejected",
                            self.token,
                        )
                    if status is not None and status >= 400:
                        body = response.read()
                        error = HTTPError(
                            request_url,
                            status,
                            f"GitHub API HTTP {status}",
                            response_headers,
                            None,
                        )
                        setattr(
                            error,
                            "_github_error_body",
                            self._decode_error_body(body),
                        )
                        raise error
                    payload_bytes = response.read()

                try:
                    payload = json.loads(
                        payload_bytes.decode("utf-8")
                    )
                except (
                    UnicodeDecodeError,
                    json.JSONDecodeError,
                ):
                    raise ValueError(
                        "GitHub API 返回无效 JSON"
                    ) from None
                if not isinstance(payload, dict):
                    raise ValueError(
                        "GitHub API 返回值不是 JSON 对象"
                    )
                self._store_etag(
                    request_url,
                    payload,
                    response_headers,
                )
                return deepcopy(payload)
            except GitHubAPIError:
                raise
            except HTTPError as error:
                if error.code == 304:
                    self._close_http_error(error)
                    return self._cached_body(request_url)
                if (
                    error.code in {
                        403,
                        429,
                    }
                    and self._is_secondary_rate_limit(error)
                ):
                    self._close_http_error(error)
                    raise GitHubAPIError(
                        error.code,
                        "GitHub API secondary rate limit; retries stopped",
                        self.token,
                    ) from None
                if not self._should_retry(
                    error,
                    attempt,
                ):
                    sanitized_error = self._sanitize_http_error(error)
                    self._close_http_error(error)
                    raise sanitized_error from None
                wait_seconds, reset_at = self._retry_wait(error, attempt)
                self._close_http_error(error)
                if wait_seconds > self.max_wait_seconds:
                    raise GitHubAPIError(
                        error.code,
                        "GitHub API rate limit wait exceeds cap: "
                        f"reset_at={reset_at or 'unknown'} "
                        f"wait_seconds={self._format_seconds(wait_seconds)} "
                        "max_wait_seconds="
                        f"{self._format_seconds(self.max_wait_seconds)}",
                        self.token,
                    ) from None
                self.sleep_fn(wait_seconds)
            except (
                URLError,
                TimeoutError,
                ConnectionError,
            ) as error:
                if attempt >= self.retries:
                    category, reason_type = _network_error_details(
                        error,
                        self.proxy_configured,
                    )
                    raise GitHubNetworkError(
                        category,
                        reason_type,
                        self.proxy_configured,
                        self.token,
                    ) from None
                wait_seconds = float(
                    2 ** attempt
                )
                if wait_seconds > self.max_wait_seconds:
                    category, reason_type = _network_error_details(
                        error,
                        self.proxy_configured,
                    )
                    raise GitHubNetworkError(
                        f"{category}; retry wait exceeds cap",
                        reason_type,
                        self.proxy_configured,
                        self.token,
                    ) from None
                self.sleep_fn(wait_seconds)
        raise RuntimeError("GitHub API 重试流程异常结束")

    def _build_api_url(
        self,
        path: str,
    ) -> str:
        """只允许 HTTPS api.github.com，并拒绝凭据查询参数。"""
        candidate = str(path)
        if candidate.startswith("//"):
            raise ValueError(
                "GitHub API URL 必须使用 https://api.github.com"
            )
        try:
            parsed_input = urlsplit(candidate)
            if not parsed_input.scheme and not parsed_input.netloc:
                suffix = (
                    candidate
                    if candidate.startswith("/")
                    else f"/{candidate}"
                )
                candidate = f"{GITHUB_API_URL}{suffix}"
            parsed = urlsplit(candidate)
            hostname = (parsed.hostname or "").lower()
            port = parsed.port
        except ValueError:
            raise ValueError(
                "GitHub API URL 必须使用 https://api.github.com"
            ) from None
        if (
            parsed.scheme.lower() != "https"
            or hostname != GITHUB_API_HOST
            or port is not None
            or parsed.username
            or parsed.password
        ):
            raise ValueError(
                "GitHub API URL 必须使用 https://api.github.com"
            )
        query_keys = {
            key.lower()
            for key, _ in self._query_pairs(parsed.query)
        }
        if query_keys.intersection(
            {
                "token",
                "access_token",
                "authorization",
            }
        ):
            raise ValueError(
                "GitHub API URL 不得包含凭据查询参数"
            )
        if self.token and (
            self.token in candidate
            or self.token in unquote(candidate)
        ):
            raise ValueError(
                "GitHub API URL 不得包含凭据"
            )
        return candidate

    @staticmethod
    def _query_pairs(
        query: str,
    ) -> list[tuple[str, str]]:
        """解析查询键名而不记录查询值。"""
        return parse_qsl(
            query,
            keep_blank_values=True,
        )

    def _open_request(
        self,
        request: Request,
    ) -> Any:
        """打开请求并拒绝非 GitHub API 的最终响应地址。"""
        if self.proxy_mode == "explicit" and proxy_bypass(
            GITHUB_API_HOST,
        ):
            raise GitHubProxyConfigError(
                "GITHUB_PROXY 与 NO_PROXY 冲突，"
                "api.github.com 将被自动绕过"
            )
        response = self.opener(
            request,
            timeout=self.timeout,
        )
        try:
            self._validate_response_url(response)
        except Exception:
            close = getattr(
                response,
                "close",
                None,
            )
            if callable(close):
                close()
            raise
        return response

    def _validate_response_url(
        self,
        response: Any,
    ) -> None:
        """校验响应最终 URL，防止注入的 opener 绕过主机限制。"""
        response_url = _response_url(response)
        if response_url is None:
            return
        try:
            self._build_api_url(response_url)
        except ValueError:
            raise GitHubAPIError(
                310,
                "GitHub API redirect target rejected",
                self.token,
            ) from None

    def _cached_body(
        self,
        request_url: str,
    ) -> dict[str, Any]:
        """返回 304 对应的内存缓存，缺失时抛出清理后的错误。"""
        cached_entry = self._etag_cache.get(request_url)
        if cached_entry is None:
            raise GitHubAPIError(
                304,
                "GitHub API returned 304 without a cached body",
                self.token,
            )
        self._etag_cache.move_to_end(request_url)
        return deepcopy(cached_entry[1])

    def _store_etag(
        self,
        request_url: str,
        payload: dict[str, Any],
        headers: Any,
    ) -> None:
        """在固定容量的进程内缓存中保存响应体和 ETag。"""
        self._etag_cache[request_url] = (
            _header_value(
                headers,
                "ETag",
            ),
            deepcopy(payload),
        )
        self._etag_cache.move_to_end(request_url)
        while len(self._etag_cache) > self.etag_cache_size:
            self._etag_cache.popitem(
                last=False
            )

    def _should_retry(
        self,
        error: HTTPError,
        attempt: int,
    ) -> bool:
        """判断限流或暂时性服务端错误是否允许重试。"""
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

    def _retry_wait(
        self,
        error: HTTPError,
        attempt: int,
    ) -> tuple[float, str | None]:
        """按 Retry-After、HTTP-date、Reset 或退避计算等待时间。"""
        retry_after = _header_value(
            error.headers,
            "Retry-After",
        )
        now = float(
            self.time_fn()
        )
        if not isfinite(now):
            now = time.time()
        if retry_after:
            try:
                numeric = float(retry_after)
                if isfinite(numeric):
                    wait_seconds = max(
                        0.0,
                        numeric,
                    )
                    return (
                        wait_seconds,
                        self._format_reset_at(
                            now + wait_seconds
                        ),
                    )
            except (TypeError, ValueError):
                pass
            try:
                retry_at = parsedate_to_datetime(retry_after)
                if retry_at.tzinfo is None:
                    retry_at = retry_at.replace(
                        tzinfo=timezone.utc
                    )
                wait_seconds = max(
                    0.0,
                    retry_at.timestamp() - now,
                )
                return (
                    wait_seconds,
                    retry_at.isoformat(),
                )
            except (
                TypeError,
                ValueError,
                OverflowError,
            ):
                pass

        reset_header = _header_value(
            error.headers,
            "X-RateLimit-Reset",
        )
        if reset_header:
            try:
                reset_epoch = float(reset_header)
                if isfinite(reset_epoch):
                    return (
                        max(
                            0.0,
                            reset_epoch - now,
                        ),
                        self._format_reset_at(reset_epoch),
                    )
            except (
                TypeError,
                ValueError,
                OverflowError,
            ):
                pass

        wait_seconds = float(
            2 ** attempt
        )
        return (
            wait_seconds,
            None,
        )

    def _is_secondary_rate_limit(
        self,
        error: HTTPError,
    ) -> bool:
        """识别 GitHub secondary rate limit 或 abuse 信号。"""
        signals = " ".join(
            (
                str(error.reason or ""),
                self._read_error_body(error),
            )
        ).lower()
        return any(
            marker in signals
            for marker in (
                "secondary rate limit",
                "abuse detection",
                "abuse rate limit",
            )
        )

    @staticmethod
    def _decode_error_body(
        body: bytes | str | None,
    ) -> str:
        """读取错误体用于分类，但不把它放入对外错误消息。"""
        if body is None:
            return ""
        if isinstance(body, bytes):
            return body.decode(
                "utf-8",
                errors="replace",
            )
        return str(body)

    def _read_error_body(
        self,
        error: HTTPError,
    ) -> str:
        """读取并缓存错误体，仅用于判断 secondary 限流。"""
        cached = getattr(
            error,
            "_github_error_body",
            None,
        )
        if cached is not None:
            return str(cached)
        try:
            body = error.read()
        except (
            AttributeError,
            OSError,
            ValueError,
        ):
            body = b""
        decoded = self._decode_error_body(body)
        setattr(
            error,
            "_github_error_body",
            decoded,
        )
        return decoded

    @staticmethod
    def _close_http_error(
        error: HTTPError,
    ) -> None:
        """关闭标准库错误体，避免响应句柄和敏感内容继续存活。"""
        close = getattr(
            error,
            "close",
            None,
        )
        if callable(close):
            close()

    def _sanitize_http_error(
        self,
        error: HTTPError,
    ) -> GitHubAPIError:
        """把标准库 HTTPError 转为不泄露细节的异常。"""
        message = (
            "GitHub Token 无效或已过期"
            if error.code == 401
            else f"GitHub API returned HTTP {error.code}"
        )
        return GitHubAPIError(
            error.code,
            message,
            self.token,
        )

    @staticmethod
    def _format_seconds(
        value: float,
    ) -> str:
        """以稳定短格式输出等待秒数。"""
        if value.is_integer():
            return str(
                int(value)
            )
        return f"{value:.3f}".rstrip("0").rstrip(".")

    @staticmethod
    def _format_reset_at(
        epoch: float,
    ) -> str:
        """把 Unix 时间转换为 UTC 文本，异常时保留数值。"""
        try:
            return datetime.fromtimestamp(
                epoch,
                tz=timezone.utc,
            ).isoformat()
        except (
            OverflowError,
            OSError,
            ValueError,
        ):
            return str(epoch)


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
        enrich_readme: bool = False,
        readme_limit: int = DEFAULT_README_LIMIT,
    ) -> list[Item]:
        """执行查询、去重并按上限补充入选项目的 README。"""
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
        release_cache: dict[
            str,
            dict[str, Any] | None,
        ] = {}
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
                    release_cache,
                )
                if item:
                    collected.append(item)
        unique_items = deduplicate_items(collected)
        if not enrich_readme:
            return unique_items
        return self._enrich_readmes(
            unique_items,
            readme_limit=readme_limit,
        )

    def _enrich_readmes(
        self,
        items: list[Item],
        readme_limit: int,
    ) -> list[Item]:
        """只为有限数量的最终候选项目请求 README，避免浪费 API 配额。"""
        limit = max(
            0,
            int(readme_limit),
        )
        if limit == 0:
            return items
        selected_indexes = sorted(
            range(len(items)),
            key=lambda index: self._candidate_score(items[index]),
            reverse=True,
        )[:limit]
        selected = set(selected_indexes)
        enriched: list[Item] = []
        for index, item in enumerate(items):
            if index not in selected:
                enriched.append(item)
                continue
            enriched.append(
                self._enrich_item_with_readme(item)
            )
        return enriched

    def _enrich_item_with_readme(
        self,
        item: Item,
    ) -> Item:
        """读取单个仓库 README，并把解析结果写入 metadata。"""
        repo_name = item.repo_full_name
        if not repo_name:
            return item
        metadata = dict(item.metadata)
        try:
            payload = self.client.get_json(
                f"/repos/{repo_name}/readme"
            )
        except HTTPError as error:
            metadata["readme"] = {
                "status": "missing"
                if error.code == 404
                else "failed",
                "error_type": type(error).__name__,
            }
            return item.with_updates(
                metadata=metadata,
            )
        except Exception as error:
            metadata["readme"] = {
                "status": "failed",
                "error_type": type(error).__name__,
            }
            return item.with_updates(
                metadata=metadata,
            )

        readme = self._parse_readme_payload(payload)
        metadata["readme"] = readme
        return item.with_updates(
            metadata=metadata,
        )

    @staticmethod
    def _candidate_score(
        item: Item,
    ) -> tuple[int, int, str]:
        """用可解释字段选择 README 候选，不把分数写入业务数据。"""
        metadata = item.metadata
        section_priority = 1 if metadata.get("section") == "github_hot" else 0
        stars = int(item.stars or 0)
        pushed_at = str(metadata.get("pushed_at") or "")
        return (
            section_priority,
            stars,
            pushed_at,
        )

    @staticmethod
    def _parse_readme_payload(
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        """解析 GitHub README Base64 响应并保留可追溯链接。"""
        raw_content = payload.get("content")
        if not isinstance(raw_content, str) or not raw_content.strip():
            return {
                "status": "unparseable",
                "error_type": "missing_content",
            }
        encoding = str(
            payload.get("encoding") or "base64"
        ).casefold()
        try:
            if encoding == "base64":
                decoded = base64.b64decode(
                    "".join(raw_content.split()),
                    validate=False,
                ).decode(
                    "utf-8",
                    errors="replace",
                )
            else:
                decoded = raw_content
        except (
            binascii.Error,
            UnicodeError,
            ValueError,
        ):
            return {
                "status": "unparseable",
                "error_type": "invalid_encoding",
            }
        cleaned = _clean_readme_text(decoded)
        if not cleaned:
            return {
                "status": "unparseable",
                "error_type": "empty_content",
            }
        truncated = len(cleaned) > README_MAX_CHARS
        if truncated:
            cleaned = cleaned[:README_MAX_CHARS].rstrip()
        return {
            "status": "success",
            "content": cleaned,
            "truncated": truncated,
            "html_url": payload.get("html_url"),
            "download_url": payload.get("download_url"),
        }

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
        release_cache: dict[
            str,
            dict[str, Any] | None,
        ] | None = None,
    ) -> Item | None:
        """把 GitHub 仓库 JSON 转成统一项目模型。"""
        full_name = str(repository.get("full_name") or "").strip()
        html_url = str(repository.get("html_url") or "").strip()
        if not full_name or not html_url:
            return None
        latest_release: dict[str, Any] | None = None
        if include_releases:
            release_key = full_name.casefold()
            if (
                release_cache is not None
                and release_key in release_cache
            ):
                latest_release = release_cache[release_key]
            else:
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
                if release_cache is not None:
                    release_cache[release_key] = latest_release
        license_info = repository.get("license") or {}
        metadata: dict[str, Any] = {
            "query_name": query_name,
            "name": repository.get("name") or full_name.rsplit(
                "/",
                1,
            )[-1],
            "repository_url": html_url,
            "homepage": repository.get("homepage"),
            "topics": repository.get("topics") or [],
            "license": license_info.get("spdx_id") or license_info.get("name"),
            "open_issues_count": int(
                repository.get("open_issues_count") or 0
            ),
            "watchers_count": int(
                repository.get("watchers_count") or 0
            ),
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
        timezone_name: str = "Asia/Shanghai",
        now: datetime | None = None,
    ) -> str:
        """返回指定时区的逻辑日期，供 Star 快照使用。"""
        from ..config import date_in_timezone

        return date_in_timezone(
            timezone_name,
            now,
        ).isoformat()


def _clean_readme_text(
    value: str,
) -> str:
    """清理 README 控制字符并保留标题、列表和段落结构。"""
    lines = []
    blank_count = 0
    for raw_line in value.replace(
        "\r\n",
        "\n",
    ).replace(
        "\r",
        "\n",
    ).split(
        "\n"
    ):
        line = raw_line.replace(
            "\x00",
            "",
        ).rstrip()
        if not line.strip():
            blank_count += 1
            if blank_count <= 2:
                lines.append("")
            continue
        blank_count = 0
        lines.append(line)
    return "\n".join(lines).strip()


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

