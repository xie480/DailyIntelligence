"""专业日报、QQ Markdown 渲染和原子落盘。"""

from __future__ import annotations

from datetime import date, datetime
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Iterable

from .config import DEFAULT_TIMEZONE, RuntimePaths, date_in_timezone
from .deduplication import content_fingerprint, normalize_url


SECTION_DEFINITIONS = (
    ("github_hot", "GitHub 热点", 6),
    ("github_interesting", "有趣项目", 4),
    ("ai", "AI 新闻", 5),
    ("agent", "Agent 新闻", 5),
    ("software", "软件开发新闻", 5),
)
SECTION_LABELS = {
    "ai": "AI",
    "agent": "Agent",
    "software": "软件开发",
}
CREATOR_SECTION_DEFINITIONS = (
    ("bilibili", "video", "今日 B站新视频"),
    ("bilibili", "dynamic", "今日 B站新动态"),
    ("youtube", "video", "今日 YouTube 新视频"),
)
QQ_DEFAULT_MAX_CHARS = 3500
QQ_COMPLETION_MARKER = "日报发送完成。"


class DailyReportRenderer:
    """把推荐项目渲染为完整日报和 QQ Markdown 阅读版。"""

    def select_rendered_items(
        self,
        items: Iterable[dict[str, Any]],
        total_limit: int = 15,
    ) -> list[dict[str, Any]]:
        """筛选实际会出现在日报板块中的项目并消除跨来源重复。"""
        max_items = max(
            0,
            total_limit,
        )
        section_counts: dict[str, int] = {
            key: 0
            for key, _, _ in SECTION_DEFINITIONS
        }
        seen_urls: set[str] = set()
        seen_fingerprints: set[str] = set()
        seen_events: set[str] = set()
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
            fingerprint = content_fingerprint(
                str(item.get("title") or ""),
                str(
                    item.get("content")
                    or item.get("summary")
                    or ""
                ),
            )
            event_key = str(
                metadata.get("event_key")
                or metadata.get("canonical_event")
                or ""
            ).strip()
            if normalized in seen_urls or fingerprint in seen_fingerprints:
                continue
            if event_key and event_key in seen_events:
                continue
            seen_urls.add(normalized)
            seen_fingerprints.add(fingerprint)
            if event_key:
                seen_events.add(event_key)
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
        collection_status: dict[str, Any] | None = None,
        creator_updates: Iterable[dict[str, Any]] | None = None,
        creator_status: dict[str, Any] | None = None,
    ) -> str:
        """渲染摘要、项目、新闻、重点推荐和数据来源状态。"""
        current_date = report_date or date_in_timezone(
            timezone_name,
            now,
        )
        status = collection_status or {}
        rendered_items = self.select_rendered_items(
            items,
            total_limit=total_limit,
        )
        grouped: dict[str, list[dict[str, Any]]] = {
            key: []
            for key, _, _ in SECTION_DEFINITIONS
        }
        for item in rendered_items:
            section = self._section_for(item)
            if section not in grouped:
                section = "software"
            grouped[section].append(item)
        output = [
            f"# Daily Intelligence 日报 - {current_date.isoformat()}",
            "",
            f"生成时间：{status.get('generated_at') or current_date.isoformat() + ' 00:00'}",
            "统计周期：最近 24 小时；不足时由 Hermes 交接文件明确扩展范围。",
            "采集来源：GitHub API · RSS/Atom · Hermes Web Search",
            "",
            "## 今日情报速览",
            "",
        ]
        output.extend(
            self._render_overview(
                rendered_items,
            )
        )
        for key, title, _ in SECTION_DEFINITIONS:
            output.append(f"## {title}")
            output.append("")
            section_items = grouped[key]
            if not section_items:
                output.append("暂无符合条件的内容。")
                output.append("")
                continue
            for index, item in enumerate(
                section_items,
                1,
            ):
                output.extend(
                    self._render_item(
                        item,
                        index,
                    )
                )
        output.extend(
            self._render_creator_updates(
                creator_updates or [],
                creator_status or status.get("creator_updates") or {},
            )
        )
        output.append("## 今日重点推荐")
        output.append("")
        output.extend(
            self._render_focus(
                rendered_items,
                total_limit,
            )
        )
        output.append("## 数据来源与采集状态")
        output.append("")
        output.extend(
            self._render_collection_status(
                rendered_items,
                status,
                creator_status or status.get("creator_updates") or {},
            )
        )
        return "\n".join(output).rstrip() + "\n"

    def render_qq(
        self,
        items: Iterable[dict[str, Any]],
        report_date: date | None = None,
        total_limit: int = 15,
        timezone_name: str = DEFAULT_TIMEZONE,
        now: datetime | None = None,
        collection_status: dict[str, Any] | None = None,
        creator_updates: Iterable[dict[str, Any]] | None = None,
        creator_status: dict[str, Any] | None = None,
    ) -> str:
        """生成保留详细项目、新闻和链接的 QQ Markdown 版本。"""
        markdown = self.render(
            items,
            report_date=report_date,
            total_limit=total_limit,
            timezone_name=timezone_name,
            now=now,
            collection_status=collection_status,
            creator_updates=creator_updates,
            creator_status=creator_status,
        )
        lines = markdown.splitlines()
        if lines:
            lines[0] = "# 每日技术情报"
        return "\n".join(lines).rstrip() + "\n"

    def _render_overview(
        self,
        items: list[dict[str, Any]],
    ) -> list[str]:
        """渲染三条以内的重点速览，避免重复堆叠全文。"""
        if not items:
            return [
                "暂无可核实的重点内容。",
                "",
            ]
        lines: list[str] = []
        for item in sorted(
            items,
            key=lambda value: float(
                value.get("recommendation_score") or 0
            ),
            reverse=True,
        )[:3]:
            metadata = item.get("metadata") or {}
            analysis = metadata.get("project_analysis") or {}
            summary = str(
                metadata.get("why_it_matters")
                or analysis.get("summary")
                or item.get("summary")
                or "值得结合原始来源继续阅读。"
            )
            lines.append(
                f"- **{item.get('title') or '未命名'}**："
                f"{_short_text(summary, 180)}"
            )
        lines.append("")
        return lines

    def _render_item(
        self,
        item: dict[str, Any],
        index: int,
    ) -> list[str]:
        """根据内容类型渲染项目卡片或独立新闻条目。"""
        if item.get("item_type") == "github":
            return self._render_github_item(
                item,
                index,
            )
        return self._render_news_item(
            item,
            index,
        )

    def _render_github_item(
        self,
        item: dict[str, Any],
        index: int,
    ) -> list[str]:
        """渲染 GitHub 项目定位、指标、时间、特色、场景和链接。"""
        metadata = item.get("metadata") or {}
        analysis = metadata.get("project_analysis") or {}
        title = item.get("title") or "未命名项目"
        summary = (
            analysis.get("summary")
            or item.get("summary")
            or "暂无项目定位。"
        )
        language = item.get("language") or "未知语言"
        stars = _number_text(item.get("stars"))
        forks = _number_text(item.get("forks"))
        output = [
            f"### {index}. {title}",
            f"**项目定位：** {summary}",
            f"**数据：** ★ {stars} Stars · {forks} Forks · {language}",
            f"**项目创建时间：** {_display_time(metadata.get('created_at'))}",
            f"**最近更新时间：** {_display_time(metadata.get('updated_at'))}",
        ]
        latest_release = metadata.get("latest_release") or {}
        if latest_release.get("published_at"):
            output.append(
                "**最新 Release：** "
                f"{latest_release.get('tag') or '未命名'} · "
                f"{_display_time(latest_release.get('published_at'))}"
            )
        output.extend(
            [
                "",
                "**详细介绍：**",
                str(summary),
                "",
                "**核心特色：**",
            ]
        )
        output.extend(
            _render_list(
                analysis.get("features") or metadata.get("topics") or [],
                "来源未提供结构化特色。",
            )
        )
        output.extend(
            [
                "",
                "**使用场景：**",
            ]
        )
        output.extend(
            _render_list(
                analysis.get("use_cases") or [],
                "来源未提供结构化使用场景。",
            )
        )
        output.extend(
            [
                "",
                "**推荐理由：**",
                str(
                    analysis.get("recommendation_reason")
                    or item.get("match_reason")
                    or "来源和更新时间较新，适合作为补充阅读。"
                ),
                "",
                f"[GitHub 仓库]({item.get('url') or ''})",
            ]
        )
        homepage = str(
            metadata.get("homepage") or ""
        ).strip()
        if homepage.startswith(
            (
                "http://",
                "https://",
            )
        ):
            output.append(
                f"[官网 / Demo]({homepage})"
            )
        output.append("")
        return output

    def _render_news_item(
        self,
        item: dict[str, Any],
        index: int,
    ) -> list[str]:
        """渲染新闻标题、来源、时间、变化、意义和原文链接。"""
        metadata = item.get("metadata") or {}
        summary = item.get("summary") or "暂无摘要。"
        key_changes = (
            metadata.get("key_changes")
            or metadata.get("highlights")
            or []
        )
        if isinstance(key_changes, str):
            key_changes = [key_changes]
        why = (
            metadata.get("why_it_matters")
            or metadata.get("why")
            or "内容与近期技术趋势相关，建议结合原文判断。"
        )
        source = item.get("source") or "未知来源"
        url = item.get("url") or ""
        return [
            f"### {item.get('title') or '未命名新闻'}",
            f"**来源：** {source}",
            f"**发布时间：** {_display_time(item.get('published_at'))}",
            "",
            f"**事件摘要：** {summary}",
            "",
            "**核心变化：**",
            *_render_list(
                key_changes,
                "来源未提供结构化变化。",
            ),
            "",
            f"**技术意义：** {why}",
            f"**兴趣匹配：** {item.get('match_reason') or '未计算'}",
            "",
            f"[阅读原文]({url})",
            "",
        ]

    def _render_focus(
        self,
        items: list[dict[str, Any]],
        total_limit: int,
    ) -> list[str]:
        """只从已经渲染的条目中选择最多三条重点推荐。"""
        focus_limit = max(
            0,
            min(
                3,
                total_limit,
            ),
        )
        if not focus_limit or not items:
            return [
                "暂无重点推荐。",
                "",
            ]
        lines: list[str] = []
        for item in sorted(
            items,
            key=lambda value: float(
                value.get("recommendation_score") or 0
            ),
            reverse=True,
        )[:focus_limit]:
            lines.append(
                "- "
                f"**{item.get('title') or '未命名'}**："
                f"{item.get('match_reason') or '值得关注'}"
            )
        lines.append("")
        return lines

    def _render_collection_status(
        self,
        items: list[dict[str, Any]],
        status: dict[str, Any],
        creator_status: dict[str, Any] | None = None,
    ) -> list[str]:
        """渲染来源状态和轻量质量指标，明确区分未执行与无结果。"""
        search_status = status.get("search_status") or {}
        lines = [
            "GitHub：日报中展示 "
            f"{sum(item.get('item_type') == 'github' for item in items)} 个项目。",
            f"RSS：{status.get('rss_status') or '状态未提供'}。",
            "Web Search：",
        ]
        if status.get("handoff_error"):
            lines.append(
                "- 交接文件：读取失败（"
                f"{status['handoff_error']}）"
            )
        for category in (
            "ai",
            "agent",
            "software",
        ):
            label = SECTION_LABELS[category]
            lines.append(
                f"- {label}：{search_status.get(category, 'not_run')}"
            )
        metrics = self.quality_metrics(
            items,
        )
        lines.extend(
            [
                "",
                "质量指标：",
                f"- README 获取成功率：{metrics['readme_success_rate']}",
                f"- 项目分析来源可追溯率：{metrics['project_traceability_rate']}",
                f"- 新闻原始链接有效率：{metrics['news_url_rate']}",
                f"- 新闻发布时间完整率：{metrics['news_published_rate']}",
                f"- 当前展示条目去重后数量：{metrics['unique_items']}",
                "",
            ]
        )
        queries = status.get("search_queries") or {}
        for category in (
            "ai",
            "agent",
            "software",
        ):
            if queries.get(category):
                lines.append(
                    f"{SECTION_LABELS[category]} 查询："
                    f"{len(queries[category])} 组"
                )
        creator = creator_status or {}
        if creator:
            lines.extend(
                [
                    "",
                    "创作者动态："
                    f"{creator.get('status') or 'not_run'}，"
                    f"展示 {creator.get('event_count', 0)} 条。",
                ]
            )
            for failure in creator.get("failures") or []:
                lines.append(
                    "- "
                    f"{failure.get('platform') or 'unknown'} "
                    f"{failure.get('content_type') or 'source'}："
                    f"{failure.get('error') or '采集失败'}"
                )
        lines.append("")
        return lines

    def _render_creator_updates(
        self,
        updates: Iterable[dict[str, Any]],
        status: dict[str, Any],
    ) -> list[str]:
        """渲染 Bilibili 视频/动态和 YouTube 视频独立章节。"""
        grouped: dict[tuple[str, str], list[dict[str, Any]]] = {
            (
                platform,
                content_type,
            ): []
            for platform, content_type, _ in CREATOR_SECTION_DEFINITIONS
        }
        for update in updates:
            key = (
                str(update.get("platform") or "").lower(),
                str(update.get("content_type") or "").lower(),
            )
            if key in grouped:
                grouped[key].append(update)
        lines = [
            "## 创作者动态追踪",
            "",
        ]
        failure_keys = {
            (
                str(failure.get("platform") or "").lower(),
                str(failure.get("content_type") or "").lower(),
            )
            for failure in status.get("failures") or []
        }
        for platform, content_type, title in CREATOR_SECTION_DEFINITIONS:
            values = sorted(
                grouped[(platform, content_type)],
                key=lambda value: str(
                    value.get("published_at") or ""
                ),
                reverse=True,
            )
            lines.append(
                f"### {title}（{len(values)} 条）"
            )
            if not values:
                lines.extend(
                    [
                        (
                            "采集失败，无法确认今日更新。"
                            if (
                                platform,
                                content_type,
                            ) in failure_keys
                            else "今日暂无更新。"
                        ),
                        "",
                    ]
                )
                continue
            for index, update in enumerate(
                values,
                1,
            ):
                lines.extend(
                    self._render_creator_update(
                        update,
                        index,
                        content_type,
                    )
                )
        failures = status.get("failures") or []
        if status.get("status") in {
            "failed",
            "partial",
        } or failures:
            lines.append(
                "采集状态：数据不完整。"
            )
            for failure in failures:
                lines.append(
                    "- "
                    f"{failure.get('platform') or 'unknown'} "
                    f"{failure.get('content_type') or 'source'}："
                    f"{failure.get('error') or '采集失败'}"
                )
            lines.append("")
        elif status.get("status") == "not_configured":
            lines.extend(
                [
                    "采集状态：尚未配置监控账号。",
                    "",
                ]
            )
        return lines

    @staticmethod
    def _render_creator_update(
        update: dict[str, Any],
        index: int,
        content_type: str,
    ) -> list[str]:
        """渲染单条创作者更新并保留原始链接。"""
        metadata = update.get("metadata") or {}
        creator_name = str(
            update.get("creator_name")
            or "未命名创作者"
        )
        title = _short_text(
            str(update.get("title") or "未命名内容"),
            180,
        )
        url = str(
            update.get("url") or ""
        )
        lines = [
            f"{index}. {creator_name}："
            f"《{title}》"
            if content_type == "video"
            else f"{index}. {creator_name}（"
            f"{metadata.get('dynamic_type') or '动态'}）",
        ]
        if content_type == "dynamic":
            lines.append(
                "   内容："
                + _short_text(
                    str(
                        update.get("summary")
                        or update.get("content")
                        or title
                    ),
                    300,
                )
            )
            images = metadata.get("images") or []
            for image_url in images[:3]:
                lines.append(
                    "   图片："
                    + str(image_url)
                )
        elif metadata.get("thumbnail"):
            lines.append(
                "   封面："
                + str(metadata.get("thumbnail"))
            )
        lines.extend(
            [
                "   发布时间："
                + _display_time(update.get("published_at")),
                f"   链接：{url}",
                "",
            ]
        )
        return lines

    @staticmethod
    def quality_metrics(
        items: Iterable[dict[str, Any]],
    ) -> dict[str, Any]:
        """统计 README、项目分析、新闻链接和时间字段的轻量质量指标。"""
        values = list(items)
        projects = [
            item
            for item in values
            if item.get("item_type") == "github"
        ]
        news = [
            item
            for item in values
            if item.get("item_type") == "news"
        ]
        readme_success = sum(
            (item.get("metadata") or {}).get("readme", {}).get("status")
            == "success"
            for item in projects
        )
        traceable = sum(
            bool(
                (item.get("metadata") or {})
                .get("project_analysis", {})
                .get("evidence_urls")
            )
            for item in projects
        )
        news_urls = sum(
            str(item.get("url") or "").startswith(
                (
                    "http://",
                    "https://",
                )
            )
            for item in news
        )
        news_published = sum(
            bool(item.get("published_at"))
            for item in news
        )
        return {
            "readme_success_rate": _rate_text(
                readme_success,
                len(projects),
            ),
            "project_traceability_rate": _rate_text(
                traceable,
                len(projects),
            ),
            "news_url_rate": _rate_text(
                news_urls,
                len(news),
            ),
            "news_published_rate": _rate_text(
                news_published,
                len(news),
            ),
            "unique_items": len(values),
        }

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


