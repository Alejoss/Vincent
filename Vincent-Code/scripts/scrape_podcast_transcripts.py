#!/usr/bin/env python3
"""Scrape transcripts for specific podcast videos (oauth_forbidden fallback)."""
from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
load_dotenv(PROJECT_ROOT / ".env", override=True)

from scripts.process_youtube_channel import parse_languages, process_video, setup_logging
from src.markdown_writer import MarkdownWriter
from src.text_processor import TextProcessor
from src.video_transcript_state import open_state, sync_status_exports
from src.youtube_transcript import YouTubeTranscriptFetcher

TARGET_IDS = [
    "UpaHqUol6wk",   # recordemos_falsa_historia_btc6
    "XUnRBOmZCeI",   # Jhon McAfee
    "V9bQ1CBHnrM",   # criptoanarquismo_puro_TE
    "tbRSS-Upq_c",   # china_anuncio
    "UaMEeL-A-ok",   # epstein_files_btc
]


def main() -> int:
    setup_logging(verbose=False)
    log = logging.getLogger(__name__)

    api_key = (os.getenv("YOUTUBE_API_KEY") or "").strip()
    if not api_key:
        log.error("Missing YOUTUBE_API_KEY")
        return 1

    vault_path = (os.getenv("OBSIDIAN_VAULT_PATH") or "../Cerebro-Vincent").strip()
    vault_resolved = (PROJECT_ROOT / vault_path).resolve()
    output_folder = os.getenv("YOUTUBE_OWN_TRANSCRIPTS_FOLDER", "Own_Transcripts").strip()
    vault_output_dir = vault_resolved / "10_Sources" / output_folder

    fetcher = YouTubeTranscriptFetcher(api_key)
    markdown_writer = MarkdownWriter(str(vault_resolved), folder_name=output_folder)
    text_processor = TextProcessor()
    conn = open_state(str(PROJECT_ROOT))
    languages = parse_languages(os.getenv("YOUTUBE_TRANSCRIPT_LANGUAGES", "es,es-419,en"))

    # Resolve titles from YouTube API
    resp = fetcher.youtube.videos().list(part="snippet", id=",".join(TARGET_IDS)).execute()
    by_id = {item["id"]: item["snippet"] for item in resp.get("items", [])}

    counts = {"done": 0, "failed": 0, "skipped": 0}
    started = time.perf_counter()

    for i, vid in enumerate(TARGET_IDS, 1):
        snippet = by_id.get(vid)
        if not snippet:
            log.error("[%s/%s] video no encontrado: %s", i, len(TARGET_IDS), vid)
            counts["failed"] += 1
            continue
        video = {"id": vid, "title": snippet["title"], "publishedAt": snippet.get("publishedAt")}
        log.info("[%s/%s] %s", i, len(TARGET_IDS), video["title"])
        outcome, _ = process_video(
            video=video,
            list_fetcher=fetcher,
            caption_fetcher=fetcher,
            method="scraper",
            markdown_writer=markdown_writer,
            text_processor=text_processor,
            conn=conn,
            languages=languages,
            dry_run=False,
            skip_existing=True,
        )
        counts[outcome] = counts.get(outcome, 0) + 1
        if outcome == "done":
            log.info("  [OK] %s", video["title"])

    sync_status_exports(
        conn,
        project_root=PROJECT_ROOT,
        vault_output_dir=vault_output_dir,
        channel_url=os.getenv("YOUTUBE_CHANNEL_URL", "https://www.youtube.com/@AcademiaBlockchain"),
    )
    elapsed = time.perf_counter() - started
    log.info(
        "Finalizado en %.1f min — OK %s | FAIL %s | SKIP %s",
        elapsed / 60,
        counts.get("done", 0),
        counts.get("failed", 0),
        counts.get("skipped", 0),
    )
    return 0 if counts.get("done", 0) > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
