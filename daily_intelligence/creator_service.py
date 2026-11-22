"""创作者账号管理、时间窗口和日报采集编排基础。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from .config import (
    DEFAULT_TIMEZONE,
    load_project_settings,
    now_in_timezone,
)
from .creator_urls import CreatorUrlError, parse_creator_url
from .database import Database
from .models import CreatorAccount, CreatorUpdate


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


@dataclass(frozen=True, slots=True)
class CreatorSourceOutcome:
    """保存单个账号和内容类型的采集窗口与结果。"""

    account_id: int
    platform: str
    account_key: str
    content_type: str
    window_start: datetime
    window_end: datetime
    status: str
    event_count: int = 0
    error: str | None = None


@dataclass(slots=True)
class CreatorCollectionResult:
    """保存一次日报触发型创作者采集的完整状态。"""

    run_key: str
    window_end: datetime
    outcomes: list[CreatorSourceOutcome]
    status: str

    @property
    def failures(self) -> list[CreatorSourceOutcome]:
        """返回本次失败来源，供日报显示数据不完整。"""
        return [
            outcome
            for outcome in self.outcomes
            if outcome.status == "failed"
        ]

    @property
    def successful(self) -> list[CreatorSourceOutcome]:
        """返回本次成功来源，供报告落盘后推进检查点。"""
        return [
            outcome
            for outcome in self.outcomes
            if outcome.status == "success"
        ]


class CreatorUpdatesService:
    """按日报窗口编排多账号采集并延迟推进检查点。"""

    def __init__(
        self,
        database: Database,
        bilibili_collector: Any | None = None,
        youtube_collector: Any | None = None,
        timezone_name: str = DEFAULT_TIMEZONE,
    ) -> None:
        """绑定数据库和可替换的平台采集器。"""
        self.database = database
        self.timezone_name = timezone_name
        if bilibili_collector is None or youtube_collector is None:
            from .collectors.creators import (
                BilibiliClient,
                BilibiliCollector,
                YouTubeClient,
                YouTubeCollector,
            )

            if bilibili_collector is None:
                bilibili_collector = BilibiliCollector(
                    BilibiliClient(
                        cookie=_bilibili_cookie(),
                    )
                )
            if youtube_collector is None:
                youtube_collector = YouTubeCollector(
                    YouTubeClient()
                )
        self.bilibili_collector = bilibili_collector
        self.youtube_collector = youtube_collector

    def collect(
        self,
        window_end: datetime | None = None,
        run_key: str | None = None,
    ) -> CreatorCollectionResult:
        """在固定截止时间采集所有 active 账号并隔离来源失败。"""
        end = _as_utc(
            window_end
            or creator_now(
                self.timezone_name,
            )
        )
        current_run_key = run_key or f"creator:{end.isoformat()}"
        accounts = self.database.list_creator_accounts(
            include_paused=False,
        )
        global_end = _parse_datetime(
            self.database.get_creator_global_last_success_end()
        )
        outcomes: list[CreatorSourceOutcome] = []
        for account in accounts:
            for content_type in self._content_types(account):
                outcome = self._collect_source(
                    account,
                    content_type,
                    global_end,
                    end,
                    current_run_key,
                )
                outcomes.append(outcome)
        if not outcomes:
            status = "not_configured"
        elif all(
            outcome.status == "success"
            for outcome in outcomes
        ):
            status = "success"
        elif any(
            outcome.status == "success"
            for outcome in outcomes
        ):
            status = "partial"
        else:
            status = "failed"
        return CreatorCollectionResult(
            run_key=current_run_key,
            window_end=end,
            outcomes=outcomes,
            status=status,
        )

    def report_updates(
        self,
        result: CreatorCollectionResult,
    ) -> list[dict[str, Any]]:
        """读取各来源窗口内已保存事件，供日报章节渲染。"""
        values: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str]] = set()
        for outcome in result.outcomes:
            account = self.database.get_creator_account(
                outcome.platform,
                outcome.account_key,
            )
            if account is None:
                continue
            events = self.database.list_creator_events(
                account_id=outcome.account_id,
                content_type=outcome.content_type,
                window_start=outcome.window_start.isoformat(),
                window_end=outcome.window_end.isoformat(),
            )
            for event in events:
                key = (
                    str(event.get("platform") or ""),
                    str(event.get("content_type") or ""),
                    str(event.get("external_id") or ""),
                )
                if key in seen:
                    continue
                seen.add(key)
                values.append(event)
        values.sort(
            key=lambda event: str(
                event.get("published_at") or ""
            ),
            reverse=True,
        )
        return values

    def finalize(
        self,
        result: CreatorCollectionResult,
        report_saved: bool,
    ) -> None:
        """仅在完整报告落盘后推进成功来源和全局截止点。"""
        if not report_saved:
            return
        for outcome in result.successful:
            self.database.mark_creator_checkpoint_success(
                outcome.account_id,
                outcome.content_type,
                outcome.window_end.isoformat(),
            )
        self.database.set_creator_global_success(
            result.window_end.isoformat()
        )

    @staticmethod
    def _content_types(
        account: dict[str, Any],
    ) -> list[str]:
        """根据账号配置确定需要采集的视频和动态来源。"""
        values: list[str] = []
        if account.get("monitor_videos"):
            values.append("video")
        if account.get("platform") == "bilibili" and account.get(
            "monitor_dynamics"
        ):
            values.append("dynamic")
        return values

    def _collect_source(
        self,
        account: dict[str, Any],
        content_type: str,
        global_end: datetime | None,
        window_end: datetime,
        run_key: str,
    ) -> CreatorSourceOutcome:
        """采集单个账号来源，失败时保留起点和失败原因。"""
        account_id = int(account["id"])
        checkpoint = self.database.get_creator_checkpoint(
            account_id,
            content_type,
        )
        account_created = _parse_datetime(
            account.get("created_at")
        )
        has_success = bool(
            checkpoint
            and checkpoint.get("last_success_end")
        )
        calculated = calculate_creator_window(
            window_end=window_end,
            global_last_success_end=global_end,
            account_created_at=account_created,
            account_has_success=has_success,
        )
        if checkpoint and checkpoint.get("first_window_start"):
            start = _parse_datetime(
                checkpoint["first_window_start"]
            ) or calculated.window_start
            if has_success:
                start = _parse_datetime(
                    checkpoint["last_success_end"]
                ) or start
            window = CreatorWindow(
                window_start=start,
                window_end=window_end,
            )
        else:
            window = calculated
        self.database.ensure_creator_checkpoint(
            account_id,
            content_type,
            window.window_start.isoformat(),
        )
        self.database.save_creator_source_run(
            run_key,
            account_id,
            content_type,
            window.window_start.isoformat(),
            window.window_end.isoformat(),
            "running",
            finished=False,
        )
        try:
            updates = self._invoke_collector(
                account,
                content_type,
                window,
            )
            filtered = [
                update
                for update in updates
                if update.content_type == content_type
                and window.contains(
                    _parse_datetime(update.published_at)
                    or window.window_start
                )
            ]
            event_count = self.database.save_creator_events(
                account_id,
                run_key,
                filtered,
            )
            self.database.save_creator_source_run(
                run_key,
                account_id,
                content_type,
                window.window_start.isoformat(),
                window.window_end.isoformat(),
                "success",
                event_count=event_count,
            )
            return CreatorSourceOutcome(
                account_id=account_id,
                platform=account["platform"],
                account_key=account["account_key"],
                content_type=content_type,
                window_start=window.window_start,
                window_end=window.window_end,
                status="success",
                event_count=event_count,
            )
        except Exception as error:
            safe_error = f"{type(error).__name__}: {str(error)[:300]}"
            self.database.mark_creator_checkpoint_failure(
                account_id,
                content_type,
                safe_error,
            )
            self.database.save_creator_source_run(
                run_key,
                account_id,
                content_type,
                window.window_start.isoformat(),
                window.window_end.isoformat(),
                "failed",
                error=safe_error,
            )
            return CreatorSourceOutcome(
                account_id=account_id,
                platform=account["platform"],
                account_key=account["account_key"],
                content_type=content_type,
                window_start=window.window_start,
                window_end=window.window_end,
                status="failed",
                error=safe_error,
            )

    def _invoke_collector(
        self,
        account: dict[str, Any],
        content_type: str,
        window: CreatorWindow,
    ) -> list[CreatorUpdate]:
        """按平台和内容类型调用对应采集器。"""
        if account["platform"] == "bilibili":
            if content_type == "video":
                return self.bilibili_collector.collect_videos(
                    account,
                    window,
                )
            return self.bilibili_collector.collect_dynamics(
                account,
                window,
            )
        if content_type != "video":
            raise ValueError("YouTube 不支持动态采集")
        return self.youtube_collector.collect_videos(
            account,
            window,
        )


def _bilibili_cookie() -> str | None:
    """读取进程环境中的 Bilibili Cookie，不写入日志或数据库。"""
    return load_project_settings().bilibili_cookie


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