def split_qq_messages(
    markdown: str,
    max_chars: int = QQ_DEFAULT_MAX_CHARS,
) -> list[str]:
    """按章节和完整条目拆分 QQ Markdown，并为每段添加日期和序号。"""
    if max_chars < 100:
        raise ValueError(
            "max_chars 必须至少为 100"
        )
    normalized = markdown.strip()
    if not normalized:
        return []
    report_date = _extract_report_date(
        normalized,
    )
    budget = _message_content_budget(
        max_chars,
        report_date,
    )
    parts = _split_markdown_sections(
        normalized,
    )
    units: list[str] = []
    for section in parts:
        units.extend(
            _split_qq_section(
                section.strip(),
                budget,
            )
        )
    chunks: list[str] = []
    current = ""
    for unit in units:
        candidate = (
            f"{current}\n\n{unit}"
            if current
            else unit
        )
        if current and len(candidate) > budget:
            chunks.append(current)
            current = unit
        else:
            current = candidate
    if current:
        chunks.append(current)
    total = len(chunks)
    messages: list[str] = []
    for index, chunk in enumerate(
        chunks,
        1,
    ):
        message = (
            f"{_message_header(report_date, index, total)}\n\n"
            f"{chunk}"
        )
        if index == total:
            message += f"\n\n{QQ_COMPLETION_MARKER}"
        messages.append(message)
    return messages


