"""日报 Markdown 渲染和原子落盘。"""

from __future__ import annotations

from datetime import date, datetime
import os
from pathlib import Path
import tempfile
from typing import Any, Iterable

from .config import DEFAULT_TIMEZONE, RuntimePaths, date_in_timezone
from .deduplication import normalize_url


SECTION_DEFINITIONS = (
    ("github_hot", "GitHub 热点", 6),
    ("github_interesting", "有趣项目", 3),
    ("ai", "AI 新闻", 4),
    ("agent", "Agent 新闻", 4),
    ("software", "软件开发新闻", 4),
)


class DailyReportRenderer:
    """把推荐项目渲染为固定板块的中文 Markdown 日报。"""

    def select_rendered_items(
        self,
        items: Iterable[dict[str, Any]],
        total_limit: int = 15,
    ) -> list[dict[str, Any]]:
        """筛选实际会出现在日报板块中的项目。"""
        max_items = max(0, total_limit)
        section_counts: dict[str, int] = {
            key: 0
            for key, _, _ in SECTION_DEFINITIONS
        }
        seen_urls: set[str] = set()
        rendered_items: list[dict[str, Any]] = []
        considered_items = 0
        for item in items:
            if considered_items >= max_items:
                break
            metadata = item.get("metadata") or {}
            if (
                item.get("item_type") == "news"
                and metadata.get("is_supplement")
                and not metadata.get("is_major_supplement")
            ):
                continue
            normalized = normalize_url(
                str(item.get("url") or "")
            )
            if normalized in seen_urls:
                continue
            seen_urls.add(normalized)
            considered_items += 1
            item_copy = dict(item)
            section = self._section_for(item_copy)
            if section not in section_counts:
                section = "software"
            if section_counts[section] >= self._section_limit(section):
                continue
            section_counts[section] += 1
            rendered_items.append(item_copy)
        return rendered_items

    def render(
        self,
        items: Iterable[dict[str, Any]],
        report_date: date | None = None,
        total_limit: int = 15,
        timezone_name: str = DEFAULT_TIMEZONE,
        now: datetime | None = None,
    ) -> str:
        """渲染日报主体和三条重点推荐。"""
        current_date = report_date or date_in_timezone(
            timezone_name,
            now,
        )
        grouped: dict[str, list[dict[str, Any]]] = {
            key: []
            for key, _, _ in SECTION_DEFINITIONS
        }
        rendered_items = self.select_rendered_items(
            items,
            total_limit=total_limit,
        )
        for item in rendered_items:
            section = self._section_for(item)
            if section not in grouped:
                section = "software"
            grouped[section].append(item)
        output = [
            f"# Daily Intelligence 日报 - {current_date.isoformat()}",
            "",
            "> 由 Daily Intelligence 生成；新闻发布时间和来源以原文为准。",
            "",
        ]
        for key, title, _ in SECTION_DEFINITIONS:
            output.append(f"## {title}")
            output.append("")
            section_items = grouped[key]
            if not section_items:
                output.append("暂无符合条件的内容。")
                output.append("")
                continue
            for item in section_items:
                output.extend(
                    self._render_item(
                        item,
                    )
                )
        output.append("## 今日重点推荐")
        output.append("")
        focus_limit = max(
            0,
            min(
                3,
                total_limit,
            ),
        )
        focus_items: list[dict[str, Any]] = []
        focus_urls: set[str] = set()
        for item in sorted(
            rendered_items,
            key=lambda value: float(
                value.get("recommendation_score") or 0
            ),
            reverse=True,
        ):
            normalized = normalize_url(
                str(item.get("url") or "")
            )
            if normalized in focus_urls:
                continue
            focus_urls.add(normalized)
            focus_items.append(item)
            if len(focus_items) >= focus_limit:
                break
        if not focus_items:
            output.append("暂无重点推荐。")
        else:
            for item in focus_items:
                output.append(
                    "- "
                    f"**{item.get('title') or '未命名'}**："
                    f"{item.get('match_reason') or '值得关注'}"
                )
        output.append("")
        return "\n".join(output)

    @staticmethod
    def _section_for(
        item: dict[str, Any],
    ) -> str:
        """根据显式 section 或内容分类选择日报板块。"""
        metadata = item.get("metadata") or {}
        explicit_section = metadata.get("section")
        if explicit_section:
            return str(explicit_section)
        if item.get("item_type") == "github":
            category = str(item.get("category") or "").casefold()
            if "interesting" in category or "有趣" in category:
                return "github_interesting"
            return "github_hot"
        category = str(item.get("category") or "").casefold()
        if "agent" in category:
            return "agent"
        if "ai" in category or "model" in category:
            return "ai"
        return "software"

    @staticmethod
    def _section_limit(
        section: str,
    ) -> int:
        """读取板块条数上限。"""
        return next(
            (
                limit
                for key, _, limit in SECTION_DEFINITIONS
                if key == section
            ),
            4,
        )

    @staticmethod
    def _render_item(
        item: dict[str, Any],
    ) -> list[str]:
        """渲染单条情报的摘要、亮点、理由和来源。"""
        metadata = item.get("metadata") or {}
        summary = item.get("summary") or "暂无摘要。"
        highlight = (
            metadata.get("core_change")
            or metadata.get("highlights")
            or summary
        )
        why = metadata.get(
            "why",
            "内容与近期技术趋势相关，建议结合原文判断。",
        )
        published_at = item.get("published_at") or "未知"
        source = item.get("source") or "未知来源"
        url = item.get("url") or ""
        return [
            f"### {item.get('title') or '未命名'}",
            f"- 简介：{summary}",
            f"- 核心亮点：{highlight}",
            f"- 为什么值得关注：{why}",
            f"- 兴趣匹配：{item.get('match_reason') or '未计算'}",
            f"- 来源：[{source}]({url})",
            f"- 发布时间：{published_at}",
            "",
        ]


def save_report(
    paths: RuntimePaths,
    markdown: str,
    report_date: date,
) -> Path:
    """以原子替换方式保存指定日期的 Markdown 日报。"""
    paths.reports_dir.mkdir(
        parents=True,
        exist_ok=True,
    )
    report_path = paths.reports_dir / f"{report_date.isoformat()}.md"
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=paths.reports_dir,
            prefix=f".{report_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(
                handle.name
            )
            handle.write(markdown)
            handle.flush()
            os.fsync(handle.fileno())
        temporary_path.replace(report_path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(
                missing_ok=True,
            )
    return report_path

