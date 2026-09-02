"""SQLite knowledge engine: videos, extractions, knowledge_items."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

STATE_DB_NAME = "state.sqlite3"
SCHEMA_VERSION = "2.0"
STATUS_JSON_NAME = "_estado_extracciones.json"
STATUS_MD_NAME = "_estado_extracciones.md"
ENGINE_JSON_NAME = "_estado_knowledge_engine.json"


def state_db_path(project_root: str | Path) -> Path:
    return Path(project_root) / "cache" / "knowledge_engine" / STATE_DB_NAME


def status_json_path(vault_extraction_dir: str | Path) -> Path:
    return Path(vault_extraction_dir) / STATUS_JSON_NAME


def status_md_path(vault_extraction_dir: str | Path) -> Path:
    return Path(vault_extraction_dir) / STATUS_MD_NAME


def engine_json_path(vault_extraction_dir: str | Path) -> Path:
    return Path(vault_extraction_dir) / ENGINE_JSON_NAME


def transcript_id_from_path(path: str | Path) -> str:
    return Path(path).stem


def infer_source_kind(source_url: str, source_type: str = "") -> str:
    url = (source_url or "").lower()
    kind = (source_type or "").lower()
    if "youtube.com" in url or "youtu.be" in url:
        return "youtube"
    if url.startswith("file:") or "own video" in kind:
        return "local"
    return "youtube" if url.startswith("http") else "local"


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS videos (
            video_id TEXT PRIMARY KEY,
            source_kind TEXT NOT NULL,
            title TEXT,
            source_url TEXT,
            source_path TEXT,
            transcript_path TEXT NOT NULL,
            transcript_hash TEXT,
            word_count INTEGER,
            language_code TEXT DEFAULT 'es',
            published_at TEXT,
            ingest_status TEXT NOT NULL,
            ingest_error TEXT,
            ingest_updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS extractions (
            extraction_id TEXT PRIMARY KEY,
            video_id TEXT NOT NULL REFERENCES videos(video_id),
            status TEXT NOT NULL,
            model TEXT,
            schema_version TEXT NOT NULL,
            transcript_hash TEXT NOT NULL,
            summary TEXT,
            output_md_path TEXT,
            output_json_path TEXT,
            prompt_tokens INTEGER,
            completion_tokens INTEGER,
            error TEXT,
            extracted_at TEXT,
            updated_at TEXT NOT NULL,
            UNIQUE(video_id, transcript_hash)
        );

        CREATE TABLE IF NOT EXISTS knowledge_items (
            item_id INTEGER PRIMARY KEY AUTOINCREMENT,
            extraction_id TEXT NOT NULL REFERENCES extractions(extraction_id),
            video_id TEXT NOT NULL REFERENCES videos(video_id),
            item_type TEXT NOT NULL,
            item_key TEXT,
            payload TEXT NOT NULL,
            anchor_text TEXT,
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_items_video ON knowledge_items(video_id);
        CREATE INDEX IF NOT EXISTS idx_items_type ON knowledge_items(item_type);
        CREATE INDEX IF NOT EXISTS idx_items_extraction ON knowledge_items(extraction_id);
        """
    )
    conn.commit()


def open_engine(project_root: str | Path) -> sqlite3.Connection:
    path = state_db_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    _init_db(conn)
    return conn


def get_extraction_status(conn: sqlite3.Connection, video_id: str) -> Optional[str]:
    row = conn.execute(
        "SELECT status FROM extractions WHERE video_id = ? ORDER BY updated_at DESC LIMIT 1",
        (video_id,),
    ).fetchone()
    return row["status"] if row else None


def upsert_video(
    conn: sqlite3.Connection,
    *,
    video_id: str,
    source_kind: str,
    title: str,
    source_url: str,
    source_path: Optional[str],
    transcript_path: str,
    transcript_hash: str,
    word_count: int,
    language_code: str,
    published_at: Optional[str],
    ingest_status: str = "done",
) -> None:
    now = _now()
    conn.execute(
        """
        INSERT INTO videos (
            video_id, source_kind, title, source_url, source_path,
            transcript_path, transcript_hash, word_count, language_code,
            published_at, ingest_status, ingest_error, ingest_updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
        ON CONFLICT(video_id) DO UPDATE SET
            source_kind = excluded.source_kind,
            title = excluded.title,
            source_url = excluded.source_url,
            source_path = excluded.source_path,
            transcript_path = excluded.transcript_path,
            transcript_hash = excluded.transcript_hash,
            word_count = excluded.word_count,
            language_code = excluded.language_code,
            published_at = COALESCE(excluded.published_at, videos.published_at),
            ingest_status = excluded.ingest_status,
            ingest_updated_at = excluded.ingest_updated_at
        """,
        (
            video_id,
            source_kind,
            title,
            source_url,
            source_path,
            transcript_path,
            transcript_hash,
            word_count,
            language_code,
            published_at,
            ingest_status,
            now,
        ),
    )
    conn.commit()


