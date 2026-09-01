#!/usr/bin/env python3
"""
Fetch YouTube captions for all uploads on a channel and save them to Obsidian.

Default method: OAuth + YouTube Data API captions.download (own channel, no IP blocks).
Legacy method: youtube-transcript-api scraper (--method scraper).

Examples (from Vincent-Code root):
  python scripts/youtube_oauth_login.py          # first-time OAuth
  python scripts/process_youtube_channel.py --limit 3
  python scripts/process_youtube_channel.py

Requires in .env:
  YOUTUBE_API_KEY
  OBSIDIAN_VAULT_PATH=../Cerebro-Vincent
  OAuth client secrets (see env.example)
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Union

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv(PROJECT_ROOT / ".env", override=True)

from src.markdown_writer import MarkdownWriter
from src.text_processor import TextProcessor
from src.video_transcript_state import (
    get_status,
    mark_done,
    mark_failed,
    mark_skipped,
    open_state,
    sync_status_exports,
    upsert_discovered,
)
from src.youtube_oauth import credentials_available
from src.youtube_oauth_captions import QUOTA_PER_VIDEO, YouTubeOAuthCaptionFetcher, caption_text_looks_corrupt
from src.youtube_transcript import YouTubeTranscriptFetcher

DEFAULT_CHANNEL_URL = "https://www.youtube.com/@AcademiaBlockchain"
DEFAULT_LANGUAGES = ["es", "es-419", "en"]
DEFAULT_OUTPUT_FOLDER = "Own_Transcripts"
DEFAULT_OAUTH_DELAY = 0.5
DEFAULT_SCRAPER_DELAY = 1.5
DEFAULT_QUOTA_BUDGET = 9000
LOG_DIR = PROJECT_ROOT / "logs"
LATEST_LOG_NAME = "youtube_channel_transcripts_latest.log"


def setup_logging(verbose: bool) -> Path:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = LOG_DIR / f"youtube_channel_transcripts_{timestamp}.log"
    latest_log = LOG_DIR / LATEST_LOG_NAME

    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    root.handlers.clear()

    detailed = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(message)s",
        datefmt="%H:%M:%S",
    )
    console = logging.Formatter("%(message)s")

    for path, mode in ((log_file, "w"), (latest_log, "w")):
        fh = logging.FileHandler(path, encoding="utf-8", mode=mode)
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(detailed)
        root.addHandler(fh)

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(console)
    root.addHandler(ch)

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("googleapiclient").setLevel(logging.WARNING)
    logging.getLogger("googleapiclient.discovery_cache").setLevel(logging.WARNING)

    log = logging.getLogger(__name__)
    log.info("=" * 60)
    log.info("Pipeline de subtítulos — Academia Blockchain")
    log.info("Log detallado: %s", log_file)
    log.info("Log en vivo (última ejecución): %s", latest_log)
    log.info("=" * 60)
    return log_file


def parse_languages(raw: Optional[str]) -> List[str]:
    if not raw or not raw.strip():
        return DEFAULT_LANGUAGES
    return [part.strip() for part in raw.split(",") if part.strip()]


def skip_reason(
    conn,
    *,
    video_id: str,
    source_url: str,
    markdown_writer: MarkdownWriter,
    skip_existing: bool,
    retry_failed: bool,
) -> Optional[str]:
    if skip_existing and markdown_writer.transcript_exists(source_url):
        return "ya existe en Obsidian (Own_Transcripts)"
    status = get_status(conn, video_id)
    if status == "done" and skip_existing:
        return "ya marcado done en state.sqlite3"
    if status == "failed" and not retry_failed:
        return "falló antes (usa --retry-failed para reintentar)"
    if status == "skipped" and skip_existing:
        return "ya marcado skipped en state.sqlite3"
    return None


def should_process_video(
    conn,
    *,
    video_id: str,
    source_url: str,
    markdown_writer: MarkdownWriter,
    skip_existing: bool,
    retry_failed: bool,
) -> bool:
    return (
        skip_reason(
            conn,
            video_id=video_id,
            source_url=source_url,
            markdown_writer=markdown_writer,
            skip_existing=skip_existing,
            retry_failed=retry_failed,
        )
        is None
    )


def save_raw_transcript(video_id: str, transcript: str) -> None:
    output_dir = PROJECT_ROOT / "raw_transcripts"
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"youtube_{video_id}.txt"
    path.write_text(transcript, encoding="utf-8")


def process_video(
    *,
    video: dict,
    list_fetcher: YouTubeTranscriptFetcher,
    caption_fetcher: Union[YouTubeOAuthCaptionFetcher, YouTubeTranscriptFetcher],
    method: str,
    markdown_writer: MarkdownWriter,
    text_processor: TextProcessor,
    conn,
    languages: List[str],
    dry_run: bool,
    skip_existing: bool,
) -> tuple[str, bool]:
    """Returns (outcome, quota_exceeded)."""
    video_id = video["id"]
    title = video["title"]
    source_url = f"https://www.youtube.com/watch?v={video_id}"
    log = logging.getLogger(__name__)

    if skip_existing and markdown_writer.transcript_exists(source_url):
        if not dry_run:
            mark_skipped(conn, video_id=video_id, title=title, source_url=source_url)
        log.info("  skip (already in vault): %s", title)
        return "skipped", False

    if dry_run:
        log.info("  [dry-run] se procesaría (%s): %s", method, source_url)
        return "dry_run", False

    log.debug("  descargando subtítulos [%s] (%s)...", method, ", ".join(languages))
    t0 = time.perf_counter()
    transcript: Optional[str] = None
    language_code: Optional[str] = None
    err = "no_captions_available"
    quota_exceeded = False

    if method == "oauth":
        outcome = caption_fetcher.fetch_transcript(video_id, languages=languages)
        elapsed = time.perf_counter() - t0
        if outcome.ok and outcome.text:
            transcript = outcome.text
            language_code = outcome.language_code or "und"
        else:
            err = outcome.error or "no_captions_available"
            quota_exceeded = outcome.quota_exceeded
            if quota_exceeded:
                log.error("  [QUOTA] Cuota diaria de YouTube API agotada")
                mark_failed(
                    conn,
                    video_id=video_id,
                    title=title,
                    source_url=source_url,
                    error=err,
                )
                return "failed", True
    else:
        result = caption_fetcher.fetch_transcript(video_id, languages=languages)
        elapsed = time.perf_counter() - t0
        if result:
            transcript, language_code = result

    if not transcript or not language_code:
        mark_failed(
            conn,
            video_id=video_id,
            title=title,
            source_url=source_url,
            error=err,
        )
        log.warning("  [FAIL] (%.1fs): %s — %s", elapsed, title, err)
        return "failed", False

    if caption_text_looks_corrupt(transcript):
        mark_failed(
            conn,
            video_id=video_id,
            title=title,
            source_url=source_url,
            error="vtt_markup_in_parsed_text",
        )
        log.error(
            "  [FAIL] (%.1fs): %s — markup VTT en subtítulos; no se guarda en Obsidian",
            elapsed,
            title,
        )
        return "failed", False

    word_count = len(transcript.split())
    log.debug(
        "  subtítulos OK (%.1fs): lang=%s, ~%s palabras",
        elapsed,
        language_code,
        word_count,
    )

    save_raw_transcript(video_id, transcript)
    processed_text = text_processor.process(transcript, language_code=language_code)
    if caption_text_looks_corrupt(processed_text):
        mark_failed(
            conn,
            video_id=video_id,
            title=title,
            source_url=source_url,
            error="vtt_markup_after_processing",
        )
        log.error(
            "  [FAIL]: %s — markup VTT tras procesar; no se guarda en Obsidian",
            title,
        )
        return "failed", False

    text_processor.save_processed_text(processed_text, video_id)

    output_path = markdown_writer.save_transcript(
        title=title,
        content=processed_text,
        source_url=source_url,
        source_type="Own Video",
        upload_date=video.get("publishedAt"),
        processed_date=datetime.now().isoformat(),
        language_code=language_code,
    )

    mark_done(
        conn,
        video_id=video_id,
        title=title,
        source_url=source_url,
        output_path=output_path,
        language_code=language_code,
    )
    log.info(
        "  [OK] guardado (%.1fs, %s, ~%s palabras): %s",
        elapsed,
        language_code,
        word_count,
        Path(output_path).name,
    )
    return "done", False


def resolve_method(explicit: Optional[str]) -> str:
    raw = (explicit or os.getenv("YOUTUBE_CAPTION_METHOD") or "oauth").strip().lower()
    if raw in {"oauth", "api", "official"}:
        return "oauth"
    if raw in {"scraper", "transcript-api", "legacy"}:
        return "scraper"
    raise ValueError(f"YOUTUBE_CAPTION_METHOD desconocido: {raw}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Transcribe a YouTube channel's captions into Obsidian."
    )
    parser.add_argument("--channel-url", default=os.getenv("YOUTUBE_CHANNEL_URL", DEFAULT_CHANNEL_URL))
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--languages",
        default=os.getenv("YOUTUBE_TRANSCRIPT_LANGUAGES", "es,es-419,en"),
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument("--no-skip-existing", action="store_true")
    parser.add_argument(
        "--method",
        choices=["oauth", "scraper"],
        default=None,
        help="oauth=API oficial (recomendado), scraper=legacy (bloqueo IP)",
    )
    parser.add_argument(
        "--quota-budget",
        type=int,
        default=int(os.getenv("YOUTUBE_OAUTH_DAILY_QUOTA_BUDGET", DEFAULT_QUOTA_BUDGET)),
        help="Máximo de unidades de cuota OAuth por ejecución (default 9000)",
    )
    parser.add_argument(
        "--delay-seconds",
        type=float,
        default=None,
        help="Pausa entre vídeos (default: 0.5 oauth, 1.5 scraper)",
    )
    parser.add_argument(
        "--output-folder",
        default=os.getenv("YOUTUBE_OWN_TRANSCRIPTS_FOLDER", DEFAULT_OUTPUT_FOLDER),
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    setup_logging(args.verbose)
    log = logging.getLogger(__name__)
    run_started = time.perf_counter()

    try:
        method = resolve_method(args.method)
    except ValueError as exc:
        log.error("%s", exc)
        return 1

    api_key = (os.getenv("YOUTUBE_API_KEY") or "").strip()
    if not api_key:
        log.error("Missing YOUTUBE_API_KEY in .env")
        return 1

    if method == "oauth" and not credentials_available(str(PROJECT_ROOT)):
        log.error(
            "No hay token OAuth. Ejecuta primero:\n"
            "  python scripts/youtube_oauth_login.py"
        )
        return 1

    vault_path = (os.getenv("OBSIDIAN_VAULT_PATH") or "../Cerebro-Vincent").strip()
    vault_resolved = (PROJECT_ROOT / vault_path).resolve()
    if not vault_resolved.is_dir():
        log.error("Obsidian vault not found: %s", vault_resolved)
        return 1

    languages = parse_languages(args.languages)
    skip_existing = not args.no_skip_existing
    state_db = PROJECT_ROOT / "cache" / "video_transcripts" / "state.sqlite3"
    output_folder = args.output_folder.strip() or DEFAULT_OUTPUT_FOLDER
    vault_output_dir = vault_resolved / "10_Sources" / output_folder

    if args.delay_seconds is None:
        if method == "oauth":
            args.delay_seconds = float(
                os.getenv("YOUTUBE_OAUTH_DELAY_SECONDS", DEFAULT_OAUTH_DELAY)
            )
        else:
            args.delay_seconds = float(
                os.getenv("YOUTUBE_TRANSCRIPT_DELAY_SECONDS", DEFAULT_SCRAPER_DELAY)
            )

    log.info("Canal: %s", args.channel_url)
    log.info("Vault: %s", vault_resolved)
    log.info("Salida: 10_Sources/%s", output_folder)
    log.info("Método: %s", method)
    log.info("Idiomas: %s", ", ".join(languages))
    log.info("State DB: %s", state_db)
    if method == "oauth":
        max_videos_quota = args.quota_budget // QUOTA_PER_VIDEO
        log.info(
            "Cuota OAuth: budget=%s (~%s vídeos), %s unidades/vídeo",
            args.quota_budget,
            max_videos_quota,
            QUOTA_PER_VIDEO,
        )
    if args.limit:
        log.info("Límite: %s vídeo(s)", args.limit)
    if args.dry_run:
        log.info("Modo: dry-run")
    if args.retry_failed:
        log.info("Modo: reintentar fallidos")
    if args.delay_seconds > 0 and not args.dry_run:
        log.info("Pausa entre vídeos: %ss", args.delay_seconds)

    list_fetcher = YouTubeTranscriptFetcher(api_key)
    oauth_fetcher: Optional[YouTubeOAuthCaptionFetcher] = None
    scraper_fetcher: Optional[YouTubeTranscriptFetcher] = None
    if method == "oauth":
        oauth_fetcher = YouTubeOAuthCaptionFetcher(str(PROJECT_ROOT))
        caption_fetcher: Union[YouTubeOAuthCaptionFetcher, YouTubeTranscriptFetcher] = oauth_fetcher
    else:
        scraper_fetcher = list_fetcher
        caption_fetcher = scraper_fetcher

    markdown_writer = MarkdownWriter(str(vault_resolved), folder_name=output_folder)
    text_processor = TextProcessor()
    conn = open_state(str(PROJECT_ROOT))

    log.info("")
    log.info("Listando vídeos del canal (YouTube Data API)...")
    list_started = time.perf_counter()
    videos = list_fetcher.list_channel_videos(args.channel_url, max_results=args.limit)
    if not videos:
        log.error("No se encontraron vídeos en el canal.")
        return 1

    log.info(
        "Listado completo: %s vídeo(s) en %.1fs",
        len(videos),
        time.perf_counter() - list_started,
    )

    for video in videos:
        upsert_discovered(
            conn,
            video_id=video["id"],
            title=video["title"],
            source_url=f"https://www.youtube.com/watch?v={video['id']}",
            published_at=video.get("publishedAt"),
            channel_url=args.channel_url,
        )

    to_process = sum(
        1
        for video in videos
        if should_process_video(
            conn,
            video_id=video["id"],
            source_url=f"https://www.youtube.com/watch?v={video['id']}",
            markdown_writer=markdown_writer,
            skip_existing=skip_existing,
            retry_failed=args.retry_failed,
        )
    )

    log.info(
        "Plan: %s a procesar, %s omitidos",
        to_process,
        len(videos) - to_process,
    )
    if method == "oauth" and to_process:
        planned = min(to_process, args.quota_budget // QUOTA_PER_VIDEO)
        if planned < to_process:
            log.info(
                "Solo se procesarán ~%s vídeos hoy por límite de cuota (relanza mañana)",
                planned,
            )
    log.info("")

    counts = {"done": 0, "failed": 0, "skipped": 0, "dry_run": 0}
    quota_used = 0
    stop_for_quota = False

    for idx, video in enumerate(videos, 1):
        if stop_for_quota:
            break

        video_id = video["id"]
        source_url = f"https://www.youtube.com/watch?v={video_id}"
        log.info("[%s/%s] %s", idx, len(videos), video.get("title", video_id))

        reason = skip_reason(
            conn,
            video_id=video_id,
            source_url=source_url,
            markdown_writer=markdown_writer,
            skip_existing=skip_existing,
            retry_failed=args.retry_failed,
        )
        if reason:
            if not args.dry_run and (
                "Obsidian" in reason
                or "done en state" in reason
                or "skipped en state" in reason
            ):
                mark_skipped(
                    conn,
                    video_id=video_id,
                    title=video["title"],
                    source_url=source_url,
                    reason=reason,
                )
            log.info("  [SKIP] omitido: %s", reason)
            counts["skipped"] += 1
            continue

        if method == "oauth" and quota_used + QUOTA_PER_VIDEO > args.quota_budget:
            log.warning(
                "  [QUOTA] Budget alcanzado (%s/%s). Deteniendo; relanza mañana.",
                quota_used,
                args.quota_budget,
            )
            break

        outcome, quota_hit = process_video(
            video=video,
            list_fetcher=list_fetcher,
            caption_fetcher=caption_fetcher,
            method=method,
            markdown_writer=markdown_writer,
            text_processor=text_processor,
            conn=conn,
            languages=languages,
            dry_run=args.dry_run,
            skip_existing=skip_existing,
        )
        counts[outcome] = counts.get(outcome, 0) + 1

        if method == "oauth" and oauth_fetcher and outcome in {"done", "failed"}:
            quota_used = oauth_fetcher.quota_used
        if quota_hit:
            stop_for_quota = True
            break

        processed_so_far = counts.get("done", 0) + counts.get("failed", 0)
        if processed_so_far and processed_so_far % 10 == 0 and outcome in {"done", "failed"}:
            log.info(
                "  --- progreso: %s | OK %s | FAIL %s | cuota %s ---",
                processed_so_far,
                counts.get("done", 0),
                counts.get("failed", 0),
                quota_used,
            )

        if (
            not args.dry_run
            and args.delay_seconds > 0
            and idx < len(videos)
            and outcome in {"done", "failed"}
            and not stop_for_quota
        ):
            time.sleep(args.delay_seconds)

    if not args.dry_run:
        paths = sync_status_exports(
            conn,
            project_root=PROJECT_ROOT,
            vault_output_dir=vault_output_dir,
            channel_url=args.channel_url,
        )
        log.info("Estado regenerado desde SQLite:")
        log.info("  JSON: %s", paths["json"])
        log.info("  Resumen: %s", paths["markdown"])

    elapsed = time.perf_counter() - run_started
    log.info("")
    log.info("=" * 60)
    log.info(
        "Finalizado en %.1f min — OK %s | FAIL %s | SKIP %s | cuota %s",
        elapsed / 60,
        counts.get("done", 0),
        counts.get("failed", 0),
        counts.get("skipped", 0),
        quota_used,
    )
    log.info("Log: logs/%s", LATEST_LOG_NAME)
    log.info("=" * 60)
    if counts.get("done", 0) == 0 and counts.get("dry_run", 0) == 0 and counts.get("skipped", 0) == 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
