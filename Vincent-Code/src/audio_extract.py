"""Extract audio from video files with ffmpeg/ffprobe."""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_SAMPLE_RATE = 16000
DEFAULT_AUDIO_BITRATE = "64k"
PODCAST_SAMPLE_RATE = 44100
PODCAST_AUDIO_BITRATE = "192k"


def find_ffmpeg() -> str:
    path = shutil.which("ffmpeg")
    if not path:
        raise RuntimeError(
            "ffmpeg no está en PATH. Instálalo (ej. winget install Gyan.FFmpeg) "
            "y vuelve a abrir la terminal."
        )
    return path


def find_ffprobe() -> str:
    path = shutil.which("ffprobe")
    if not path:
        raise RuntimeError("ffprobe no está en PATH (viene con ffmpeg).")
    return path


def get_media_duration_seconds(media_path: str | Path) -> Optional[float]:
    """Return duration in seconds, or None if unavailable."""
    ffprobe = find_ffprobe()
    path = str(Path(media_path).resolve())
    try:
        result = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                path,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        value = (result.stdout or "").strip()
        return float(value) if value else None
    except Exception as exc:
        logger.debug("ffprobe duration failed for %s: %s", path, exc)
        return None


def extract_audio(
    media_path: str | Path,
    output_path: str | Path,
    *,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    bitrate: str = DEFAULT_AUDIO_BITRATE,
) -> Path:
    """Extract mono MP3 audio suitable for Whisper."""
    ffmpeg = find_ffmpeg()
    src = str(Path(media_path).resolve())
    dst = Path(output_path)
    dst.parent.mkdir(parents=True, exist_ok=True)

    # err_detect/discardcorrupt: tolerate damaged AAC from some Odysee remuxes
    result = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-err_detect",
            "ignore_err",
            "-fflags",
            "+discardcorrupt",
            "-i",
            src,
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(sample_rate),
            "-c:a",
            "libmp3lame",
            "-b:a",
            bitrate,
            str(dst),
        ],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    if not dst.is_file() or dst.stat().st_size <= 0:
        err = (result.stderr or "").strip()[-800:]
        raise RuntimeError(f"ffmpeg extract_audio failed (exit {result.returncode}): {err}")
    if result.returncode != 0:
        logger.warning(
            "ffmpeg extract_audio exited %s but wrote %s bytes; continuing",
            result.returncode,
            dst.stat().st_size,
        )
    return dst


def extract_audio_podcast(
    media_path: str | Path,
    output_path: str | Path,
    *,
    sample_rate: int = PODCAST_SAMPLE_RATE,
    bitrate: str = PODCAST_AUDIO_BITRATE,
) -> Path:
    """Extract stereo MP3 audio suitable for podcast publishing."""
    ffmpeg = find_ffmpeg()
    src = str(Path(media_path).resolve())
    dst = Path(output_path)
    dst.parent.mkdir(parents=True, exist_ok=True)

    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-i",
            src,
            "-vn",
            "-codec:a",
            "libmp3lame",
            "-b:a",
            bitrate,
            "-ar",
            str(sample_rate),
            str(dst),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    return dst


def split_audio(
    audio_path: str | Path,
    output_dir: str | Path,
    *,
    chunk_seconds: int,
) -> list[Path]:
    """Split audio into fixed-length segments (for OpenAI Whisper size limit)."""
    ffmpeg = find_ffmpeg()
    src = Path(audio_path).resolve()
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    pattern = str(out_dir / "chunk_%03d.mp3")
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-i",
            str(src),
            "-f",
            "segment",
            "-segment_time",
            str(chunk_seconds),
            "-reset_timestamps",
            "1",
            "-ac",
            "1",
            "-ar",
            str(DEFAULT_SAMPLE_RATE),
            "-b:a",
            DEFAULT_AUDIO_BITRATE,
            pattern,
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    chunks = sorted(out_dir.glob("chunk_*.mp3"))
    if not chunks:
        raise RuntimeError(f"No se generaron chunks de audio en {out_dir}")
    return chunks
