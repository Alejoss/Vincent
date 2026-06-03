"""
Sync Slack DM messages (audio → text → Obsidian) into Obsidian notes.

Reads:
  - SLACK_BOT_TOKEN
  - SLACK_DM_CHANNEL_ID
  - SLACK_WORKSPACE_DOMAIN (optional; permalink in frontmatter)
  - OBSIDIAN_VAULT_PATH (required)
  - SLACK_INPUT_OBSIDIAN_REL (optional; default 0_Diario_Productividad/Input)
  - WHISPER_PROVIDER (optional; openai | local | auto — default auto)
  - OPENAI_API_KEY (required when WHISPER_PROVIDER=openai, or auto with key set)
  - WHISPER_MODEL (optional; default whisper-1)
  - Transcription language: Spanish (es), hardcoded in src/whisper_client.py

Writes:
  - One Markdown file per message under the vault subfolder (dedupe by slack_ts filename).
  - Local cursor: cache/slack_inbox/sync_state.sqlite3
  - Audio cache: cache/slack_audio/

Behavior:
  - Same incremental window + cursor as before (see SlackInboxStateStore).
  - Imports only messages you send to the bot (never the bot's replies). Requires a bot token (xoxb-).
  - Optional SLACK_HUMAN_USER_ID: if set, only that user id is imported (strictest).
  - Skips messages that already have a note file for that slack_ts.
  - Transcription: OpenAI Whisper API (cloud/GHA) or local whisper/faster-whisper fallback.
"""

from __future__ import annotations

import argparse
import os
import sys
import logging
import re
import subprocess
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set

import requests
from dotenv import load_dotenv

SCRIPTS_DIR = os.path.dirname(__file__)
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPTS_DIR, ".."))
sys.path.insert(0, PROJECT_ROOT)

from src.slack_inbox_obsidian import (
    default_input_rel_dir,
    message_exists,
    resolve_input_dir,
    write_slack_message_note,
)
from src.slack_inbox_state import SlackInboxStateStore
from src.whisper_client import resolve_whisper_provider, transcribe_openai

load_dotenv(override=True)

logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
log = logging.getLogger("sync_slack_inbox")

CACHE_DIR = os.path.join(PROJECT_ROOT, "cache", "slack_audio")


def _safe_filename(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"[^a-zA-Z0-9._-]+", "_", s)
    return s[:200] if len(s) > 200 else s


def _require_env(name: str) -> str:
    v = os.getenv(name)
    if not v:
        raise SystemExit(f"Missing required env var: {name}")
    return v


