"""SQLite state for Sophia topic transcript worker (content_id keyed).

Shares the same DB file as YouTube/local pipelines:
  cache/video_transcripts/state.sqlite3
Table: sophia_content_transcript
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from src.video_transcript_state import open_state, state_db_path

TABLE = "sophia_content_transcript"


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _ensure_sophia_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {TABLE} (
            content_id INTEGER PRIMARY KEY,
            topic_ids TEXT NOT NULL DEFAULT '[]',
            primary_topic_id INTEGER,
            title TEXT,
            media_type TEXT,
            source_url TEXT,
            file_key TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            method TEXT,
            transcribed_at TEXT,
            uploaded_at TEXT,
            server_created_at TEXT,
            server_updated_at TEXT,
            text_hash TEXT,
            language_code TEXT,
            output_path TEXT,
            media_cache_path TEXT,
            error TEXT,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.commit()


def open_sophia_state(project_root: str | Path) -> sqlite3.Connection:
    """Open shared state DB and ensure sophia table exists."""
    conn = open_state(str(project_root))
    _ensure_sophia_table(conn)
    return conn


def _parse_topic_ids(raw: Any) -> list[int]:
    if raw is None or raw == "":
        return []
    if isinstance(raw, list):
        return [int(x) for x in raw]
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return [int(x) for x in data]
    except (TypeError, ValueError, json.JSONDecodeError):
        pass
    return []


def _dump_topic_ids(ids: list[int]) -> str:
    unique = sorted({int(x) for x in ids})
    return json.dumps(unique)


def get_row(conn: sqlite3.Connection, content_id: int) -> Optional[dict[str, Any]]:
    _ensure_sophia_table(conn)
    row = conn.execute(
        f"SELECT * FROM {TABLE} WHERE content_id = ?",
        (int(content_id),),
    ).fetchone()
    if not row:
        return None
    data = dict(row)
    data["topic_ids"] = _parse_topic_ids(data.get("topic_ids"))
    return data


def get_status(conn: sqlite3.Connection, content_id: int) -> Optional[str]:
    row = get_row(conn, content_id)
    return row["status"] if row else None


def upsert_discovered(
    conn: sqlite3.Connection,
    *,
    content_id: int,
    topic_id: int,
    title: Optional[str] = None,
    media_type: Optional[str] = None,
    source_url: Optional[str] = None,
    file_key: Optional[str] = None,
) -> None:
    """Register content from a topic queue without overwriting done rows' success fields."""
    _ensure_sophia_table(conn)
    now = _now()
    existing = get_row(conn, content_id)
    topic_ids = existing["topic_ids"] if existing else []
    if int(topic_id) not in topic_ids:
        topic_ids.append(int(topic_id))
    topic_ids_json = _dump_topic_ids(topic_ids)

    if existing is None:
        conn.execute(
            f"""
            INSERT INTO {TABLE} (
                content_id, topic_ids, primary_topic_id, title, media_type,
                source_url, file_key, status, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)
            """,
            (
                int(content_id),
                topic_ids_json,
                int(topic_id),
                title,
                media_type,
                source_url,
                file_key,
                now,
            ),
        )
    else:
        # Always merge topic_ids; refresh metadata; keep status if already done/skipped
        conn.execute(
            f"""
            UPDATE {TABLE} SET
                topic_ids = ?,
                title = COALESCE(?, title),
                media_type = COALESCE(?, media_type),
                source_url = COALESCE(?, source_url),
                file_key = COALESCE(?, file_key),
                primary_topic_id = COALESCE(primary_topic_id, ?),
                updated_at = ?
            WHERE content_id = ?
            """,
            (
                topic_ids_json,
                title,
                media_type,
                source_url,
                file_key,
                int(topic_id),
                now,
                int(content_id),
            ),
        )
    conn.commit()