def _split_qq_section(
    section: str,
    budget: int,
) -> list[str]:
    """在超长章节内按三级标题和完整行拆分，避免截断条目。"""
    if len(section) <= budget:
        return [section]
    blocks = _split_markdown_blocks(
        section,
    )
    if len(blocks) <= 1:
        section_lines = section.splitlines()
        section_heading = ""
        section_body = section
        if section_lines and section_lines[0].strip().startswith(
            "## "
        ):
            section_heading = section_lines[0].strip()
            section_body = "\n".join(
                section_lines[1:]
            ).strip()
        if not section_heading:
            return _split_text_without_truncating(
                section,
                budget,
            )
        body_budget = max(
            1,
            budget - len(section_heading) - 2,
        )
        return [
            f"{section_heading}\n\n{part}"
            for part in _split_text_without_truncating(
                section_body,
                body_budget,
            )
        ]
    heading = blocks[0].strip()
    result: list[str] = []
    for block in blocks[1:]:
        block_text = block.strip()
        block_lines = block_text.splitlines()
        block_heading = ""
        if block_lines and block_lines[0].strip().startswith(
            "### "
        ):
            block_heading = block_lines[0].strip()
            block_text = "\n".join(
                block_lines[1:]
            ).strip()
        context = "\n\n".join(
            value
            for value in (
                heading,
                block_heading,
            )
            if value
        )
        block_budget = max(
            1,
            budget - len(context) - 2,
        )
        for part in _split_text_without_truncating(
            block_text,
            block_budget,
        ):
            result.append(
                f"{context}\n\n{part}"
            )
    return result


