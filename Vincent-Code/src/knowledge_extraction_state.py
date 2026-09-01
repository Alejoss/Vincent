"""SQLite state for Own_Transcripts knowledge extraction jobs."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


STATE_DB_NAME = "state.sqlite3"
STATUS_JSON_NAME = "_estado_extracciones.json"
STATUS_MD_NAME = "_estado_extracciones.md"


def state_db_path(project_root: str | Path) -> Path:
    return Path(project_root) / "cache" / "knowledge_extractions" / STATE_DB_NAME


def status_json_path(vault_output_dir: str | Path) -> Path:
    return Path(vault_output_dir) / STATUS_JSON_NAME


def status_md_path(vault_output_dir: str | Path) -> Path:
    return Path(vault_output_dir) / STATUS_MD_NAME


def _default_db_path(project_root: str | Path) -> str:
    path = state_db_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)


def transcript_id_from_path(path: str | Path) -> str:
    return Path(path).stem


def content_hash(text: str) -> str:
    normalized = (text or "").strip().encode("utf-8")
    return hashlib.sha256(normalized).hexdigest()


def _init_db(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS knowledge_extraction (
            transcript_id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            title TEXT,
            source_url TEXT,
            transcript_path TEXT,
            output_path TEXT,
            content_hash TEXT,
            model TEXT,
            error TEXT,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.commit()


def open_state(project_root: str | Path) -> sqlite3.Connection:
    db_path = _default_db_path(project_root)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    _init_db(conn)
    return conn


def get_status(conn: sqlite3.Connection, transcript_id: str) -> Optional[str]:
    row = conn.execute(
        "SELECT status FROM knowledge_extraction WHERE transcript_id = ?",
        (transcript_id,),
    ).fetchone()
    return row["status"] if row else None


def get_row(conn: sqlite3.Connection, transcript_id: str) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM knowledge_extraction WHERE transcript_id = ?",
        (transcript_id,),
    ).fetchone()


def upsert_discovered(
    conn: sqlite3.Connection,
    *,
    transcript_id: str,
    title: str,
    source_url: str,
    transcript_path: str,
    body_hash: str,
) -> None:
    """Register a transcript as pending without overwriting done rows."""
    now = datetime.now(tz=timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO knowledge_extraction (
            transcript_id, status, title, source_url, transcript_path,
            output_path, content_hash, model, error, updated_at
        ) VALUES (?, 'pending', ?, ?, ?, NULL, ?, NULL, NULL, ?)
        ON CONFLICT(transcript_id) DO UPDATE SET
            title = excluded.title,
            source_url = excluded.source_url,
            transcript_path = excluded.transcript_path,
            content_hash = excluded.content_hash,
            updated_at = excluded.updated_at
        WHERE knowledge_extraction.status = 'pending'
        """,
        (transcript_id, title, source_url, transcript_path, body_hash, now),
    )
    conn.commit()


def mark_content_changed(
    conn: sqlite3.Connection,
    *,
    transcript_id: str,
    body_hash: str,
) -> None:
    """Re-queue a done row when the source transcript body changed."""
    now = datetime.now(tz=timezone.utc).isoformat()
    conn.execute(
        """
        UPDATE knowledge_extraction
        SET status='pending', content_hash=?, error=NULL, updated_at=?
        WHERE transcript_id=? AND status='done' AND content_hash IS NOT NULL
          AND content_hash != ?
        """,
        (body_hash, now, transcript_id, body_hash),
    )
    conn.commit()


def mark_done(
    conn: sqlite3.Connection,
    *,
    transcript_id: str,
    title: str,
    source_url: str,
    transcript_path: str,
    output_path: str,
    content_hash_value: str,
    model: str,
) -> None:
    now = datetime.now(tz=timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO knowledge_extraction (
            transcript_id, status, title, source_url, transcript_path,
            output_path, content_hash, model, error, updated_at
        ) VALUES (?, 'done', ?, ?, ?, ?, ?, ?, NULL, ?)
        ON CONFLICT(transcript_id) DO UPDATE SET
            status='done',
            title=excluded.title,
            source_url=excluded.source_url,
            transcript_path=excluded.transcript_path,
            output_path=excluded.output_path,
            content_hash=excluded.content_hash,
            model=excluded.model,
            error=NULL,
            updated_at=excluded.updated_at
        """,
        (
            transcript_id,
            title,
            source_url,
            transcript_path,
            output_path,
            content_hash_value,
            model,
            now,
        ),
    )
    conn.commit()


def mark_failed(
    conn: sqlite3.Connection,
    *,
    transcript_id: str,
    title: str,
    source_url: str,
    transcript_path: str,
    content_hash_value: str,
    error: str,
) -> None:
    now = datetime.now(tz=timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO knowledge_extraction (
            transcript_id, status, title, source_url, transcript_path,
            output_path, content_hash, model, error, updated_at
        ) VALUES (?, 'failed', ?, ?, ?, NULL, ?, NULL, ?, ?)
        ON CONFLICT(transcript_id) DO UPDATE SET
            status='failed',
            title=excluded.title,
            source_url=excluded.source_url,
            transcript_path=excluded.transcript_path,
            content_hash=excluded.content_hash,
            error=excluded.error,
            updated_at=excluded.updated_at
        """,
        (
            transcript_id,
            title,
            source_url,
            transcript_path,
            content_hash_value,
            error[:2000],
            now,
        ),
    )
    conn.commit()


