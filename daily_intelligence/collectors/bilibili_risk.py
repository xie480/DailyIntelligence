"""Bilibili 风控错误分类、请求节流和冷却状态。"""

from __future__ import annotations

from dataclasses import dataclass
import math
import time
from typing import Callable
from urllib.parse import urlsplit


BILIBILI_RISK_CODES = frozenset(
    {
        -352,
        -412,
    }
)
BILIBILI_RISK_HTTP_STATUSES = frozenset(
    {
        412,
    }
)
DEFAULT_RISK_COOLDOWN_SECONDS = 900.0
MAX_RISK_COOLDOWN_SECONDS = 7200.0
DEFAULT_REQUEST_INTERVAL_SECONDS = 1.0


@dataclass
class _RiskState:
    """保存单个 Bilibili 接口的风控失败状态。"""

    failure_count: int = 0
    cooldown_until: float = 0.0
    endpoint: str = ""
    code: int | None = None
    http_status: int | None = None
    message: str = ""


class BilibiliRiskControlError(RuntimeError):
    """表示 Bilibili 拒绝了当前请求并要求等待冷却。"""

    def __init__(
        self,
        *,
        endpoint: str,
        code: int | None = None,
        http_status: int | None = None,
        retry_after_seconds: float = 0.0,
        message: str = "",
    ) -> None:
        """初始化脱敏的风控错误及可重试时间。"""
        self.endpoint = _safe_endpoint(endpoint)
        self.code = code
        self.http_status = http_status
        self.retry_after_seconds = max(
            0.0,
            retry_after_seconds,
        )
        identifiers: list[str] = []
        if code is not None:
            identifiers.append(
                f"code={code}"
            )
        if http_status is not None:
            identifiers.append(
                f"HTTP {http_status}"
            )
        identifier = ", ".join(
            identifiers
        ) or "unknown"
        details = message.strip()[:120]
        cooldown = (
            f"，建议约 {math.ceil(self.retry_after_seconds)} 秒后重试"
            if self.retry_after_seconds > 0
            else ""
        )
        text = (
            f"Bilibili 风控拦截（{identifier}，接口 {self.endpoint}）"
            f"{cooldown}"
        )
        if details:
            text = f"{text}：{details}"
        super().__init__(text)


class BilibiliRiskController:
    """管理 Bilibili 风控冷却、指数退避和请求间隔。"""

    def __init__(
        self,
        base_cooldown_seconds: float = DEFAULT_RISK_COOLDOWN_SECONDS,
        max_cooldown_seconds: float = MAX_RISK_COOLDOWN_SECONDS,
        minimum_request_interval_seconds: float = (
            DEFAULT_REQUEST_INTERVAL_SECONDS
        ),
        clock: Callable[[], float] | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        """初始化可注入时钟和等待函数的风控控制器。"""
        self.base_cooldown_seconds = max(
            0.0,
            base_cooldown_seconds,
        )
        self.max_cooldown_seconds = max(
            self.base_cooldown_seconds,
            max_cooldown_seconds,
        )
        self.minimum_request_interval_seconds = max(
            0.0,
            minimum_request_interval_seconds,
        )
        self._clock = clock or time.monotonic
        self._sleep = sleep or time.sleep
        self._states: dict[str, _RiskState] = {}
        self._last_request_at: float | None = None

    @staticmethod
    def is_risk_control(
        code: int | None = None,
        http_status: int | None = None,
    ) -> bool:
        """判断业务码或 HTTP 状态是否属于 Bilibili 风控。"""
        return (
            code in BILIBILI_RISK_CODES
            or http_status in BILIBILI_RISK_HTTP_STATUSES
        )

    def ensure_available(
        self,
        endpoint_key: str,
    ) -> None:
        """在接口仍处于冷却时立即抛出风控错误。"""
        state = self._states.get(
            endpoint_key
        )
        if state is None:
            return
        remaining = state.cooldown_until - self._clock()
        if remaining <= 0:
            return
        raise BilibiliRiskControlError(
            endpoint=state.endpoint or endpoint_key,
            code=state.code,
            http_status=state.http_status,
            retry_after_seconds=remaining,
            message=state.message,
        )

    def before_request(
        self,
        endpoint_key: str,
    ) -> None:
        """执行冷却检查并限制相邻 Bilibili 请求的最小间隔。"""
        self.ensure_available(
            endpoint_key,
        )
        now = self._clock()
        if self._last_request_at is not None:
            wait_seconds = (
                self.minimum_request_interval_seconds
                - (now - self._last_request_at)
            )
            if wait_seconds > 0:
                self._sleep(
                    wait_seconds,
                )
        self._last_request_at = self._clock()

    def record_success(
        self,
        endpoint_key: str,
    ) -> None:
        """成功响应后清除该接口的连续风控失败状态。"""
        self._states.pop(
            endpoint_key,
            None,
        )

    def record_failure(
        self,
        endpoint_key: str,
        *,
        endpoint: str,
        code: int | None = None,
        http_status: int | None = None,
        message: str = "",
    ) -> BilibiliRiskControlError | None:
        """记录风控失败并返回带冷却时间的专用异常。"""
        if not self.is_risk_control(
            code=code,
            http_status=http_status,
        ):
            return None
        state = self._states.setdefault(
            endpoint_key,
            _RiskState(),
        )
        state.failure_count += 1
        state.endpoint = _safe_endpoint(
            endpoint,
        )
        state.code = code
        state.http_status = http_status
        state.message = message
        cooldown = min(
            self.max_cooldown_seconds,
            self.base_cooldown_seconds
            * (2 ** (state.failure_count - 1)),
        )
        state.cooldown_until = self._clock() + cooldown
        return BilibiliRiskControlError(
            endpoint=endpoint,
            code=code,
            http_status=http_status,
            retry_after_seconds=cooldown,
            message=message,
        )


def _safe_endpoint(
    value: str,
) -> str:
    """只保留接口路径，避免错误信息带出查询参数。"""
    parsed = urlsplit(
        value,
    )
    return parsed.path or value.split(
        "?",
        1,
    )[0]
