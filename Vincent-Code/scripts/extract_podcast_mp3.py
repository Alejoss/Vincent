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
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = PROJECT_ROOT.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.audio_extract import extract_audio_podcast, find_ffmpeg

DEFAULT_INPUT_DIR = REPO_ROOT / "VideosParaPodcast"
DEFAULT_OUTPUT_SUBDIR = "mp3"
STATE_FILENAME = "_estado_podcast.json"
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v", ".flv", ".mpeg", ".mpg"}


def state_path(input_dir: Path) -> Path:
    return input_dir / STATE_FILENAME


def load_state(input_dir: Path) -> dict[str, Any]:
    path = state_path(input_dir)
    if not path.is_file():
        return {"updated_at": None, "items": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logging.getLogger(__name__).warning("No se pudo leer %s: %s", path, exc)
        return {"updated_at": None, "items": {}}
    if not isinstance(data.get("items"), dict):
        data["items"] = {}
    return data


def save_state(input_dir: Path, state: dict[str, Any]) -> None:
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    path = state_path(input_dir)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def record_item(
    state: dict[str, Any],
    video: Path,
    *,
    status: str,
    mp3: Path | None = None,
    error: str | None = None,
    skipped: bool = False,
) -> None:
    key = video.name
    entry: dict[str, Any] = {
        "title": video.stem,
        "video": video.name,
        "mp3": mp3.name if mp3 else None,
        "status": status,
        "skipped": skipped,
        "processed_at": datetime.now(timezone.utc).isoformat(),
    }
    if error:
        entry["error"] = error
    state["items"][key] = entry


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

    state = load_state(input_dir)
    processed = 0
    skipped = 0
    failed = 0

    for video in videos:
        output = output_dir / f"{video.stem}.mp3"
        if should_skip(video, output, force=args.force):
            logger.info("Omitido (ya existe): %s", output.name)
            record_item(
                state,
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
            record_item(state, video, status="done", mp3=output)
            processed += 1
        except Exception as exc:
            logger.error("Error con %s: %s", video.name, exc)
            record_item(state, video, status="failed", error=str(exc))
            failed += 1

    if not args.dry_run:
        save_state(input_dir, state)
        logger.info("Estado guardado en %s", state_path(input_dir))

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