def mark_done(
    conn: sqlite3.Connection,
    *,
    content_id: int,
    topic_id: int,
    title: Optional[str] = None,
    media_type: Optional[str] = None,
    source_url: Optional[str] = None,
    file_key: Optional[str] = None,
    method: str,
    transcribed_at: Optional[str] = None,
    uploaded_at: Optional[str] = None,
    server_created_at: Optional[str] = None,
    server_updated_at: Optional[str] = None,
    text_hash: Optional[str] = None,
    language_code: Optional[str] = None,
    output_path: Optional[str] = None,
    media_cache_path: Optional[str] = None,
) -> None:
    _ensure_sophia_table(conn)
    now = _now()
    when = transcribed_at or now
    uploaded = uploaded_at or when
    existing = get_row(conn, content_id)
    topic_ids = existing["topic_ids"] if existing else []
    if int(topic_id) not in topic_ids:
        topic_ids.append(int(topic_id))

    conn.execute(
        f"""
        INSERT INTO {TABLE} (
            content_id, topic_ids, primary_topic_id, title, media_type,
            source_url, file_key, status, method, transcribed_at, uploaded_at,
            server_created_at, server_updated_at, text_hash, language_code,
            output_path, media_cache_path, error, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'done', ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
        ON CONFLICT(content_id) DO UPDATE SET
            topic_ids = excluded.topic_ids,
            primary_topic_id = excluded.primary_topic_id,
            title = COALESCE(excluded.title, {TABLE}.title),
            media_type = COALESCE(excluded.media_type, {TABLE}.media_type),
            source_url = COALESCE(excluded.source_url, {TABLE}.source_url),
            file_key = COALESCE(excluded.file_key, {TABLE}.file_key),
            status = 'done',
            method = excluded.method,
            transcribed_at = excluded.transcribed_at,
            uploaded_at = excluded.uploaded_at,
            server_created_at = COALESCE(excluded.server_created_at, {TABLE}.server_created_at),
            server_updated_at = COALESCE(excluded.server_updated_at, {TABLE}.server_updated_at),
            text_hash = COALESCE(excluded.text_hash, {TABLE}.text_hash),
            language_code = COALESCE(excluded.language_code, {TABLE}.language_code),
            output_path = COALESCE(excluded.output_path, {TABLE}.output_path),
            media_cache_path = COALESCE(excluded.media_cache_path, {TABLE}.media_cache_path),
            error = NULL,
            updated_at = excluded.updated_at
        """,
        (
            int(content_id),
            _dump_topic_ids(topic_ids),
            int(topic_id),
            title,
            media_type,
            source_url,
            file_key,
            method,
            when,
            uploaded,
            server_created_at,
            server_updated_at,
            text_hash,
            language_code,
            output_path,
            media_cache_path,
            now,
        ),
    )
    conn.commit()


def mark_failed(
    conn: sqlite3.Connection,
    *,
    content_id: int,
    topic_id: int,
    error: str,
    title: Optional[str] = None,
    media_type: Optional[str] = None,
    source_url: Optional[str] = None,
    file_key: Optional[str] = None,
) -> None:
    _ensure_sophia_table(conn)
    now = _now()
    existing = get_row(conn, content_id)
    topic_ids = existing["topic_ids"] if existing else []
    if int(topic_id) not in topic_ids:
        topic_ids.append(int(topic_id))
    # Do not overwrite a successful done row with failed
    if existing and existing.get("status") == "done":
        conn.execute(
            f"""
            UPDATE {TABLE} SET topic_ids = ?, updated_at = ?
            WHERE content_id = ?
            """,
            (_dump_topic_ids(topic_ids), now, int(content_id)),
        )
        conn.commit()
        return

    conn.execute(
        f"""
        INSERT INTO {TABLE} (
            content_id, topic_ids, primary_topic_id, title, media_type,
            source_url, file_key, status, error, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'failed', ?, ?)
        ON CONFLICT(content_id) DO UPDATE SET
            topic_ids = excluded.topic_ids,
            primary_topic_id = COALESCE({TABLE}.primary_topic_id, excluded.primary_topic_id),
            title = COALESCE(excluded.title, {TABLE}.title),
            media_type = COALESCE(excluded.media_type, {TABLE}.media_type),
            source_url = COALESCE(excluded.source_url, {TABLE}.source_url),
            file_key = COALESCE(excluded.file_key, {TABLE}.file_key),
            status = 'failed',
            error = excluded.error,
            updated_at = excluded.updated_at
        WHERE {TABLE}.status != 'done'
        """,
        (
            int(content_id),
            _dump_topic_ids(topic_ids),
            int(topic_id),
            title,
            media_type,
            source_url,
            file_key,
            (error or "")[:2000],
            now,
        ),
    )
    conn.commit()


def mark_skipped(
    conn: sqlite3.Connection,
    *,
    content_id: int,
    topic_id: int,
    reason: str = "already_has_transcript",
    title: Optional[str] = None,
    media_type: Optional[str] = None,
    source_url: Optional[str] = None,
    file_key: Optional[str] = None,
    text_hash: Optional[str] = None,
    server_created_at: Optional[str] = None,
    server_updated_at: Optional[str] = None,
) -> None:
    _ensure_sophia_table(conn)
    now = _now()
    existing = get_row(conn, content_id)
    topic_ids = existing["topic_ids"] if existing else []
    if int(topic_id) not in topic_ids:
        topic_ids.append(int(topic_id))

    if existing and existing.get("status") == "done":
        conn.execute(
            f"""
            UPDATE {TABLE} SET
                topic_ids = ?,
                text_hash = COALESCE(?, text_hash),
                server_created_at = COALESCE(?, server_created_at),
                server_updated_at = COALESCE(?, server_updated_at),
                updated_at = ?
            WHERE content_id = ?
            """,
            (
                _dump_topic_ids(topic_ids),
                text_hash,
                server_created_at,
                server_updated_at,
                now,
                int(content_id),
            ),
        )
        conn.commit()
        return

    conn.execute(
        f"""
        INSERT INTO {TABLE} (
            content_id, topic_ids, primary_topic_id, title, media_type,
            source_url, file_key, status, error, text_hash,
            server_created_at, server_updated_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'skipped', ?, ?, ?, ?, ?)
        ON CONFLICT(content_id) DO UPDATE SET
            topic_ids = excluded.topic_ids,
            primary_topic_id = COALESCE({TABLE}.primary_topic_id, excluded.primary_topic_id),
            title = COALESCE(excluded.title, {TABLE}.title),
            media_type = COALESCE(excluded.media_type, {TABLE}.media_type),
            source_url = COALESCE(excluded.source_url, {TABLE}.source_url),
            file_key = COALESCE(excluded.file_key, {TABLE}.file_key),
            status = 'skipped',
            error = excluded.error,
            text_hash = COALESCE(excluded.text_hash, {TABLE}.text_hash),
            server_created_at = COALESCE(excluded.server_created_at, {TABLE}.server_created_at),
            server_updated_at = COALESCE(excluded.server_updated_at, {TABLE}.server_updated_at),
            updated_at = excluded.updated_at
        WHERE {TABLE}.status != 'done'
        """,
        (
            int(content_id),
            _dump_topic_ids(topic_ids),
            int(topic_id),
            title,
            media_type,
            source_url,
            file_key,
            reason,
            text_hash,
            server_created_at,
            server_updated_at,
            now,
        ),
    )
    conn.commit()