def read_qq_report(
    report_path: Path | str,
    max_chars: int = QQ_DEFAULT_MAX_CHARS,
) -> dict[str, Any]:
    """以 UTF-8 读取指定 QQ 日报，并返回完整正文和消息分段。"""
    resolved_path = Path(
        report_path
    ).expanduser().resolve()
    if not resolved_path.name.endswith(
        ".qq.md"
    ):
        raise ValueError(
            f"日报正文接口只接受 .qq.md 文件：{resolved_path}"
        )
    try:
        content = resolved_path.read_text(
            encoding="utf-8",
        )
    except UnicodeError as error:
        raise ValueError(
            f"日报文件不是有效 UTF-8：{resolved_path}"
        ) from error
    except OSError as error:
        raise OSError(
            f"日报文件读取失败：{resolved_path}：{error}"
        ) from error
    if not content.strip():
        raise ValueError(
            f"日报正文为空：{resolved_path}"
        )
    messages = split_qq_messages(
        content,
        max_chars=max_chars,
    )
    if not messages:
        raise ValueError(
            f"日报正文为空：{resolved_path}"
        )
    return {
        "path": str(resolved_path),
        "report_date": _extract_report_date(
            content,
        ),
        "content": content,
        "char_count": len(content),
        "message_count": len(messages),
        "messages": messages,
    }


