"""SQLite state for YouTube channel transcript batch jobs."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


STATE_DB_NAME = "state.sqlite3"
STATUS_JSON_NAME = "_estado_videos.json"
STATUS_MD_NAME = "_estado_procesamiento.md"
LOCAL_STATUS_JSON_NAME = "_estado_videos_local.json"
LOCAL_STATUS_MD_NAME = "_estado_procesamiento_local.md"


def state_db_path(project_root: str | Path) -> Path:
    return Path(project_root) / "cache" / "video_transcripts" / STATE_DB_NAME


def status_json_path(vault_output_dir: str | Path) -> Path:
    return Path(vault_output_dir) / STATUS_JSON_NAME


def status_md_path(vault_output_dir: str | Path) -> Path:
    return Path(vault_output_dir) / STATUS_MD_NAME


def local_status_json_path(vault_output_dir: str | Path) -> Path:
    return Path(vault_output_dir) / LOCAL_STATUS_JSON_NAME


def local_status_md_path(vault_output_dir: str | Path) -> Path:
    return Path(vault_output_dir) / LOCAL_STATUS_MD_NAME


def _default_db_path(project_root: str) -> str:
    path = state_db_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)

def _ensure_columns(conn: sqlite3.Connection) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(video_transcript)")}
    if "published_at" not in cols:
        conn.execute("ALTER TABLE video_transcript ADD COLUMN published_at TEXT")
    if "channel_url" not in cols:
        conn.execute("ALTER TABLE video_transcript ADD COLUMN channel_url TEXT")
    if "source_kind" not in cols:
        conn.execute("ALTER TABLE video_transcript ADD COLUMN source_kind TEXT DEFAULT 'youtube'")
    if "source_path" not in cols:
        conn.execute("ALTER TABLE video_transcript ADD COLUMN source_path TEXT")
    conn.execute(
        "UPDATE video_transcript SET source_kind='youtube' WHERE source_kind IS NULL OR source_kind=''"
    )


def _init_db(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS video_transcript (
            video_id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            title TEXT,
            source_url TEXT,
            output_path TEXT,
            language_code TEXT,
            error TEXT,
            published_at TEXT,
            channel_url TEXT,
            source_kind TEXT,
            source_path TEXT,
            updated_at TEXT NOT NULL
        )
        """
    )
    _ensure_columns(conn)
    conn.commit()


def open_state(project_root: str) -> sqlite3.Connection:
    db_path = _default_db_path(project_root)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    _init_db(conn)
    return conn


def get_status(conn: sqlite3.Connection, video_id: str) -> Optional[str]:
    row = conn.execute(
        "SELECT status FROM video_transcript WHERE video_id = ?",
        (video_id,),
    ).fetchone()
    return row["status"] if row else None


def upsert_discovered(
    conn: sqlite3.Connection,
    *,
    video_id: str,
    title: str,
    source_url: str,
    published_at: Optional[str],
    channel_url: str,
) -> None:
    """Register a channel video as pending without overwriting done/failed rows."""
    now = datetime.now(tz=timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO video_transcript (
            video_id, status, title, source_url, output_path,
            language_code, error, published_at, channel_url, updated_at
        ) VALUES (?, 'pending', ?, ?, NULL, NULL, NULL, ?, ?, ?)
        ON CONFLICT(video_id) DO UPDATE SET
            title = excluded.title,
            source_url = excluded.source_url,
            published_at = COALESCE(video_transcript.published_at, excluded.published_at),
            channel_url = COALESCE(video_transcript.channel_url, excluded.channel_url),
            updated_at = excluded.updated_at
        WHERE video_transcript.status = 'pending'
        """,
        (video_id, title, source_url, published_at, channel_url, now),
    )
    conn.commit()


def local_video_id(path: str | Path) -> str:
    """Stable ID for a local file path (survives renames if path unchanged)."""
    key = Path(path).resolve().as_posix().lower()
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]
    return f"local:{digest}"


def upsert_local_discovered(
    conn: sqlite3.Connection,
    *,
    video_id: str,
    title: str,
    source_url: str,
    source_path: str,
    published_at: Optional[str] = None,
) -> None:
    """Register a local video as pending without overwriting done/failed rows."""
    now = datetime.now(tz=timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO video_transcript (
            video_id, status, title, source_url, output_path,
            language_code, error, published_at, channel_url,
            source_kind, source_path, updated_at
        ) VALUES (?, 'pending', ?, ?, NULL, NULL, NULL, ?, NULL, 'local', ?, ?)
        ON CONFLICT(video_id) DO UPDATE SET
            title = excluded.title,
            source_url = excluded.source_url,
            source_path = excluded.source_path,
            published_at = COALESCE(video_transcript.published_at, excluded.published_at),
            updated_at = excluded.updated_at
        WHERE video_transcript.status = 'pending'
        """,
        (video_id, title, source_url, published_at, source_path, now),
    )
    conn.commit()


