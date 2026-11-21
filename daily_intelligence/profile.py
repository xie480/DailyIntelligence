"""用户兴趣画像、显式反馈和隐式信号管理。"""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import RuntimePaths, now_iso
from .database import Database


DEFAULT_INTERESTS = {
    "AI Agent": 95,
    "Agent Harness": 90,
    "Hermes": 90,
    "Codex": 90,
    "Claude Code": 80,
    "MCP": 90,
    "Skills": 88,
    "AI Coding": 90,
    "Software Engineering": 80,
    "System Architecture": 75,
    "Frontend": 65,
    "UI/UX": 60,
    "Open Source": 85,
    "Self-hosting": 75,
    "Innovative Projects": 80,
    "Model Releases": 50,
    "普通 AI 套壳项目": 15,
}
MAX_EVIDENCE_LENGTH = 160
WEIGHT_STEP = 10
IMPLICIT_SIGNAL_THRESHOLD = 3


@dataclass(frozen=True, slots=True)
class FeedbackResult:
    """描述一次自然语言反馈解析结果。"""

    action: str
    changes: dict[str, int] = field(default_factory=dict)
    target: str = ""
    message: str = ""


class InterestProfileStore:
    """把用户画像保存为 JSON，并把反馈历史写入 SQLite。"""

    def __init__(
        self,
        paths: RuntimePaths,
        database: Database,
    ) -> None:
        """绑定运行路径和反馈数据库。"""
        self.paths = paths
        self.database = database
        self._profile: dict[str, Any] | None = None

    def load(self) -> dict[str, Any]:
        """读取画像，不存在或损坏时创建安全的默认画像。"""
        if self._profile is not None:
            return copy.deepcopy(self._profile)
        if not self.paths.profile_path.is_file():
            self._profile = self._default_profile()
            self.save()
            return copy.deepcopy(self._profile)
        try:
            raw = json.loads(
                self.paths.profile_path.read_text(
                    encoding="utf-8"
                )
            )
            self._profile = self._normalize_profile(raw)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            self._profile = self._default_profile()
            self.save()
        return copy.deepcopy(self._profile)

    def save(
        self,
        profile: dict[str, Any] | None = None,
    ) -> None:
        """以原子替换方式持久化画像 JSON。"""
        current = self._normalize_profile(
            profile
            if profile is not None
            else self._profile
            or self._default_profile()
        )
        current["updated_at"] = now_iso()
        self.paths.config_dir.mkdir(
            parents=True,
            exist_ok=True,
        )
        temporary_path = self.paths.profile_path.with_name(
            f"{self.paths.profile_path.name}.tmp"
        )
        temporary_path.write_text(
            json.dumps(
                current,
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        temporary_path.replace(self.paths.profile_path)
        self._profile = current

    def reset(self) -> dict[str, Any]:
        """清除排除列表、证据和隐式信号并恢复默认权重。"""
        self._profile = self._default_profile()
        self.save()
        self.database.save_feedback(
            action="reset",
            note="用户重置兴趣画像",
        )
        return copy.deepcopy(self._profile)

    def set_enabled(
        self,
        enabled: bool,
    ) -> dict[str, Any]:
        """开启或关闭画像参与推荐。"""
        profile = self.load()
        profile["enabled"] = bool(enabled)
        self.save(profile)
        self.database.save_feedback(
            action="profile_enabled" if enabled else "profile_disabled",
            note="用户切换兴趣画像",
            signal={
                "enabled": enabled,
            },
        )
        return copy.deepcopy(self._profile)

    def apply_feedback(
        self,
        command: str,
        target: str | None = None,
    ) -> FeedbackResult:
        """解析一条明确反馈并保存最小结构化证据。"""
        normalized_command = command.strip()
        if not normalized_command:
            raise ValueError("反馈内容不能为空")
        lowered = normalized_command.casefold()
        clean_target = (target or "").strip()
        if "重置" in lowered:
            self.reset()
            return FeedbackResult(
                action="reset",
                target=clean_target,
                message="兴趣画像已重置",
            )
        if "关闭" in lowered and (
            "画像" in lowered
            or "推荐" in lowered
        ):
            self.set_enabled(False)
            return FeedbackResult(
                action="disable",
                target=clean_target,
                message="兴趣画像已关闭",
            )
        if "开启" in lowered and (
            "画像" in lowered
            or "推荐" in lowered
        ):
            self.set_enabled(True)
            return FeedbackResult(
                action="enable",
                target=clean_target,
                message="兴趣画像已开启",
            )

        profile = self.load()
        changes: dict[str, int] = {}
        action = "note"
        message = "已记录反馈"
        if clean_target and (
            "不要再推荐" in normalized_command
            or "不推荐" in normalized_command
            or "不喜欢" in normalized_command
        ):
            action = "exclude_project"
            if clean_target not in profile["excluded_projects"]:
                profile["excluded_projects"].append(clean_target)
            message = f"已排除项目 {clean_target}"
        elif "喜欢" in normalized_command or "有意思" in normalized_command:
            action = "like"
            message = "已记录正向反馈"
        elif (
            "多关注" in normalized_command
            or "多推荐" in normalized_command
            or "多看" in normalized_command
        ):
            topic = self._extract_topic(
                normalized_command,
                (
                    "多关注",
                    "多推荐",
                    "多看",
                ),
            )
            key = self._resolve_interest_key(
                profile,
                topic,
            )
            changes[key] = WEIGHT_STEP
            action = "increase_interest"
            message = f"已提高 {key} 的兴趣权重"
        elif (
            "减少" in normalized_command
            or "少看" in normalized_command
            or "少推荐" in normalized_command
        ):
            topic = self._extract_topic(
                normalized_command,
                (
                    "减少",
                    "少看",
                    "少推荐",
                ),
            )
            key = self._resolve_interest_key(
                profile,
                topic,
            )
            changes[key] = -WEIGHT_STEP
            action = "decrease_interest"
            message = f"已降低 {key} 的兴趣权重"
            if "套壳" in normalized_command:
                excluded_topic = "普通 AI 套壳项目"
                if excluded_topic not in profile["excluded_topics"]:
                    profile["excluded_topics"].append(excluded_topic)
        for key, delta in changes.items():
            profile["interests"][key] = _clamp(
                profile["interests"].get(key, 50) + delta,
            )
        self._append_evidence(
            profile,
            action,
            normalized_command,
            changes,
        )
        self.save(profile)
        self.database.save_feedback(
            action=action,
            target=clean_target,
            note=normalized_command[:MAX_EVIDENCE_LENGTH],
            signal={
                "explicit": True,
                "changes": changes,
            },
        )
        return FeedbackResult(
            action=action,
            changes=changes,
            target=clean_target,
            message=message,
        )

    def record_implicit_signal(
        self,
        topic: str,
        reason: str,
    ) -> int:
        """累计隐式信号，达到阈值后才小幅调整权重。"""
        profile = self.load()
        key = self._resolve_interest_key(
            profile,
            topic,
        )
        counts = profile["implicit_signals"]
        counts[key] = int(counts.get(key, 0)) + 1
        adjustment = 0
        if counts[key] >= IMPLICIT_SIGNAL_THRESHOLD and (
            counts[key] % IMPLICIT_SIGNAL_THRESHOLD == 0
        ):
            adjustment = 2
            profile["interests"][key] = _clamp(
                profile["interests"].get(key, 50) + adjustment,
            )
            self._append_evidence(
                profile,
                "implicit_signal",
                reason,
                {
                    key: adjustment,
                },
            )
        self.save(profile)
        self.database.save_feedback(
            action="implicit_signal",
            target=key,
            note=reason[:MAX_EVIDENCE_LENGTH],
            signal={
                "count": counts[key],
                "adjustment": adjustment,
            },
        )
        return adjustment

    @staticmethod
    def _default_profile() -> dict[str, Any]:
        """构造包含初始兴趣方向的画像。"""
        return {
            "version": 1,
            "enabled": True,
            "interests": dict(DEFAULT_INTERESTS),
            "excluded_projects": [],
            "excluded_topics": [],
            "implicit_signals": {},
            "evidence": [],
            "updated_at": now_iso(),
        }

    @staticmethod
    def _normalize_profile(
        raw: Any,
    ) -> dict[str, Any]:
        """补齐画像字段并限制权重范围。"""
        if not isinstance(raw, dict):
            raise ValueError("画像 JSON 必须是对象")
        default = InterestProfileStore._default_profile()
        interests = raw.get("interests")
        if not isinstance(interests, dict):
            interests = {}
        merged_interests = dict(default["interests"])
        for key, value in interests.items():
            if isinstance(key, str):
                try:
                    merged_interests[key] = _clamp(int(value))
                except (TypeError, ValueError):
                    continue
        return {
            "version": int(raw.get("version") or 1),
            "enabled": bool(raw.get("enabled", True)),
            "interests": merged_interests,
            "excluded_projects": _string_list(
                raw.get("excluded_projects")
            ),
            "excluded_topics": _string_list(
                raw.get("excluded_topics")
            ),
            "implicit_signals": _int_map(
                raw.get("implicit_signals")
            ),
            "evidence": (
                raw.get("evidence")
                if isinstance(raw.get("evidence"), list)
                else []
            )[-20:],
            "updated_at": str(
                raw.get("updated_at")
                or now_iso()
            ),
        }

    @staticmethod
    def _extract_topic(
        command: str,
        markers: tuple[str, ...],
    ) -> str:
        """提取反馈动词后面的短主题，不保存完整对话上下文。"""
        for marker in markers:
            if marker not in command:
                continue
            topic = command.split(
                marker,
                1,
            )[1].strip(
                " ：:，,。.!！?"
            )
            topic = re.sub(
                r"(项目|新闻|内容)$",
                "",
                topic,
            ).strip()
            return topic[:50] or "未指定主题"
        return "未指定主题"

    @staticmethod
    def _resolve_interest_key(
        profile: dict[str, Any],
        topic: str,
    ) -> str:
        """把用户主题映射到已有兴趣键，必要时创建中性新键。"""
        normalized_topic = topic.strip()
        if not normalized_topic or normalized_topic == "未指定主题":
            return "AI Agent"
        lowered = normalized_topic.casefold()
        aliases = {
            "模型发布": "Model Releases",
            "模型": "Model Releases",
            "agent": "AI Agent",
            "ai agent": "AI Agent",
            "mcp": "MCP",
            "codex": "Codex",
            "claude code": "Claude Code",
            "skills": "Skills",
        }
        if lowered in aliases:
            return aliases[lowered]
        for key in profile["interests"]:
            if lowered == key.casefold() or lowered in key.casefold():
                return key
        profile["interests"][normalized_topic] = 50
        return normalized_topic

    @staticmethod
    def _append_evidence(
        profile: dict[str, Any],
        kind: str,
        summary: str,
        changes: dict[str, int],
    ) -> None:
        """保存不超过 20 条的短结构化依据。"""
        profile["evidence"].append(
            {
                "kind": kind,
                "summary": summary[:MAX_EVIDENCE_LENGTH],
                "changes": changes,
                "at": now_iso(),
            }
        )
        profile["evidence"] = profile["evidence"][-20:]


def _clamp(
    value: int,
) -> int:
    """把兴趣权重限制在 0 到 100。"""
    return max(
        0,
        min(
            100,
            int(value),
        ),
    )


def _string_list(
    value: Any,
) -> list[str]:
    """过滤画像中的字符串列表字段。"""
    if not isinstance(value, list):
        return []
    return [
        item.strip()
        for item in value
        if isinstance(item, str) and item.strip()
    ]


def _int_map(
    value: Any,
) -> dict[str, int]:
    """过滤隐式信号计数字典。"""
    if not isinstance(value, dict):
        return {}
    result: dict[str, int] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            continue
        try:
            result[key] = max(0, int(item))
        except (TypeError, ValueError):
            continue
    return result

