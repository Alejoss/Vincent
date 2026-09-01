"""Resolve embeddable plain text for Sophia topic contents.

Priority for VIDEO/AUDIO:
  1) sophia_content_transcript.output_path (topic worker)
  2) video_transcript via YouTube id / source_url (Knowledge Engine / local pipelines)
  3) vault note sophia-{content_id}-*.md or frontmatter sophia_content_id
  4) remote transcript-ingest API

TEXT:
  - PDF from S3/public file URL via PyMuPDF
  - external URL (Medium etc.) marked pending (no scrape by default)
"""

from __future__ import annotations

import logging
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import fitz
import requests

from src.sophia_local_transcript_lookup import find_local_transcript
from src.sophia_transcript_ingest import SophiaTranscriptIngestClient
from src.sophia_transcript_state import get_row, open_sophia_state
from src.sophia_youtube_captions import extract_youtube_video_id

logger = logging.getLogger(__name__)


@dataclass
class ResolvedText:
    content_id: Optional[int]
    media_type: str
    title: str
    author: str
    text: str
    source: str
    status: str  # ok | missing | skipped
    notes: str = ""


def _vault_path(project_root: Path) -> Path:
    raw = (os.getenv("OBSIDIAN_VAULT_PATH") or "../Cerebro-Vincent").strip()
    p = Path(raw)
    return p if p.is_absolute() else (project_root / p).resolve()


def _strip_frontmatter(raw: str) -> str:
    if not raw.startswith("---"):
        return raw.strip()
    parts = raw.split("---", 2)
    if len(parts) < 3:
        return raw.strip()
    return parts[2].lstrip("\n").strip()


def _read_md_body(path: Path) -> Optional[str]:
    if not path.is_file():
        return None
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("Cannot read %s: %s", path, exc)
        return None
    body = _strip_frontmatter(raw)
    return body or None


def _find_vault_sophia_note(
    transcripts_dir: Path, content_id: int
) -> Optional[Path]:
    hits = sorted(transcripts_dir.glob(f"sophia-{int(content_id)}-*.md"))
    if hits:
        return hits[0]
    # Frontmatter scan (knowledge-engine / reused notes)
    needle = re.compile(
        rf"^sophia_content_id:\s*[\"']?{int(content_id)}[\"']?\s*$",
        re.MULTILINE,
    )
    if not transcripts_dir.is_dir():
        return None
    for path in transcripts_dir.glob("*.md"):
        if path.name.startswith("_"):
            continue
        try:
            head = path.read_text(encoding="utf-8", errors="replace")[:2000]
        except OSError:
            continue
        if needle.search(head):
            return path
    return None


def _youtube_id_from_item(item: dict) -> Optional[str]:
    yt = (item.get("youtube_video_id") or "").strip()
    if yt:
        return yt
    url = item.get("url") or ""
    fd = item.get("file_details") or {}
    return extract_youtube_video_id(url) or extract_youtube_video_id(fd.get("url") or "")


def resolve_media_text(
    *,
    project_root: str | Path,
    item: dict,
    ingest_client: Optional[SophiaTranscriptIngestClient] = None,
) -> ResolvedText:
    content_id = int(item["id"])
    media_type = str(item.get("media_type") or "").upper()
    title = item.get("original_title") or f"content-{content_id}"
    author = item.get("original_author") or ""
    root = Path(project_root)
    vault = _vault_path(root)
    transcripts_dir = vault / "10_Sources" / "Own_Transcripts"

    base = ResolvedText(
        content_id=content_id,
        media_type=media_type,
        title=title,
        author=author,
        text="",
        source="",
        status="missing",
    )

    if media_type == "IMAGE":
        base.status = "skipped"
        base.notes = "images_excluded"
        return base

    if media_type in {"VIDEO", "AUDIO"}:
        # 1) topic worker SQLite
        try:
            conn = open_sophia_state(root)
            row = get_row(conn, content_id)
            conn.close()
        except Exception:  # noqa: BLE001
            row = None
        if row and row.get("output_path"):
            body = _read_md_body(Path(row["output_path"]))
            if body:
                base.text = body
                base.source = f"sophia_state:{row['output_path']}"
                base.status = "ok"
                return base

        # 2) Knowledge Engine / video_transcript by YT id or URL
        hit = find_local_transcript(
            project_root=root,
            youtube_video_id=_youtube_id_from_item(item),
            source_url=item.get("url"),
        )
        if hit and hit.plain_text.strip():
            base.text = hit.plain_text.strip()
            base.source = f"video_transcript:{hit.match_via}:{hit.output_path}"
            base.status = "ok"
            return base

        # 3) vault sophia-* or frontmatter
        note = _find_vault_sophia_note(transcripts_dir, content_id)
        if note:
            body = _read_md_body(note)
            if body:
                base.text = body
                base.source = f"vault:{note.name}"
                base.status = "ok"
                return base

        # 4) remote ingest API
        client = ingest_client or SophiaTranscriptIngestClient()
        try:
            detail = client.get_item(content_id)
        except Exception as exc:  # noqa: BLE001
            base.notes = f"api_error:{exc}"
            return base
        tr = detail.get("transcript")
        text = ""
        if isinstance(tr, dict):
            text = (tr.get("text") or tr.get("body") or tr.get("content") or "").strip()
        elif isinstance(tr, str):
            text = tr.strip()
        if not text:
            text = (detail.get("text") or "").strip()
        if text:
            base.text = text
            base.source = "api:transcript-ingest"
            base.status = "ok"
            return base
        base.notes = "no_local_or_remote_transcript"
        return base

    if media_type == "TEXT":
        fd = item.get("file_details") or {}
        file_url = fd.get("file") or fd.get("url") or ""
        if file_url:
            try:
                response = requests.get(file_url, timeout=180)
                response.raise_for_status()
                tmp = Path(tempfile.gettempdir()) / f"sophia_text_{content_id}.pdf"
                tmp.write_bytes(response.content)
                doc = fitz.open(tmp)
                parts = [doc[i].get_text("text") or "" for i in range(doc.page_count)]
                pages = doc.page_count
                doc.close()
                text = "\n".join(parts).strip()
                if text:
                    base.text = text
                    base.source = "s3_pdf:" + file_url.rstrip("/").split("/")[-1]
                    base.status = "ok"
                    base.notes = f"pages={pages}"
                    return base
                base.notes = "pdf_empty_text"
                return base
            except Exception as exc:  # noqa: BLE001
                base.notes = f"pdf_error:{exc}"
                return base
        if item.get("url"):
            base.status = "missing"
            base.notes = f"external_url_pending:{item['url']}"
            return base
        base.notes = "no_file_or_url"
        return base

    base.status = "skipped"
    base.notes = f"unsupported_media:{media_type}"
    return base


def resolve_topic_description(topic: dict) -> ResolvedText:
    desc = (topic.get("description") or "").strip()
    title = topic.get("title") or f"topic-{topic.get('id')}"
    return ResolvedText(
        content_id=None,
        media_type="TOPIC_DESCRIPTION",
        title=title,
        author="",
        text=desc,
        source="api:topic.description",
        status="ok" if desc else "missing",
        notes="" if desc else "empty_description",
    )
