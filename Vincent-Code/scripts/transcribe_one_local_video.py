#!/usr/bin/env python3
"""Transcribe a single local video file into Obsidian Own_Transcripts."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / ".env", override=True)

from scripts.process_local_videos import (  # noqa: E402
    process_local_video,
    resolve_chunk_long_audio,
    setup_logging,
)
from src.markdown_writer import MarkdownWriter  # noqa: E402
from src.text_processor import TextProcessor  # noqa: E402
from src.video_transcript_state import open_state  # noqa: E402
from src.whisper_client import resolve_whisper_provider  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Transcribe one local video file.")
    parser.add_argument("video", type=Path, help="Path to .mp4/.mkv/...")
    parser.add_argument(
        "--output-folder",
        default="Own_Transcripts",
        help="Subfolder under 10_Sources (default: Own_Transcripts)",
    )
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument("--no-skip-existing", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    setup_logging(args.verbose)

    video = args.video.expanduser().resolve()
    if not video.is_file():
        print(f"Video not found: {video}", file=sys.stderr)
        return 1

    vault = (PROJECT_ROOT / "../Cerebro-Vincent").resolve()
    conn = open_state(str(PROJECT_ROOT))
    result = process_local_video(
        video_path=video,
        markdown_writer=MarkdownWriter(str(vault), folder_name=args.output_folder),
        text_processor=TextProcessor(),
        conn=conn,
        whisper_provider=resolve_whisper_provider(None),
        dry_run=False,
        skip_existing=not args.no_skip_existing,
        retry_failed=args.retry_failed,
        name_suffix="",
        chunk_long_audio=resolve_chunk_long_audio(None),
    )
    print(f"RESULT: {result}")
    return 0 if result == "done" else 1


if __name__ == "__main__":
    raise SystemExit(main())