def mark_done(
    conn: sqlite3.Connection,
    *,
    video_id: str,
    title: str,
    source_url: str,
    output_path: str,
    language_code: str,
) -> None:
    now = datetime.now(tz=timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO video_transcript (
            video_id, status, title, source_url, output_path,
            language_code, error, updated_at
        ) VALUES (?, 'done', ?, ?, ?, ?, NULL, ?)
        ON CONFLICT(video_id) DO UPDATE SET
            status = 'done',
            title = excluded.title,
            source_url = excluded.source_url,
            output_path = excluded.output_path,
            language_code = excluded.language_code,
            error = NULL,
            updated_at = excluded.updated_at
        """,
        (video_id, title, source_url, output_path, language_code, now),
    )
    conn.commit()


def mark_failed(
    conn: sqlite3.Connection,
    *,
    video_id: str,
    title: str,
    source_url: str,
    error: str,
) -> None:
    now = datetime.now(tz=timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO video_transcript (
            video_id, status, title, source_url, output_path,
            language_code, error, updated_at
        ) VALUES (?, 'failed', ?, ?, NULL, NULL, ?, ?)
        ON CONFLICT(video_id) DO UPDATE SET
            status = 'failed',
            title = excluded.title,
            source_url = excluded.source_url,
            error = excluded.error,
            updated_at = excluded.updated_at
        """,
        (video_id, title, source_url, error[:2000], now),
    )
    conn.commit()


def mark_skipped(
    conn: sqlite3.Connection,
    *,
    video_id: str,
    title: str,
    source_url: str,
    reason: str = "already_exists",
) -> None:
    now = datetime.now(tz=timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO video_transcript (
            video_id, status, title, source_url, output_path,
            language_code, error, updated_at
        ) VALUES (?, 'skipped', ?, ?, NULL, NULL, ?, ?)
        ON CONFLICT(video_id) DO UPDATE SET
            status = 'skipped',
            title = excluded.title,
            source_url = excluded.source_url,
            error = excluded.error,
            updated_at = excluded.updated_at
        WHERE video_transcript.status != 'done'
        """,
        (video_id, title, source_url, reason, now),
    )
    conn.commit()


def summary_counts(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute(
        "SELECT status, COUNT(*) AS n FROM video_transcript GROUP BY status"
    ).fetchall()
    return {row["status"]: row["n"] for row in rows}


def list_by_status(conn: sqlite3.Connection, status: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT video_id, title, source_url, output_path, error, published_at, updated_at
        FROM video_transcript
        WHERE status = ?
        ORDER BY published_at DESC NULLS LAST, updated_at DESC
        """,
        (status,),
    ).fetchall()
    return [dict(row) for row in rows]


