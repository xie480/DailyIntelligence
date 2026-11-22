"""基于兴趣画像和历史反馈的轻量推荐排序。"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable

from .config import now_iso
from .database import Database
from .profile import InterestProfileStore


RECOMMENDATION_COOLDOWN_DAYS = 30
SIGNIFICANT_STAR_GROWTH = 100


class RecommendationEngine:
    """读取项目并计算可解释的兴趣匹配分数。"""

    def __init__(
        self,
        database: Database,
        profile: InterestProfileStore,
    ) -> None:
        """绑定数据库和画像存储。"""
        self.database = database
        self.profile = profile

    def recommend(
        self,
        limit: int = 15,
        item_type: str | None = None,
        now: datetime | None = None,
        record: bool = True,
    ) -> list[dict[str, Any]]:
        """返回排序后的推荐，并可记录本次推荐历史。"""
        profile = self.profile.load()
        if not profile["enabled"]:
            return []
        current = self._ensure_aware(
            now
            or datetime.now(timezone.utc)
        )
        cutoff = (
            current
            - timedelta(days=RECOMMENDATION_COOLDOWN_DAYS)
        ).isoformat()
        recent_ids = self.database.recent_recommendation_ids(cutoff)
        candidates = self.database.list_items(
            item_type=item_type,
            limit=500,
        )
        results: list[dict[str, Any]] = []
        for item in candidates:
            item_id = int(item["id"])
            if item_id in recent_ids and not self._has_cooldown_override(
                item,
                current,
            ):
                continue
            if self._is_excluded(
                item,
                profile,
            ):
                continue
            score, matched_interests = self._score_item(
                item,
                profile,
                current,
            )
            result = dict(item)
            result["recommendation_score"] = round(
                score,
                2,
            )
            result["match_reason"] = self._match_reason(
                matched_interests,
                item,
            )
            results.append(result)
        results.sort(
            key=lambda item: (
                -item["recommendation_score"],
                item.get("published_at") or "",
            )
        )
        selected = results[: max(0, limit)]
        if record:
            self.record_recommendations(selected)
        return selected

    def record_recommendations(
        self,
        items: Iterable[dict[str, Any]],
        report_date: date | None = None,
    ) -> int:
        """记录实际展示的推荐，并按日报日期避免重复写入。"""
        report_date_value = (
            report_date.isoformat()
            if report_date is not None
            else None
        )
        recorded = 0
        seen_item_ids: set[int] = set()
        pending: list[dict[str, Any]] = []
        for item in items:
            item_id = int(item["id"])
            if item_id in seen_item_ids:
                continue
            seen_item_ids.add(item_id)
            if (
                report_date_value is not None
                and self.database.has_recommendation_for_report(
                    item_id,
                    report_date_value,
                )
            ):
                continue
            signal = {
                "score": item["recommendation_score"],
                "recommended_at": now_iso(),
            }
            if report_date_value is not None:
                signal["report_date"] = report_date_value
            pending.append(
                {
                    "action": "recommended",
                    "target": item.get("repo_full_name")
                    or item.get("url")
                    or "",
                    "item_id": item_id,
                    "note": item["match_reason"],
                    "signal": signal,
                }
            )
        if pending:
            recorded = self.database.save_feedback_batch(
                pending,
            )
        return recorded

    def _score_item(
        self,
        item: dict[str, Any],
        profile: dict[str, Any],
        current: datetime,
    ) -> tuple[float, list[str]]:
        """按关键词、权重、时效和社区活跃度计算分数。"""
        metadata = item.get("metadata") or {}
        searchable = " ".join(
            str(value)
            for value in (
                item.get("title"),
                item.get("summary"),
                item.get("category"),
                item.get("repo_full_name"),
                " ".join(metadata.get("topics") or []),
                item.get("language"),
            )
            if value
        ).casefold()
        score = 1.0
        matched: list[str] = []
        for interest, weight in profile["interests"].items():
            terms = {
                interest.casefold(),
                interest.replace(
                    " ",
                    "",
                ).casefold(),
            }
            if any(
                term and term in searchable
                for term in terms
            ):
                score += 10.0 + float(weight) * 0.35
                matched.append(interest)
        target = str(
            item.get("repo_full_name")
            or item.get("url")
            or ""
        ).casefold()
        if any(
            favorite.casefold() in target
            for favorite in profile.get("favorite_projects", [])
        ):
            score += 20.0
            matched.append("已收藏项目")
        published_at = self._parse_datetime(
            item.get("published_at")
        )
        if published_at:
            age_days = max(
                0.0,
                (
                    current - published_at
                ).total_seconds()
                / 86400,
            )
            score += max(
                0.0,
                15.0 - age_days,
            )
        if item.get("stars"):
            score += min(
                10.0,
                math.log10(
                    int(item["stars"]) + 1
                ) * 2,
            )
        repo_name = str(
            item.get("repo_full_name")
            or ""
        )
        if repo_name:
            growth = self.database.star_growth(
                repo_name,
                7,
            )
            if growth:
                metadata["star_growth_7d"] = growth
                score += min(
                    10.0,
                    max(
                        0.0,
                        growth / 50.0,
                    ),
                )
        source = str(item.get("source") or "").casefold()
        if "official" in source:
            score += 5.0
        return score, matched

    @staticmethod
    def _is_excluded(
        item: dict[str, Any],
        profile: dict[str, Any],
    ) -> bool:
        """过滤用户明确排除的项目和主题。"""
        target_text = " ".join(
            str(item.get(key) or "")
            for key in (
                "repo_full_name",
                "title",
                "url",
            )
        ).casefold()
        if any(
            excluded.casefold() in target_text
            for excluded in profile["excluded_projects"]
        ):
            return True
        topic_text = " ".join(
            str(value)
            for value in (
                item.get("title"),
                item.get("summary"),
                item.get("category"),
                " ".join(
                    (item.get("metadata") or {}).get("topics") or []
                ),
            )
            if value
        ).casefold()
        return any(
            excluded.casefold() in topic_text
            for excluded in profile["excluded_topics"]
        )

    def _has_cooldown_override(
        self,
        item: dict[str, Any],
        current: datetime,
    ) -> bool:
        """允许新 Release 或显著 Star 增长绕过推荐冷却。"""
        release = (
            item.get("metadata") or {}
        ).get("latest_release") or {}
        published = RecommendationEngine._parse_datetime(
            release.get("published_at")
        )
        fresh_release = bool(
            published
            and current - published <= timedelta(days=7)
        )
        repo_name = str(
            item.get("repo_full_name")
            or ""
        )
        growth = (
            self.database.star_growth(
                repo_name,
                7,
            )
            if repo_name
            else 0
        )
        return fresh_release or growth >= SIGNIFICANT_STAR_GROWTH

    @staticmethod
    def _match_reason(
        matched_interests: list[str],
        item: dict[str, Any],
    ) -> str:
        """生成日报中可直接展示的推荐理由。"""
        if matched_interests:
            return "匹配兴趣：" + "、".join(
                matched_interests[:4]
            )
        return "来源和更新时间较新，适合作为补充阅读"

    @staticmethod
    def _parse_datetime(
        value: Any,
    ) -> datetime | None:
        """解析项目时间并统一为带 UTC 时区的时间。"""
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(
                str(value).replace(
                    "Z",
                    "+00:00",
                )
            )
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _ensure_aware(
        value: datetime,
    ) -> datetime:
        """为推荐计算的无时区时间补 UTC。"""
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

