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

