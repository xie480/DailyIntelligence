"""SQLite 数据库、迁移和幂等持久化。"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Iterator

from .config import now_iso
from .deduplication import content_fingerprint, normalize_url
from .models import CreatorAccount, CreatorUpdate, Item


SCHEMA_VERSION = 2


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
        self.connection.execute(
            "PRAGMA foreign_keys = ON"
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
            self._apply_v1()
            self._apply_v2()
            if current_version < SCHEMA_VERSION:
                self.connection.execute(
                    """
                    INSERT INTO schema_version(version, applied_at)
                    VALUES (?, ?)
                    """,
                    (
                        SCHEMA_VERSION,
                        now_iso(),
                    ),
                )

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

    def _apply_v2(self) -> None:
        """创建创作者账号、事件、检查点和授权表，保持 v1 数据不变。"""
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS creator_authorizations (
                owner_key TEXT PRIMARY KEY,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS creator_accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                platform TEXT NOT NULL,
                account_key TEXT NOT NULL,
                display_name TEXT NOT NULL DEFAULT '',
                profile_url TEXT NOT NULL,
                owner_key TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                monitor_videos INTEGER NOT NULL DEFAULT 1,
                monitor_dynamics INTEGER NOT NULL DEFAULT 0,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(platform, account_key),
                FOREIGN KEY(owner_key)
                    REFERENCES creator_authorizations(owner_key)
            );

            CREATE INDEX IF NOT EXISTS idx_creator_accounts_owner
                ON creator_accounts(owner_key, status);

            CREATE TABLE IF NOT EXISTS creator_state (
                state_key TEXT PRIMARY KEY,
                last_success_end TEXT,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS creator_checkpoints (
                account_id INTEGER NOT NULL,
                content_type TEXT NOT NULL,
                first_window_start TEXT,
                last_success_end TEXT,
                last_status TEXT NOT NULL DEFAULT 'pending',
                last_error TEXT,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(account_id, content_type),
                FOREIGN KEY(account_id)
                    REFERENCES creator_accounts(id)
                    ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS creator_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                platform TEXT NOT NULL,
                content_type TEXT NOT NULL,
                external_id TEXT NOT NULL,
                creator_name TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL,
                summary TEXT NOT NULL DEFAULT '',
                content TEXT NOT NULL DEFAULT '',
                url TEXT NOT NULL,
                published_at TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                collected_at TEXT NOT NULL,
                collection_run_key TEXT NOT NULL,
                UNIQUE(platform, content_type, external_id),
                FOREIGN KEY(account_id)
                    REFERENCES creator_accounts(id)
                    ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_creator_events_window
                ON creator_events(account_id, content_type, published_at);

            CREATE TABLE IF NOT EXISTS creator_source_runs (
                collection_run_key TEXT NOT NULL,
                account_id INTEGER NOT NULL,
                content_type TEXT NOT NULL,
                window_start TEXT NOT NULL,
                window_end TEXT NOT NULL,
                status TEXT NOT NULL,
                event_count INTEGER NOT NULL DEFAULT 0,
                error TEXT,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                PRIMARY KEY(collection_run_key, account_id, content_type),
                FOREIGN KEY(account_id)
                    REFERENCES creator_accounts(id)
                    ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_creator_source_runs_status
                ON creator_source_runs(status, finished_at);
            """,
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

    def enrich_repository(
        self,
        repo_full_name: str,
        analysis: dict[str, Any],
    ) -> int:
        """把 Hermes 对 README 的结构化分析合并到仓库元数据。"""
        repository = repo_full_name.strip()
        if not repository:
            return 0
        rows = self.connection.execute(
            """
            SELECT id, summary, content, metadata_json
            FROM items
            WHERE item_type = 'github' AND repo_full_name = ?
            """,
            (repository,),
        ).fetchall()
        if not rows:
            return 0
        clean_analysis = dict(analysis)
        summary = str(
            clean_analysis.get("summary") or ""
        ).strip()
        content_parts = [
            summary,
            " ".join(
                str(value).strip()
                for value in clean_analysis.get("features") or []
                if str(value).strip()
            ),
            " ".join(
                str(value).strip()
                for value in clean_analysis.get("use_cases") or []
                if str(value).strip()
            ),
        ]
        with self.transaction():
            for row in rows:
                metadata = json.loads(
                    row["metadata_json"] or "{}"
                )
                metadata["project_analysis"] = clean_analysis
                next_summary = summary or row["summary"]
                next_content = " ".join(
                    part
                    for part in (
                        row["content"],
                        *content_parts,
                    )
                    if part
                ).strip()
                self.connection.execute(
                    """
                    UPDATE items
                    SET summary = ?, content = ?, metadata_json = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        next_summary,
                        next_content,
                        json.dumps(
                            metadata,
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                        now_iso(),
                        row["id"],
                    ),
                )
        return len(rows)

    def count_items(self) -> int:
        """返回当前项目总数。"""
        row = self.connection.execute(
            "SELECT COUNT(*) AS count FROM items"
        ).fetchone()
        return int(row["count"])

    def authorize_creator_owner(
        self,
        owner_key: str,
    ) -> None:
        """登记可管理创作者账号的稳定 owner 标识。"""
        cleaned = owner_key.strip()
        if not cleaned:
            raise ValueError("owner_key 不能为空")
        with self.transaction():
            self.connection.execute(
                """
                INSERT INTO creator_authorizations(owner_key, created_at)
                VALUES (?, ?)
                ON CONFLICT(owner_key) DO NOTHING
                """,
                (
                    cleaned,
                    now_iso(),
                ),
            )

    def bootstrap_creator_owner(
        self,
        owner_key: str,
    ) -> bool:
        """在授权表为空时原子登记首个 owner，并返回是否登记成功。"""
        cleaned = owner_key.strip()
        if not cleaned:
            raise ValueError("owner_key 不能为空")
        with self.transaction():
            cursor = self.connection.execute(
                """
                INSERT INTO creator_authorizations(owner_key, created_at)
                SELECT ?, ?
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM creator_authorizations
                )
                """,
                (
                    cleaned,
                    now_iso(),
                ),
            )
        return cursor.rowcount == 1

    def is_creator_owner_authorized(
        self,
        owner_key: str,
    ) -> bool:
        """判断 owner 是否已被授权管理创作者账号。"""
        row = self.connection.execute(
            """
            SELECT 1
            FROM creator_authorizations
            WHERE owner_key = ?
            """,
            (
                owner_key.strip(),
            ),
        ).fetchone()
        return row is not None

    def add_creator_account(
        self,
        account: CreatorAccount,
    ) -> int:
        """写入一个不重复的创作者账号并返回数据库 ID。"""
        current_time = now_iso()
        created_at = account.created_at or current_time
        with self.transaction():
            cursor = self.connection.execute(
                """
                INSERT INTO creator_accounts(
                    platform, account_key, display_name, profile_url,
                    owner_key, status, monitor_videos, monitor_dynamics,
                    metadata_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    account.platform,
                    account.account_key,
                    account.display_name,
                    account.profile_url,
                    account.owner_key,
                    account.status,
                    int(account.monitor_videos),
                    int(account.monitor_dynamics),
                    json.dumps(
                        account.metadata,
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    created_at,
                    current_time,
                ),
            )
        return int(cursor.lastrowid)

    def get_creator_account(
        self,
        platform: str,
        account_key: str,
    ) -> dict[str, Any] | None:
        """按平台和唯一账号键读取一个创作者账号。"""
        row = self.connection.execute(
            """
            SELECT *
            FROM creator_accounts
            WHERE platform = ? AND account_key = ?
            """,
            (
                platform.strip().lower(),
                account_key.strip(),
            ),
        ).fetchone()
        return self._creator_account_row_to_dict(row) if row else None

    def list_creator_accounts(
        self,
        owner_key: str | None = None,
        include_paused: bool = True,
    ) -> list[dict[str, Any]]:
        """按 owner 读取创作者账号，默认保留暂停账号。"""
        clauses: list[str] = []
        values: list[Any] = []
        if owner_key is not None:
            clauses.append("owner_key = ?")
            values.append(owner_key.strip())
        if not include_paused:
            clauses.append("status = 'active'")
        where = (
            "WHERE " + " AND ".join(clauses)
            if clauses
            else ""
        )
        rows = self.connection.execute(
            f"""
            SELECT *
            FROM creator_accounts
            {where}
            ORDER BY platform, display_name, id
            """,
            tuple(values),
        ).fetchall()
        return [
            self._creator_account_row_to_dict(row)
            for row in rows
        ]

    def update_creator_account(
        self,
        platform: str,
        account_key: str,
        **updates: Any,
    ) -> None:
        """更新账号状态、名称或监控类型，字段名受白名单限制。"""
        allowed = {
            "display_name",
            "profile_url",
            "status",
            "monitor_videos",
            "monitor_dynamics",
            "metadata_json",
        }
        unknown = set(updates) - allowed
        if unknown:
            raise ValueError(
                "不允许更新创作者字段: "
                + ", ".join(sorted(unknown))
            )
        if not updates:
            return
        assignments = ", ".join(
            f"{key} = ?"
            for key in updates
        )
        values = list(updates.values())
        values.extend(
            [
                now_iso(),
                platform.strip().lower(),
                account_key.strip(),
            ]
        )
        with self.transaction():
            self.connection.execute(
                f"""
                UPDATE creator_accounts
                SET {assignments}, updated_at = ?
                WHERE platform = ? AND account_key = ?
                """,
                tuple(values),
            )

    def delete_creator_account(
        self,
        platform: str,
        account_key: str,
    ) -> bool:
        """删除账号及其检查点、事件和来源运行记录。"""
        with self.transaction():
            cursor = self.connection.execute(
                """
                DELETE FROM creator_accounts
                WHERE platform = ? AND account_key = ?
                """,
                (
                    platform.strip().lower(),
                    account_key.strip(),
                ),
            )
        return cursor.rowcount > 0

    def get_creator_global_last_success_end(self) -> str | None:
        """读取最近一次成功落盘日报对应的全局创作者截止时间。"""
        row = self.connection.execute(
            """
            SELECT last_success_end
            FROM creator_state
            WHERE state_key = 'global'
            """
        ).fetchone()
        if not row:
            return None
        return row["last_success_end"]

    def set_creator_global_success(
        self,
        window_end: str,
    ) -> None:
        """在日报已经可靠保存后推进全局创作者截止时间。"""
        with self.transaction():
            self.connection.execute(
                """
                INSERT INTO creator_state(
                    state_key, last_success_end, updated_at
                )
                VALUES ('global', ?, ?)
                ON CONFLICT(state_key) DO UPDATE SET
                    last_success_end = excluded.last_success_end,
                    updated_at = excluded.updated_at
                """,
                (
                    window_end,
                    now_iso(),
                ),
            )

    def ensure_creator_checkpoint(
        self,
        account_id: int,
        content_type: str,
        first_window_start: str,
    ) -> dict[str, Any]:
        """创建来源检查点并保留首次窗口起点，重复调用不会覆盖进度。"""
        with self.transaction():
            self.connection.execute(
                """
                INSERT INTO creator_checkpoints(
                    account_id, content_type, first_window_start,
                    updated_at
                )
                VALUES (?, ?, ?, ?)
                ON CONFLICT(account_id, content_type) DO NOTHING
                """,
                (
                    account_id,
                    content_type,
                    first_window_start,
                    now_iso(),
                ),
            )
        return self.get_creator_checkpoint(
            account_id,
            content_type,
        ) or {}

    def get_creator_checkpoint(
        self,
        account_id: int,
        content_type: str,
    ) -> dict[str, Any] | None:
        """读取账号和内容类型独立的采集检查点。"""
        row = self.connection.execute(
            """
            SELECT *
            FROM creator_checkpoints
            WHERE account_id = ? AND content_type = ?
            """,
            (
                account_id,
                content_type,
            ),
        ).fetchone()
        return dict(row) if row else None

    def save_creator_events(
        self,
        account_id: int,
        collection_run_key: str,
        events: Iterable[CreatorUpdate],
    ) -> int:
        """在事务中幂等保存来源事件，返回本次处理的事件数量。"""
        values = list(events)
        if not values:
            return 0
        with self.transaction():
            for event in values:
                self.connection.execute(
                    """
                    INSERT INTO creator_events(
                        account_id, platform, content_type, external_id,
                        creator_name, title, summary, content, url,
                        published_at, metadata_json, collected_at,
                        collection_run_key
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(platform, content_type, external_id) DO UPDATE SET
                        account_id = excluded.account_id,
                        creator_name = excluded.creator_name,
                        title = excluded.title,
                        summary = excluded.summary,
                        content = excluded.content,
                        url = excluded.url,
                        published_at = excluded.published_at,
                        metadata_json = excluded.metadata_json,
                        collected_at = excluded.collected_at,
                        collection_run_key = excluded.collection_run_key
                    """,
                    (
                        account_id,
                        event.platform,
                        event.content_type,
                        event.external_id,
                        event.creator_name,
                        event.title,
                        event.summary,
                        event.content,
                        event.url,
                        event.published_at,
                        json.dumps(
                            event.metadata,
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                        now_iso(),
                        collection_run_key,
                    ),
                )
        return len(values)

    def save_creator_source_run(
        self,
        collection_run_key: str,
        account_id: int,
        content_type: str,
        window_start: str,
        window_end: str,
        status: str,
        event_count: int = 0,
        error: str | None = None,
        finished: bool = True,
    ) -> None:
        """记录单个账号来源的成功、失败或部分采集状态。"""
        current_time = now_iso()
        with self.transaction():
            self.connection.execute(
                """
                INSERT INTO creator_source_runs(
                    collection_run_key, account_id, content_type,
                    window_start, window_end, status, event_count, error,
                    started_at, finished_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(collection_run_key, account_id, content_type)
                DO UPDATE SET
                    window_start = excluded.window_start,
                    window_end = excluded.window_end,
                    status = excluded.status,
                    event_count = excluded.event_count,
                    error = excluded.error,
                    finished_at = excluded.finished_at
                """,
                (
                    collection_run_key,
                    account_id,
                    content_type,
                    window_start,
                    window_end,
                    status,
                    event_count,
                    error,
                    current_time,
                    current_time if finished else None,
                ),
            )

    def mark_creator_checkpoint_success(
        self,
        account_id: int,
        content_type: str,
        window_end: str,
    ) -> None:
        """在报告落盘后推进单个来源检查点。"""
        with self.transaction():
            self.connection.execute(
                """
                UPDATE creator_checkpoints
                SET last_success_end = ?, last_status = 'success',
                    last_error = NULL, updated_at = ?
                WHERE account_id = ? AND content_type = ?
                """,
                (
                    window_end,
                    now_iso(),
                    account_id,
                    content_type,
                ),
            )

    def mark_creator_checkpoint_failure(
        self,
        account_id: int,
        content_type: str,
        error: str,
    ) -> None:
        """保存来源失败原因但不推进成功检查点。"""
        with self.transaction():
            self.connection.execute(
                """
                UPDATE creator_checkpoints
                SET last_status = 'failed', last_error = ?, updated_at = ?
                WHERE account_id = ? AND content_type = ?
                """,
                (
                    error[:500],
                    now_iso(),
                    account_id,
                    content_type,
                ),
            )

    def list_creator_events(
        self,
        account_id: int,
        content_type: str,
        window_start: str,
        window_end: str,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """读取指定来源时间窗口内的事件并按发布时间倒序排列。"""
        rows = self.connection.execute(
            """
            SELECT *
            FROM creator_events
            WHERE account_id = ?
              AND content_type = ?
              AND published_at > ?
              AND published_at <= ?
            ORDER BY published_at DESC, id DESC
            LIMIT ?
            """,
            (
                account_id,
                content_type,
                window_start,
                window_end,
                limit,
            ),
        ).fetchall()
        return [
            self._creator_event_row_to_dict(row)
            for row in rows
        ]

    @staticmethod
    def _creator_account_row_to_dict(
        row: sqlite3.Row,
    ) -> dict[str, Any]:
        """把创作者账号行转换为可供服务层使用的字典。"""
        result = dict(row)
        result["monitor_videos"] = bool(result["monitor_videos"])
        result["monitor_dynamics"] = bool(result["monitor_dynamics"])
        result["metadata"] = json.loads(
            result.pop("metadata_json") or "{}"
        )
        return result

    @staticmethod
    def _creator_event_row_to_dict(
        row: sqlite3.Row,
    ) -> dict[str, Any]:
        """把创作者事件行转换为报告渲染字典。"""
        result = dict(row)
        result["metadata"] = json.loads(
            result.pop("metadata_json") or "{}"
        )
        return result

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
            "partial",
            "failed",
        }:
            raise ValueError(
                "运行状态必须是 success、partial 或 failed"
            )
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
            None,
        )
        if baseline is None:
            return 0
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
            return self._insert_feedback(
                action=action,
                target=target,
                item_id=item_id,
                note=note,
                signal=signal,
            )

    def save_feedback_batch(
        self,
        records: Iterable[dict[str, Any]],
    ) -> int:
        """在一个事务中保存多条反馈，失败时整体回滚。"""
        saved = 0
        with self.transaction():
            for record in records:
                self._insert_feedback(
                    action=str(record.get("action") or ""),
                    target=str(record.get("target") or ""),
                    item_id=record.get("item_id"),
                    note=str(record.get("note") or ""),
                    signal=record.get("signal"),
                )
                saved += 1
        return saved

    def _insert_feedback(
        self,
        action: str,
        target: str,
        item_id: int | None,
        note: str,
        signal: dict[str, Any] | None,
    ) -> int:
        """向当前事务写入单条反馈，不单独提交事务。"""
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

    def has_recommendation_for_report(
        self,
        item_id: int,
        report_date: date | str,
    ) -> bool:
        """判断项目是否已为指定日报日期记录推荐历史。"""
        report_date_value = (
            report_date.isoformat()
            if isinstance(report_date, date)
            else str(report_date)
        )
        rows = self.connection.execute(
            """
            SELECT signal_json, created_at
            FROM feedback
            WHERE action = 'recommended'
              AND item_id = ?
            ORDER BY id DESC
            """,
            (item_id,),
        ).fetchall()
        for row in rows:
            try:
                signal = json.loads(row["signal_json"] or "{}")
            except (
                TypeError,
                json.JSONDecodeError,
            ):
                signal = {}
            if not isinstance(signal, dict):
                continue
            if signal.get("report_date") == report_date_value:
                return True
            if (
                "report_date" not in signal
                and str(row["created_at"] or "")[:10]
                == report_date_value
            ):
                return True
        return False

    @staticmethod
    def _item_row_to_dict(
        row: sqlite3.Row,
    ) -> dict[str, Any]:
        """把 SQLite 行转换成可供推荐和报告使用的字典。"""
        result = dict(row)
        result["metadata"] = json.loads(result.pop("metadata_json") or "{}")
        return result