def list_all(conn: sqlite3.Connection, *, source_kind: Optional[str] = None) -> list[dict[str, Any]]:
    if source_kind:
        rows = conn.execute(
            """
            SELECT
                video_id, status, title, source_url, output_path,
                language_code, error, published_at, channel_url,
                source_kind, source_path, updated_at
            FROM video_transcript
            WHERE COALESCE(source_kind, 'youtube') = ?
            ORDER BY published_at DESC, updated_at DESC
            """,
            (source_kind,),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT
                video_id, status, title, source_url, output_path,
                language_code, error, published_at, channel_url,
                source_kind, source_path, updated_at
            FROM video_transcript
            ORDER BY published_at DESC, updated_at DESC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def summary_counts_for_kind(conn: sqlite3.Connection, source_kind: str) -> dict[str, int]:
    rows = conn.execute(
        """
        SELECT status, COUNT(*) AS n
        FROM video_transcript
        WHERE COALESCE(source_kind, 'youtube') = ?
        GROUP BY status
        """,
        (source_kind,),
    ).fetchall()
    return {row["status"]: row["n"] for row in rows}


def repair_local_skipped_with_output(conn: sqlite3.Connection) -> int:
    """Restore done for local rows wrongly downgraded to skipped (e.g. on --retry-failed)."""
    cur = conn.execute(
        """
        UPDATE video_transcript
        SET status='done', error=NULL
        WHERE COALESCE(source_kind, 'local') = 'local'
          AND status = 'skipped'
          AND output_path IS NOT NULL AND output_path != ''
        """
    )
    conn.commit()
    return cur.rowcount


def repair_misclassified_failed(conn: sqlite3.Connection) -> int:
    """Restore failed status for rows wrongly marked skipped during skip pass."""
    cur = conn.execute(
        """
        UPDATE video_transcript
        SET status='failed', error='no_captions_available'
        WHERE status='skipped' AND (output_path IS NULL OR output_path='')
          AND (error LIKE '%falló antes%' OR error LIKE '%no_captions%')
        """
    )
    conn.commit()
    return cur.rowcount


def _markdown_body(text: str) -> str:
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            return parts[2]
    return text


def vault_note_is_ready(output_path: Optional[str]) -> Optional[bool]:
    """
    Return True if the Obsidian note exists and has no corrupt caption markup.
    False if corrupt. None if file missing or path empty.
    """
    from src.youtube_oauth_captions import caption_text_looks_corrupt

    if not output_path:
        return None
    path = Path(output_path)
    if not path.is_file():
        return None
    body = _markdown_body(path.read_text(encoding="utf-8"))
    return not caption_text_looks_corrupt(body)


def reconcile_done_with_vault(conn: sqlite3.Connection) -> dict[str, int]:
    """
    Align SQLite with vault reality: done only when the .md exists and is readable.
    Corrupt notes move to needs_repair; missing files move to pending.
    """
    now = datetime.now(tz=timezone.utc).isoformat()
    stats = {
        "kept_done": 0,
        "needs_repair": 0,
        "missing_file_pending": 0,
        "skipped_corrupt": 0,
    }

    rows = conn.execute(
        """
        SELECT video_id, status, output_path, title, source_url
        FROM video_transcript
        WHERE status IN ('done', 'skipped')
        """
    ).fetchall()

    for row in rows:
        ready = vault_note_is_ready(row["output_path"])
        if ready is True:
            if row["status"] == "done":
                stats["kept_done"] += 1
            continue

        if ready is None:
            cur = conn.execute(
                """
                UPDATE video_transcript
                SET status='pending', error='vault_file_missing', updated_at=?
                WHERE video_id=? AND status='done'
                """,
                (now, row["video_id"]),
            )
            if cur.rowcount:
                stats["missing_file_pending"] += 1
            continue

        # Corrupt vault markdown
        cur = conn.execute(
            """
            UPDATE video_transcript
            SET status='needs_repair',
                error='vault_markdown_corrupt',
                updated_at=?
            WHERE video_id=?
            """,
            (now, row["video_id"]),
        )
        if cur.rowcount:
            if row["status"] == "skipped":
                stats["skipped_corrupt"] += 1
            else:
                stats["needs_repair"] += 1

    conn.commit()
    return stats


def build_status_manifest(conn: sqlite3.Connection, channel_url: str, project_root: str | Path) -> dict[str, Any]:
    counts = summary_counts_for_kind(conn, "youtube")
    videos = list_all(conn, source_kind="youtube")
    db = state_db_path(project_root)
    return {
        "source_of_truth": str(db.resolve()),
        "derived_export": True,
        "do_not_edit": "Regenerado desde SQLite. Editar aquí no afecta al pipeline.",
        "updated_at": datetime.now(tz=timezone.utc).isoformat(),
        "channel_url": channel_url,
        "pipeline": "youtube_channel_oauth",
        "source_kind": "youtube",
        "summary": {
            "done": counts.get("done", 0),
            "pending": counts.get("pending", 0),
            "needs_repair": counts.get("needs_repair", 0),
            "failed": counts.get("failed", 0),
            "skipped": counts.get("skipped", 0),
            "total": sum(counts.values()),
        },
        "videos": videos,
    }


def build_local_status_manifest(
    conn: sqlite3.Connection,
    *,
    project_root: str | Path,
    input_dir: str,
) -> dict[str, Any]:
    counts = summary_counts_for_kind(conn, "local")
    videos = list_all(conn, source_kind="local")
    db = state_db_path(project_root)
    return {
        "source_of_truth": str(db.resolve()),
        "derived_export": True,
        "do_not_edit": "Regenerado desde SQLite. Editar aquí no afecta al pipeline.",
        "updated_at": datetime.now(tz=timezone.utc).isoformat(),
        "input_dir": input_dir,
        "pipeline": "local_whisper",
        "source_kind": "local",
        "summary": {
            "done": counts.get("done", 0),
            "pending": counts.get("pending", 0),
            "needs_repair": counts.get("needs_repair", 0),
            "failed": counts.get("failed", 0),
            "skipped": counts.get("skipped", 0),
            "total": sum(counts.values()),
        },
        "videos": videos,
    }


def write_status_json(
    conn: sqlite3.Connection,
    output_path: str | Path,
    channel_url: str,
    project_root: str | Path,
) -> Path:
    payload = build_status_manifest(conn, channel_url, project_root)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return path


def write_status_summary_markdown(
    conn: sqlite3.Connection,
    output_path: str | Path,
    channel_url: str,
    project_root: str | Path,
) -> Path:
    """Resumen legible en Obsidian; los datos completos viven en _estado_videos.json."""
    manifest = build_status_manifest(conn, channel_url, project_root)
    counts = manifest["summary"]
    now = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    db = state_db_path(project_root)

    lines = [
        "---",
        'title: "Estado — transcripciones YouTube (resumen)"',
        f'channel_url: "{channel_url}"',
        f'updated_at: "{now}"',
        "tags: [transcript, pipeline, own-video]",
        "---",
        "",
        "# Estado del pipeline (resumen)",
        "",
        "Fuente de verdad (no editar a mano):",
        f"`{db.resolve()}`",
        "",
        "Export derivado con el listado completo:",
        f"[[{STATUS_JSON_NAME}]]",
        "",
        f"Canal: {channel_url}",
        f"Actualizado: {now}",
        "",
        "## Conteo",
        "",
        "| Estado | Cantidad |",
        "|--------|----------|",
        f"| done | {counts.get('done', 0)} |",
        f"| pending | {counts.get('pending', 0)} |",
        f"| needs_repair | {counts.get('needs_repair', 0)} |",
        f"| failed | {counts.get('failed', 0)} |",
        f"| skipped | {counts.get('skipped', 0)} |",
        f"| **total** | **{counts.get('total', 0)}** |",
        "",
        "## Regenerar",
        "",
        "```powershell",
        "cd E:\\Vincent\\Vincent-Code",
        ".\\venv\\Scripts\\python.exe scripts\\export_youtube_transcript_status.py",
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
    vault_output_dir: str | Path,
    channel_url: str,
    repair: bool = True,
) -> dict[str, Path]:
    """
    Regenera los export derivados del vault desde SQLite (única fuente de verdad).
    """
    if repair:
        repair_misclassified_failed(conn)

    vault_dir = Path(vault_output_dir)
    json_path = write_status_json(
        conn, status_json_path(vault_dir), channel_url, project_root
    )
    md_path = write_status_summary_markdown(
        conn, status_md_path(vault_dir), channel_url, project_root
    )
    return {"json": json_path, "markdown": md_path}


def write_local_status_json(
    conn: sqlite3.Connection,
    output_path: str | Path,
    *,
    project_root: str | Path,
    input_dir: str,
) -> Path:
    payload = build_local_status_manifest(conn, project_root=project_root, input_dir=input_dir)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return path


def write_local_status_summary_markdown(
    conn: sqlite3.Connection,
    output_path: str | Path,
    *,
    project_root: str | Path,
    input_dir: str,
) -> Path:
    manifest = build_local_status_manifest(conn, project_root=project_root, input_dir=input_dir)
    counts = manifest["summary"]
    now = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    db = state_db_path(project_root)

    lines = [
        "---",
        'title: "Estado — transcripciones locales (resumen)"',
        f'input_dir: "{input_dir}"',
        f'updated_at: "{now}"',
        "tags: [transcript, pipeline, own-video, local-video]",
        "---",
        "",
        "# Estado del pipeline local (resumen)",
        "",
        "Fuente de verdad (no editar a mano):",
        f"`{db.resolve()}`",
        "",
        "Export derivado con el listado completo:",
        f"[[{LOCAL_STATUS_JSON_NAME}]]",
        "",
        f"Carpeta de vídeos: `{input_dir}`",
        f"Actualizado: {now}",
        "",
        "## Conteo",
        "",
        "| Estado | Cantidad |",
        "|--------|----------|",
        f"| done | {counts.get('done', 0)} |",
        f"| pending | {counts.get('pending', 0)} |",
        f"| needs_repair | {counts.get('needs_repair', 0)} |",
        f"| failed | {counts.get('failed', 0)} |",
        f"| skipped | {counts.get('skipped', 0)} |",
        f"| **total** | **{counts.get('total', 0)}** |",
        "",
        "## Regenerar",
        "",
        "```powershell",
        "cd E:\\Vincent\\Vincent-Code",
        ".\\venv\\Scripts\\python.exe scripts\\export_local_transcript_status.py",
        "```",
        "",
    ]

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def sync_local_status_exports(
    conn: sqlite3.Connection,
    *,
    project_root: str | Path,
    vault_output_dir: str | Path,
    input_dir: str,
) -> dict[str, Path]:
    """Regenera export derivados del vault para vídeos locales."""
    vault_dir = Path(vault_output_dir)
    json_path = write_local_status_json(
        conn,
        local_status_json_path(vault_dir),
        project_root=project_root,
        input_dir=input_dir,
    )
    md_path = write_local_status_summary_markdown(
        conn,
        local_status_md_path(vault_dir),
        project_root=project_root,
        input_dir=input_dir,
    )
    return {"json": json_path, "markdown": md_path}


# Backwards-compatible aliases (deprecated)
def export_status_json(conn, output_path, channel_url, project_root=None):
    root = project_root or Path(output_path).parents[3]
    return str(write_status_json(conn, output_path, channel_url, root))


def write_status_markdown(conn, output_path, channel_url, project_root=None):
    root = project_root or Path.cwd()
    write_status_summary_markdown(conn, output_path, channel_url, root)
