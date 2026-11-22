"""Hermes Web Search 与 Daily Intelligence 之间的 JSON 交接。"""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from typing import Any, Iterable
from urllib.parse import urlsplit

from .database import Database
from .deduplication import deduplicate_items
from .models import Item


HANDOFF_SCHEMA_VERSION = "1.0"
SEARCH_CATEGORIES = (
    "ai",
    "agent",
    "software",
)
SEARCH_STATUSES = frozenset(
    {
        "success",
        "partial",
        "empty",
        "unavailable",
        "network_error",
        "page_unavailable",
        "time_unverified",
        "low_confidence",
        "not_run",
    }
)
MAX_HANDOFF_TEXT_LENGTH = 30000


class HandoffValidationError(ValueError):
    """表示 Hermes 交接 JSON 缺少必需字段或包含不安全数据。"""


def write_handoff(
    path: Path | str,
    payload: dict[str, Any],
) -> Path:
    """校验并原子写入交接 JSON，不暴露或保存凭证字段。"""
    normalized = validate_handoff(payload)
    target = Path(path).expanduser()
    target.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(
                handle.name
            )
            handle.write(
                json.dumps(
                    normalized,
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n"
            )
            handle.flush()
            os.fsync(handle.fileno())
        temporary_path.replace(target)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(
                missing_ok=True,
            )
    return target


def load_handoff(
    path: Path | str,
) -> dict[str, Any]:
    """读取并校验 Hermes 交接 JSON。"""
    source = Path(path).expanduser()
    try:
        raw = json.loads(
            source.read_text(
                encoding="utf-8",
            )
        )
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
    ) as error:
        raise HandoffValidationError(
            f"无法读取交接文件 {source.name}：{type(error).__name__}"
        ) from None
    return validate_handoff(raw)


def validate_handoff(
    payload: Any,
) -> dict[str, Any]:
    """验证交接格式并返回不含未知危险字段的规范化副本。"""
    if not isinstance(payload, dict):
        raise HandoffValidationError(
            "交接 JSON 顶层必须是对象"
        )
    if str(payload.get("schema_version") or "") != HANDOFF_SCHEMA_VERSION:
        raise HandoffValidationError(
            f"不支持的交接 schema_version：{payload.get('schema_version')}"
        )
    generated_at = _required_text(
        payload,
        "generated_at",
    )
    timezone_name = _required_text(
        payload,
        "timezone",
    )
    status_map = _normalize_status_map(
        payload.get("search_status")
    )
    query_map = _normalize_query_map(
        payload.get("search_queries")
    )
    news = _normalize_news(
        payload.get("news")
    )
    projects = _normalize_projects(
        payload.get("projects")
    )
    window_hours = payload.get("window_hours")
    try:
        normalized_window_hours = int(window_hours or 24)
    except (
        TypeError,
        ValueError,
    ):
        raise HandoffValidationError(
            "window_hours 必须是整数"
        ) from None
    if normalized_window_hours <= 0:
        raise HandoffValidationError(
            "window_hours 必须大于 0"
        )
    return {
        "schema_version": HANDOFF_SCHEMA_VERSION,
        "generated_at": generated_at,
        "timezone": timezone_name,
        "window_hours": normalized_window_hours,
        "search_status": status_map,
        "search_queries": query_map,
        "news": news,
        "projects": projects,
        "collection_stats": _normalize_mapping(
            payload.get("collection_stats")
        ),
    }


def news_items_from_handoff(
    payload: dict[str, Any],
) -> list[Item]:
    """把已校验的 Web Search 新闻转换为统一 Item。"""
    normalized = validate_handoff(payload)
    status_map = normalized["search_status"]
    query_map = normalized["search_queries"]
    items: list[Item] = []
    for news in normalized["news"]:
        category = news["category"]
        summary = news["summary"]
        key_changes = news["key_changes"]
        why_it_matters = news["why_it_matters"]
        metadata = {
            "section": category,
            "source_type": "hermes_web_search",
            "search_status": status_map[category],
            "search_queries": query_map[category],
            "event_at": news.get("event_at"),
            "updated_at": news.get("updated_at"),
            "key_changes": key_changes,
            "importance": news["importance"],
            "why_it_matters": why_it_matters,
            "why": why_it_matters,
            "source_verified": news["source_verified"],
            "evidence_urls": news["evidence_urls"],
            "search_window_hours": normalized["window_hours"],
        }
        published_at = news.get("published_at")
        items.append(
            Item(
                item_type="news",
                external_id=news["url"],
                title=news["title"],
                url=news["url"],
                source=news["source_name"],
                published_at=published_at,
                summary=summary,
                content=" ".join(
                    [
                        summary,
                        " ".join(key_changes),
                        why_it_matters,
                    ]
                ).strip(),
                category=category,
                metadata=metadata,
            )
        )
    return items


