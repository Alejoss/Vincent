#!/usr/bin/env python3
"""
Regenera los export derivados del estado de transcripción local (desde SQLite).

Fuente de verdad:
  Vincent-Code/cache/video_transcripts/state.sqlite3

Export derivado (vault, regenerable):
  Cerebro-Vincent/10_Sources/Own_Transcripts/_estado_videos_local.json
  Cerebro-Vincent/10_Sources/Own_Transcripts/_estado_procesamiento_local.md

Uso:
  python scripts/export_local_transcript_status.py
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv(PROJECT_ROOT / ".env", override=True)

from src.video_transcript_state import (
    build_local_status_manifest,
    open_state,
    state_db_path,
    sync_local_status_exports,
)

DEFAULT_OUTPUT_FOLDER = "Own_Transcripts"
DEFAULT_INPUT_DIR = PROJECT_ROOT


def resolve_input_dir(explicit: Optional[str] = None) -> Path:
    raw = (explicit or os.getenv("LOCAL_VIDEOS_INPUT_DIR") or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return DEFAULT_INPUT_DIR.resolve()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Regenerar export de estado local desde SQLite."
    )
    parser.add_argument("--input-dir", default=None)
    parser.add_argument(
        "--output-folder",
        default=os.getenv("YOUTUBE_OWN_TRANSCRIPTS_FOLDER", DEFAULT_OUTPUT_FOLDER),
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    log = logging.getLogger(__name__)

    input_dir = resolve_input_dir(args.input_dir)

    vault_path = (os.getenv("OBSIDIAN_VAULT_PATH") or "../Cerebro-Vincent").strip()
    vault_resolved = (PROJECT_ROOT / vault_path).resolve()
    output_dir = vault_resolved / "10_Sources" / args.output_folder.strip()

    conn = open_state(str(PROJECT_ROOT))
    paths = sync_local_status_exports(
        conn,
        project_root=PROJECT_ROOT,
        vault_output_dir=output_dir,
        input_dir=str(Path(input_dir).resolve()),
    )
    manifest = build_local_status_manifest(
        conn,
        project_root=PROJECT_ROOT,
        input_dir=str(Path(input_dir).resolve()),
    )
    summary = manifest["summary"]

    log.info("Fuente de verdad: %s", state_db_path(PROJECT_ROOT).resolve())
    log.info(
        "Estado local (%s vídeos): done=%s pending=%s failed=%s skipped=%s",
        summary["total"],
        summary["done"],
        summary["pending"],
        summary["failed"],
        summary["skipped"],
    )
    log.info("JSON (completo): %s", paths["json"])
    log.info("Markdown (resumen): %s", paths["markdown"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
