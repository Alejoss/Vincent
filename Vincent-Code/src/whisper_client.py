"""
OpenAI Whisper API client for transcribing Slack audio attachments.

Uses the same OPENAI_API_KEY as the chat/classifier API (no separate Whisper key).

Env (used by sync_slack_inbox_to_obsidian.py):
  WHISPER_PROVIDER=openai|local|auto   (default auto)
  OPENAI_API_KEY                       (required when provider is openai)
  WHISPER_MODEL                        (default whisper-1; optional override)
  OPENAI_API_BASE                      (optional; default https://api.openai.com/v1)
  WHISPER_CHUNK_LONG_AUDIO             (1/true to chunk by duration for OpenAI)
  WHISPER_CHUNK_SECONDS                (default 600)
  LOCAL_WHISPER_MODEL                  (default small; faster-whisper)

Transcription language is fixed to Spanish (es) in code — Vincent messages are voice in Spanish.
"""

from __future__ import annotations

import logging
import mimetypes
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, Union

import requests

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "whisper-1"
DEFAULT_LANGUAGE = "es"
DEFAULT_BASE_URL = "https://api.openai.com/v1"
MAX_FILE_BYTES = 25 * 1024 * 1024  # OpenAI limit
DEFAULT_CHUNK_SECONDS = 600


def resolve_whisper_provider(explicit: Optional[str] = None) -> str:
    """Return 'openai' or 'local'."""
    raw = (explicit or os.getenv("WHISPER_PROVIDER") or "auto").strip().lower()
    if raw in {"openai", "api"}:
        return "openai"
    if raw == "local":
        return "local"
    if os.getenv("OPENAI_API_KEY", "").strip():
        return "openai"
    return "local"


def resolve_chunk_long_audio(explicit: Optional[bool] = None) -> bool:
    """Whether to split long audio by duration before OpenAI transcription."""
    if explicit is not None:
        return explicit
    raw = (os.getenv("WHISPER_CHUNK_LONG_AUDIO") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _chunk_seconds() -> int:
    raw = (os.getenv("WHISPER_CHUNK_SECONDS") or "").strip()
    try:
        value = int(raw) if raw else DEFAULT_CHUNK_SECONDS
    except ValueError:
        value = DEFAULT_CHUNK_SECONDS
    return max(60, value)


def transcribe_openai(
    audio_path: str,
    *,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    language: Optional[str] = None,
    base_url: Optional[str] = None,
    timeout: float = 120.0,
) -> str:
    """Transcribe an audio file with the OpenAI Whisper API. Returns plain text."""
    key = (api_key or os.getenv("OPENAI_API_KEY") or "").strip()
    if not key:
        raise ValueError("OPENAI_API_KEY is required for OpenAI Whisper transcription")

    path = os.path.abspath(audio_path)
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Audio file not found: {path}")

    size = os.path.getsize(path)
    if size > MAX_FILE_BYTES:
        raise ValueError(
            f"Audio file too large for Whisper API ({size} bytes; max {MAX_FILE_BYTES})"
        )

    model_name = (model or os.getenv("WHISPER_MODEL") or DEFAULT_MODEL).strip()
    lang = (language if language is not None else DEFAULT_LANGUAGE).strip()
    root = (base_url or os.getenv("OPENAI_API_BASE") or DEFAULT_BASE_URL).rstrip("/")
    url = f"{root}/audio/transcriptions"

    mime, _ = mimetypes.guess_type(path)
    if not mime or not mime.startswith("audio/"):
        mime = "application/octet-stream"

    data = {"model": model_name, "response_format": "text", "language": lang}

    headers = {"Authorization": f"Bearer {key}"}

    with open(path, "rb") as handle:
        files = {"file": (os.path.basename(path), handle, mime)}
        response = requests.post(url, headers=headers, data=data, files=files, timeout=timeout)

    if response.status_code >= 400:
        detail = (response.text or "").strip()[:500]
        raise RuntimeError(f"Whisper API error {response.status_code}: {detail}")

    return (response.text or "").strip()


def _transcribe_openai_chunked(audio_path: Path, *, chunk_long_audio: bool) -> str:
    from src.audio_extract import get_media_duration_seconds, split_audio

    size = audio_path.stat().st_size
    duration = get_media_duration_seconds(audio_path)
    chunk_seconds = _chunk_seconds()
    should_chunk = size > MAX_FILE_BYTES or (
        chunk_long_audio and duration is not None and duration > chunk_seconds
    )

    if not should_chunk:
        return transcribe_openai(str(audio_path))

    with tempfile.TemporaryDirectory(prefix="whisper_chunks_") as tmp:
        chunks = split_audio(audio_path, tmp, chunk_seconds=chunk_seconds)
        parts: list[str] = []
        for index, chunk_path in enumerate(chunks, start=1):
            logger.info("Transcribing chunk %s/%s: %s", index, len(chunks), chunk_path.name)
            text = transcribe_openai(str(chunk_path), timeout=300.0)
            if text:
                parts.append(text)
        return "\n\n".join(parts).strip()


def _local_whisper_model() -> str:
    return (os.getenv("LOCAL_WHISPER_MODEL") or "small").strip() or "small"


def _transcribe_whisper_local(audio_path: Path, *, cache_dir: Optional[Path] = None) -> str:
    """Local fallback: whisper CLI, then faster-whisper."""
    out_root = cache_dir or Path(tempfile.gettempdir()) / "vincent_whisper"
    out_root.mkdir(parents=True, exist_ok=True)

    if shutil.which("whisper"):
        try:
            out_dir = out_root / "cli_out"
            out_dir.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                [
                    "whisper",
                    str(audio_path),
                    "--output_format",
                    "txt",
                    "--output_dir",
                    str(out_dir),
                    "--task",
                    "transcribe",
                    "--language",
                    DEFAULT_LANGUAGE,
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            txt_path = out_dir / f"{audio_path.stem}.txt"
            if txt_path.is_file():
                return txt_path.read_text(encoding="utf-8").strip()
        except Exception as exc:
            logger.debug("whisper CLI failed: %s", exc)

    try:
        from faster_whisper import WhisperModel  # type: ignore

        model = WhisperModel(_local_whisper_model())
        segments, _info = model.transcribe(str(audio_path), language=DEFAULT_LANGUAGE)
        parts: list[str] = []
        for seg in segments:
            text = (getattr(seg, "text", "") or "").strip()
            if text:
                parts.append(text)
        return "\n".join(parts).strip()
    except Exception as exc:
        raise RuntimeError(
            "Local Whisper failed. Install faster-whisper (`pip install faster-whisper`) "
            f"or the openai-whisper CLI. Detail: {exc}"
        ) from exc


def transcribe_audio(
    audio_path: Union[str, Path],
    *,
    provider: Optional[str] = None,
    cache_dir: Optional[Union[str, Path]] = None,
    chunk_long_audio: bool = False,
) -> str:
    """Transcribe audio with OpenAI or local Whisper."""
    path = Path(audio_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Audio file not found: {path}")

    backend = resolve_whisper_provider(provider)
    cache = Path(cache_dir).resolve() if cache_dir else None

    if backend == "openai":
        return _transcribe_openai_chunked(path, chunk_long_audio=chunk_long_audio)
    return _transcribe_whisper_local(path, cache_dir=cache)
