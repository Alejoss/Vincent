"""Local video tools: Whisper transcript + podcast MP3 extract."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from src.mcp.confirm import write_gate
from src.mcp.jobs import run_script
from src.mcp.paths import PROJECT_ROOT

VIDEO_EXTENSIONS = frozenset(
    {".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v", ".wmv", ".flv", ".mpeg", ".mpg"}
)
DEFAULT_AUDIO_OUTPUT_DIR = PROJECT_ROOT.parent / "VideosParaPodcast" / "mp3"


def resolve_local_video(video: str) -> tuple[Optional[Path], Optional[dict[str, Any]]]:
    raw = (video or "").strip()
    if not raw:
        return None, {"ok": False, "error": "video path is empty"}
    path = Path(raw).expanduser().resolve()
    if not path.is_file():
        return None, {"ok": False, "error": f"Video not found: {path}"}
    if path.suffix.lower() not in VIDEO_EXTENSIONS:
        return None, {
            "ok": False,
            "error": f"Unsupported video extension: {path.suffix or '(none)'}",
        }
    return path, None


def transcribe_local_video(
    video: str,
    *,
    confirm: bool = False,
    dry_run: bool = False,
    wait: bool = False,
    retry_failed: bool = False,
    force: bool = False,
    chunk_long_audio: bool = True,
) -> dict[str, Any]:
    refused = write_gate(confirm, dry_run)
    if refused:
        return refused

    path, error = resolve_local_video(video)
    if error:
        return error
    assert path is not None

    args = [str(path)]
    if dry_run:
        args.append("--dry-run")
    if retry_failed:
        args.append("--retry-failed")
    if force:
        args.append("--no-skip-existing")
    if chunk_long_audio:
        args.append("--chunk-long-audio")
    else:
        args.append("--no-chunk-long-audio")

    return run_script(
        "transcribe_local_video",
        "transcribe_one_local_video.py",
        args,
        wait=wait,
        timeout_s=7200,
        dry_run=dry_run,
    )


def extract_local_audio(
    video: str,
    *,
    confirm: bool = False,
    dry_run: bool = False,
    wait: bool = False,
    force: bool = False,
    output_dir: Optional[str] = None,
) -> dict[str, Any]:
    refused = write_gate(confirm, dry_run)
    if refused:
        return refused

    path, error = resolve_local_video(video)
    if error:
        return error
    assert path is not None

    dest = (
        Path(output_dir).expanduser().resolve()
        if (output_dir or "").strip()
        else DEFAULT_AUDIO_OUTPUT_DIR
    )
    args = [str(path), "--output-dir", str(dest)]
    if dry_run:
        args.append("--dry-run")
    if force:
        args.append("--force")

    result = run_script(
        "extract_local_audio",
        "extract_one_video_audio.py",
        args,
        wait=wait,
        timeout_s=3600,
        dry_run=dry_run,
    )
    result.setdefault("video", str(path))
    result.setdefault("output_mp3", str(dest / f"{path.stem}.mp3"))
    return result


def generate_podcast_covers(
    *,
    episode_id: Optional[str] = None,
    limit: Optional[int] = None,
    word: Optional[str] = None,
    confirm: bool = False,
    dry_run: bool = False,
    wait: bool = False,
    force: bool = False,
    include_unpublished: bool = False,
) -> dict[str, Any]:
    refused = write_gate(confirm, dry_run)
    if refused:
        return refused

    args: list[str] = []
    if (episode_id or "").strip():
        args.extend(["--episode-id", episode_id.strip()])
    if limit is not None:
        if int(limit) < 1:
            return {"ok": False, "error": "limit must be >= 1 when set"}
        args.extend(["--limit", str(int(limit))])
    if (word or "").strip():
        args.extend(["--word", word.strip()])
    if dry_run:
        args.append("--dry-run")
    if force:
        args.append("--force")
    if include_unpublished:
        args.append("--include-unpublished")

    result = run_script(
        "generate_podcast_covers",
        "generate_podcast_covers.py",
        args,
        wait=wait,
        timeout_s=7200,
        dry_run=dry_run,
    )
    if (episode_id or "").strip():
        result.setdefault("episode_id", episode_id.strip())
    if limit is not None:
        result.setdefault("limit", int(limit))
    return result