def list_for_topic(conn: sqlite3.Connection, topic_id: int) -> list[dict[str, Any]]:
    _ensure_sophia_table(conn)
    rows = conn.execute(f"SELECT * FROM {TABLE} ORDER BY content_id").fetchall()
    tid = int(topic_id)
    out: list[dict[str, Any]] = []
    for row in rows:
        data = dict(row)
        topic_ids = _parse_topic_ids(data.get("topic_ids"))
        primary = data.get("primary_topic_id")
        if tid in topic_ids or primary == tid:
            data["topic_ids"] = topic_ids
            out.append(data)
    return out


def summary_counts_for_topic(conn: sqlite3.Connection, topic_id: int) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in list_for_topic(conn, topic_id):
        status = row.get("status") or "unknown"
        counts[status] = counts.get(status, 0) + 1
    return counts


def coverage_export_paths(vault_output_dir: str | Path, topic_id: int) -> tuple[Path, Path]:
    root = Path(vault_output_dir)
    return (
        root / f"_estado_tema_{int(topic_id)}.json",
        root / f"_estado_tema_{int(topic_id)}.md",
    )


def sync_topic_coverage_exports(
    conn: sqlite3.Connection,
    *,
    topic_id: int,
    vault_output_dir: str | Path,
    remote_pending: Optional[int] = None,
    remote_completed: Optional[int] = None,
    remote_total: Optional[int] = None,
    project_root: Optional[str | Path] = None,
) -> tuple[Path, Path]:
    """Write JSON + Markdown coverage report for a topic."""
    rows = list_for_topic(conn, topic_id)
    counts = summary_counts_for_topic(conn, topic_id)
    json_path, md_path = coverage_export_paths(vault_output_dir, topic_id)
    json_path.parent.mkdir(parents=True, exist_ok=True)

    db_hint = str(state_db_path(project_root)) if project_root else "cache/video_transcripts/state.sqlite3"
    payload = {
        "topic_id": int(topic_id),
        "generated_at": _now(),
        "counts": counts,
        "remote": {
            "pending": remote_pending,
            "completed": remote_completed,
            "total": remote_total,
        },
        "state_db": db_hint,
        "items": [
            {
                "content_id": r["content_id"],
                "status": r.get("status"),
                "title": r.get("title"),
                "media_type": r.get("media_type"),
                "method": r.get("method"),
                "transcribed_at": r.get("transcribed_at"),
                "uploaded_at": r.get("uploaded_at"),
                "server_created_at": r.get("server_created_at"),
                "text_hash": r.get("text_hash"),
                "topic_ids": r.get("topic_ids"),
                "error": r.get("error"),
                "source_url": r.get("source_url"),
                "file_key": r.get("file_key"),
            }
            for r in rows
        ],
    }
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    lines = [
        f"# Cobertura transcripts — Tema {int(topic_id)}",
        "",
        f"Generado: `{payload['generated_at']}`",
        "",
        "## Conteos locales",
        "",
    ]
    for status in ("done", "pending", "failed", "skipped"):
        if status in counts:
            lines.append(f"- **{status}**: {counts[status]}")
    other = {k: v for k, v in counts.items() if k not in {"done", "pending", "failed", "skipped"}}
    for status, n in sorted(other.items()):
        lines.append(f"- **{status}**: {n}")
    lines.append("")
    if remote_total is not None:
        lines.extend(
            [
                "## Remoto (cola ingest)",
                "",
                f"- total VIDEO/AUDIO: {remote_total}",
                f"- con transcript: {remote_completed}",
                f"- pendientes: {remote_pending}",
                "",
            ]
        )
    lines.extend(["## Ítems", ""])
    for r in rows:
        title = (r.get("title") or "").replace("|", "/")
        lines.append(
            f"- `{r['content_id']}` [{r.get('status')}] "
            f"{r.get('media_type') or '?'} — {title} "
            f"(transcribed_at={r.get('transcribed_at') or '—'}; method={r.get('method') or '—'})"
        )
        if r.get("error") and r.get("status") == "failed":
            lines.append(f"  - error: {r['error'][:200]}")
    lines.append("")
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, md_path
