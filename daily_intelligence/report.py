"""日报 Markdown 渲染和原子落盘。"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Iterable

from .config import RuntimePaths
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

    def render(
        self,
        items: Iterable[dict[str, Any]],
        report_date: date | None = None,
        total_limit: int = 15,
    ) -> str:
        """渲染日报主体和三条重点推荐。"""
        current_date = report_date or date.today()
        grouped: dict[str, list[dict[str, Any]]] = {
            key: []
            for key, _, _ in SECTION_DEFINITIONS
        }
        seen_urls: set[str] = set()
        all_items: list[dict[str, Any]] = []
        for item in items:
            normalized = normalize_url(
                str(item.get("url") or "")
            )
            if normalized in seen_urls:
                continue
            seen_urls.add(normalized)
            item_copy = dict(item)
            section = self._section_for(item_copy)
            if section not in grouped:
                section = "software"
            if len(grouped[section]) < self._section_limit(section):
                grouped[section].append(item_copy)
            all_items.append(item_copy)
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
        focus_items = sorted(
            all_items,
            key=lambda item: float(
                item.get("recommendation_score") or 0
            ),
            reverse=True,
        )[: min(3, total_limit)]
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
    temporary_path = report_path.with_name(
        f".{report_path.name}.tmp"
    )
    temporary_path.write_text(
        markdown,
        encoding="utf-8",
    )
    temporary_path.replace(report_path)
    return report_path

