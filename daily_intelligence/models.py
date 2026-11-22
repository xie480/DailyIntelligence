"""项目内部使用的数据模型。"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any


ITEM_TYPES = frozenset(
    {
        "github",
        "news",
    }
)

CREATOR_PLATFORMS = frozenset(
    {
        "bilibili",
        "youtube",
    }
)
CREATOR_CONTENT_TYPES = frozenset(
    {
        "video",
        "dynamic",
    }
)


@dataclass(slots=True)
class Item:
    """新闻或 GitHub 项目的统一领域模型。"""

    item_type: str
    title: str
    url: str
    source: str
    published_at: str | None = None
    summary: str = ""
    content: str = ""
    category: str = ""
    language: str | None = None
    repo_full_name: str | None = None
    stars: int | None = None
    forks: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    external_id: str | None = None

    def __post_init__(self) -> None:
        """校验并清理外部采集得到的基础字段。"""
        self.item_type = self.item_type.strip().lower()
        self.title = self.title.strip()
        self.url = self.url.strip()
        self.source = self.source.strip()
        self.summary = self.summary.strip()
        self.content = self.content.strip()
        self.category = self.category.strip()
        if self.item_type not in ITEM_TYPES:
            raise ValueError(f"不支持的内容类型: {self.item_type}")
        if not self.title:
            raise ValueError("内容标题不能为空")
        if not self.url:
            raise ValueError("内容 URL 不能为空")

    def with_updates(
        self,
        **updates: Any,
    ) -> "Item":
        """返回应用字段更新后的新模型，不修改原对象。"""
        return replace(self, **updates)


@dataclass(slots=True)
class CreatorAccount:
    """创作者监控账号模型，供账号管理和采集编排复用。"""

    platform: str
    account_key: str
    display_name: str
    profile_url: str
    owner_key: str
    monitor_videos: bool = True
    monitor_dynamics: bool = False
    status: str = "active"
    created_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """校验平台、账号键和监控类型，阻止无效配置进入数据库。"""
        self.platform = self.platform.strip().lower()
        self.account_key = self.account_key.strip()
        self.display_name = self.display_name.strip()
        self.profile_url = self.profile_url.strip()
        self.owner_key = self.owner_key.strip()
        self.status = self.status.strip().lower()
        if self.platform not in CREATOR_PLATFORMS:
            raise ValueError(f"不支持的创作者平台: {self.platform}")
        if not self.account_key:
            raise ValueError("创作者账号唯一标识不能为空")
        if not self.profile_url:
            raise ValueError("创作者主页链接不能为空")
        if not self.owner_key:
            raise ValueError("创作者账号必须绑定授权 owner")
        if self.status not in {
            "active",
            "paused",
        }:
            raise ValueError("创作者账号状态必须是 active 或 paused")
        if self.platform == "youtube" and self.monitor_dynamics:
            raise ValueError("YouTube 只支持视频监控")


@dataclass(slots=True)
class CreatorUpdate:
    """统一表示 Bilibili 或 YouTube 的单条创作者更新事件。"""

    platform: str
    content_type: str
    external_id: str
    creator_name: str
    title: str
    url: str
    published_at: str
    summary: str = ""
    content: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """清理第三方字段并校验事件的唯一键和内容类型。"""
        self.platform = self.platform.strip().lower()
        self.content_type = self.content_type.strip().lower()
        self.external_id = self.external_id.strip()
        self.creator_name = self.creator_name.strip()
        self.title = self.title.strip()
        self.url = self.url.strip()
        self.published_at = self.published_at.strip()
        self.summary = self.summary.strip()
        self.content = self.content.strip()
        if self.platform not in CREATOR_PLATFORMS:
            raise ValueError(f"不支持的创作者平台: {self.platform}")
        if self.content_type not in CREATOR_CONTENT_TYPES:
            raise ValueError(f"不支持的创作者内容类型: {self.content_type}")
        if not self.external_id:
            raise ValueError("创作者更新的外部唯一 ID 不能为空")
        if not self.title:
            raise ValueError("创作者更新标题不能为空")
        if not self.url:
            raise ValueError("创作者更新链接不能为空")
        if not self.published_at:
            raise ValueError("创作者更新时间不能为空")

