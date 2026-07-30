"""Obsidian helpers for Slack task-update notes (completion path)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional, Tuple

from src.slack_inbox_obsidian import (
    default_input_rel_dir,
    note_path,
    resolve_input_dir,
    write_slack_message_note,
)
from src.slack_task_intent import INTENT_COMPLETAR, normalize_intent

TASK_UPDATE_SKIP_STATUSES = frozenset({"true", "yes", "1", "unmatched", "ignored", "failed", "applied"})


def frontmatter_flag(value: str) -> str:
    return (value or "").strip().strip('"').strip("'").lower()


def is_task_update_processed(value: str) -> bool:
    return frontmatter_flag(value) in TASK_UPDATE_SKIP_STATUSES


def slack_plain_for_gate(body: str) -> str:
    text = (body or "").strip()
    marker = "## Contenido completo (Slack)"
    if marker in text:
        return text.split(marker, 1)[1].lstrip("\n").strip()
    return text


def note_intent(fm: Dict[str, str]) -> str:
    return normalize_intent(frontmatter_flag(fm.get("intencion", "")))


def should_skip_productivity_classify(fm: Dict[str, str], body: str = "") -> bool:
    """Skip classifier only when a completion update was already applied."""
    del body  # kept for call-site compatibility
    return is_task_update_processed(fm.get("task_update_processed", ""))


def should_skip_notion_create(fm: Dict[str, str], body: str = "") -> bool:
    """
    Do not upsert a new Notion row for this slack_ts when the note is a
    completion of an *existing* task (or already applied as task update).
    """
    if is_task_update_processed(fm.get("task_update_processed", "")):
        return True
    if note_intent(fm) == INTENT_COMPLETAR:
        return True
    del body
    return False


def _quote_yaml(value: str) -> str:
    escaped = (value or "").replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _parse_frontmatter(content: str) -> Tuple[Dict[str, str], str]:
    text = content or ""
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end == -1:
        return {}, text
    block = text[4:end]
    body = text[end + 5 :]
    fm: Dict[str, str] = {}
    for line in block.splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        fm[k.strip()] = v.strip()
    return fm, body


def _compose_note(frontmatter: Dict[str, str], body: str) -> str:
    lines = ["---"]
    for key, value in frontmatter.items():
        lines.append(f"{key}: {value}")
    lines.extend(["---", "", (body or "").strip(), ""])
    return "\n".join(lines)


def ensure_input_note(
    *,
    vault_path: str,
    input_rel: str,
    slack_ts: str,
    message_text: str,
    source_url: str = "",
    transcribed: bool = False,
    dry_run: bool = False,
) -> Optional[Path]:
    """Create Input/slack-<ts>.md if missing (Pipeline 3 may run before inbox sync)."""
    if not vault_path:
        return None
    input_dir = resolve_input_dir(vault_path, input_rel or default_input_rel_dir())
    path = Path(note_path(input_dir, slack_ts))
    if path.is_file():
        return path
    if dry_run:
        return path
    body = (message_text or "").strip()
    if not body:
        return None
    ok = write_slack_message_note(
        input_dir=input_dir,
        body=body,
        slack_ts=slack_ts,
        source_url=source_url,
        transcribed=transcribed,
    )
    return path if ok else None


def mark_task_update_note(
    *,
    vault_path: str,
    input_rel: str,
    slack_ts: str,
    message_text: str,
    source_url: str,
    transcribed: bool,
    status: str,
    action: str,
    page_id: str,
    model_label: str,
    reason: str,
    dry_run: bool,
) -> bool:
    """Ensure Input note exists and write task_update_* frontmatter."""
    if not vault_path:
        return False
    path = ensure_input_note(
        vault_path=vault_path,
        input_rel=input_rel,
        slack_ts=slack_ts,
        message_text=message_text,
        source_url=source_url,
        transcribed=transcribed,
        dry_run=dry_run,
    )
    if not path:
        return False
    if dry_run:
        return True
    if not path.is_file():
        return False
    raw = path.read_text(encoding="utf-8")
    fm, body = _parse_frontmatter(raw)
    fm["task_update_processed"] = _quote_yaml(status)
    fm["task_update_action"] = _quote_yaml(action)
    if page_id:
        fm["task_update_notion_page"] = _quote_yaml(page_id)
    fm["task_update_model"] = _quote_yaml(model_label)
    fm["task_update_actualizada"] = _quote_yaml(datetime.now(tz=timezone.utc).isoformat())
    if reason:
        fm["task_update_razon"] = _quote_yaml(reason[:500])
    path.write_text(_compose_note(fm, body), encoding="utf-8", newline="\n")
    return True


def mark_note_path_task_update(
    path: Path,
    *,
    status: str,
    action: str,
    page_id: str,
    model_label: str,
    reason: str,
    dry_run: bool = False,
) -> bool:
    """Write task_update_* on an existing classified note path."""
    if dry_run:
        return True
    if not path.is_file():
        return False
    raw = path.read_text(encoding="utf-8")
    fm, body = _parse_frontmatter(raw)
    fm["task_update_processed"] = _quote_yaml(status)
    fm["task_update_action"] = _quote_yaml(action)
    if page_id:
        fm["task_update_notion_page"] = _quote_yaml(page_id)
    fm["task_update_model"] = _quote_yaml(model_label)
    fm["task_update_actualizada"] = _quote_yaml(datetime.now(tz=timezone.utc).isoformat())
    if reason:
        fm["task_update_razon"] = _quote_yaml(reason[:500])
    path.write_text(_compose_note(fm, body), encoding="utf-8", newline="\n")
    return True
