"""SQLite 数据库、迁移和幂等持久化。"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterator

from .config import now_iso
from .deduplication import content_fingerprint, normalize_url
from .models import Item


SCHEMA_VERSION = 1


class Database:
    """管理情报项目、快照、反馈和运行状态的 SQLite 存储。"""

    def __init__(
        self,
        database_path: Path | str,
    ) -> None:
        """打开数据库连接，实际表结构由 initialize 创建。"""
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(
            self.database_path,
            timeout=30,
            check_same_thread=False,
        )
        self.connection.row_factory = sqlite3.Row

    def initialize(self) -> None:
        """创建数据库表并执行必要的版本迁移。"""
        with self.transaction():
            self.connection.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_version (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                )
                """
            )
            current_row = self.connection.execute(
                "SELECT MAX(version) AS version FROM schema_version"
            ).fetchone()
            current_version = int(current_row["version"] or 0)
            if current_version < 1:
                self._apply_v1()

    def close(self) -> None:
        """关闭 SQLite 连接。"""
        self.connection.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """提供可回滚的数据库事务上下文。"""
        try:
            yield self.connection
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

    def _apply_v1(self) -> None:
        """创建 v1 所需的最小数据表和索引。"""
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_type TEXT NOT NULL,
                external_id TEXT,
                title TEXT NOT NULL,
                url TEXT NOT NULL,
                normalized_url TEXT NOT NULL,
                source TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT '',
                published_at TEXT,
                summary TEXT NOT NULL DEFAULT '',
                content TEXT NOT NULL DEFAULT '',
                language TEXT,
                repo_full_name TEXT,
                stars INTEGER,
                forks INTEGER,
                fingerprint TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(item_type, normalized_url)
            );

            CREATE INDEX IF NOT EXISTS idx_items_published_at
                ON items(published_at);
            CREATE INDEX IF NOT EXISTS idx_items_repo_full_name
                ON items(repo_full_name);
            CREATE INDEX IF NOT EXISTS idx_items_fingerprint
                ON items(fingerprint);

            CREATE TABLE IF NOT EXISTS repo_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                repo_full_name TEXT NOT NULL,
                snapshot_date TEXT NOT NULL,
                stars INTEGER NOT NULL,
                forks INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                UNIQUE(repo_full_name, snapshot_date)
            );

            CREATE TABLE IF NOT EXISTS feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action TEXT NOT NULL,
                target TEXT NOT NULL DEFAULT '',
                item_id INTEGER,
                note TEXT NOT NULL DEFAULT '',
                signal_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                FOREIGN KEY(item_id) REFERENCES items(id)
            );

            CREATE INDEX IF NOT EXISTS idx_feedback_action_created
                ON feedback(action, created_at);

            CREATE TABLE IF NOT EXISTS runs (
                run_key TEXT PRIMARY KEY,
                run_type TEXT NOT NULL,
                status TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                error TEXT
            );

            """,
        )
        self.connection.execute(
            """
            INSERT INTO schema_version(version, applied_at)
            VALUES (1, ?)
            """,
            (now_iso(),),
        )

    def upsert_item(
        self,
        item: Item,
    ) -> int:
        """按内容类型和规范化 URL 幂等写入项目，并返回数据库 ID。"""
        normalized_url = normalize_url(item.url)
        fingerprint = content_fingerprint(
            item.title,
            item.content or item.summary,
        )
        current_time = now_iso()
        metadata_json = json.dumps(
            item.metadata,
            ensure_ascii=False,
            sort_keys=True,
        )
        with self.transaction():
            self.connection.execute(
                """
                INSERT INTO items (
                    item_type, external_id, title, url, normalized_url,
                    source, category, published_at, summary, content,
                    language, repo_full_name, stars, forks, fingerprint,
                    metadata_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(item_type, normalized_url) DO UPDATE SET
                    external_id = excluded.external_id,
                    title = excluded.title,
                    url = excluded.url,
                    source = excluded.source,
                    category = excluded.category,
                    published_at = excluded.published_at,
                    summary = excluded.summary,
                    content = excluded.content,
                    language = excluded.language,
                    repo_full_name = excluded.repo_full_name,
                    stars = excluded.stars,
                    forks = excluded.forks,
                    fingerprint = excluded.fingerprint,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at
                """,
                (
                    item.item_type,
                    item.external_id,
                    item.title,
                    item.url,
                    normalized_url,
                    item.source,
                    item.category,
                    item.published_at,
                    item.summary,
                    item.content,
                    item.language,
                    item.repo_full_name,
                    item.stars,
                    item.forks,
                    fingerprint,
                    metadata_json,
                    current_time,
                    current_time,
                ),
            )
            row = self.connection.execute(
                """
                SELECT id
                FROM items
                WHERE item_type = ? AND normalized_url = ?
                """,
                (
                    item.item_type,
                    normalized_url,
                ),
            ).fetchone()
        return int(row["id"])

    def get_item(
        self,
        item_id: int,
    ) -> dict[str, Any] | None:
        """读取单条项目并解析 JSON 元数据。"""
        row = self.connection.execute(
            "SELECT * FROM items WHERE id = ?",
            (item_id,),
        ).fetchone()
        return self._item_row_to_dict(row) if row else None

    def list_items(
        self,
        item_type: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """按更新时间倒序读取项目。"""
        if item_type:
            rows = self.connection.execute(
                """
                SELECT * FROM items
                WHERE item_type = ?
                ORDER BY COALESCE(published_at, updated_at) DESC
                LIMIT ?
                """,
                (
                    item_type,
                    limit,
                ),
            ).fetchall()
        else:
            rows = self.connection.execute(
                """
                SELECT * FROM items
                ORDER BY COALESCE(published_at, updated_at) DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            self._item_row_to_dict(row)
            for row in rows
        ]

    def count_items(self) -> int:
        """返回当前项目总数。"""
        row = self.connection.execute(
            "SELECT COUNT(*) AS count FROM items"
        ).fetchone()
        return int(row["count"])

    def begin_run(
        self,
        run_type: str,
        run_key: str,
    ) -> bool:
        """登记一次运行，成功或运行中的同一键会被幂等拦截。"""
        current_time = now_iso()
        with self.transaction():
            row = self.connection.execute(
                "SELECT status FROM runs WHERE run_key = ?",
                (run_key,),
            ).fetchone()
            if row and row["status"] in {
                "running",
                "success",
            }:
                return False
            if row:
                self.connection.execute(
                    """
                    UPDATE runs
                    SET run_type = ?, status = 'running',
                        started_at = ?, finished_at = NULL, error = NULL
                    WHERE run_key = ?
                    """,
                    (
                        run_type,
                        current_time,
                        run_key,
                    ),
                )
            else:
                self.connection.execute(
                    """
                    INSERT INTO runs(
                        run_key, run_type, status, started_at
                    )
                    VALUES (?, ?, 'running', ?)
                    """,
                    (
                        run_key,
                        run_type,
                        current_time,
                    ),
                )
        return True

    def finish_run(
        self,
        run_key: str,
        status: str,
        error: str | None = None,
    ) -> None:
        """写入运行结束状态和可选错误信息。"""
        if status not in {
            "success",
            "failed",
        }:
            raise ValueError("运行状态必须是 success 或 failed")
        with self.transaction():
            self.connection.execute(
                """
                UPDATE runs
                SET status = ?, finished_at = ?, error = ?
                WHERE run_key = ?
                """,
                (
                    status,
                    now_iso(),
                    error,
                    run_key,
                ),
            )

    def save_repo_snapshot(
        self,
        repo_full_name: str,
        snapshot_date: str,
        stars: int,
        forks: int,
    ) -> None:
        """保存或更新一个仓库的每日 Star/Fork 快照。"""
        with self.transaction():
            self.connection.execute(
                """
                INSERT INTO repo_snapshots(
                    repo_full_name, snapshot_date, stars, forks, created_at
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(repo_full_name, snapshot_date) DO UPDATE SET
                    stars = excluded.stars,
                    forks = excluded.forks
                """,
                (
                    repo_full_name,
                    snapshot_date,
                    stars,
                    forks,
                    now_iso(),
                ),
            )

    def star_growth(
        self,
        repo_full_name: str,
        days: int,
    ) -> int:
        """根据已有快照计算窗口内 Star 增量，没有历史时返回零。"""
        rows = self.connection.execute(
            """
            SELECT snapshot_date, stars
            FROM repo_snapshots
            WHERE repo_full_name = ?
            ORDER BY snapshot_date DESC
            """,
            (repo_full_name,),
        ).fetchall()
        if len(rows) < 2:
            return 0
        latest_date = date.fromisoformat(rows[0]["snapshot_date"])
        cutoff = latest_date - timedelta(days=days)
        baseline = next(
            (
                row
                for row in reversed(rows)
                if date.fromisoformat(row["snapshot_date"]) <= cutoff
            ),
            rows[-1],
        )
        return int(rows[0]["stars"]) - int(baseline["stars"])

    def save_feedback(
        self,
        action: str,
        target: str = "",
        item_id: int | None = None,
        note: str = "",
        signal: dict[str, Any] | None = None,
    ) -> int:
        """保存结构化用户反馈或推荐历史并返回记录 ID。"""
        with self.transaction():
            cursor = self.connection.execute(
                """
                INSERT INTO feedback(
                    action, target, item_id, note, signal_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    action,
                    target,
                    item_id,
                    note,
                    json.dumps(
                        signal or {},
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    now_iso(),
                ),
            )
        return int(cursor.lastrowid)

    def list_feedback(
        self,
        limit: int = 100,
        action: str | None = None,
    ) -> list[dict[str, Any]]:
        """读取最近反馈并把结构化信号还原为字典。"""
        if action:
            rows = self.connection.execute(
                """
                SELECT * FROM feedback
                WHERE action = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (
                    action,
                    limit,
                ),
            ).fetchall()
        else:
            rows = self.connection.execute(
                """
                SELECT * FROM feedback
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            {
                **dict(row),
                "signal": json.loads(row["signal_json"] or "{}"),
            }
            for row in rows
        ]

    def recent_recommendation_ids(
        self,
        cutoff_iso: str,
    ) -> set[int]:
        """返回截止时间之后已经推荐过的项目 ID。"""
        rows = self.connection.execute(
            """
            SELECT item_id
            FROM feedback
            WHERE action = 'recommended'
              AND item_id IS NOT NULL
              AND created_at >= ?
            """,
            (cutoff_iso,),
        ).fetchall()
        return {
            int(row["item_id"])
            for row in rows
        }

    @staticmethod
    def _item_row_to_dict(
        row: sqlite3.Row,
    ) -> dict[str, Any]:
        """把 SQLite 行转换成可供推荐和报告使用的字典。"""
        result = dict(row)
        result["metadata"] = json.loads(result.pop("metadata_json") or "{}")
        return result

