"""Download captions from your own YouTube videos via OAuth + Data API v3."""

from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload

from src.youtube_oauth import get_authenticated_youtube_service

logger = logging.getLogger(__name__)

QUOTA_PER_VIDEO = 250  # captions.list (50) + captions.download (200)

# YouTube VTT karaoke / metadata leaked into plain text breaks Obsidian.
VTT_MARKUP_RE = re.compile(
    r"<c[\s>]|captions Language\s*:|<\.\d|Kind:\s*captions",
    re.IGNORECASE,
)


def caption_text_looks_corrupt(text: str) -> bool:
    """True if parsed caption text still contains VTT markup (must not save to vault)."""
    return bool(VTT_MARKUP_RE.search(text))


@dataclass
class CaptionFetchOutcome:
    ok: bool
    text: Optional[str] = None
    language_code: Optional[str] = None
    error: Optional[str] = None
    quota_exceeded: bool = False


def strip_inline_caption_tags(text: str) -> str:
    """Remove YouTube karaoke markup (<c>, <00:01.234>, etc.) from VTT lines."""
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _skip_vtt_line(stripped: str) -> bool:
    if stripped.upper().startswith("WEBVTT"):
        return True
    if stripped.startswith("NOTE"):
        return True
    if "-->" in stripped:
        return True
    if re.match(r"^\d+$", stripped):
        return True
    if re.match(r"^(Kind|Language|Style):", stripped, re.I):
        return True
    if re.match(r"^align:", stripped, re.I):
        return True
    return False


def _best_vtt_cue_line(lines: List[str]) -> str:
    candidates = [strip_inline_caption_tags(line) for line in lines]
    candidates = [c for c in candidates if c]
    if not candidates:
        return ""
    return max(candidates, key=len)


def merge_overlapping_cue_parts(parts: List[str]) -> str:
    """Merge SRT/VTT cues that overlap word-by-word (YouTube auto-captions)."""
    words_result: List[str] = []
    for part in parts:
        words = part.split()
        if not words:
            continue
        if not words_result:
            words_result = words
            continue
        max_k = min(len(words_result), len(words), 30)
        overlap = 0
        for k in range(max_k, 0, -1):
            if words_result[-k:] == words[:k]:
                overlap = k
                break
        words_result.extend(words[overlap:])
    return " ".join(words_result)


def parse_vtt(raw: str) -> str:
    cues: List[str] = []
    block_lines: List[str] = []

    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            if block_lines:
                cue = _best_vtt_cue_line(block_lines)
                if cue:
                    cues.append(cue)
                block_lines = []
            continue
        if _skip_vtt_line(stripped):
            continue
        block_lines.append(stripped)

    if block_lines:
        cue = _best_vtt_cue_line(block_lines)
        if cue:
            cues.append(cue)

    return merge_overlapping_cue_parts(cues)


def parse_srt(raw: str) -> str:
    blocks = re.split(r"\n\s*\n", raw.strip())
    parts: List[str] = []
    for block in blocks:
        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        if len(lines) < 2:
            continue
        text_lines = []
        for line in lines:
            if re.match(r"^\d+$", line):
                continue
            if "-->" in line:
                continue
            text_lines.append(line)
        if text_lines:
            parts.append(" ".join(text_lines))
    return merge_overlapping_cue_parts(parts)


def parse_subtitle_bytes(data: bytes, fmt: str = "vtt") -> str:
    raw = data.decode("utf-8", errors="replace")
    if fmt == "srt":
        return parse_srt(raw)
    return parse_vtt(raw)


def _pick_caption_track(items: List[dict], languages: List[str]) -> Optional[dict]:
    def lang_rank(item: dict) -> Tuple[int, int]:
        snippet = item.get("snippet") or {}
        lang = (snippet.get("language") or "").lower()
        track_kind = snippet.get("trackKind") or ""
        for idx, preferred in enumerate(languages):
            pref = preferred.lower()
            if lang == pref or lang.startswith(pref + "-") or pref.startswith(lang):
                manual_bonus = 0 if track_kind == "standard" else 1
                return (idx, manual_bonus)
        return (999, 999)

    if not items:
        return None

    ranked = sorted(items, key=lang_rank)
    best = ranked[0]
    if lang_rank(best)[0] == 999:
        best = items[0]
    return best


class YouTubeOAuthCaptionFetcher:
    """Fetch captions using captions.list + captions.download (channel owner OAuth)."""

    def __init__(self, project_root: str):
        self.project_root = project_root
        self.youtube = get_authenticated_youtube_service(project_root)
        self.quota_used = 0

    def fetch_transcript(
        self, video_id: str, languages: Optional[List[str]] = None
    ) -> CaptionFetchOutcome:
        if languages is None:
            languages = ["es", "es-419", "en"]

        try:
            list_resp = self.youtube.captions().list(
                part="snippet", videoId=video_id
            ).execute()
            self.quota_used += 50
        except HttpError as exc:
            return self._http_error_outcome(exc, video_id, phase="list")

        items = list_resp.get("items") or []
        if not items:
            return CaptionFetchOutcome(ok=False, error="no_captions_available")

        track = _pick_caption_track(items, languages)
        if not track:
            return CaptionFetchOutcome(ok=False, error="no_captions_available")

        caption_id = track["id"]
        language_code = (track.get("snippet") or {}).get("language") or "und"

        try:
            # SRT avoids YouTube VTT karaoke tags (<c>, inline timestamps) that break Obsidian.
            request = self.youtube.captions().download(id=caption_id, tfmt="srt")
            buffer = io.BytesIO()
            downloader = MediaIoBaseDownload(buffer, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
            self.quota_used += 200
            text = parse_subtitle_bytes(buffer.getvalue(), fmt="srt")
            if not text:
                return CaptionFetchOutcome(ok=False, error="empty_caption_track")
            if caption_text_looks_corrupt(text):
                logger.error(
                    "Parsed SRT still contains VTT markup for %s; refusing corrupt text",
                    video_id,
                )
                return CaptionFetchOutcome(ok=False, error="vtt_markup_in_parsed_text")
            logger.debug(
                "OAuth captions OK for %s (lang=%s, track=%s)",
                video_id,
                language_code,
                caption_id,
            )
            return CaptionFetchOutcome(
                ok=True, text=text, language_code=language_code
            )
        except HttpError as exc:
            return self._http_error_outcome(exc, video_id, phase="download")

    def _http_error_outcome(
        self, exc: HttpError, video_id: str, *, phase: str
    ) -> CaptionFetchOutcome:
        status = exc.resp.status if exc.resp else "?"
        detail = str(exc)
        logger.error("OAuth captions %s failed for %s: %s", phase, video_id, detail)

        if status == 403 and "quotaExceeded" in detail:
            return CaptionFetchOutcome(
                ok=False,
                error="quota_exceeded",
                quota_exceeded=True,
            )
        if status == 403:
            return CaptionFetchOutcome(ok=False, error="oauth_forbidden")
        if status == 404:
            return CaptionFetchOutcome(ok=False, error="no_captions_available")
        return CaptionFetchOutcome(ok=False, error=f"oauth_http_{status}")
