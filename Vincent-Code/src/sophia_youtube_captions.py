"""Fetch public YouTube captions as plain text + optional SRT (no OAuth)."""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)


def extract_youtube_video_id(url_or_id: str) -> Optional[str]:
    raw = (url_or_id or "").strip()
    if re.fullmatch(r"[a-zA-Z0-9_-]{11}", raw):
        return raw
    patterns = [
        r"(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/|youtube\.com/live/)([a-zA-Z0-9_-]{11})",
        r"youtube\.com/watch\?.*v=([a-zA-Z0-9_-]{11})",
        r"youtube\.com/shorts/([a-zA-Z0-9_-]{11})",
    ]
    for pattern in patterns:
        match = re.search(pattern, raw)
        if match:
            return match.group(1)
    return None


def _ms_to_srt_time(ms: float) -> str:
    total_ms = max(0, int(round(ms)))
    hours, rem = divmod(total_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    seconds, millis = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def cues_to_srt(cues: list[dict[str, Any]]) -> str:
    """Build SRT from list of {text, start, duration} (seconds)."""
    blocks: list[str] = []
    index = 1
    for cue in cues:
        text = (cue.get("text") or "").strip()
        if not text:
            continue
        start_s = float(cue.get("start") or 0)
        duration_s = float(cue.get("duration") or 0)
        end_s = start_s + (duration_s if duration_s > 0 else 2.0)
        start_ms = start_s * 1000
        end_ms = end_s * 1000
        blocks.append(
            f"{index}\n{_ms_to_srt_time(start_ms)} --> {_ms_to_srt_time(end_ms)}\n{text}\n"
        )
        index += 1
    return "\n".join(blocks).strip() + ("\n" if blocks else "")


def fetch_youtube_captions(
    video_id_or_url: str,
    *,
    languages: Optional[list[str]] = None,
) -> Optional[dict[str, Any]]:
    """
    Return dict with keys: video_id, language_code, plain_text, source_subtitles (SRT), cues.
    None if unavailable.
    """
    video_id = extract_youtube_video_id(video_id_or_url)
    if not video_id:
        return None

    preferred = languages or ["es", "en"]
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        from youtube_transcript_api._errors import NoTranscriptFound, TranscriptsDisabled
    except ImportError as exc:
        raise RuntimeError(
            "youtube-transcript-api is required: pip install youtube-transcript-api"
        ) from exc

    ytt = YouTubeTranscriptApi()
    transcript_data = None
    language_code = None

    try:
        fetched = ytt.fetch(video_id, languages=preferred)
        transcript_data = fetched.to_raw_data()
        language_code = fetched.language_code
    except (TranscriptsDisabled, NoTranscriptFound):
        try:
            for transcript in ytt.list(video_id):
                try:
                    fetched = transcript.fetch()
                    transcript_data = fetched.to_raw_data()
                    language_code = fetched.language_code
                    break
                except Exception as inner:
                    logger.debug("Skip caption track: %s", inner)
        except Exception as exc:
            logger.warning("No captions list for %s: %s", video_id, exc)
            return None
    except Exception as exc:
        logger.warning("Caption fetch failed for %s: %s", video_id, exc)
        return None

    if not transcript_data:
        return None

    plain = " ".join(
        (entry.get("text") or "").strip() for entry in transcript_data if entry.get("text")
    ).strip()
    if not plain:
        return None

    srt = cues_to_srt(transcript_data)
    return {
        "video_id": video_id,
        "language_code": language_code or "es",
        "plain_text": plain,
        "source_subtitles": srt,
        "format": "SRT",
        "cues": transcript_data,
    }