def import_handoff(
    database: Database,
    source_path: Path | str,
    target_path: Path | str | None = None,
) -> dict[str, Any]:
    """导入搜索新闻和项目分析，并可把已校验文件保存到运行目录。"""
    payload = load_handoff(
        source_path,
    )
    if target_path is not None:
        write_handoff(
            target_path,
            payload,
        )
    incoming_items = news_items_from_handoff(
        payload,
    )
    existing_items = [
        _item_from_record(record)
        for record in database.list_items(
            item_type="news",
            limit=5000,
        )
    ]
    merged_items = deduplicate_items(
        [
            *existing_items,
            *incoming_items,
        ]
    )
    for item in merged_items:
        database.upsert_item(
            item,
        )
    projects_updated = 0
    for project in payload["projects"]:
        projects_updated += database.enrich_repository(
            project["repository"],
            project,
        )
    return {
        "news_imported": len(incoming_items),
        "news_unique": len(merged_items),
        "projects_updated": projects_updated,
        "search_status": payload["search_status"],
        "generated_at": payload["generated_at"],
    }


def _item_from_record(
    record: dict[str, Any],
) -> Item:
    """把数据库字典转换回去重需要的领域模型。"""
    return Item(
        item_type=str(record.get("item_type") or "news"),
        external_id=record.get("external_id"),
        title=str(record.get("title") or "未命名"),
        url=str(record.get("url") or ""),
        source=str(record.get("source") or "未知来源"),
        published_at=record.get("published_at"),
        summary=str(record.get("summary") or ""),
        content=str(record.get("content") or ""),
        category=str(record.get("category") or ""),
        language=record.get("language"),
        repo_full_name=record.get("repo_full_name"),
        stars=record.get("stars"),
        forks=record.get("forks"),
        metadata=record.get("metadata") or {},
    )


def _normalize_status_map(
    value: Any,
) -> dict[str, str]:
    """规范化三个领域的搜索状态，缺省领域明确标记为未执行。"""
    source = value if isinstance(value, dict) else {}
    result: dict[str, str] = {}
    for category in SEARCH_CATEGORIES:
        status = str(
            source.get(category) or "not_run"
        ).casefold()
        if status not in SEARCH_STATUSES:
            raise HandoffValidationError(
                f"{category} 的 search_status 无效：{status}"
            )
        result[category] = status
    return result


def _normalize_query_map(
    value: Any,
) -> dict[str, list[str]]:
    """规范化每个领域的搜索查询列表。"""
    source = value if isinstance(value, dict) else {}
    result: dict[str, list[str]] = {}
    for category in SEARCH_CATEGORIES:
        raw_queries = source.get(category) or []
        if not isinstance(raw_queries, list):
            raise HandoffValidationError(
                f"{category} 的 search_queries 必须是列表"
            )
        result[category] = [
            _bounded_text(
                query,
                "search_query",
            )
            for query in raw_queries
            if str(query).strip()
        ]
    return result


