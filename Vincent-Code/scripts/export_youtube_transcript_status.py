#!/usr/bin/env python3
"""
Regenera los export derivados del estado de transcripción (desde SQLite).

Fuente de verdad:
  Vincent-Code/cache/video_transcripts/state.sqlite3

Export derivado (vault, regenerable):
  Cerebro-Vincent/10_Sources/Own_Transcripts/_estado_videos.json
  Cerebro-Vincent/10_Sources/Own_Transcripts/_estado_procesamiento.md  (solo resumen)

Uso:
  python scripts/export_youtube_transcript_status.py
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv(PROJECT_ROOT / ".env", override=True)

from src.video_transcript_state import (
    build_status_manifest,
    open_state,
    reconcile_done_with_vault,
    state_db_path,
    sync_status_exports,
)

DEFAULT_CHANNEL_URL = "https://www.youtube.com/@AcademiaBlockchain"
DEFAULT_OUTPUT_FOLDER = "Own_Transcripts"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Regenerar export de estado desde SQLite (fuente de verdad)."
    )
    parser.add_argument(
        "--channel-url",
        default=os.getenv("YOUTUBE_CHANNEL_URL", DEFAULT_CHANNEL_URL),
    )
    parser.add_argument(
        "--output-folder",
        default=os.getenv("YOUTUBE_OWN_TRANSCRIPTS_FOLDER", DEFAULT_OUTPUT_FOLDER),
    )
    parser.add_argument(
        "--reconcile",
        action="store_true",
        help="Alinear done/skipped con .md del vault antes de exportar",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    log = logging.getLogger(__name__)

    vault_path = (os.getenv("OBSIDIAN_VAULT_PATH") or "../Cerebro-Vincent").strip()
    vault_resolved = (PROJECT_ROOT / vault_path).resolve()
    output_dir = vault_resolved / "10_Sources" / args.output_folder.strip()

    conn = open_state(str(PROJECT_ROOT))
    if args.reconcile:
        stats = reconcile_done_with_vault(conn)
        log.info(
            "Reconciliación vault: done_ok=%s needs_repair=%s missing→pending=%s skipped_corrupt=%s",
            stats["kept_done"],
            stats["needs_repair"],
            stats["missing_file_pending"],
            stats["skipped_corrupt"],
        )
    paths = sync_status_exports(
        conn,
        project_root=PROJECT_ROOT,
        vault_output_dir=output_dir,
        channel_url=args.channel_url,
    )
    manifest = build_status_manifest(conn, args.channel_url, PROJECT_ROOT)
    summary = manifest["summary"]

    log.info("Fuente de verdad: %s", state_db_path(PROJECT_ROOT).resolve())
    log.info(
        "Estado (%s vídeos): done=%s pending=%s needs_repair=%s failed=%s skipped=%s",
        summary["total"],
        summary["done"],
        summary["pending"],
        summary.get("needs_repair", 0),
        summary["failed"],
        summary["skipped"],
    )
    log.info("JSON (completo): %s", paths["json"])
    log.info("Markdown (resumen): %s", paths["markdown"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
