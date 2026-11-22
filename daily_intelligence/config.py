"""运行路径、时区和配置文件的统一管理。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
import logging
import os
from pathlib import Path
import re
from types import MappingProxyType
from typing import Mapping
from zoneinfo import ZoneInfo


DEFAULT_DATA_DIR = Path(r"E:\HermesData\daily-intelligence")
DEFAULT_TIMEZONE = "Asia/Shanghai"
DATABASE_DIR_NAME = "database"
CONFIG_DIR_NAME = "config"
REPORTS_DIR_NAME = "reports"
LOGS_DIR_NAME = "logs"
LOG_FILE_NAME = "daily-intelligence.log"
DATABASE_FILE_NAME = "intelligence.db"
PROFILE_FILE_NAME = "user_profile.json"
SOURCES_FILE_NAME = "sources.json"
PROJECT_ENV_FILE_NAME = ".env"
GITHUB_TOKEN_NAME = "GITHUB_TOKEN"
GITHUB_PROXY_NAME = "GITHUB_PROXY"
_ENV_KEY_PATTERN = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*$"
)


class DotEnvError(ValueError):
    """表示项目 `.env` 文件无法安全解析或读取。"""

    def __init__(
        self,
        path: Path,
        line_number: int,
        reason: str,
    ) -> None:
        """创建只包含文件名和解析位置的安全错误。"""
        self.path = path
        self.line_number = line_number
        super().__init__(
            f"项目环境文件 {path.name} 第 {line_number} 行：{reason}"
        )


@dataclass(frozen=True, slots=True)
class ProjectSettings:
    """保存项目环境变量及其来源路径，不在表示文本中展开变量值。"""

    project_root: Path
    env_path: Path
    variables: Mapping[str, str] = field(
        repr=False,
    )
    project_variables: Mapping[str, str] = field(
        default_factory=dict,
        repr=False,
    )
    process_variables: Mapping[str, str] = field(
        default_factory=dict,
        repr=False,
    )

    @property
    def github_token(self) -> str | None:
        """返回去除首尾空格的 GitHub Token，空值表示匿名访问。"""
        value = self.variables.get(
            GITHUB_TOKEN_NAME
        )
        return _clean_setting_value(value)

    @property
    def github_proxy(self) -> str | None:
        """返回按进程变量优先级解析的 GitHub 专用代理地址。"""
        process_value = self.process_variables.get(
            GITHUB_PROXY_NAME
        )
        if _clean_setting_value(process_value):
            return _clean_setting_value(process_value)
        project_value = _clean_setting_value(
            self.project_variables.get(
                GITHUB_PROXY_NAME
            )
        )
        if project_value:
            return project_value
        return _clean_setting_value(
            self.variables.get(
                GITHUB_PROXY_NAME
            )
        )

    @property
    def github_proxy_source(self) -> str:
        """返回 GitHub 专用代理的来源，缺失时返回 auto。"""
        if _clean_setting_value(
            self.process_variables.get(
                GITHUB_PROXY_NAME
            )
        ):
            return "process_env"
        if _clean_setting_value(
            self.project_variables.get(
                GITHUB_PROXY_NAME
            )
        ):
            return "project_env"
        if _clean_setting_value(
            self.variables.get(
                GITHUB_PROXY_NAME
            )
        ):
            return "project_env"
        return "auto"


def _clean_setting_value(
    value: object,
) -> str | None:
    """清理配置值并把空字符串统一为缺失。"""
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def resolve_project_root(
    project_root: Path | str | None = None,
) -> Path:
    """基于配置模块位置解析项目根目录，不依赖当前工作目录。"""
    if project_root is not None:
        return Path(
            project_root
        ).expanduser().resolve()
    return Path(__file__).resolve().parent.parent


def _parse_env_value(
    raw_value: str,
    path: Path,
    line_number: int,
) -> str:
    """解析一个环境变量值并拒绝未闭合或多余的引号内容。"""
    value = raw_value.strip()
    if not value:
        return ""
    if value[0] in {
        "'",
        '"',
    }:
        quote_char = value[0]
        closing_index = None
        for index in range(
            1,
            len(value),
        ):
            if (
                value[index] == quote_char
                and value[index - 1] != "\\"
            ):
                closing_index = index
                break
        if closing_index is None:
            raise DotEnvError(
                path,
                line_number,
                "引号未闭合",
            )
        trailing = value[
            closing_index + 1:
        ].strip()
        if trailing and not trailing.startswith("#"):
            raise DotEnvError(
                path,
                line_number,
                "引号后存在无法解析的内容",
            )
        return value[
            1:closing_index
        ]
    comment_index = re.search(
        r"\s+#",
        value,
    )
    if comment_index:
        return value[
            :comment_index.start()
        ].rstrip()
    return value


def parse_env_file(
    path: Path | str,
) -> dict[str, str]:
    """使用标准库解析项目 `.env` 文件，缺失文件返回空字典。"""
    env_path = Path(path).expanduser()
    if not env_path.is_file():
        return {}
    try:
        with env_path.open(
            "r",
            encoding="utf-8-sig",
            newline=None,
        ) as handle:
            lines = handle.read().splitlines()
    except UnicodeError:
        raise DotEnvError(
            env_path,
            0,
            "文件不是有效 UTF-8",
        ) from None
    except OSError:
        raise DotEnvError(
            env_path,
            0,
            "文件无法读取",
        ) from None

    values: dict[str, str] = {}
    for line_number, line in enumerate(
        lines,
        start=1,
    ):
        content = line.strip()
        if not content or content.startswith("#"):
            continue
        if content.startswith("export "):
            content = content[
                len("export "):
            ].lstrip()
        if "=" not in content:
            raise DotEnvError(
                env_path,
                line_number,
                "缺少 '='",
            )
        raw_key, raw_value = content.split(
            "=",
            1,
        )
        key = raw_key.strip()
        if not _ENV_KEY_PATTERN.fullmatch(key):
            raise DotEnvError(
                env_path,
                line_number,
                "变量名格式无效",
            )
        values[key] = _parse_env_value(
            raw_value,
            env_path,
            line_number,
        )
    return values


def load_project_settings(
    project_root: Path | str | None = None,
    environ: Mapping[str, str] | None = None,
) -> ProjectSettings:
    """合并项目 `.env` 与当前进程环境，进程变量优先。"""
    root = resolve_project_root(
        project_root,
    )
    env_path = root / PROJECT_ENV_FILE_NAME
    values = parse_env_file(env_path)
    process_environment = (
        os.environ
        if environ is None
        else environ
    )
    process_values = {
        key: value
        for key, value in process_environment.items()
        if isinstance(key, str) and isinstance(value, str)
    }
    merged = dict(values)
    merged.update(process_values)
    return ProjectSettings(
        project_root=root,
        env_path=env_path,
        variables=MappingProxyType(merged),
        project_variables=MappingProxyType(
            dict(values)
        ),
        process_variables=MappingProxyType(
            process_values
        ),
    )


@dataclass(frozen=True, slots=True)
class RuntimePaths:
    """运行数据目录下各类持久化文件的路径集合。"""

    data_dir: Path
    database_path: Path
    config_dir: Path
    profile_path: Path
    sources_path: Path
    reports_dir: Path
    logs_dir: Path

    @classmethod
    def from_data_dir(
        cls,
        data_dir: Path | str | None = None,
    ) -> "RuntimePaths":
        """根据运行数据目录构造完整路径。"""
        resolved_dir = Path(data_dir or DEFAULT_DATA_DIR).expanduser()
        return cls(
            data_dir=resolved_dir,
            database_path=resolved_dir / DATABASE_DIR_NAME / DATABASE_FILE_NAME,
            config_dir=resolved_dir / CONFIG_DIR_NAME,
            profile_path=resolved_dir / CONFIG_DIR_NAME / PROFILE_FILE_NAME,
            sources_path=resolved_dir / CONFIG_DIR_NAME / SOURCES_FILE_NAME,
            reports_dir=resolved_dir / REPORTS_DIR_NAME,
            logs_dir=resolved_dir / LOGS_DIR_NAME,
        )

    def ensure(self) -> "RuntimePaths":
        """创建运行时所需目录并返回自身。"""
        for directory in (
            self.data_dir,
            self.database_path.parent,
            self.config_dir,
            self.reports_dir,
            self.logs_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)
        return self

    @property
    def log_path(self) -> Path:
        """返回项目日志文件路径。"""
        return self.logs_dir / LOG_FILE_NAME


def timezone_or_default(
    timezone_name: str | None,
) -> ZoneInfo:
    """解析 IANA 时区，缺省时使用项目默认时区。"""
    return ZoneInfo(timezone_name or DEFAULT_TIMEZONE)


def now_iso(
    timezone_name: str | None = None,
    now: datetime | None = None,
) -> str:
    """返回带时区的 ISO 8601 时间字符串，支持注入时间。"""
    return now_in_timezone(
        timezone_name,
        now,
    ).isoformat(timespec="seconds")


def now_in_timezone(
    timezone_name: str | None = None,
    now: datetime | None = None,
) -> datetime:
    """把可注入的时间转换到指定 IANA 时区。"""
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(
            tzinfo=timezone.utc,
        )
    return current.astimezone(
        timezone_or_default(timezone_name),
    )


def date_in_timezone(
    timezone_name: str | None = None,
    now: datetime | None = None,
) -> date:
    """返回指定 IANA 时区的逻辑日期，避免跨午夜日期漂移。"""
    return now_in_timezone(
        timezone_name,
        now,
    ).date()


def configure_logging(
    paths: RuntimePaths,
) -> logging.Logger:
    """为当前运行目录配置 UTF-8 文件日志并关闭旧目录句柄。"""
    paths.logs_dir.mkdir(
        parents=True,
        exist_ok=True,
    )
    logger = logging.getLogger("daily_intelligence")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    target_path = str(
        paths.log_path.resolve()
    )
    for handler in list(logger.handlers):
        handler_path = getattr(
            handler,
            "baseFilename",
            "",
        )
        if handler_path != target_path:
            logger.removeHandler(handler)
            handler.close()
    if not any(
        getattr(handler, "baseFilename", "") == target_path
        for handler in logger.handlers
    ):
        handler = logging.FileHandler(
            paths.log_path,
            encoding="utf-8",
        )
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)s %(message)s"
            )
        )
        logger.addHandler(handler)
    logger.info(
        "runtime initialized: %s",
        paths.data_dir,
    )
    return logger