def _extract_report_date(
    markdown: str,
) -> str | None:
    """从日报标题或生成时间中提取逻辑日期。"""
    match = re.search(
        r"(?<!\d)(\d{4}-\d{2}-\d{2})(?!\d)",
        markdown,
    )
    return match.group(1) if match else None


def _message_header(
    report_date: str | None,
    index: int,
    total: int,
) -> str:
    """生成每条 QQ 消息都携带的日报日期和连续序号。"""
    date_text = report_date or "日报"
    return (
        f"DailyIntelligence {date_text}\n"
        f"第 {index}/{total} 部分"
    )


def _message_content_budget(
    max_chars: int,
    report_date: str | None,
) -> int:
    """为消息序号头预留空间，保证正常分段不超过消息上限。"""
    reserve = len(
        _message_header(
            report_date,
            999999,
            999999,
        )
    ) + len(
        f"\n\n{QQ_COMPLETION_MARKER}"
    )
    return max(
        1,
        max_chars - reserve,
    )


def _split_markdown_sections(
    markdown: str,
) -> list[str]:
    """按顶层二级标题拆分 Markdown，同时避开 fenced code block。"""
    return _split_markdown_at_heading(
        markdown,
        "## ",
    )


def _split_markdown_blocks(
    markdown: str,
) -> list[str]:
    """按顶层三级标题拆分 Markdown，同时避开 fenced code block。"""
    return _split_markdown_at_heading(
        markdown,
        "### ",
    )