def slack_api_get(token: str, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
    r = requests.get(
        f"https://slack.com/api/{method}",
        headers={"Authorization": f"Bearer {token}"},
        params=params,
        timeout=30,
    )
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(f"Slack API {method} failed: {data}")
    return data


def slack_api_post(token: str, method: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    r = requests.post(
        f"https://slack.com/api/{method}",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"},
        json=payload,
        timeout=30,
    )
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(f"Slack API {method} failed: {data}")
    return data


# Subtypes that are never "you talking to the bot" in conversations.history
_SKIP_SUBTYPES: Set[str] = {
    "bot_message",
    "message_deleted",
    "channel_join",
    "channel_leave",
    "channel_topic",
    "channel_purpose",
    "channel_name",
    "channel_archive",
    "channel_unarchive",
    "pinned_item",
    "unpinned_item",
}


def _slack_bot_user_id(slack_token: str) -> str:
    data = slack_api_post(slack_token, "auth.test", {})
    uid = (data.get("user_id") or "").strip()
    if not uid:
        raise RuntimeError("auth.test returned no user_id")
    return uid


def is_human_message_to_bot(
    m: Dict[str, Any],
    bot_user_id: str,
    human_user_id: Optional[str],
) -> bool:
    """
    True only for messages authored by the human toward the bot (DM).

    Excludes: bot user id, missing user, bot_message and other non-user subtypes.
    If human_user_id is set (env SLACK_HUMAN_USER_ID), only that Slack user id matches.
    """
    sub = (m.get("subtype") or "").strip()
    if sub in _SKIP_SUBTYPES:
        return False
    uid = (m.get("user") or "").strip()
    if not uid:
        return False
    if uid == bot_user_id:
        return False
    if human_user_id:
        return uid == human_user_id.strip()
    return True


def ts_to_epoch_seconds(ts: str) -> float:
    try:
        return float(ts)
    except Exception:
        return 0.0


def build_message_permalink(workspace_domain: str, channel_id: str, ts: str) -> str:
    w = (workspace_domain or "").strip().replace("https://", "").replace("http://", "")
    if not w:
        return ""
    ts_compact = (ts or "").replace(".", "")
    if not ts_compact:
        return ""
    return f"https://{w}.slack.com/archives/{channel_id}/p{ts_compact}"


def _is_audio_file(f: Dict[str, Any]) -> bool:
    if not isinstance(f, dict):
        return False
    if f.get("is_external") is True:
        return False
    mimetype = (f.get("mimetype") or "").lower()
    filetype = (f.get("filetype") or "").lower()
    if mimetype.startswith("audio/"):
        return True
    return filetype in {"mp3", "m4a", "wav", "ogg", "webm"}


def _download_slack_file(slack_token: str, url: str, out_path: str) -> None:
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with requests.get(
        url,
        headers={"Authorization": f"Bearer {slack_token}"},
        stream=True,
        timeout=60,
    ) as r:
        r.raise_for_status()
        with open(out_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)


def _transcribe_whisper_local(audio_path: str) -> str:
    """Local fallback: whisper CLI, then faster-whisper."""
    """
    Try OpenAI whisper CLI first (if `whisper` is on PATH), then faster-whisper.
    Returns plain text or empty string.
    """
    try:
        out_dir = os.path.join(CACHE_DIR, "whisper_out")
        os.makedirs(out_dir, exist_ok=True)
        subprocess.run(
            ["whisper", audio_path, "--output_format", "txt", "--output_dir", out_dir, "--task", "transcribe"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        base = os.path.splitext(os.path.basename(audio_path))[0]
        txt_path = os.path.join(out_dir, f"{base}.txt")
        if os.path.isfile(txt_path):
            with open(txt_path, "r", encoding="utf-8") as f:
                return f.read().strip()
    except Exception:
        pass

    try:
        from faster_whisper import WhisperModel  # type: ignore

        model = WhisperModel("small")
        segments, _info = model.transcribe(audio_path)
        parts: List[str] = []
        for seg in segments:
            t = (getattr(seg, "text", "") or "").strip()
            if t:
                parts.append(t)
        return "\n".join(parts).strip()
    except Exception:
        pass

    return ""


def _transcribe_audio(audio_path: str, provider: str) -> str:
    if provider == "openai":
        return transcribe_openai(audio_path)
    return _transcribe_whisper_local(audio_path)


def fetch_messages_incremental(
    slack_token: str,
    channel_id: str,
    days: int,
    last_ts: Optional[str],
    full_refresh: bool,
) -> List[Dict[str, Any]]:
    now = datetime.now(tz=timezone.utc)
    window_start = (now - timedelta(days=days)).timestamp()

    if full_refresh or not last_ts:
        oldest_epoch = window_start
        log.info(f"Slack fetch: rolling window last {days} day(s) (no cursor or --full-refresh).")
    else:
        cursor_epoch = ts_to_epoch_seconds(last_ts) + 1e-6
        oldest_epoch = max(window_start, cursor_epoch)
        log.info(f"Slack fetch: incremental from cursor (oldest_epoch={oldest_epoch:.6f}, cap=last {days}d).")

    messages: List[Dict[str, Any]] = []
    cursor: Optional[str] = None
    while True:
        params: Dict[str, Any] = {
            "channel": channel_id,
            "oldest": oldest_epoch,
            "limit": 200,
        }
        if cursor:
            params["cursor"] = cursor
        data = slack_api_get(slack_token, "conversations.history", params=params)
        batch = data.get("messages", []) or []
        messages.extend(batch)
        cursor = (data.get("response_metadata") or {}).get("next_cursor") or None
        if not cursor:
            break
    return messages


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync Slack DM messages into Obsidian (0_Diario_productividad/Input)")
    parser.add_argument("--days", type=int, default=3, help="Import messages from last N days (default 3)")
    parser.add_argument("--dry-run", action="store_true", help="Do not write notes; only log actions")
    parser.add_argument(
        "--audio",
        dest="audio",
        action="store_true",
        default=True,
        help="Process audio attachments (default: true)",
    )
    parser.add_argument(
        "--no-audio",
        dest="audio",
        action="store_false",
        help="Skip audio transcription",
    )
    parser.add_argument(
        "--whisper-provider",
        choices=("openai", "local", "auto"),
        default=None,
        help="Transcription backend (default: WHISPER_PROVIDER env or auto)",
    )
    parser.add_argument(
        "--full-refresh",
        action="store_true",
        help="Ignore saved cursor; fetch last --days from Slack (slower, for backfill).",
    )
    parser.add_argument(
        "--input-rel",
        default=None,
        help="Subfolder under vault (overrides SLACK_INPUT_OBSIDIAN_REL for this run).",
    )
    args = parser.parse_args()

    print(
        "\n".join(
            [
                "==============================",
                "         VINCENT",
                " Slack -> Obsidian sync...",
                " Do not close this window.",
                "==============================",
            ]
        ),
        flush=True,
    )

    slack_token = _require_env("SLACK_BOT_TOKEN").strip().strip('"').strip("'")
    if not slack_token.startswith("xoxb-"):
        raise SystemExit(
            "SLACK_BOT_TOKEN must be a Bot User OAuth token (starts with xoxb-). "
            "User tokens (xoxp-) make auth.test return your user id, so the script would import "
            "the bot's messages instead of yours."
        )
    channel_id = _require_env("SLACK_DM_CHANNEL_ID").strip()
    workspace_domain = (os.getenv("SLACK_WORKSPACE_DOMAIN") or "").strip()
    human_user_id = (os.getenv("SLACK_HUMAN_USER_ID") or "").strip() or None
    if human_user_id:
        log.info(f"Strict human filter: SLACK_HUMAN_USER_ID={human_user_id}")

    vault = _require_env("OBSIDIAN_VAULT_PATH").strip().strip('"').strip("'")
    rel_input = (args.input_rel or os.getenv("SLACK_INPUT_OBSIDIAN_REL") or "").strip()
    if not rel_input:
        rel_input = default_input_rel_dir()
    input_dir = resolve_input_dir(vault, rel_input)
    log.info(f"Obsidian vault: {os.path.abspath(vault)}")
    log.info(f"Slack notes directory: {input_dir}")

    bot_user_id = _slack_bot_user_id(slack_token)
    log.info(f"Slack bot_user_id (messages from this user are skipped): {bot_user_id}")
    log.info(f"Slack channel: {channel_id}")
    log.info(f"Import window cap: last {args.days} day(s)")

    whisper_provider = resolve_whisper_provider(args.whisper_provider)
    if args.audio:
        log.info(f"Audio transcription: {whisper_provider}")
        if whisper_provider == "openai" and not (os.getenv("OPENAI_API_KEY") or "").strip():
            raise SystemExit(
                "WHISPER_PROVIDER=openai (or --whisper-provider openai) requires OPENAI_API_KEY"
            )

    state_store = SlackInboxStateStore(PROJECT_ROOT)
    last_ts = None if args.full_refresh else state_store.load_last_ts(channel_id)
    if last_ts:
        log.info(f"Loaded Slack cursor last_ts={last_ts}")

    raw_messages = fetch_messages_incremental(
        slack_token, channel_id, args.days, last_ts, args.full_refresh
    )
    raw_messages.sort(key=lambda m: ts_to_epoch_seconds(m.get("ts", "")))

    mine = [m for m in raw_messages if is_human_message_to_bot(m, bot_user_id, human_user_id)]
    log.info(
        f"Fetched {len(raw_messages)} message(s); {len(mine)} to import "
        f"(human -> bot only{', strict user id' if human_user_id else ''})."
    )

    created = 0
    skipped = 0
    max_ts_in_batch = ""
    max_ts_epoch = 0.0

    for m in mine:
        ts = (m.get("ts") or "").strip()
        text = (m.get("text") or "").strip()
        if not ts:
            skipped += 1
            continue

        te = ts_to_epoch_seconds(ts)
        if te >= max_ts_epoch:
            max_ts_epoch = te
            max_ts_in_batch = ts

        if message_exists(input_dir, ts):
            skipped += 1
            continue

        permalink = build_message_permalink(workspace_domain, channel_id, ts)

        transcript_text = ""
        if args.audio:
            files = m.get("files") or []
            for f in files if isinstance(files, list) else []:
                if not _is_audio_file(f):
                    continue
                file_id = (f.get("id") or "").strip()
                url = (f.get("url_private_download") or f.get("url_private") or "").strip()
                if not file_id or not url:
                    continue
                ext = (f.get("filetype") or "").strip().lower() or "bin"
                audio_path = os.path.join(CACHE_DIR, f"{_safe_filename(file_id)}.{ext}")
                txt_path = os.path.join(CACHE_DIR, f"{_safe_filename(file_id)}.txt")

                if args.dry_run:
                    transcript_text = "[transcript dry-run]"
                    break

                if os.path.isfile(txt_path):
                    try:
                        with open(txt_path, "r", encoding="utf-8") as rf:
                            transcript_text = rf.read().strip()
                    except Exception:
                        transcript_text = ""
                else:
                    if not os.path.isfile(audio_path):
                        try:
                            _download_slack_file(slack_token, url, audio_path)
                        except Exception as e:
                            log.info(f"Audio download failed for file_id={file_id}: {e}")
                            continue
                    try:
                        transcript_text = _transcribe_audio(audio_path, whisper_provider).strip()
                    except Exception as e:
                        log.info(f"Transcription failed for file_id={file_id} ({whisper_provider}): {e}")
                        transcript_text = ""
                    if transcript_text:
                        try:
                            os.makedirs(os.path.dirname(txt_path), exist_ok=True)
                            with open(txt_path, "w", encoding="utf-8") as wf:
                                wf.write(transcript_text)
                        except Exception:
                            pass
                    elif whisper_provider == "openai":
                        log.info(
                            f"Empty transcript for file_id={file_id}; message ts={ts} will be skipped if no text"
                        )

                if transcript_text:
                    break

        final_text = text
        was_transcribed = False
        if transcript_text:
            was_transcribed = True
            if final_text:
                final_text = f"{final_text}\n\n{transcript_text}"
            else:
                final_text = transcript_text

        if not (final_text or "").strip():
            log.info(f"Skipping ts={ts}: empty message and no transcript")
            skipped += 1
            continue

        if args.dry_run:
            log.info(f"[dry-run] would write slack-{ts}.md ({len(final_text)} chars, transcribed={was_transcribed})")
            created += 1
            continue

        ok = write_slack_message_note(
            input_dir=input_dir,
            body=final_text,
            slack_ts=ts,
            source_url=permalink,
            transcribed=was_transcribed,
        )
        if ok:
            created += 1
        else:
            skipped += 1

    if not args.dry_run and max_ts_in_batch:
        state_store.save_last_ts(channel_id, max_ts_in_batch)
        log.info(f"Saved Slack cursor last_ts={max_ts_in_batch}")

    log.info(f"Done. Wrote {created}, skipped {skipped}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
