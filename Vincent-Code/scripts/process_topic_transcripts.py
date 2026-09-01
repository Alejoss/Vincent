#!/usr/bin/env python3
"""
Ensure VIDEO/AUDIO contents of a Sophia topic have ContentTranscript.

Pulls the work queue from transcript-ingest, generates text via YouTube captions
or Whisper (S3 / yt-dlp), PUTs artifacts to Digital Ocean, and tracks state in
local SQLite (topic_ids + transcribed_at).

Examples (from Vincent-Code root):
  python scripts/process_topic_transcripts.py --topic-id 12 --dry-run
  python scripts/process_topic_transcripts.py --topic-id 12 --limit 1
  python scripts/process_topic_transcripts.py --topic-id 12 --content-id 101
  python scripts/process_topic_transcripts.py --topic-id 12 --export-only

Requires in .env (Vincent-Code and/or Sophia acbc_app/.env fallback):
  SOPHIA_API_BASE=https://www.academiablockchain.com/api
  TRANSCRIPT_INGEST_API_KEY=...
  AWS_STORAGE_BUCKET_NAME / AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY (for file_key)
  OPENAI_API_KEY when WHISPER_PROVIDER=openai
  OBSIDIAN_VAULT_PATH=../Cerebro-Vincent
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Load Vincent-Code .env first, then Sophia backend .env for AWS / ingest key fallbacks
load_dotenv(PROJECT_ROOT / ".env", override=True)
_SOPHIA_ENV = Path(r"E:\Sophia.AI Academia Blockchain\acbc_app\.env")
if _SOPHIA_ENV.is_file():
    load_dotenv(_SOPHIA_ENV, override=False)

from src.audio_extract import extract_audio
from src.sophia_local_transcript_lookup import find_local_transcript
from src.sophia_s3 import download_s3_object, resolve_bucket
from src.sophia_transcript_ingest import (
    SophiaTranscriptIngestClient,
    SophiaTranscriptIngestError,
)
from src.sophia_transcript_state import (
    get_status,
    mark_done,
    mark_failed,
    mark_skipped,
    open_sophia_state,
    sync_topic_coverage_exports,
    upsert_discovered,
)
from src.sophia_youtube_captions import extract_youtube_video_id, fetch_youtube_captions
from src.text_processor import TextProcessor
from src.whisper_client import (
    resolve_chunk_long_audio,
    resolve_whisper_provider,
    transcribe_audio,
)

DEFAULT_OUTPUT_FOLDER = "Own_Transcripts"
LOG_DIR = PROJECT_ROOT / "logs"
LATEST_LOG_NAME = "topic_transcripts_latest.log"
MEDIA_CACHE_DIR = PROJECT_ROOT / "cache" / "sophia_media"
AUDIO_CACHE_DIR = PROJECT_ROOT / "cache" / "sophia_media" / "audio"
WHISPER_CACHE_DIR = PROJECT_ROOT / "cache" / "sophia_media" / "whisper"


def setup_logging(verbose: bool) -> Path:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = LOG_DIR / f"topic_transcripts_{timestamp}.log"
    latest_log = LOG_DIR / LATEST_LOG_NAME

    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    root.handlers.clear()

    detailed = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(message)s",
        datefmt="%H:%M:%S",
    )
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(detailed)
    root.addHandler(fh)

    fh_latest = logging.FileHandler(latest_log, mode="w", encoding="utf-8")
    fh_latest.setLevel(logging.DEBUG)
    fh_latest.setFormatter(detailed)
    root.addHandler(fh_latest)

    sh = logging.StreamHandler(sys.stdout)
    sh.setLevel(logging.DEBUG if verbose else logging.INFO)
    sh.setFormatter(detailed)
    root.addHandler(sh)

    logging.info("Log file: %s", log_file)
    logging.info("Latest log: %s", latest_log)
    return log_file


def _slug(text: str, max_len: int = 80) -> str:
    slug = re.sub(r"[^\w\s-]", "", (text or "").lower())
    slug = re.sub(r"[-\s]+", "-", slug).strip("-")
    return (slug or "content")[:max_len]


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _resolve_ytdlp() -> list[str]:
    """Return argv prefix to invoke yt-dlp (PATH, venv Scripts, or python -m)."""
    for name in ("yt-dlp", "youtube-dl"):
        found = shutil.which(name)
        if found:
            return [found]
    venv_exe = PROJECT_ROOT / "venv" / "Scripts" / "yt-dlp.exe"
    if venv_exe.is_file():
        return [str(venv_exe)]
    try:
        import yt_dlp  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(
            "yt-dlp not found (PATH, venv/Scripts, or python -m yt_dlp)"
        ) from exc
    return [sys.executable, "-m", "yt_dlp"]


def download_ytdlp_audio(url: str, dest_dir: Path, content_id: int) -> Path:
    """Download best audio with yt-dlp into dest_dir; return media path."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    existing = [
        p
        for p in dest_dir.glob(f"{content_id}.*")
        if p.is_file() and p.suffix.lower() not in {".part", ".ytdl", ".temp"}
        and p.stat().st_size > 0
    ]
    if existing:
        return max(existing, key=lambda p: p.stat().st_mtime)

    # Prefer container as downloaded (no -x). Odysee/LBRY "ExtractAudio" to m4a
    # has produced corrupt AAC that ffmpeg cannot fully decode.
    out_tmpl = str(dest_dir / f"{content_id}.%(ext)s")
    ytdlp = _resolve_ytdlp()
    cmd = [
        *ytdlp,
        "-f",
        "bestaudio/best",
        "-o",
        out_tmpl,
        "--no-playlist",
        "--no-mtime",
        url,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "").strip()[:800]
        raise RuntimeError(f"yt-dlp failed: {err}")

    matches = list(dest_dir.glob(f"{content_id}.*"))
    matches = [p for p in matches if p.is_file() and p.suffix.lower() != ".part"]
    if not matches:
        raise RuntimeError(f"yt-dlp produced no file for content {content_id}")
    return max(matches, key=lambda p: p.stat().st_mtime)