def mark_content_changed(conn: sqlite3.Connection, *, video_id: str, transcript_hash: str) -> None:
    now = _now()
    conn.execute(
        """
        UPDATE extractions
        SET status='pending', error=NULL, updated_at=?
        WHERE video_id=? AND status='done' AND transcript_hash != ?
        """,
        (now, video_id, transcript_hash),
    )
    conn.commit()


def delete_knowledge_items(conn: sqlite3.Connection, extraction_id: str) -> None:
    conn.execute("DELETE FROM knowledge_items WHERE extraction_id = ?", (extraction_id,))
    conn.commit()


def insert_knowledge_items(
    conn: sqlite3.Connection,
    *,
    extraction_id: str,
    video_id: str,
    items: list[dict[str, Any]],
) -> int:
    if not items:
        return 0
    now = _now()
    rows = [
        (
            extraction_id,
            video_id,
            item["item_type"],
            item.get("item_key"),
            json.dumps(item["payload"], ensure_ascii=False),
            item.get("anchor_text"),
            now,
        )
        for item in items
    ]
    conn.executemany(
        """
        INSERT INTO knowledge_items (
            extraction_id, video_id, item_type, item_key, payload, anchor_text, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()
    return len(rows)


def mark_extraction_done(
    conn: sqlite3.Connection,
    *,
    video_id: str,
    extraction_id: str,
    model: str,
    transcript_hash: str,
    summary: str,
    output_md_path: str,
    output_json_path: str,
    prompt_tokens: Optional[int] = None,
    completion_tokens: Optional[int] = None,
) -> None:
    now = _now()
    conn.execute(
        """
        INSERT INTO extractions (
            extraction_id, video_id, status, model, schema_version,
            transcript_hash, summary, output_md_path, output_json_path,
            prompt_tokens, completion_tokens, error, extracted_at, updated_at
        ) VALUES (?, ?, 'done', ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)
        ON CONFLICT(extraction_id) DO UPDATE SET
            status='done',
            model=excluded.model,
            schema_version=excluded.schema_version,
            transcript_hash=excluded.transcript_hash,
            summary=excluded.summary,
            output_md_path=excluded.output_md_path,
            output_json_path=excluded.output_json_path,
            prompt_tokens=excluded.prompt_tokens,
            completion_tokens=excluded.completion_tokens,
            error=NULL,
            extracted_at=excluded.extracted_at,
            updated_at=excluded.updated_at
        """,
        (
            extraction_id,
            video_id,
            model,
            SCHEMA_VERSION,
            transcript_hash,
            summary,
            output_md_path,
            output_json_path,
            prompt_tokens,
            completion_tokens,
            now,
            now,
        ),
    )
    conn.commit()


def mark_extraction_failed(
    conn: sqlite3.Connection,
    *,
    video_id: str,
    extraction_id: str,
    transcript_hash: str,
    error: str,
) -> None:
    now = _now()
    conn.execute(
        """
        INSERT INTO extractions (
            extraction_id, video_id, status, model, schema_version,
            transcript_hash, summary, output_md_path, output_json_path,
            prompt_tokens, completion_tokens, error, extracted_at, updated_at
        ) VALUES (?, ?, 'failed', NULL, ?, ?, NULL, NULL, NULL, NULL, NULL, ?, NULL, ?)
        ON CONFLICT(extraction_id) DO UPDATE SET
            status='failed',
            transcript_hash=excluded.transcript_hash,
            error=excluded.error,
            updated_at=excluded.updated_at
        """,
        (extraction_id, video_id, SCHEMA_VERSION, transcript_hash, error[:2000], now),
    )
    conn.commit()


def mark_extraction_skipped(
    conn: sqlite3.Connection,
    *,
    video_id: str,
    extraction_id: str,
    error: str,
) -> None:
    now = _now()
    conn.execute(
        """
        INSERT INTO extractions (
            extraction_id, video_id, status, model, schema_version,
            transcript_hash, summary, output_md_path, output_json_path,
            prompt_tokens, completion_tokens, error, extracted_at, updated_at
        ) VALUES (?, ?, 'skipped', NULL, ?, '', NULL, NULL, NULL, NULL, NULL, ?, NULL, ?)
        ON CONFLICT(extraction_id) DO UPDATE SET
            status='skipped',
            error=excluded.error,
            updated_at=excluded.updated_at
        """,
        (extraction_id, video_id, SCHEMA_VERSION, error[:2000], now),
    )
    conn.commit()


def count_items_by_type(conn: sqlite3.Connection, video_id: str) -> dict[str, int]:
    rows = conn.execute(
        """
        SELECT item_type, COUNT(*) AS n
        FROM knowledge_items
        WHERE video_id = ?
        GROUP BY item_type
        ORDER BY n DESC
        """,
        (video_id,),
    ).fetchall()
    return {row["item_type"]: row["n"] for row in rows}


def summary_counts(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute(
        "SELECT status, COUNT(*) AS n FROM extractions GROUP BY status"
    ).fetchall()
    return {row["status"]: row["n"] for row in rows}


def search_knowledge_items(
    conn: sqlite3.Connection,
    query: str,
    *,
    limit: int = 20,
    item_type: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Keyword search over extracted knowledge items (payload, summary, title)."""
    tokens = [t for t in (query or "").lower().replace("%", " ").replace("_", " ").split() if t]
    sql = """
        SELECT
            ki.item_id,
            ki.item_type,
            ki.item_key,
            ki.payload,
            ki.anchor_text,
            ki.video_id,
            e.summary,
            e.output_md_path,
            e.status AS extraction_status,
            v.title
        FROM knowledge_items ki
        JOIN extractions e ON e.extraction_id = ki.extraction_id
        JOIN videos v ON v.video_id = ki.video_id
        WHERE e.status = 'done'
    """
    params: list[Any] = []
    if item_type:
        sql += " AND ki.item_type = ?"
        params.append(item_type)
    for token in tokens:
        like = f"%{token}%"
        sql += (
            " AND ("
            "LOWER(ki.payload) LIKE ? OR LOWER(IFNULL(ki.anchor_text,'')) LIKE ? "
            "OR LOWER(IFNULL(e.summary,'')) LIKE ? OR LOWER(IFNULL(v.title,'')) LIKE ? "
            "OR LOWER(ki.item_type) LIKE ?"
            ")"
        )
        params.extend([like, like, like, like, like])
    sql += " ORDER BY ki.item_id DESC LIMIT ?"
    params.append(max(1, int(limit)))
    return [dict(row) for row in conn.execute(sql, params).fetchall()]


def list_extractions(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT e.extraction_id, e.video_id, e.status, e.model, e.schema_version,
               e.transcript_hash, e.summary, e.output_md_path, e.output_json_path,
               e.prompt_tokens, e.completion_tokens, e.error, e.extracted_at, e.updated_at,
               v.title, v.source_url, v.transcript_path
        FROM extractions e
        JOIN videos v ON v.video_id = e.video_id
        ORDER BY e.updated_at DESC
        """
    ).fetchall()
    return [dict(row) for row in rows]


def reconcile_done_with_vault(conn: sqlite3.Connection) -> dict[str, int]:
    now = _now()
    stats = {"kept_done": 0, "missing_output_pending": 0, "missing_source_skipped": 0}

    rows = conn.execute(
        """
        SELECT e.extraction_id, e.video_id, e.status, e.output_md_path, e.transcript_hash,
               v.transcript_path, v.title
        FROM extractions e
        JOIN videos v ON v.video_id = e.video_id
        WHERE e.status IN ('done', 'pending', 'failed')
        """
    ).fetchall()

    for row in rows:
        transcript_path = Path(row["transcript_path"] or "")
        if not transcript_path.is_file():
            cur = conn.execute(
                """
                UPDATE extractions SET status='skipped', error='transcript_file_missing', updated_at=?
                WHERE extraction_id=?
                """,
                (now, row["extraction_id"]),
            )
            if cur.rowcount:
                stats["missing_source_skipped"] += 1
            continue

        if row["status"] != "done":
            continue

        output_path = Path(row["output_md_path"] or "")
        if output_path.is_file():
            stats["kept_done"] += 1
            continue

        cur = conn.execute(
            """
            UPDATE extractions SET status='pending', error='output_file_missing', updated_at=?
            WHERE extraction_id=? AND status='done'
            """,
            (now, row["extraction_id"]),
        )
        if cur.rowcount:
            stats["missing_output_pending"] += 1

    conn.commit()
    return stats


def build_status_manifest(
    conn: sqlite3.Connection,
    *,
    project_root: str | Path,
    transcript_input_dir: str,
    extraction_output_dir: str,
) -> dict[str, Any]:
    counts = summary_counts(conn)
    items = list_extractions(conn)
    video_count = conn.execute("SELECT COUNT(*) FROM videos").fetchone()[0]
    item_count = conn.execute("SELECT COUNT(*) FROM knowledge_items").fetchone()[0]
    db = state_db_path(project_root)
    return {
        "source_of_truth": str(db.resolve()),
        "derived_export": True,
        "do_not_edit": "Regenerado desde SQLite. Editar aquí no afecta al pipeline.",
        "updated_at": _now(),
        "pipeline": "knowledge_engine",
        "schema_version": SCHEMA_VERSION,
        "transcript_input_dir": transcript_input_dir,
        "extraction_output_dir": extraction_output_dir,
        "summary": {
            "videos": video_count,
            "knowledge_items": item_count,
            "done": counts.get("done", 0),
            "pending": counts.get("pending", 0),
            "failed": counts.get("failed", 0),
            "skipped": counts.get("skipped", 0),
            "extractions_total": sum(counts.values()),
        },
        "extractions": items,
    }


def write_status_json(conn: sqlite3.Connection, output_path: str | Path, manifest: dict[str, Any]) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return path


def write_status_summary_markdown(
    conn: sqlite3.Connection,
    output_path: str | Path,
    *,
    project_root: str | Path,
    transcript_input_dir: str,
    extraction_output_dir: str,
) -> Path:
    manifest = build_status_manifest(
        conn,
        project_root=project_root,
        transcript_input_dir=transcript_input_dir,
        extraction_output_dir=extraction_output_dir,
    )
    counts = manifest["summary"]
    now = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    db = state_db_path(project_root)

    lines = [
        "---",
        'title: "Estado — Knowledge Engine (resumen)"',
        f'updated_at: "{now}"',
        "tags: [extraction, pipeline, knowledge-engine]",
        "---",
        "",
        "# Knowledge Engine — estado",
        "",
        f"Fuente de verdad: `{db.resolve()}`",
        "",
        f"Export JSON: [[{STATUS_JSON_NAME}]] · Engine: [[{ENGINE_JSON_NAME}]]",
        "",
        f"Transcripts: `{transcript_input_dir}`",
        f"Extracciones: `{extraction_output_dir}`",
        "",
        "## Conteo",
        "",
        "| Métrica | Cantidad |",
        "|---------|----------|",
        f"| videos | {counts.get('videos', 0)} |",
        f"| knowledge_items | {counts.get('knowledge_items', 0)} |",
        f"| extractions done | {counts.get('done', 0)} |",
        f"| pending | {counts.get('pending', 0)} |",
        f"| failed | {counts.get('failed', 0)} |",
        f"| skipped | {counts.get('skipped', 0)} |",
        "",
    ]
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def sync_status_exports(
    conn: sqlite3.Connection,
    *,
    project_root: str | Path,
    vault_extraction_dir: str | Path,
    transcript_input_dir: str,
) -> dict[str, Path]:
    vault_dir = Path(vault_extraction_dir)
    extraction_output_dir = str(vault_dir.resolve())
    manifest = build_status_manifest(
        conn,
        project_root=project_root,
        transcript_input_dir=transcript_input_dir,
        extraction_output_dir=extraction_output_dir,
    )
    json_path = write_status_json(conn, status_json_path(vault_dir), manifest)
    md_path = write_status_summary_markdown(
        conn,
        status_md_path(vault_dir),
        project_root=project_root,
        transcript_input_dir=transcript_input_dir,
        extraction_output_dir=extraction_output_dir,
    )
    engine_path = write_status_json(conn, engine_json_path(vault_dir), manifest)
    return {"json": json_path, "markdown": md_path, "engine": engine_path}