def _split_markdown_at_heading(
    markdown: str,
    heading_prefix: str,
) -> list[str]:
    """在未进入代码块时按标题切分，并保留每个切片的原文。"""
    lines = markdown.splitlines()
    parts: list[str] = []
    current: list[str] = []
    fence: str | None = None
    for line in lines:
        stripped = line.strip()
        is_fence = stripped.startswith(
            (
                "```",
                "~~~",
            )
        )
        if (
            not current
            or fence is not None
            or not stripped.startswith(heading_prefix)
        ):
            current.append(line)
        else:
            parts.append(
                "\n".join(current).strip()
            )
            current = [line]
        if is_fence:
            marker = stripped[:3]
            if fence is None:
                fence = marker
            elif marker == fence:
                fence = None
    if current:
        parts.append(
            "\n".join(current).strip()
        )
    return [
        part
        for part in parts
        if part
    ]


def _split_text_without_truncating(
    text: str,
    budget: int,
) -> list[str]:
    """按完整行和完整代码块切分文本，不截断 URL 或 Markdown。"""
    if len(text) <= budget:
        return [text]
    lines = text.splitlines()
    units: list[str] = []
    current: list[str] = []
    fence: str | None = None
    for line in lines:
        stripped = line.strip()
        is_fence = stripped.startswith(
            (
                "```",
                "~~~",
            )
        )
        current.append(line)
        if is_fence:
            marker = stripped[:3]
            if fence is None:
                fence = marker
            elif marker == fence:
                fence = None
        if fence is None and line.strip() == "":
            units.append(
                "\n".join(current).strip()
            )
            current = []
    if current:
        units.append(
            "\n".join(current).strip()
        )
    if not units:
        return [text]
    expanded_units: list[str] = []
    for unit in units:
        expanded_units.extend(
            _split_oversized_unit(
                unit,
                budget,
            )
        )
    units = expanded_units
    chunks: list[str] = []
    current_text = ""
    for unit in units:
        candidate = (
            f"{current_text}\n\n{unit}"
            if current_text
            else unit
        )
        if current_text and len(candidate) > budget:
            chunks.append(current_text)
            current_text = unit
        else:
            current_text = candidate
    if current_text:
        chunks.append(current_text)
    return chunks