def mark_skipped(
    conn: sqlite3.Connection,
    *,
    transcript_id: str,
    title: str,
    source_url: str,
    transcript_path: str,
    error: str,
) -> None:
    now = datetime.now(tz=timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO knowledge_extraction (
            transcript_id, status, title, source_url, transcript_path,
            output_path, content_hash, model, error, updated_at
        ) VALUES (?, 'skipped', ?, ?, ?, NULL, NULL, NULL, ?, ?)
        ON CONFLICT(transcript_id) DO UPDATE SET
            status='skipped',
            title=excluded.title,
            source_url=excluded.source_url,
            transcript_path=excluded.transcript_path,
            error=excluded.error,
            updated_at=excluded.updated_at
        """,
        (transcript_id, title, source_url, transcript_path, error[:2000], now),
    )
    conn.commit()


def summary_counts(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute(
        "SELECT status, COUNT(*) AS n FROM knowledge_extraction GROUP BY status"
    ).fetchall()
    return {row["status"]: row["n"] for row in rows}


def list_all(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT transcript_id, status, title, source_url, transcript_path,
               output_path, content_hash, model, error, updated_at
        FROM knowledge_extraction
        ORDER BY updated_at DESC
        """
    ).fetchall()
    return [dict(row) for row in rows]


def reconcile_done_with_vault(conn: sqlite3.Connection) -> dict[str, int]:
    """Align SQLite with vault: done only when output markdown exists."""
    now = datetime.now(tz=timezone.utc).isoformat()
    stats = {"kept_done": 0, "missing_output_pending": 0, "missing_source_skipped": 0}

    rows = conn.execute(
        """
        SELECT transcript_id, status, output_path, transcript_path, title, source_url
        FROM knowledge_extraction
        WHERE status IN ('done', 'pending', 'failed')
        """
    ).fetchall()

    for row in rows:
        transcript_path = Path(row["transcript_path"] or "")
        if not transcript_path.is_file():
            cur = conn.execute(
                """
                UPDATE knowledge_extraction
                SET status='skipped', error='transcript_file_missing', updated_at=?
                WHERE transcript_id=?
                """,
                (now, row["transcript_id"]),
            )
            if cur.rowcount:
                stats["missing_source_skipped"] += 1
            continue

        if row["status"] != "done":
            continue

        output_path = Path(row["output_path"] or "")
        if output_path.is_file():
            stats["kept_done"] += 1
            continue

        cur = conn.execute(
            """
            UPDATE knowledge_extraction
            SET status='pending', error='output_file_missing', updated_at=?
            WHERE transcript_id=? AND status='done'
            """,
            (now, row["transcript_id"]),
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
    items = list_all(conn)
    db = state_db_path(project_root)
    return {
        "source_of_truth": str(db.resolve()),
        "derived_export": True,
        "do_not_edit": "Regenerado desde SQLite. Editar aquí no afecta al pipeline.",
        "updated_at": datetime.now(tz=timezone.utc).isoformat(),
        "pipeline": "own_transcript_knowledge",
        "transcript_input_dir": transcript_input_dir,
        "extraction_output_dir": extraction_output_dir,
        "summary": {
            "done": counts.get("done", 0),
            "pending": counts.get("pending", 0),
            "failed": counts.get("failed", 0),
            "skipped": counts.get("skipped", 0),
            "total": sum(counts.values()),
        },
        "extractions": items,
    }


def write_status_json(
    conn: sqlite3.Connection,
    output_path: str | Path,
    *,
    project_root: str | Path,
    transcript_input_dir: str,
    extraction_output_dir: str,
) -> Path:
    payload = build_status_manifest(
        conn,
        project_root=project_root,
        transcript_input_dir=transcript_input_dir,
        extraction_output_dir=extraction_output_dir,
    )
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
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
        'title: "Estado — extracción de conocimiento (resumen)"',
        f'updated_at: "{now}"',
        "tags: [extraction, pipeline, own-video, knowledge]",
        "---",
        "",
        "# Estado del pipeline de extracción",
        "",
        "Fuente de verdad (no editar a mano):",
        f"`{db.resolve()}`",
        "",
        "Export derivado con el listado completo:",
        f"[[{STATUS_JSON_NAME}]]",
        "",
        f"Transcripts: `{transcript_input_dir}`",
        f"Extracciones: `{extraction_output_dir}`",
        f"Actualizado: {now}",
        "",
        "## Conteo",
        "",
        "| Estado | Cantidad |",
        "|--------|----------|",
        f"| done | {counts.get('done', 0)} |",
        f"| pending | {counts.get('pending', 0)} |",
        f"| failed | {counts.get('failed', 0)} |",
        f"| skipped | {counts.get('skipped', 0)} |",
        f"| **total** | **{counts.get('total', 0)}** |",
        "",
        "## Regenerar",
        "",
        "```powershell",
        "cd E:\\Vincent\\Vincent-Code",
        ".\\venv\\Scripts\\python.exe scripts\\extract_own_transcript_knowledge.py --export-status",
        "```",
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
    json_path = write_status_json(
        conn,
        status_json_path(vault_dir),
        project_root=project_root,
        transcript_input_dir=transcript_input_dir,
        extraction_output_dir=extraction_output_dir,
    )
    md_path = write_status_summary_markdown(
        conn,
        status_md_path(vault_dir),
        project_root=project_root,
        transcript_input_dir=transcript_input_dir,
        extraction_output_dir=extraction_output_dir,
    )
    return {"json": json_path, "markdown": md_path}