def build_obsidian_markdown(
    *,
    title: str,
    source_url: str,
    body: str,
    language_code: str,
    content_id: int,
    topic_id: int,
    method: str,
) -> str:
    processed_date = _now_iso()
    front = (
        "---\n"
        f"title: \"{title.replace(chr(34), chr(39))}\"\n"
        f"source_url: \"{source_url or ''}\"\n"
        f"source_type: sophia\n"
        f"sophia_content_id: {int(content_id)}\n"
        f"sophia_topic_id: {int(topic_id)}\n"
        f"transcript_method: {method}\n"
        f"language_code: {language_code}\n"
        f"processed_date: {processed_date}\n"
        "tags:\n"
        "  - transcript\n"
        "  - sophia\n"
        "  - topic\n"
        "---\n\n"
    )
    return front + (body or "").strip() + "\n"


def write_local_note(
    *,
    vault_resolved: Path,
    output_folder: str,
    title: str,
    content_id: int,
    markdown: str,
) -> Path:
    out_dir = vault_resolved / "10_Sources" / output_folder
    out_dir.mkdir(parents=True, exist_ok=True)
    filename = f"sophia-{content_id}-{_slug(title)}.md"
    path = out_dir / filename
    path.write_text(markdown, encoding="utf-8")
    return path


