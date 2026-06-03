"""
OpenAI Whisper API client for transcribing Slack audio attachments.

Uses the same OPENAI_API_KEY as the chat/classifier API (no separate Whisper key).

Env (used by sync_slack_inbox_to_obsidian.py):
  WHISPER_PROVIDER=openai|local|auto   (default auto)
  OPENAI_API_KEY                       (required when provider is openai)
  WHISPER_MODEL                        (default whisper-1; optional override)
  OPENAI_API_BASE                      (optional; default https://api.openai.com/v1)

Transcription language is fixed to Spanish (es) in code — Vincent messages are voice in Spanish.
"""

from __future__ import annotations

import mimetypes
import os
from typing import Optional

import requests

DEFAULT_MODEL = "whisper-1"
DEFAULT_LANGUAGE = "es"
DEFAULT_BASE_URL = "https://api.openai.com/v1"
MAX_FILE_BYTES = 25 * 1024 * 1024  # OpenAI limit


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
