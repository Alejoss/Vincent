#!/usr/bin/env python3
"""Extract podcast-quality MP3 from a single local video file."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = PROJECT_ROOT.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / ".env", override=True)

from src.audio_extract import extract_audio_podcast, find_ffmpeg  # noqa: E402
from src.podcast_catalog import (  # noqa: E402
    default_catalog_dir,
    record_item,
)
from src.video_transcript_state import open_state  # noqa: E402

DEFAULT_OUTPUT_DIR = REPO_ROOT / "VideosParaPodcast" / "mp3"
VIDEO_EXTENSIONS = {
    ".mp4",
    ".mkv",
    ".mov",
    ".avi",
    ".webm",
    ".m4v",
    ".wmv",
    ".flv",
    ".mpeg",
    ".mpg",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract MP3 audio from one video file.")
    parser.add_argument("video", type=Path, help="Path to .mp4/.mkv/...")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Folder for the MP3 (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument("--force", action="store_true", help="Overwrite an existing MP3.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    log = logging.getLogger(__name__)

    video = args.video.expanduser().resolve()
    if not video.is_file():
        print(f"Video not found: {video}", file=sys.stderr)
        return 1
    if video.suffix.lower() not in VIDEO_EXTENSIONS:
        print(f"Unsupported video extension: {video.suffix}", file=sys.stderr)
        return 1

    output_dir = args.output_dir.expanduser().resolve()
    output = output_dir / f"{video.stem}.mp3"

    catalog_dir = default_catalog_dir(REPO_ROOT)

    def write_catalog(*, status: str, skipped: bool) -> None:
        if output.parent.resolve() != (catalog_dir / "mp3").resolve():
            return
        source_path = None if video.parent.resolve() == catalog_dir.resolve() else video
        conn = open_state(str(PROJECT_ROOT))
        try:
            record_item(
                conn,
                video,
                status=status,
                mp3=output,
                skipped=skipped,
                source_path=source_path,
            )
        finally:
            conn.close()

    if args.dry_run:
        print(f"RESULT: dry_run")
        print(f"SOURCE: {video}")
        print(f"OUTPUT: {output}")
        return 0

    if output.is_file() and not args.force:
        write_catalog(status="done", skipped=True)
        print(f"RESULT: skipped")
        print(f"OUTPUT: {output}")
        return 0

    try:
        find_ffmpeg()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    output_dir.mkdir(parents=True, exist_ok=True)
    log.info("Extracting %s -> %s", video.name, output)
    extract_audio_podcast(video, output)
    write_catalog(status="done", skipped=False)
    print(f"RESULT: done")
    print(f"OUTPUT: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
