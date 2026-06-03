"""
Local state for Slack → Obsidian inbox sync (incremental cursor per channel).

Uses SQLite (stdlib) instead of one .txt per channel so we can extend the schema
later (e.g. run stats, multiple channels) without scattering files.

Database path: cache/slack_inbox/sync_state.sqlite3 (under project root).
"""

from __future__ import annotations

import glob
import logging
import os
import re
import sqlite3
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1


def _channel_storage_id(channel_id: str) -> str:
    """Same rules as legacy last_ts_<safe>.txt filenames (alphanumeric + ._-)."""
    s = (channel_id or "").strip()
    s = re.sub(r"[^a-zA-Z0-9._-]+", "_", s)
    return s[:200] if len(s) > 200 else s


def _default_db_path(project_root: str) -> str:
    d = os.path.join(project_root, "cache", "slack_inbox")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "sync_state.sqlite3")


def _init_db(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS slack_channel_cursor (
            channel_id TEXT PRIMARY KEY,
            last_ts TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO meta (key, value) VALUES ('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
    conn.commit()


def _migrate_txt_cursors(state_dir: str, db_path: str) -> None:
    """Import legacy last_ts_<safe_channel>.txt files into SQLite once."""
    if not os.path.isdir(state_dir):
        return
    pattern = os.path.join(state_dir, "last_ts_*.txt")
    files = glob.glob(pattern)
    if not files:
        return
    conn = sqlite3.connect(db_path)
    try:
        _init_db(conn)
        migrated = conn.execute(
            "SELECT value FROM meta WHERE key = 'txt_migration_done'"
        ).fetchone()
        if migrated and migrated[0] == "1":
            return
        prefix = "last_ts_"
        for path in files:
            base = os.path.basename(path)
            if not base.lower().endswith(".txt") or not base.startswith(prefix):
                continue
            stem = base[: -len(".txt")]
            channel_id = stem[len(prefix) :]  # same as _safe_filename(channel_id) in legacy script
            try:
                with open(path, "r", encoding="utf-8") as f:
                    ts = f.read().strip()
            except Exception:
                continue
            if not channel_id or not ts:
                continue
            now = datetime.now(tz=timezone.utc).isoformat()
            conn.execute(
                """
                INSERT INTO slack_channel_cursor (channel_id, last_ts, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(channel_id) DO UPDATE SET
                    last_ts = excluded.last_ts,
                    updated_at = excluded.updated_at
                """,
                (channel_id, ts, now),
            )
            logger.info("Migrated Slack cursor from %s -> channel_id=%s", path, channel_id)
        conn.execute(
            "INSERT INTO meta (key, value) VALUES ('txt_migration_done', '1') "
            "ON CONFLICT(key) DO UPDATE SET value = '1'"
        )
        conn.commit()
    finally:
        conn.close()


class SlackInboxStateStore:
    """SQLite-backed cursor for incremental Slack history fetch."""

    def __init__(self, project_root: str):
        self._db_path = _default_db_path(project_root)
        self._state_dir = os.path.join(project_root, "cache", "slack_inbox")
        _migrate_txt_cursors(self._state_dir, self._db_path)

    def load_last_ts(self, channel_id: str) -> Optional[str]:
        key = _channel_storage_id(channel_id)
        if not key:
            return None
        conn = sqlite3.connect(self._db_path)
        try:
            _init_db(conn)
            row = conn.execute(
                "SELECT last_ts FROM slack_channel_cursor WHERE channel_id = ?",
                (key,),
            ).fetchone()
            return row[0] if row else None
        finally:
            conn.close()

    def save_last_ts(self, channel_id: str, slack_ts: str) -> None:
        key = _channel_storage_id(channel_id)
        slack_ts = (slack_ts or "").strip()
        if not key or not slack_ts:
            return
        now = datetime.now(tz=timezone.utc).isoformat()
        conn = sqlite3.connect(self._db_path)
        try:
            _init_db(conn)
            conn.execute(
                """
                INSERT INTO slack_channel_cursor (channel_id, last_ts, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(channel_id) DO UPDATE SET
                    last_ts = excluded.last_ts,
                    updated_at = excluded.updated_at
                """,
                (key, slack_ts, now),
            )
            conn.commit()
        except Exception as e:
            logger.warning("Could not save Slack cursor to SQLite: %s", e)
        finally:
            conn.close()