def _split_oversized_unit(
    text: str,
    budget: int,
) -> list[str]:
    """拆分超长普通文本，保留 Markdown 链接和代码块完整性。"""
    if len(text) <= budget:
        return [text]
    if "```" in text or "~~~" in text:
        fenced_parts = _split_oversized_fenced_block(
            text,
            budget,
        )
        if fenced_parts is not None:
            return fenced_parts
        return [text]
    tokens = re.findall(
        r"\[[^\]\n]+\]\([^\)\n]+\)|https?://\S+|\S+",
        text,
    )
    if not tokens or any(
        len(token) > budget
        for token in tokens
    ):
        return [text]
    chunks: list[str] = []
    current = ""
    for token in tokens:
        candidate = (
            f"{current} {token}"
            if current
            else token
        )
        if current and len(candidate) > budget:
            chunks.append(current)
            current = token
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def _split_oversized_fenced_block(
    text: str,
    budget: int,
) -> list[str] | None:
    """为超长 fenced code block 重复围栏并分段，避免破坏 Markdown。"""
    lines = text.splitlines()
    opening_index = next(
        (
            index
            for index, line in enumerate(lines)
            if line.strip().startswith(
                (
                    "```",
                    "~~~",
                )
            )
        ),
        None,
    )
    if opening_index is None:
        return None
    opening = lines[opening_index].strip()
    marker = opening[:3]
    closing_index = next(
        (
            index
            for index in range(
                opening_index + 1,
                len(lines),
            )
            if lines[index].strip() == marker
        ),
        None,
    )
    if closing_index is None:
        return None
    if any(
        line.strip()
        for line in lines[:opening_index]
    ) or any(
        line.strip()
        for line in lines[closing_index + 1:]
    ):
        return None
    body_lines = lines[opening_index + 1:closing_index]
    body_budget = budget - len(opening) - len(marker) - 2
    if body_budget < 1:
        return None
    if any(
        len(line) > body_budget
        for line in body_lines
    ):
        return None
    chunks: list[str] = []
    current: list[str] = []
    current_length = 0
    for line in body_lines:
        line_length = len(line)
        separator_length = 1 if current else 0
        if (
            current
            and current_length + separator_length + line_length
            > body_budget
        ):
            chunks.append(
                "\n".join(
                    [
                        opening,
                        *current,
                        marker,
                    ]
                )
            )
            current = []
            current_length = 0
        current.append(line)
        current_length += separator_length + line_length
    if current or not body_lines:
        chunks.append(
            "\n".join(
                [
                    opening,
                    *current,
                    marker,
                ]
            )
        )
    return chunks


