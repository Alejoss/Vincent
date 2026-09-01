"""Find existing local transcripts via SQLite index (video_transcript).

Match by YouTube video id or exact source_url, then read the Own_Transcripts
note pointed by output_path. No full-folder scan and no title fuzzy-match
(titles diverge between Sophia and Obsidian; YouTube id is stable).
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from src.sophia_youtube_captions import extract_youtube_video_id
from src.video_transcript_state import open_state
from src.youtube_oauth_captions import caption_text_looks_corrupt

logger = logging.getLogger(__name__)


@dataclass
class LocalTranscriptHit:
    youtube_video_id: Optional[str]
    source_url: Optional[str]
    output_path: str
    language_code: str
    plain_text: str
    obsidian_markdown: str
    sqlite_status: Optional[str]
    match_via: str  # video_id | source_url


def _split_frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    meta: dict[str, str] = {}
    for line in parts[1].splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip().strip('"').strip("'")
    return meta, parts[2].lstrip("\n")


def _read_note(path: Path) -> Optional[tuple[dict[str, str], str, str]]:
    """Return (frontmatter, body, full_text) or None if unusable."""
    if not path.is_file():
        return None
    try:
        full = path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("Cannot read local transcript %s: %s", path, exc)
        return None
    meta, body = _split_frontmatter(full)
    body = (body or "").strip()
    if not body:
        return None
    if caption_text_looks_corrupt(body):
        logger.warning("Local transcript looks corrupt, skipping: %s", path)
        return None
    return meta, body, full


def _row_usable(row: sqlite3.Row | dict[str, Any]) -> bool:
    status = (row["status"] if isinstance(row, sqlite3.Row) else row.get("status")) or ""
    output_path = (row["output_path"] if isinstance(row, sqlite3.Row) else row.get("output_path")) or ""
    if not output_path:
        return False
    # done is ideal; skipped often still points at a valid Own_Transcripts note
    return status in {"done", "skipped"}


def find_local_transcript(
    *,
    project_root: str | Path,
    youtube_video_id: Optional[str] = None,
    source_url: Optional[str] = None,
    vault_transcripts_dir: Optional[str | Path] = None,
) -> Optional[LocalTranscriptHit]:
    """
    Look up an existing local transcript.

    Order:
      1) video_transcript.video_id == youtube id (from Sophia URL)
      2) video_transcript.source_url == Sophia url (exact)

    Then open output_path (.md in Own_Transcripts). ``vault_transcripts_dir``
    is accepted for API compatibility but unused (no directory scan).
    """
    del vault_transcripts_dir  # unused; kept so callers need not change
    root = Path(project_root)
    yt_id = (youtube_video_id or "").strip() or None
    if not yt_id and source_url:
        yt_id = extract_youtube_video_id(source_url)

    conn = open_state(str(root))
    try:
        row = None
        match_via = ""
        if yt_id:
            row = conn.execute(
                """
                SELECT video_id, status, title, source_url, output_path, language_code
                FROM video_transcript
                WHERE video_id = ?
                """,
                (yt_id,),
            ).fetchone()
            if row and _row_usable(row):
                match_via = "video_id"
            else:
                row = None

        if row is None and source_url:
            row = conn.execute(
                """
                SELECT video_id, status, title, source_url, output_path, language_code
                FROM video_transcript
                WHERE source_url = ?
                ORDER BY CASE status WHEN 'done' THEN 0 WHEN 'skipped' THEN 1 ELSE 2 END
                LIMIT 1
                """,
                (source_url,),
            ).fetchone()
            if row and _row_usable(row):
                match_via = "source_url"
            else:
                row = None

        if row is None:
            return None

        path = Path(row["output_path"])
        parsed = _read_note(path)
        if not parsed:
            return None
        meta, body, full = parsed
        lang = (
            (row["language_code"] or "").strip()
            or meta.get("language_code")
            or "es"
        )
        return LocalTranscriptHit(
            youtube_video_id=yt_id or extract_youtube_video_id(row["source_url"] or ""),
            source_url=row["source_url"] or source_url,
            output_path=str(path),
            language_code=lang,
            plain_text=body,
            obsidian_markdown=full if full.startswith("---") else "",
            sqlite_status=row["status"],
            match_via=match_via,
        )
    finally:
        conn.close()
