#!/usr/bin/env python3
"""
Re-fetch YouTube captions (SRT) and rewrite broken Obsidian transcript notes.

Broken notes contain YouTube VTT karaoke markup (<c>, <00:01.234>) that hangs Obsidian.

Usage (from Vincent-Code root):
  python scripts/repair_youtube_transcript_markdown.py --dry-run
  python scripts/repair_youtube_transcript_markdown.py --limit 5
  python scripts/repair_youtube_transcript_markdown.py
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv(PROJECT_ROOT / ".env", override=True)

from src.text_processor import TextProcessor
from src.youtube_oauth import credentials_available
from src.youtube_oauth_captions import QUOTA_PER_VIDEO, YouTubeOAuthCaptionFetcher

log = logging.getLogger("repair_youtube_transcripts")

BROKEN_RE = re.compile(
    r"<c[\s>]|captions Language\s*:|<\.\d|Kind:\s*captions",
    re.IGNORECASE,
)
VIDEO_ID_RE = re.compile(
    r"(?:youtube\.com/watch\?v=|youtu\.be/)([a-zA-Z0-9_-]{11})"
)


def split_frontmatter(text: str) -> tuple[str, str]:
    if not text.startswith("---"):
        return "", text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return "", text
    return parts[1], parts[2].lstrip("\n")


def extract_video_id(frontmatter: str, body: str) -> str | None:
    for chunk in (frontmatter, body):
        match = re.search(r'source_url:\s*["\']?([^"\'\n]+)', chunk)
        if match:
            url = match.group(1).strip()
            vid = VIDEO_ID_RE.search(url)
            if vid:
                return vid.group(1)
    return None


def extract_language(frontmatter: str) -> str:
    match = re.search(r"language_code:\s*['\"]?(\w+)", frontmatter)
    return match.group(1) if match else "es"


def is_broken(body: str) -> bool:
    return bool(BROKEN_RE.search(body))


def find_transcript_dir() -> Path:
    vault = os.getenv("OBSIDIAN_VAULT_PATH", "../Cerebro-Vincent")
    return (PROJECT_ROOT / vault / "10_Sources" / "Own_Transcripts").resolve()


def rewrite_note(path: Path, frontmatter: str, body: str) -> None:
    path.write_text(f"---{frontmatter}---\n\n{body.rstrip()}\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Repair broken YouTube transcript markdown files")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=0, help="Max files to repair (0 = all)")
    parser.add_argument("--file", type=str, default="", help="Repair a single markdown path")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if not credentials_available(PROJECT_ROOT):
        log.error("OAuth no configurado. Corre: python scripts/youtube_oauth_login.py")
        return 1

    transcript_dir = find_transcript_dir()
    if not transcript_dir.is_dir():
        log.error("No existe: %s", transcript_dir)
        return 1

    if args.file:
        candidates = [Path(args.file).resolve()]
    else:
        candidates = sorted(transcript_dir.glob("*.md"))

    broken: list[tuple[Path, str, str, str]] = []
    for path in candidates:
        if path.name.startswith("_estado"):
            continue
        text = path.read_text(encoding="utf-8")
        fm, body = split_frontmatter(text)
        if not is_broken(body):
            continue
        video_id = extract_video_id(fm, body)
        if not video_id:
            log.warning("Sin video_id: %s", path.name)
            continue
        broken.append((path, fm, body, video_id))

    log.info("Notas rotas encontradas: %s", len(broken))
    if args.limit > 0:
        broken = broken[: args.limit]

    if not broken:
        log.info("Nada que reparar.")
        return 0

    if args.dry_run:
        for path, _, _, video_id in broken:
            log.info("[dry-run] %s (%s)", path.name, video_id)
        est_quota = len(broken) * QUOTA_PER_VIDEO
        log.info("Cuota estimada: ~%s unidades (%s vídeos)", est_quota, len(broken))
        return 0

    fetcher = YouTubeOAuthCaptionFetcher(str(PROJECT_ROOT))
    processor = TextProcessor()
    ok = fail = 0

    for path, fm, _old_body, video_id in broken:
        lang = extract_language(fm)
        log.info("Reparando %s (%s)...", path.name, video_id)
        outcome = fetcher.fetch_transcript(video_id, languages=[lang, "es", "es-419", "en"])
        if not outcome.ok or not outcome.text:
            log.warning("  FAIL: %s", outcome.error or "empty")
            fail += 1
            if outcome.quota_exceeded:
                log.error("Cuota agotada. Relanza mañana: python scripts/repair_youtube_transcript_markdown.py")
                break
            continue

        processed = processor.process(
            outcome.text,
            language_code=outcome.language_code or lang,
        )
        rewrite_note(path, fm, processed)
        log.info("  OK (~%s palabras, cuota acumulada %s)", len(processed.split()), fetcher.quota_used)
        ok += 1

    log.info("Listo: OK=%s FAIL=%s cuota=%s", ok, fail, fetcher.quota_used)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
