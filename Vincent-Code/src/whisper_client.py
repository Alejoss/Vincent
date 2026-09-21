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
  LOCAL_WHISPER_DEVICE                 (default cuda; CPU fallback on load failure)
  LOCAL_WHISPER_COMPUTE                (default float16)
  WHISPER_OPENAI_TIMEOUT               (optional request timeout in seconds)

Transcription defaults to Spanish (es); callers may override the language.
"""

from __future__ import annotations

import logging
import math
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


def _openai_timeout(explicit: Optional[float], default: float) -> float:
    value = explicit if explicit is not None else os.getenv("WHISPER_OPENAI_TIMEOUT")
    if value is None or value == "":
        return default
    try:
        seconds = float(value)
    except (ValueError, TypeError):
        return default
    return seconds if math.isfinite(seconds) and seconds > 0 else default


def _transcribe_openai_chunked(
    audio_path: Path, *, chunk_long_audio: bool,
    language: str = DEFAULT_LANGUAGE, timeout: Optional[float] = None,
) -> str:
    from src.audio_extract import get_media_duration_seconds, split_audio

    size = audio_path.stat().st_size
    duration = get_media_duration_seconds(audio_path) if chunk_long_audio else None
    chunk_seconds = _chunk_seconds()
    should_chunk = size > MAX_FILE_BYTES or (
        chunk_long_audio and duration is not None and duration > chunk_seconds
    )

    if not should_chunk:
        return transcribe_openai(str(audio_path), language=language, timeout=_openai_timeout(timeout, 120.0))

    with tempfile.TemporaryDirectory(prefix="whisper_chunks_") as tmp:
        chunks = split_audio(audio_path, tmp, chunk_seconds=chunk_seconds)
        parts: list[str] = []
        for index, chunk_path in enumerate(chunks, start=1):
            if chunk_path.stat().st_size > MAX_FILE_BYTES:
                raise ValueError(f"Chunk still too large: {chunk_path.name}. Reduce WHISPER_CHUNK_SECONDS.")
            logger.info("Transcribing chunk %s/%s: %s", index, len(chunks), chunk_path.name)
            text = transcribe_openai(str(chunk_path), language=language, timeout=_openai_timeout(timeout, 300.0))
            if text:
                parts.append(text)
        if not parts:
            raise RuntimeError(f"Empty transcript after chunking {audio_path.name}")
        return "\n\n".join(parts).strip()


def _local_whisper_model() -> str:
    return (os.getenv("LOCAL_WHISPER_MODEL") or "small").strip() or "small"


def _ensure_nvidia_dll_path() -> None:
    """Put pip nvidia-* bin dirs on PATH so ctranslate2 can load cublas/cudnn."""
    try:
        import site
    except ImportError:
        return
    candidates: list[Path] = []
    for base in site.getsitepackages() + ([site.getusersitepackages()] if site.getusersitepackages() else []):
        root = Path(base) / "nvidia"
        if not root.is_dir():
            continue
        candidates.extend(
            [
                root / "cublas" / "bin",
                root / "cuda_nvrtc" / "bin",
                root / "cudnn" / "bin",
            ]
        )
    # Also cover venv layout when running under -m / editable installs.
    here = Path(__file__).resolve().parents[1] / "venv" / "Lib" / "site-packages" / "nvidia"
    if here.is_dir():
        candidates.extend(
            [
                here / "cublas" / "bin",
                here / "cuda_nvrtc" / "bin",
                here / "cudnn" / "bin",
            ]
        )
    prepend = []
    seen: set[str] = set()
    for p in candidates:
        key = str(p).lower()
        if p.is_dir() and key not in seen:
            seen.add(key)
            prepend.append(str(p))
    if not prepend:
        return
    current = os.environ.get("PATH", "")
    missing = [p for p in prepend if p.lower() not in current.lower()]
    if missing:
        os.environ["PATH"] = os.pathsep.join(missing + ([current] if current else []))


def _transcribe_whisper_local(
    audio_path: Path, *, cache_dir: Optional[Path] = None,
    language: str = DEFAULT_LANGUAGE, model_name: Optional[str] = None,
) -> str:
    """Local fallback: whisper CLI, then faster-whisper."""
    out_root = cache_dir or Path(tempfile.gettempdir()) / "vincent_whisper"
    chosen_model = (model_name or _local_whisper_model()).strip()
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
                    language,
                    "--model",
                    chosen_model,
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

        _ensure_nvidia_dll_path()
        device = (os.getenv("LOCAL_WHISPER_DEVICE") or "cuda").strip() or "cuda"
        compute_type = (os.getenv("LOCAL_WHISPER_COMPUTE") or "float16").strip() or "float16"
        try:
            model = WhisperModel(
                chosen_model,
                device=device,
                compute_type=compute_type,
            )
        except Exception as cuda_exc:
            logger.warning("CUDA Whisper load failed (%s); falling back to CPU int8", cuda_exc)
            model = WhisperModel(chosen_model, device="cpu", compute_type="int8")
        segments, _info = model.transcribe(str(audio_path), language=language)
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


def transcribe_whisper_local(
    audio_path: Union[str, Path], *, language: Optional[str] = None,
    model_name: Optional[str] = None, cache_dir: Optional[Union[str, Path]] = None,
) -> str:
    """Public local entry point retained from the saved transcription work."""
    return _transcribe_whisper_local(
        Path(audio_path).resolve(),
        language=language if language is not None else DEFAULT_LANGUAGE,
        model_name=model_name,
        cache_dir=Path(cache_dir).resolve() if cache_dir else None,
    )


def transcribe_audio(
    audio_path: Union[str, Path],
    *,
    provider: Optional[str] = None,
    cache_dir: Optional[Union[str, Path]] = None,
    chunk_long_audio: Optional[bool] = None,
    language: Optional[str] = None,
    timeout: Optional[float] = None,
) -> str:
    """Transcribe audio with OpenAI or local Whisper."""
    path = Path(audio_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Audio file not found: {path}")

    backend = resolve_whisper_provider(provider)
    cache = Path(cache_dir).resolve() if cache_dir else None
    lang = language if language is not None else DEFAULT_LANGUAGE

    if backend == "openai":
        return _transcribe_openai_chunked(
            path, chunk_long_audio=resolve_chunk_long_audio(chunk_long_audio),
            language=lang, timeout=timeout,
        )
    return _transcribe_whisper_local(path, cache_dir=cache, language=lang)
