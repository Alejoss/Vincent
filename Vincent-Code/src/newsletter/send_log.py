"""Minimal send log (no stats — use SMTP2GO Reports for that)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import PROJECT_ROOT
from .send_result import SendResult
from .renderer import RenderedNewsletter

LOG_PATH = PROJECT_ROOT / "data" / "newsletter_send_log.jsonl"


def append_send_log(
    rendered: RenderedNewsletter,
    result: SendResult,
    *,
    send_type: str,
    segment: str | None = None,
    to_email: str | None = None,
) -> None:
    entry: dict[str, Any] = {
        "at": datetime.now(timezone.utc).isoformat(),
        "type": send_type,
        "subject": rendered.subject,
        "tag": rendered.tag,
        "segment": segment or rendered.segment,
        "md_path": str(rendered.md_path) if rendered.md_path else None,
        "recipient_count": result.recipient_count,
        "ok": result.ok,
        "method": result.method,
        "bulk_id": result.bulk_id,
        "to_email": to_email,
        "error": result.error,
    }
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def read_send_log(limit: int = 50) -> list[dict[str, Any]]:
    if not LOG_PATH.is_file():
        return []
    lines = LOG_PATH.read_text(encoding="utf-8").strip().splitlines()
    entries: list[dict[str, Any]] = []
    for line in lines[-limit:]:
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return list(reversed(entries))
