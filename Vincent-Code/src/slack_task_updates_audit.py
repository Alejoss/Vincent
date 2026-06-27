"""Append-only audit log for Slack -> Notion task completions (Pipeline 3)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

OUTCOME_GATE_SKIP = "gate_skip"
OUTCOME_EMPTY = "empty"
OUTCOME_APPLIED = "applied"
OUTCOME_IGNORED = "ignored"
OUTCOME_UNMATCHED = "unmatched"
OUTCOME_FAILED = "failed"

GATE_PHRASE_MATCH = "phrase_match"
GATE_NO_PHRASE = "no_phrase"

CURSOR_ADVANCE_OUTCOMES = frozenset({OUTCOME_GATE_SKIP, OUTCOME_EMPTY, OUTCOME_APPLIED})


def default_audit_path(project_root: str) -> Path:
    return Path(project_root) / "state" / "slack_task_updates_audit.jsonl"


def should_advance_cursor(outcome: str) -> bool:
    """Whether processing this message allows moving the Slack cursor past its ts."""
    return (outcome or "").strip() in CURSOR_ADVANCE_OUTCOMES


def append_audit_entry(
    path: Path,
    entry: Dict[str, Any],
    *,
    dry_run: bool = False,
) -> None:
    if dry_run:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    row = dict(entry)
    row.setdefault("logged_at", datetime.now(tz=timezone.utc).isoformat())
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def build_audit_entry(
    *,
    slack_ts: str,
    outcome: str,
    action: str = "",
    gate: str = "",
    page_id: str = "",
    title: str = "",
    confidence: Optional[float] = None,
    model: str = "",
    reason: str = "",
    transcribed: bool = False,
    dry_run: bool = False,
) -> Dict[str, Any]:
    entry: Dict[str, Any] = {
        "ts": slack_ts,
        "outcome": outcome,
        "gate": gate,
        "dry_run": dry_run,
    }
    if action:
        entry["action"] = action
    if page_id:
        entry["page_id"] = page_id
    if title:
        entry["title"] = title
    if confidence is not None:
        entry["confidence"] = round(confidence, 4)
    if model:
        entry["model"] = model
    if reason:
        entry["reason"] = reason[:500]
    if transcribed:
        entry["transcribed"] = True
    return entry