def _normalize_news(
    value: Any,
) -> list[dict[str, Any]]:
    """校验新闻字段、来源链接和发布时间，不根据标题猜测内容。"""
    if value is None:
        return []
    if not isinstance(value, list):
        raise HandoffValidationError(
            "news 必须是列表"
        )
    result: list[dict[str, Any]] = []
    for index, raw in enumerate(value):
        if not isinstance(raw, dict):
            raise HandoffValidationError(
                f"news[{index}] 必须是对象"
            )
        category = _required_text(
            raw,
            "category",
        ).casefold()
        if category not in SEARCH_CATEGORIES:
            raise HandoffValidationError(
                f"news[{index}] category 无效：{category}"
            )
        url = _required_text(
            raw,
            "url",
        )
        if urlsplit(url).scheme.casefold() not in {
            "http",
            "https",
        }:
            raise HandoffValidationError(
                f"news[{index}] url 必须是 http/https"
            )
        result.append(
            {
                "title": _bounded_text(raw.get("title"), "title"),
                "category": category,
                "source_name": _bounded_text(
                    raw.get("source_name"),
                    "source_name",
                ),
                "published_at": _optional_text(raw.get("published_at")),
                "event_at": _optional_text(raw.get("event_at")),
                "updated_at": _optional_text(raw.get("updated_at")),
                "url": url,
                "summary": _bounded_text(raw.get("summary"), "summary"),
                "key_changes": _text_list(
                    raw.get("key_changes"),
                    "key_changes",
                ),
                "importance": raw.get("importance") or 0,
                "why_it_matters": _bounded_text(
                    raw.get("why_it_matters"),
                    "why_it_matters",
                ),
                "source_verified": bool(raw.get("source_verified")),
                "evidence_urls": _url_list(
                    raw.get("evidence_urls"),
                    "evidence_urls",
                ),
            }
        )
    return result


def _normalize_projects(
    value: Any,
) -> list[dict[str, Any]]:
    """校验 README 分析结果及其证据链接。"""
    if value is None:
        return []
    if not isinstance(value, list):
        raise HandoffValidationError(
            "projects 必须是列表"
        )
    result: list[dict[str, Any]] = []
    for index, raw in enumerate(value):
        if not isinstance(raw, dict):
            raise HandoffValidationError(
                f"projects[{index}] 必须是对象"
            )
        repository = _required_text(
            raw,
            "repository",
        )
        if repository.count("/") != 1:
            raise HandoffValidationError(
                f"projects[{index}] repository 必须是 owner/repo"
            )
        result.append(
            {
                "repository": repository,
                "summary": _bounded_text(raw.get("summary"), "summary"),
                "features": _text_list(
                    raw.get("features"),
                    "features",
                ),
                "use_cases": _text_list(
                    raw.get("use_cases"),
                    "use_cases",
                ),
                "recommendation_reason": _bounded_text(
                    raw.get("recommendation_reason"),
                    "recommendation_reason",
                ),
                "evidence_urls": _url_list(
                    raw.get("evidence_urls"),
                    "evidence_urls",
                ),
            }
        )
    return result


def _required_text(
    mapping: dict[str, Any],
    key: str,
) -> str:
    """读取必需文本并限制最大长度。"""
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise HandoffValidationError(
            f"缺少必需字段：{key}"
        )
    return _bounded_text(
        value,
        key,
    )


def _optional_text(
    value: Any,
) -> str | None:
    """把可选时间字段清理为空值或有限长度文本。"""
    if not isinstance(value, str) or not value.strip():
        return None
    return _bounded_text(
        value,
        "datetime",
    )


def _bounded_text(
    value: Any,
    field_name: str,
) -> str:
    """校验文本字段并拒绝超长或非文本输入。"""
    if not isinstance(value, str) or not value.strip():
        raise HandoffValidationError(
            f"{field_name} 必须是非空字符串"
        )
    text = value.strip()
    if len(text) > MAX_HANDOFF_TEXT_LENGTH:
        raise HandoffValidationError(
            f"{field_name} 超过长度限制"
        )
    return text


def _text_list(
    value: Any,
    field_name: str,
) -> list[str]:
    """校验结构化文本列表。"""
    if value is None:
        return []
    if not isinstance(value, list):
        raise HandoffValidationError(
            f"{field_name} 必须是列表"
        )
    return [
        _bounded_text(
            item,
            field_name,
        )
        for item in value
        if isinstance(item, str) and item.strip()
    ]


def _url_list(
    value: Any,
    field_name: str,
) -> list[str]:
    """校验证据链接列表。"""
    urls = _text_list(
        value,
        field_name,
    )
    for url in urls:
        if urlsplit(url).scheme.casefold() not in {
            "http",
            "https",
        }:
            raise HandoffValidationError(
                f"{field_name} 只能包含 http/https 链接"
            )
    return urls


def _normalize_mapping(
    value: Any,
) -> dict[str, Any]:
    """限制可选统计对象为 JSON 对象。"""
    return dict(value) if isinstance(value, dict) else {}
