"""运行路径、时区和配置文件的统一管理。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import logging
from pathlib import Path
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
) -> str:
    """返回带时区的当前 ISO 8601 时间字符串。"""
    return datetime.now(
        timezone_or_default(timezone_name)
    ).isoformat(timespec="seconds")


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

