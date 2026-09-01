#!/usr/bin/env python3
"""
Transcribe local video files with Whisper and save to Obsidian.

Scans a folder of video files (.mp4, .mkv, ...), extracts audio with ffmpeg,
transcribes with OpenAI Whisper API or local faster-whisper, and writes notes
to Cerebro-Vincent/10_Sources/Own_Transcripts/.

Examples (from Vincent-Code root):
  python scripts/process_local_videos.py --dry-run
  python scripts/process_local_videos.py --limit 1
  python scripts/process_local_videos.py

Requires in .env:
  OBSIDIAN_VAULT_PATH=../Cerebro-Vincent
  OPENAI_API_KEY (when WHISPER_PROVIDER=openai)

Vídeos: coloca carpetas/archivos bajo Vincent-Code (raíz del repo) con nombre *_final.mp4
Override opcional: --input-dir E:/otra/ruta
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Optional

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv(PROJECT_ROOT / ".env", override=True)

from src.audio_extract import extract_audio, get_media_duration_seconds
from src.markdown_writer import MarkdownWriter
from src.text_processor import TextProcessor
from src.video_transcript_state import (
    get_status,
    local_video_id,
    mark_done,
    mark_failed,
    mark_skipped,
    open_state,
    sync_local_status_exports,
    upsert_local_discovered,
    repair_local_skipped_with_output,
)
from src.whisper_client import (
    resolve_chunk_long_audio,
    resolve_whisper_provider,
    transcribe_audio,
)

DEFAULT_OUTPUT_FOLDER = "Own_Transcripts"
DEFAULT_EXTENSIONS = ("mp4", "mkv", "mov", "avi", "webm", "m4v", "wmv", "flv")
DEFAULT_FILENAME_SUFFIX = "_final"
# Raíz Vincent-Code; escaneo recursivo de subcarpetas con archivos *_final.*
DEFAULT_INPUT_DIR = PROJECT_ROOT
LOG_DIR = PROJECT_ROOT / "logs"
LATEST_LOG_NAME = "local_videos_transcripts_latest.log"
AUDIO_CACHE_DIR = PROJECT_ROOT / "cache" / "local_videos" / "audio"
WHISPER_CACHE_DIR = PROJECT_ROOT / "cache" / "local_videos" / "whisper"


def resolve_input_dir(explicit: Optional[str] = None) -> Path:
    """Default: raíz Vincent-Code. Override con --input-dir o LOCAL_VIDEOS_INPUT_DIR."""
    raw = (explicit or os.getenv("LOCAL_VIDEOS_INPUT_DIR") or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return DEFAULT_INPUT_DIR.resolve()


def setup_logging(verbose: bool) -> Path:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = LOG_DIR / f"local_videos_transcripts_{timestamp}.log"
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

    log = logging.getLogger(__name__)
    log.info("=" * 60)
    log.info("Pipeline local — Whisper + ffmpeg")
    log.info("Log detallado: %s", log_file)
    log.info("Log en vivo (última ejecución): %s", latest_log)
    log.info("=" * 60)
    return log_file


def parse_extensions(raw: Optional[str]) -> tuple[str, ...]:
    if not raw or not raw.strip():
        return DEFAULT_EXTENSIONS
    parts = []
    for part in raw.split(","):
        ext = part.strip().lower().lstrip(".")
        if ext:
            parts.append(ext)
    return tuple(parts) or DEFAULT_EXTENSIONS


def title_from_path(path: Path, *, name_suffix: str = DEFAULT_FILENAME_SUFFIX) -> str:
    stem = path.stem
    if name_suffix and stem.lower().endswith(name_suffix.lower()):
        stem = stem[: -len(name_suffix)]
    stem = stem.replace("_", " ").replace("-", " ")
    cleaned = " ".join(stem.split())
    return cleaned or path.name


def published_at_from_path(path: Path) -> str:
    mtime = path.stat().st_mtime
    return datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()


def matches_filename_suffix(path: Path, name_suffix: Optional[str]) -> bool:
    """When name_suffix is set, only stems ending with it match (e.g. foo_final.mp4)."""
    if not name_suffix:
        return True
    return path.stem.lower().endswith(name_suffix.lower())


def discover_videos(
    input_dir: Path,
    *,
    extensions: tuple[str, ...],
    recursive: bool,
    name_suffix: Optional[str] = DEFAULT_FILENAME_SUFFIX,
) -> List[Path]:
    files: list[Path] = []
    iterator: Iterable[Path]
    if recursive:
        iterator = input_dir.rglob("*")
    else:
        iterator = input_dir.glob("*")

    for path in iterator:
        if not path.is_file():
            continue
        if path.suffix.lower().lstrip(".") not in extensions:
            continue
        if not matches_filename_suffix(path, name_suffix):
            continue
        files.append(path.resolve())

    files.sort(key=lambda p: p.as_posix().lower())
    return files


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
    safe_id = video_id.replace(":", "_")
    path = output_dir / f"{safe_id}.txt"
    path.write_text(transcript, encoding="utf-8")


def process_local_video(
    *,
    video_path: Path,
    markdown_writer: MarkdownWriter,
    text_processor: TextProcessor,
    conn,
    whisper_provider: str,
    dry_run: bool,
    skip_existing: bool,
    retry_failed: bool,
    name_suffix: str = "",
    chunk_long_audio: bool = False,
) -> str:
    log = logging.getLogger(__name__)
    video_id = local_video_id(video_path)
    title = title_from_path(video_path, name_suffix=name_suffix)
    source_url = video_path.resolve().as_uri()
    source_path = str(video_path.resolve())

    reason = skip_reason(
        conn,
        video_id=video_id,
        source_url=source_url,
        markdown_writer=markdown_writer,
        skip_existing=skip_existing,
        retry_failed=retry_failed,
    )
    if reason:
        if not dry_run and get_status(conn, video_id) != "done":
            mark_skipped(
                conn,
                video_id=video_id,
                title=title,
                source_url=source_url,
                reason=reason,
            )
        log.info("  [SKIP] %s — %s", title, reason)
        return "skipped"

    if dry_run:
        duration = get_media_duration_seconds(video_path)
        mins = f"{duration / 60:.1f} min" if duration else "duración desconocida"
        log.info("  [dry-run] se procesaría (%s, %s): %s", whisper_provider, mins, video_path.name)
        return "dry_run"

    log.info("  extrayendo audio: %s", video_path.name)
    audio_path = AUDIO_CACHE_DIR / f"{video_id.replace(':', '_')}.mp3"
    t0 = time.perf_counter()

    try:
        extract_audio(video_path, audio_path)
    except Exception as exc:
        mark_failed(
            conn,
            video_id=video_id,
            title=title,
            source_url=source_url,
            error=f"ffmpeg_extract_failed: {exc}",
        )
        log.warning("  [FAIL] extracción de audio: %s — %s", title, exc)
        return "failed"

    extract_elapsed = time.perf_counter() - t0
    log.debug("  audio extraído en %.1fs -> %s", extract_elapsed, audio_path.name)

    try:
        log.info("  transcribiendo (%s)...", whisper_provider)
        t1 = time.perf_counter()
        transcript = transcribe_audio(
            audio_path,
            provider=whisper_provider,
            cache_dir=WHISPER_CACHE_DIR,
            chunk_long_audio=chunk_long_audio,
        ).strip()
        transcribe_elapsed = time.perf_counter() - t1
    except Exception as exc:
        mark_failed(
            conn,
            video_id=video_id,
            title=title,
            source_url=source_url,
            error=f"whisper_failed: {exc}",
        )
        log.warning("  [FAIL] transcripción: %s — %s", title, exc)
        return "failed"

    if not transcript:
        mark_failed(
            conn,
            video_id=video_id,
            title=title,
            source_url=source_url,
            error="empty_transcript",
        )
        log.warning("  [FAIL] transcript vacío: %s", title)
        return "failed"

    language_code = "es"
    word_count = len(transcript.split())
    log.debug(
        "  whisper OK (%.1fs): ~%s palabras",
        transcribe_elapsed,
        word_count,
    )

    save_raw_transcript(video_id, transcript)
    processed_text = text_processor.process(transcript, language_code=language_code)
    text_processor.save_processed_text(processed_text, video_id.replace(":", "_"))

    output_path = markdown_writer.save_transcript(
        title=title,
        content=processed_text,
        source_url=source_url,
        source_type="Own Video",
        upload_date=published_at_from_path(video_path),
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
    total_elapsed = time.perf_counter() - t0
    log.info(
        "  [OK] guardado (%.1f min, ~%s palabras): %s",
        total_elapsed / 60,
        word_count,
        Path(output_path).name,
    )
    return "done"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Transcribir vídeos locales con Whisper → Obsidian."
    )
    parser.add_argument(
        "--input-dir",
        default=None,
        help=f"Carpeta raíz a escanear (default: {DEFAULT_INPUT_DIR})",
    )
    parser.add_argument(
        "--output-folder",
        default=os.getenv("YOUTUBE_OWN_TRANSCRIPTS_FOLDER", DEFAULT_OUTPUT_FOLDER),
    )
    parser.add_argument(
        "--extensions",
        default=os.getenv("LOCAL_VIDEOS_EXTENSIONS", ",".join(DEFAULT_EXTENSIONS)),
        help="Extensiones separadas por coma (default: mp4,mkv,mov,...)",
    )
    parser.add_argument(
        "--recursive",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Buscar vídeos en subcarpetas (default: sí)",
    )
    parser.add_argument(
        "--filename-suffix",
        default=os.getenv("LOCAL_VIDEOS_FILENAME_SUFFIX", DEFAULT_FILENAME_SUFFIX),
        help="Solo procesar archivos cuyo nombre termine así antes de la extensión (default: _final)",
    )
    parser.add_argument(
        "--all-files",
        action="store_true",
        help="Procesar todos los vídeos, sin filtrar por sufijo _final",
    )
    parser.add_argument(
        "--chunk-long-audio",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Trocea audios largos por duración en OpenAI (WHISPER_CHUNK_LONG_AUDIO)",
    )
    parser.add_argument(
        "--whisper-provider",
        default=None,
        help="openai | local | auto (default: WHISPER_PROVIDER env o auto)",
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument("--no-skip-existing", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    setup_logging(args.verbose)
    log = logging.getLogger(__name__)

    input_dir = resolve_input_dir(args.input_dir)
    if not input_dir.is_dir():
        log.error("Carpeta de vídeos no encontrada: %s", input_dir)
        return 1

    vault_path = (os.getenv("OBSIDIAN_VAULT_PATH") or "../Cerebro-Vincent").strip()
    vault_resolved = (PROJECT_ROOT / vault_path).resolve()
    if not vault_resolved.is_dir():
        log.error("Obsidian vault not found: %s", vault_resolved)
        return 1

    whisper_provider = resolve_whisper_provider(args.whisper_provider)
    chunk_long_audio = resolve_chunk_long_audio(args.chunk_long_audio)
    if whisper_provider == "openai" and not (os.getenv("OPENAI_API_KEY") or "").strip():
        log.error(
            "WHISPER_PROVIDER=openai requiere OPENAI_API_KEY en .env "
            "(o usa --whisper-provider local)"
        )
        return 1

    extensions = parse_extensions(args.extensions)
    name_suffix = None if args.all_files else (args.filename_suffix or "").strip() or None
    skip_existing = not args.no_skip_existing
    output_folder = args.output_folder.strip() or DEFAULT_OUTPUT_FOLDER
    vault_output_dir = vault_resolved / "10_Sources" / output_folder
    state_db = PROJECT_ROOT / "cache" / "video_transcripts" / "state.sqlite3"

    log.info("Entrada: %s", input_dir)
    log.info("Vault: %s", vault_resolved)
    log.info("Salida: 10_Sources/%s", output_folder)
    log.info("Whisper: %s", whisper_provider)
    if whisper_provider == "openai":
        log.info(
            "Troceo por duración: %s",
            "sí" if chunk_long_audio else "no (solo si >25 MB)",
        )
    log.info("Extensiones: %s", ", ".join(extensions))
    if name_suffix:
        log.info("Filtro de nombre: *%s.*", name_suffix)
    else:
        log.info("Filtro de nombre: (todos los archivos)")
    log.info("State DB: %s", state_db)
    if args.limit:
        log.info("Límite: %s vídeo(s)", args.limit)
    if args.dry_run:
        log.info("Modo: dry-run")
    if args.retry_failed:
        log.info("Modo: reintentar fallidos")

    markdown_writer = MarkdownWriter(str(vault_resolved), folder_name=output_folder)
    text_processor = TextProcessor()
    conn = open_state(str(PROJECT_ROOT))

    log.info("")
    log.info("Buscando vídeos...")
    videos = discover_videos(
        input_dir,
        extensions=extensions,
        recursive=args.recursive,
        name_suffix=name_suffix,
    )
    if args.limit:
        videos = videos[: args.limit]

    if not videos:
        hint = (
            f" (¿renombraste los vídeos a *{name_suffix}.* antes de la extensión?)"
            if name_suffix
            else ""
        )
        log.error("No se encontraron vídeos en %s%s", input_dir, hint)
        return 1

    log.info("Encontrados: %s archivo(s)", len(videos))

    for video_path in videos:
        video_id = local_video_id(video_path)
        upsert_local_discovered(
            conn,
            video_id=video_id,
            title=title_from_path(video_path, name_suffix=name_suffix or ""),
            source_url=video_path.resolve().as_uri(),
            source_path=str(video_path.resolve()),
            published_at=published_at_from_path(video_path),
        )

    to_process = sum(
        1
        for video_path in videos
        if should_process_video(
            conn,
            video_id=local_video_id(video_path),
            source_url=video_path.resolve().as_uri(),
            markdown_writer=markdown_writer,
            skip_existing=skip_existing,
            retry_failed=args.retry_failed,
        )
    )
    log.info("Plan: %s a procesar, %s omitidos", to_process, len(videos) - to_process)
    log.info("")

    counts = {"done": 0, "failed": 0, "skipped": 0, "dry_run": 0}
    run_started = time.perf_counter()

    for idx, video_path in enumerate(videos, 1):
        video_id = local_video_id(video_path)
        title = title_from_path(video_path, name_suffix=name_suffix or "")
        log.info("[%s/%s] %s", idx, len(videos), title)

        outcome = process_local_video(
            video_path=video_path,
            markdown_writer=markdown_writer,
            text_processor=text_processor,
            conn=conn,
            whisper_provider=whisper_provider,
            dry_run=args.dry_run,
            skip_existing=skip_existing,
            retry_failed=args.retry_failed,
            name_suffix=name_suffix or "",
            chunk_long_audio=chunk_long_audio,
        )
        counts[outcome] = counts.get(outcome, 0) + 1

        processed_so_far = counts.get("done", 0) + counts.get("failed", 0)
        if processed_so_far and processed_so_far % 5 == 0 and outcome in {"done", "failed"}:
            log.info(
                "  --- progreso: %s | OK %s | FAIL %s ---",
                processed_so_far,
                counts.get("done", 0),
                counts.get("failed", 0),
            )

    if not args.dry_run:
        repaired = repair_local_skipped_with_output(conn)
        if repaired:
            log.info("Estado reparado: %s fila(s) local(es) restauradas a done", repaired)
        paths = sync_local_status_exports(
            conn,
            project_root=PROJECT_ROOT,
            vault_output_dir=vault_output_dir,
            input_dir=str(input_dir),
        )
        log.info("Estado local regenerado desde SQLite:")
        log.info("  JSON: %s", paths["json"])
        log.info("  Resumen: %s", paths["markdown"])

    elapsed = time.perf_counter() - run_started
    log.info("")
    log.info("=" * 60)
    log.info(
        "Finalizado en %.1f min — OK %s | FAIL %s | SKIP %s",
        elapsed / 60,
        counts.get("done", 0),
        counts.get("failed", 0),
        counts.get("skipped", 0),
    )
    log.info("=" * 60)

    if counts.get("done", 0) == 0 and counts.get("dry_run", 0) == 0 and counts.get("skipped", 0) == 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
