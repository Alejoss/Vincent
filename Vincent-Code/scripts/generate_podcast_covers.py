#!/usr/bin/env python3
"""Generate square podcast covers from podcast_episode via OpenAI Images."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = PROJECT_ROOT.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / ".env", override=True)

from src.podcast_covers import (  # noqa: E402
    DEFAULT_MODEL,
    DEFAULT_QUALITY,
    DEFAULT_SIZE,
    generate_covers,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate 1:1 podcast covers with the Academia Blockchain style reference.",
    )
    parser.add_argument(
        "--episode-id",
        default=None,
        help="podcast_episode.episode_id (video filename). Default: catalog order.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Only the first N published episodes (rss_pub_date order).",
    )
    parser.add_argument("--word", default=None, help="Override the 1–2 cover words.")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--size", default=DEFAULT_SIZE, help="Must be square, e.g. 1024x1024.")
    parser.add_argument("--quality", default=DEFAULT_QUALITY)
    parser.add_argument("--include-unpublished", action="store_true")
    parser.add_argument("--force", action="store_true", help="Regenerate even if a cover exists.")
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
    width, _, height = args.size.lower().partition("x")
    if not (width.isdigit() and height.isdigit() and width == height):
        print(f"Size must be square (1:1), got {args.size!r}", file=sys.stderr)
        return 2
    result = generate_covers(
        project_root=PROJECT_ROOT,
        repo_root=REPO_ROOT,
        episode_id=args.episode_id,
        limit=args.limit,
        include_unpublished=args.include_unpublished,
        dry_run=args.dry_run,
        force=args.force,
        word_override=args.word,
        model=args.model,
        size=args.size,
        quality=args.quality,
    )
    payload = json.dumps(result, ensure_ascii=False, indent=2)
    sys.stdout.buffer.write((payload + "\n").encode("utf-8", errors="replace"))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
