"""创作者账号管理、时间窗口和日报采集编排基础。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from .config import DEFAULT_TIMEZONE, now_in_timezone, timezone_or_default
from .creator_urls import (
    CreatorUrlError,
    ParsedCreatorUrl,
    parse_creator_url,
)
from .database import Database
from .models import CreatorAccount


UTC = timezone.utc
CREATOR_CONTENT_TYPES = {
    "video",
    "dynamic",
}


@dataclass(frozen=True, slots=True)
class CreatorWindow:
    """保存一次平台来源采集的半开时间窗口。"""

    window_start: datetime
    window_end: datetime

    def __post_init__(self) -> None:
        """把窗口两端统一成 UTC 带时区时间。"""
        start = _as_utc(self.window_start)
        end = _as_utc(self.window_end)
        if start > end:
            raise ValueError("创作者采集窗口起点不能晚于终点")
        object.__setattr__(
            self,
            "window_start",
            start,
        )
        object.__setattr__(
            self,
            "window_end",
            end,
        )

    def contains(
        self,
        published_at: datetime,
    ) -> bool:
        """判断发布时间是否满足 window_start < time <= window_end。"""
        current = _as_utc(published_at)
        return self.window_start < current <= self.window_end


def calculate_creator_window(
    window_end: datetime,
    global_last_success_end: datetime | str | None,
    account_created_at: datetime | str | None,
    account_has_success: bool = True,
) -> CreatorWindow:
    """计算首次 24 小时、普通成功检查点或新账号窗口。"""
    end = _as_utc(window_end)
    previous = _parse_datetime(global_last_success_end)
    created = _parse_datetime(account_created_at)
    first_run_start = end - timedelta(hours=24)
    if previous is None:
        start = first_run_start
        if created is not None and created > start:
            start = created
    elif not account_has_success and created is not None:
        start = created
    else:
        start = previous
    return CreatorWindow(
        window_start=start,
        window_end=end,
    )


class CreatorAccountService:
    """执行经过 owner 授权的创作者账号增删改查。"""

    def __init__(
        self,
        database: Database,
    ) -> None:
        """绑定创作者数据库。"""
        self.database = database

    def add_account(
        self,
        url: str,
        owner_key: str,
        display_name: str | None = None,
        monitor_videos: bool = True,
        monitor_dynamics: bool | None = None,
        resolved_account_key: str | None = None,
        resolved_display_name: str | None = None,
        created_at: str | None = None,
    ) -> dict[str, Any]:
        """解析并添加账号，handle 必须先解析成真实 Channel ID。"""
        self._require_owner(owner_key)
        parsed = parse_creator_url(url)
        account_key = (
            resolved_account_key.strip()
            if resolved_account_key
            else parsed.account_key
        )
        if parsed.requires_resolution and not resolved_account_key:
            raise CreatorUrlError(
                "该 YouTube 链接需要先解析为真实 Channel ID"
            )
        if parsed.platform == "youtube":
            profile_url = (
                f"https://www.youtube.com/channel/{account_key}"
            )
        else:
            profile_url = parsed.canonical_url
        if monitor_dynamics is None:
            monitor_dynamics = parsed.platform == "bilibili"
        account = CreatorAccount(
            platform=parsed.platform,
            account_key=account_key,
            display_name=(
                display_name
                or resolved_display_name
                or f"{parsed.platform} {account_key}"
            ),
            profile_url=profile_url,
            owner_key=owner_key,
            monitor_videos=monitor_videos,
            monitor_dynamics=monitor_dynamics,
            created_at=created_at,
        )
        if self.database.get_creator_account(
            account.platform,
            account.account_key,
        ):
            raise ValueError("同平台账号已经存在")
        try:
            account_id = self.database.add_creator_account(account)
        except Exception as error:
            if "UNIQUE" in str(error).upper():
                raise ValueError("同平台账号已经存在") from error
            raise
        result = self.database.get_creator_account(
            account.platform,
            account.account_key,
        )
        if result is None:
            raise RuntimeError(
                f"创作者账号写入后无法读取: {account_id}"
            )
        return result

    def list_accounts(
        self,
        owner_key: str,
        include_paused: bool = True,
    ) -> list[dict[str, Any]]:
        """读取当前授权 owner 的账号列表。"""
        self._require_owner(owner_key)
        return self.database.list_creator_accounts(
            owner_key=owner_key,
            include_paused=include_paused,
        )

    def remove_account(
        self,
        platform: str,
        account_key: str,
        owner_key: str,
    ) -> None:
        """删除当前 owner 拥有的账号及其事件。"""
        self._require_owned(
            platform,
            account_key,
            owner_key,
        )
        if not self.database.delete_creator_account(
            platform,
            account_key,
        ):
            raise ValueError("创作者账号不存在")

    def pause_account(
        self,
        platform: str,
        account_key: str,
        owner_key: str,
    ) -> None:
        """暂停账号采集但保留历史事件和配置。"""
        self._set_status(
            platform,
            account_key,
            owner_key,
            "paused",
        )

    def resume_account(
        self,
        platform: str,
        account_key: str,
        owner_key: str,
    ) -> None:
        """恢复账号采集。"""
        self._set_status(
            platform,
            account_key,
            owner_key,
            "active",
        )

    def configure_account(
        self,
        platform: str,
        account_key: str,
        owner_key: str,
        monitor_videos: bool,
        monitor_dynamics: bool,
    ) -> None:
        """修改账号监控类型，YouTube 动态监控始终拒绝。"""
        self._require_owned(
            platform,
            account_key,
            owner_key,
        )
        if platform.strip().lower() == "youtube" and monitor_dynamics:
            raise ValueError("YouTube 只支持视频监控")
        self.database.update_creator_account(
            platform,
            account_key,
            monitor_videos=int(monitor_videos),
            monitor_dynamics=int(monitor_dynamics),
        )

    def _set_status(
        self,
        platform: str,
        account_key: str,
        owner_key: str,
        status: str,
    ) -> None:
        """更新账号 active/paused 状态。"""
        self._require_owned(
            platform,
            account_key,
            owner_key,
        )
        self.database.update_creator_account(
            platform,
            account_key,
            status=status,
        )

    def _require_owned(
        self,
        platform: str,
        account_key: str,
        owner_key: str,
    ) -> dict[str, Any]:
        """校验 owner 授权和账号归属。"""
        self._require_owner(owner_key)
        account = self.database.get_creator_account(
            platform,
            account_key,
        )
        if account is None:
            raise ValueError("创作者账号不存在")
        if account["owner_key"] != owner_key:
            raise PermissionError("当前 owner 无权管理该创作者账号")
        return account

    def _require_owner(
        self,
        owner_key: str,
    ) -> None:
        """拒绝未写入授权表的消息发送者。"""
        if not self.database.is_creator_owner_authorized(owner_key):
            raise PermissionError("当前 owner 未获授权管理创作者账号")


def _as_utc(
    value: datetime,
) -> datetime:
    """把 datetime 统一为带 UTC 时区的值。"""
    current = value
    if current.tzinfo is None:
        current = current.replace(
            tzinfo=UTC,
        )
    return current.astimezone(UTC)


def _parse_datetime(
    value: datetime | str | None,
) -> datetime | None:
    """解析 datetime 或 ISO 字符串，解析失败返回空值。"""
    if value is None:
        return None
    if isinstance(value, datetime):
        return _as_utc(value)
    try:
        return _as_utc(
            datetime.fromisoformat(
                str(value).replace(
                    "Z",
                    "+00:00",
                )
            )
        )
    except ValueError:
        return None


def creator_now(
    timezone_name: str = DEFAULT_TIMEZONE,
    now: datetime | None = None,
) -> datetime:
    """返回业务时区下的当前时间，供日报入口固定 window_end。"""
    return now_in_timezone(
        timezone_name,
        now,
    )
