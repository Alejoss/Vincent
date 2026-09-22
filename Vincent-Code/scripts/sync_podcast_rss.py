#!/usr/bin/env python3
"""Match VideosParaPodcast/mp3 against the Spotify/Anchor RSS feed."""

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

from src.podcast_catalog import DEFAULT_RSS_URL, default_catalog_dir, sync_from_rss


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sync podcast MP3 catalog from RSS into SQLite (podcast_episode).",
    )
    parser.add_argument("--rss-url", default=DEFAULT_RSS_URL)
    parser.add_argument("--catalog-dir", type=Path, default=None)
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
    catalog_dir = (args.catalog_dir or default_catalog_dir(REPO_ROOT)).expanduser().resolve()
    result = sync_from_rss(
        catalog_dir,
        project_root=PROJECT_ROOT,
        rss_url=args.rss_url,
        dry_run=args.dry_run,
    )
    payload = json.dumps(result, ensure_ascii=False, indent=2)
    sys.stdout.buffer.write((payload + "\n").encode("utf-8", errors="replace"))
    if result["unmatched_rss"]:
        logging.getLogger(__name__).warning(
            "RSS sin MP3 local: %s", "; ".join(result["unmatched_rss"])
        )
    if result["unmatched_local"]:
        logging.getLogger(__name__).info(
            "MP3 local sin publicar: %s", "; ".join(result["unmatched_local"])
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