def save_report(
    paths: RuntimePaths,
    markdown: str,
    report_date: date,
) -> Path:
    """以原子替换方式保存指定日期的完整 Markdown 日报。"""
    report_path = paths.reports_dir / f"{report_date.isoformat()}.md"
    return _save_markdown(
        paths.reports_dir,
        report_path,
        markdown,
    )


def save_qq_report(
    paths: RuntimePaths,
    markdown: str,
    report_date: date,
) -> Path:
    """保存供 QQ Bot 媒体上传使用的 Markdown 附件文件。"""
    report_path = paths.reports_dir / f"{report_date.isoformat()}.qq.md"
    return _save_markdown(
        paths.reports_dir,
        report_path,
        markdown,
    )


def _save_markdown(
    directory: Path,
    target: Path,
    markdown: str,
) -> Path:
    """执行带 fsync 的 Markdown 原子写入。"""
    directory.mkdir(
        parents=True,
        exist_ok=True,
    )
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=directory,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(
                handle.name
            )
            handle.write(markdown)
            handle.flush()
            os.fsync(handle.fileno())
        temporary_path.replace(target)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(
                missing_ok=True,
            )
    return target


def _render_list(
    values: Iterable[Any],
    empty_text: str,
) -> list[str]:
    """把列表字段渲染为 Markdown 列表。"""
    normalized = [
        str(value).strip()
        for value in values
        if str(value).strip()
    ]
    if not normalized:
        return [
            f"- {empty_text}",
        ]
    return [
        f"- {value}"
        for value in normalized
    ]


def _display_time(
    value: Any,
) -> str:
    """显示时间字段，未知值不被伪造为当前时间。"""
    if not value:
        return "未知"
    return str(value).replace(
        "T",
        " ",
    ).replace(
        "+00:00",
        " UTC",
    )


def _number_text(
    value: Any,
) -> str:
    """格式化 Star/Fork 数字并保留未知状态。"""
    if value is None or value == "":
        return "未知"
    try:
        return f"{int(value):,}"
    except (
        TypeError,
        ValueError,
    ):
        return "未知"


def _short_text(
    value: str,
    limit: int,
) -> str:
    """限制摘要长度，避免速览区吞没完整条目。"""
    text = " ".join(value.split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _rate_text(
    numerator: int,
    denominator: int,
) -> str:
    """把质量指标转换为可读百分比并区分无样本。"""
    if denominator <= 0:
        return "无样本"
    return f"{numerator}/{denominator} ({numerator / denominator:.0%})"
