#!/usr/bin/env python3
"""
Initialize Knowledge Engine: SQLite + Obsidian folders + video registry.

Examples:
  python scripts/init_knowledge_engine.py
  python scripts/init_knowledge_engine.py --export-status
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv(PROJECT_ROOT / ".env", override=True)

from src.knowledge_extraction_state import content_hash
from src.knowledge_engine_state import (
    infer_source_kind,
    mark_content_changed,
    open_engine,
    state_db_path,
    sync_status_exports,
    transcript_id_from_path,
    upsert_video,
)
from src.knowledge_extractor import is_status_artifact, parse_frontmatter

DEFAULT_TRANSCRIPT_FOLDER = "Own_Transcripts"
DEFAULT_EXTRACTION_FOLDER = "Own_Transcripts"

# Obsidian layout for Knowledge Engine (human + pipeline)
VAULT_DIRS = (
    "10_Sources/Own_Transcripts",
    "20_Extractions/Own_Transcripts",
    "20_Extractions/Editorial",
    "30_Knowledge/Entities",
    "30_Knowledge/Topics",
)


def resolve_vault_path(explicit: Optional[str] = None) -> Path:
    raw = (explicit or os.getenv("OBSIDIAN_VAULT_PATH") or "../Cerebro-Vincent").strip()
    return (PROJECT_ROOT / raw).resolve()


def ensure_vault_structure(vault_path: Path, log: logging.Logger) -> None:
    for rel in VAULT_DIRS:
        path = vault_path / rel
        path.mkdir(parents=True, exist_ok=True)
        log.info("  vault: %s", path)


def list_transcript_files(transcript_dir: Path) -> List[Path]:
    if not transcript_dir.is_dir():
        return []
    return [
        path
        for path in sorted(transcript_dir.glob("*.md"))
        if path.is_file() and not is_status_artifact(path)
    ]


def register_transcripts(conn, *, transcript_dir: Path, log: logging.Logger) -> int:
    registered = 0
    for path in list_transcript_files(transcript_dir):
        video_id = transcript_id_from_path(path)
        raw = path.read_text(encoding="utf-8")
        fm, body = parse_frontmatter(raw)
        title = (fm.get("title") or video_id).strip()
        source_url = (fm.get("source_url") or "").strip()
        source_type = (fm.get("source_type") or "").strip()
        language = (fm.get("language_code") or "es").strip() or "es"
        published_at = (fm.get("uploaded_date") or fm.get("published_at") or "").strip() or None
        body_hash = content_hash(body)
        word_count = len(body.split())

        source_path = None
        if source_url.lower().startswith("file:"):
            source_path = source_url

        upsert_video(
            conn,
            video_id=video_id,
            source_kind=infer_source_kind(source_url, source_type),
            title=title,
            source_url=source_url,
            source_path=source_path,
            transcript_path=str(path.resolve()),
            transcript_hash=body_hash,
            word_count=word_count,
            language_code=language,
            published_at=published_at,
            ingest_status="done",
        )
        mark_content_changed(conn, video_id=video_id, transcript_hash=body_hash)
        registered += 1
    return registered


def main() -> int:
    parser = argparse.ArgumentParser(description="Inicializar Knowledge Engine (SQLite + Obsidian).")
    parser.add_argument("--vault", default=None, help="Ruta al vault Obsidian")
    parser.add_argument(
        "--transcript-folder",
        default=os.getenv("KNOWLEDGE_TRANSCRIPT_FOLDER", DEFAULT_TRANSCRIPT_FOLDER),
    )
    parser.add_argument(
        "--extraction-folder",
        default=os.getenv("KNOWLEDGE_EXTRACTION_FOLDER", DEFAULT_EXTRACTION_FOLDER),
    )
    parser.add_argument("--export-status", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    log = logging.getLogger(__name__)

    vault_path = resolve_vault_path(args.vault)
    if not vault_path.is_dir():
        log.error("Vault no encontrado: %s", vault_path)
        return 1

    transcript_dir = vault_path / "10_Sources" / args.transcript_folder.strip()
    extraction_dir = vault_path / "20_Extractions" / args.extraction_folder.strip()

    log.info("Knowledge Engine — init")
    log.info("SQLite: %s", state_db_path(PROJECT_ROOT).resolve())
    log.info("Estructura Obsidian:")
    ensure_vault_structure(vault_path, log)

    conn = open_engine(PROJECT_ROOT)
    count = register_transcripts(conn, transcript_dir=transcript_dir, log=log)
    log.info("Videos registrados: %s", count)

    paths = sync_status_exports(
        conn,
        project_root=PROJECT_ROOT,
        vault_extraction_dir=extraction_dir,
        transcript_input_dir=str(transcript_dir.resolve()),
    )
    log.info("Estado exportado:")
    log.info("  %s", paths["markdown"])
    log.info("  %s", paths["engine"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
