#!/usr/bin/env python3
"""
Extract MP3 audio from videos in VideosParaPodcast/ (repo root).

Place video files (.mp4, .mkv, .mov, ...) in:
  E:/Vincent/VideosParaPodcast/

MP3 files are written to:
  E:/Vincent/VideosParaPodcast/mp3/

Examples (from Vincent-Code root):
  python scripts/extract_podcast_mp3.py
  python scripts/extract_podcast_mp3.py --dry-run
  python scripts/extract_podcast_mp3.py --force
  python scripts/extract_podcast_mp3.py --input-dir E:/otra/ruta
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = PROJECT_ROOT.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.audio_extract import extract_audio_podcast, find_ffmpeg
from src.podcast_catalog import record_item
from src.video_transcript_state import open_state, state_db_path

DEFAULT_INPUT_DIR = REPO_ROOT / "VideosParaPodcast"
DEFAULT_OUTPUT_SUBDIR = "mp3"
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v", ".flv", ".mpeg", ".mpg"}


def find_videos(input_dir: Path) -> list[Path]:
    if not input_dir.is_dir():
        return []
    videos = [
        path
        for path in sorted(input_dir.iterdir())
        if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS
    ]
    return videos


def should_skip(video: Path, output: Path, *, force: bool) -> bool:
    if force or not output.is_file():
        return False
    return output.stat().st_mtime >= video.stat().st_mtime


def setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extrae MP3 de vídeos en VideosParaPodcast/ para publicar como podcast.",
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=DEFAULT_INPUT_DIR,
        help=f"Carpeta con vídeos (default: {DEFAULT_INPUT_DIR})",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Carpeta de salida MP3 (default: <input-dir>/mp3)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Regenerar MP3 aunque ya exista uno actualizado",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Solo listar qué archivos se procesarían",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Log detallado",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    setup_logging(args.verbose)
    logger = logging.getLogger(__name__)

    input_dir = args.input_dir.expanduser().resolve()
    output_dir = (
        args.output_dir.expanduser().resolve()
        if args.output_dir
        else (input_dir / DEFAULT_OUTPUT_SUBDIR)
    )

    if not args.dry_run:
        try:
            find_ffmpeg()
        except RuntimeError as exc:
            logger.error("%s", exc)
            return 1

    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    videos = find_videos(input_dir)
    if not videos:
        logger.info("No hay vídeos en %s", input_dir)
        logger.info(
            "Coloca archivos %s en esa carpeta y vuelve a ejecutar.",
            ", ".join(sorted(VIDEO_EXTENSIONS)),
        )
        return 0

    conn = None
    if not args.dry_run:
        conn = open_state(str(PROJECT_ROOT))

    processed = 0
    skipped = 0
    failed = 0

    try:
        for video in videos:
            output = output_dir / f"{video.stem}.mp3"
            if should_skip(video, output, force=args.force):
                logger.info("Omitido (ya existe): %s", output.name)
                if conn is not None:
                    record_item(
                        conn,
                        video,
                        status="done",
                        mp3=output,
                        skipped=True,
                    )
                skipped += 1
                continue

            if args.dry_run:
                logger.info("[dry-run] %s -> %s", video.name, output.name)
                processed += 1
                continue

            logger.info("Extrayendo: %s", video.name)
            try:
                extract_audio_podcast(video, output)
                logger.info("Listo: %s", output)
                assert conn is not None
                record_item(conn, video, status="done", mp3=output)
                processed += 1
            except Exception as exc:
                logger.error("Error con %s: %s", video.name, exc)
                assert conn is not None
                record_item(conn, video, status="failed", error=str(exc))
                failed += 1
    finally:
        if conn is not None:
            conn.close()

    if not args.dry_run:
        logger.info("Estado guardado en %s (tabla podcast_episode)", state_db_path(PROJECT_ROOT))

    logger.info(
        "Resumen: %d procesados, %d omitidos, %d errores (de %d vídeos)",
        processed,
        skipped,
        failed,
        len(videos),
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
