"""
Persist Slack inbox captures as Markdown files under the Obsidian vault.

Default folder (relative to vault root): 0_Diario_productividad/Input
Override with env SLACK_INPUT_OBSIDIAN_REL (use forward slashes or OS separators).
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone


def default_input_rel_dir() -> str:
    return os.path.join("0_Diario_productividad", "Input")


def resolve_input_dir(vault_path: str, rel_dir: str) -> str:
    root = os.path.abspath(os.path.expanduser((vault_path or "").strip()))
    rel = (rel_dir or "").strip().strip("/").replace("\\", os.sep).replace("/", os.sep)
    out = os.path.join(root, rel)
    os.makedirs(out, exist_ok=True)
    return out


def _slack_ts_file_stem(slack_ts: str) -> str:
    s = (slack_ts or "").strip()
    s = re.sub(r"[^\w.-]+", "_", s)
    return s or "unknown"


def note_path(input_dir: str, slack_ts: str) -> str:
    return os.path.join(input_dir, f"slack-{_slack_ts_file_stem(slack_ts)}.md")


def message_exists(input_dir: str, slack_ts: str) -> bool:
    return os.path.isfile(note_path(input_dir, slack_ts))


def slack_ts_to_iso_z(slack_ts: str) -> str:
    try:
        secs = float(slack_ts)
    except Exception:
        secs = datetime.now(tz=timezone.utc).timestamp()
    return datetime.fromtimestamp(secs, tz=timezone.utc).isoformat()


def _yaml_double_quoted(s: str) -> str:
    t = (s or "").replace("\\", "\\\\").replace('"', '\\"')
    return f'"{t}"'


def write_slack_message_note(
    input_dir: str,
    body: str,
    slack_ts: str,
    source_url: str,
    transcribed: bool,
) -> bool:
    """
    Write one note. Filename encodes slack_ts for idempotent runs / dedupe.
    Returns True on success.
    """
    path = note_path(input_dir, slack_ts)
    when = slack_ts_to_iso_z(slack_ts)
    src = (source_url or "").strip()
    lines = [
        "---",
        f"slack_ts: {_yaml_double_quoted(slack_ts.strip())}",
        f"message_at: {_yaml_double_quoted(when)}",
        f"source: {_yaml_double_quoted(src)}",
        f"transcribed: {'true' if transcribed else 'false'}",
        "---",
        "",
        (body or "").strip(),
        "",
    ]
    try:
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(lines))
        return True
    except OSError:
        return False