def process_item(
    *,
    client: SophiaTranscriptIngestClient,
    conn,
    item: dict[str, Any],
    topic_id: int,
    dry_run: bool,
    force: bool,
    keep_media: bool,
    whisper_provider: str,
    chunk_long_audio: bool,
    text_processor: Optional[TextProcessor],
    vault_resolved: Optional[Path],
    output_folder: str,
    log: logging.Logger,
) -> str:
    content_id = int(item["id"])
    title = item.get("original_title") or f"content-{content_id}"
    media_type = item.get("media_type")
    source_url = item.get("url") or ""
    file_key = item.get("file_key") or ""
    has_transcript = bool(item.get("has_transcript"))
    is_youtube = bool(item.get("is_youtube"))
    youtube_id = (item.get("youtube_video_id") or "").strip() or (
        extract_youtube_video_id(source_url) or ""
    )

    upsert_discovered(
        conn,
        content_id=content_id,
        topic_id=topic_id,
        title=title,
        media_type=media_type,
        source_url=source_url,
        file_key=file_key or None,
    )

    local_status = get_status(conn, content_id)
    if has_transcript and not force:
        detail_meta: dict[str, Any] = {}
        try:
            detail = client.get_item(content_id)
            tr = detail.get("transcript") or {}
            detail_meta = {
                "text_hash": tr.get("text_hash"),
                "server_created_at": tr.get("created_at"),
                "server_updated_at": tr.get("updated_at"),
            }
        except SophiaTranscriptIngestError as exc:
            log.debug("Detail fetch for skip meta failed: %s", exc)

        mark_skipped(
            conn,
            content_id=content_id,
            topic_id=topic_id,
            reason="remote_has_transcript",
            title=title,
            media_type=media_type,
            source_url=source_url,
            file_key=file_key or None,
            **detail_meta,
        )
        log.info("[%s] skip — already has transcript remotely", content_id)
        return "skipped"

    if local_status == "done" and not force:
        mark_skipped(
            conn,
            content_id=content_id,
            topic_id=topic_id,
            reason="local_done",
            title=title,
            media_type=media_type,
            source_url=source_url,
            file_key=file_key or None,
        )
        log.info("[%s] skip — local status done (use --force to redo)", content_id)
        return "skipped"

    local_hit = find_local_transcript(
        project_root=PROJECT_ROOT,
        youtube_video_id=youtube_id or None,
        source_url=source_url or None,
    )

    if dry_run:
        if local_hit:
            log.info(
                "[%s] dry-run would REUSE LOCAL (%s): %s | %s",
                content_id,
                local_hit.match_via,
                title,
                Path(local_hit.output_path).name,
            )
            return "dry_run_local"
        log.info(
            "[%s] dry-run would GENERATE: %s | yt=%s file=%s",
            content_id,
            title,
            is_youtube or bool(youtube_id),
            bool(file_key),
        )
        return "dry_run"

    method = ""
    plain = ""
    language = "es"
    source_subtitles = ""
    subtitle_format = "SRT"
    media_cache_path: Optional[Path] = None
    existing_obsidian_md = ""
    reuse_output_path: Optional[str] = None

    t0 = time.perf_counter()
    try:
        # 0) Local vault / SQLite transcript (Own_Transcripts)
        if local_hit:
            method = "local_vault"
            plain = local_hit.plain_text
            language = local_hit.language_code or "es"
            existing_obsidian_md = local_hit.obsidian_markdown or ""
            reuse_output_path = local_hit.output_path
            log.info(
                "[%s] local reuse OK via %s (%s chars): %s",
                content_id,
                local_hit.match_via,
                len(plain),
                Path(local_hit.output_path).name,
            )

        # 1) YouTube captions
        if not plain and (
            is_youtube or youtube_id or "youtube.com" in source_url or "youtu.be" in source_url
        ):
            cap = fetch_youtube_captions(youtube_id or source_url, languages=["es", "en"])
            if cap and cap.get("plain_text"):
                method = "youtube_captions"
                plain = cap["plain_text"]
                language = cap.get("language_code") or "es"
                source_subtitles = cap.get("source_subtitles") or ""
                subtitle_format = cap.get("format") or "SRT"
                log.info("[%s] captions OK (%s)", content_id, language)

        # 2) S3 file → Whisper
        if not plain and file_key:
            method = "whisper_s3"
            ext = Path(file_key).suffix or ".bin"
            media_path = MEDIA_CACHE_DIR / str(content_id) / f"source{ext}"
            media_cache_path = download_s3_object(file_key, media_path)
            audio_path = AUDIO_CACHE_DIR / f"{content_id}.mp3"
            if media_type == "AUDIO" and media_cache_path.suffix.lower() in {
                ".mp3",
                ".m4a",
                ".wav",
                ".ogg",
                ".flac",
                ".webm",
            }:
                # Still normalize for Whisper size limits
                extract_audio(media_cache_path, audio_path)
            else:
                extract_audio(media_cache_path, audio_path)
            plain = transcribe_audio(
                audio_path,
                provider=whisper_provider,
                cache_dir=WHISPER_CACHE_DIR,
                chunk_long_audio=chunk_long_audio,
            )
            language = "es"
            log.info("[%s] whisper_s3 OK (~%s chars)", content_id, len(plain))

        # 3) yt-dlp audio → Whisper
        if not plain and source_url:
            method = "whisper_ytdlp"
            ytdlp_dir = MEDIA_CACHE_DIR / str(content_id) / "ytdlp"
            media_cache_path = download_ytdlp_audio(source_url, ytdlp_dir, content_id)
            audio_path = AUDIO_CACHE_DIR / f"{content_id}.mp3"
            extract_audio(media_cache_path, audio_path)
            plain = transcribe_audio(
                audio_path,
                provider=whisper_provider,
                cache_dir=WHISPER_CACHE_DIR,
                chunk_long_audio=chunk_long_audio,
            )
            language = "es"
            log.info("[%s] whisper_ytdlp OK (~%s chars)", content_id, len(plain))

        if not plain.strip():
            raise RuntimeError(
                "No transcript source available (no captions, no file_key, no usable URL)"
            )

        if method == "local_vault":
            # Vault note is already cleaned; avoid double spaCy + keep original markdown when present
            processed = plain
            obsidian_md = existing_obsidian_md or build_obsidian_markdown(
                title=title,
                source_url=source_url,
                body=processed,
                language_code=language,
                content_id=content_id,
                topic_id=topic_id,
                method=method,
            )
        else:
            processed = plain
            if text_processor is not None:
                try:
                    processed = text_processor.process(plain, language_code=language) or plain
                except Exception as exc:
                    log.warning("[%s] text_processor failed, using raw: %s", content_id, exc)
                    processed = plain

            obsidian_md = build_obsidian_markdown(
                title=title,
                source_url=source_url,
                body=processed,
                language_code=language,
                content_id=content_id,
                topic_id=topic_id,
                method=method,
            )

        payload: dict[str, Any] = {
            "parsed_plain": plain,
            "processed_plain": processed,
            "obsidian_markdown": obsidian_md,
            "language": language,
        }
        if source_subtitles.strip():
            payload["source_subtitles"] = source_subtitles
            payload["format"] = subtitle_format

        put_result = client.put_transcript(content_id, payload)
        transcribed_at = _now_iso()
        tr = put_result.get("transcript") or {}

        output_path = reuse_output_path
        if output_path is None and vault_resolved is not None:
            note_path = write_local_note(
                vault_resolved=vault_resolved,
                output_folder=output_folder,
                title=title,
                content_id=content_id,
                markdown=obsidian_md,
            )
            output_path = str(note_path)

        mark_done(
            conn,
            content_id=content_id,
            topic_id=topic_id,
            title=title,
            media_type=media_type,
            source_url=source_url,
            file_key=file_key or None,
            method=method,
            transcribed_at=transcribed_at,
            uploaded_at=transcribed_at,
            server_created_at=tr.get("created_at"),
            server_updated_at=tr.get("updated_at"),
            text_hash=tr.get("text_hash"),
            language_code=language,
            output_path=output_path,
            media_cache_path=str(media_cache_path) if media_cache_path else None,
        )

        if not keep_media and media_cache_path is not None:
            try:
                parent = MEDIA_CACHE_DIR / str(content_id)
                if parent.is_dir():
                    shutil.rmtree(parent, ignore_errors=True)
                audio_file = AUDIO_CACHE_DIR / f"{content_id}.mp3"
                if audio_file.is_file():
                    audio_file.unlink(missing_ok=True)
            except Exception as exc:
                log.debug("Cleanup media failed: %s", exc)

        elapsed = time.perf_counter() - t0
        log.info(
            "[%s] DONE via %s in %.1fs (created=%s hash=%s)",
            content_id,
            method,
            elapsed,
            put_result.get("created"),
            (tr.get("text_hash") or "")[:12],
        )
        return "done"

    except Exception as exc:
        log.exception("[%s] FAILED: %s", content_id, exc)
        mark_failed(
            conn,
            content_id=content_id,
            topic_id=topic_id,
            error=str(exc),
            title=title,
            media_type=media_type,
            source_url=source_url,
            file_key=file_key or None,
        )
        return "failed"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Transcribir VIDEO/AUDIO de un tema Sophia → transcript-ingest + SQLite local."
    )
    parser.add_argument("--topic-id", type=int, required=True)
    parser.add_argument("--content-id", type=int, default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true", help="Re-procesar aunque remoto/local ya tenga transcript")
    parser.add_argument(
        "--include-completed",
        action="store_true",
        help="Traer también ítems con transcript (para reconcile / --force)",
    )
    parser.add_argument("--export-only", action="store_true", help="Solo exportar cobertura local + remoto")
    parser.add_argument("--keep-media", action="store_true", help="Conservar descargas S3/yt-dlp en cache")
    parser.add_argument("--no-keep-media", action="store_true", help="Borrar media tras procesar (default)")
    parser.add_argument(
        "--skip-obsidian",
        action="store_true",
        help="No escribir nota local en el vault",
    )
    parser.add_argument(
        "--output-folder",
        default=os.getenv("YOUTUBE_OWN_TRANSCRIPTS_FOLDER", DEFAULT_OUTPUT_FOLDER),
    )
    parser.add_argument("--whisper-provider", default=None)
    parser.add_argument(
        "--chunk-long-audio",
        action=argparse.BooleanOptionalAction,
        default=None,
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    setup_logging(args.verbose)
    log = logging.getLogger(__name__)
    topic_id = int(args.topic_id)
    keep_media = bool(args.keep_media) and not bool(args.no_keep_media)

    try:
        client = SophiaTranscriptIngestClient()
    except ValueError as exc:
        log.error("%s", exc)
        return 1

    try:
        resolve_bucket()
    except ValueError as exc:
        log.warning("%s — S3 downloads will fail if a file_key is required", exc)

    vault_path = (os.getenv("OBSIDIAN_VAULT_PATH") or "../Cerebro-Vincent").strip()
    vault_resolved = (PROJECT_ROOT / vault_path).resolve()
    if not args.skip_obsidian and not vault_resolved.is_dir():
        log.warning("Obsidian vault not found (%s); continuing without local notes", vault_resolved)
        vault_resolved = None
    if args.skip_obsidian:
        vault_resolved = None

    output_folder = (args.output_folder or DEFAULT_OUTPUT_FOLDER).strip()
    export_dir = (
        vault_resolved / "10_Sources" / output_folder
        if vault_resolved
        else PROJECT_ROOT / "cache" / "sophia_media" / "reports"
    )
    export_dir.mkdir(parents=True, exist_ok=True)

    conn = open_sophia_state(PROJECT_ROOT)

    # Remote inventory
    try:
        all_items = client.list_queue_all(
            topic_id=topic_id,
            include_completed=True,
            content_id=args.content_id,
        )
    except SophiaTranscriptIngestError as exc:
        log.error("Failed to list queue: %s", exc)
        return 1

    pending_remote = [i for i in all_items if not i.get("has_transcript")]
    completed_remote = [i for i in all_items if i.get("has_transcript")]
    log.info(
        "Topic %s: remote total=%s pending=%s completed=%s",
        topic_id,
        len(all_items),
        len(pending_remote),
        len(completed_remote),
    )

    for item in all_items:
        upsert_discovered(
            conn,
            content_id=int(item["id"]),
            topic_id=topic_id,
            title=item.get("original_title"),
            media_type=item.get("media_type"),
            source_url=item.get("url") or "",
            file_key=item.get("file_key") or None,
        )
        if item.get("has_transcript") and get_status(conn, int(item["id"])) != "done":
            mark_skipped(
                conn,
                content_id=int(item["id"]),
                topic_id=topic_id,
                reason="remote_has_transcript",
                title=item.get("original_title"),
                media_type=item.get("media_type"),
                source_url=item.get("url") or "",
                file_key=item.get("file_key") or None,
            )

    json_path, md_path = sync_topic_coverage_exports(
        conn,
        topic_id=topic_id,
        vault_output_dir=export_dir,
        remote_pending=len(pending_remote),
        remote_completed=len(completed_remote),
        remote_total=len(all_items),
        project_root=PROJECT_ROOT,
    )
    log.info("Coverage export: %s | %s", json_path, md_path)

    if args.export_only:
        return 0

    work_items = all_items if (args.force or args.include_completed) else pending_remote
    if args.content_id is not None:
        work_items = [i for i in work_items if int(i["id"]) == int(args.content_id)]
    if args.limit is not None:
        work_items = work_items[: max(0, int(args.limit))]

    whisper_provider = resolve_whisper_provider(args.whisper_provider)
    chunk_long_audio = resolve_chunk_long_audio(args.chunk_long_audio)
    if whisper_provider == "openai" and not (os.getenv("OPENAI_API_KEY") or "").strip():
        log.warning(
            "OPENAI_API_KEY missing; Whisper OpenAI will fail — captions-only items can still succeed"
        )

    text_processor: Optional[TextProcessor] = None
    try:
        text_processor = TextProcessor()
    except Exception as exc:
        log.warning("TextProcessor unavailable (%s); uploading raw plain text", exc)

    stats = {
        "done": 0,
        "skipped": 0,
        "failed": 0,
        "dry_run": 0,
        "dry_run_local": 0,
    }
    for item in work_items:
        result = process_item(
            client=client,
            conn=conn,
            item=item,
            topic_id=topic_id,
            dry_run=args.dry_run,
            force=args.force,
            keep_media=keep_media,
            whisper_provider=whisper_provider,
            chunk_long_audio=chunk_long_audio,
            text_processor=text_processor,
            vault_resolved=vault_resolved,
            output_folder=output_folder,
            log=log,
        )
        stats[result] = stats.get(result, 0) + 1

    # Refresh remote counts after run
    try:
        refreshed = client.list_queue_all(topic_id=topic_id, include_completed=True)
        pending_remote = [i for i in refreshed if not i.get("has_transcript")]
        completed_remote = [i for i in refreshed if i.get("has_transcript")]
        all_items = refreshed
    except SophiaTranscriptIngestError as exc:
        log.warning("Post-run reconcile failed: %s", exc)

    sync_topic_coverage_exports(
        conn,
        topic_id=topic_id,
        vault_output_dir=export_dir,
        remote_pending=len(pending_remote),
        remote_completed=len(completed_remote),
        remote_total=len(all_items),
        project_root=PROJECT_ROOT,
    )

    log.info(
        "Finished topic %s | %s | remote pending=%s completed=%s",
        topic_id,
        stats,
        len(pending_remote),
        len(completed_remote),
    )
    conn.close()
    return 1 if stats.get("failed") else 0


if __name__ == "__main__":
    raise SystemExit(main())
