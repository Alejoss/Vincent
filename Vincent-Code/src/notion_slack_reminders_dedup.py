"""Dedup rules for Notion → Slack due-date reminders."""

from __future__ import annotations

from datetime import date
from typing import Dict, Optional


def parse_iso_date(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    t = str(s).strip()
    if not t:
        return None
    if "T" in t:
        t = t.split("T", 1)[0]
    try:
        y, m, d = t.split("-", 2)
        return date(int(y), int(m), int(d))
    except Exception:
        return None


def effective_dedup_days(is_overdue: bool, dedup_days: int, dedup_days_overdue: int) -> int:
    """Shorter window for overdue pending tasks so they reappear sooner."""
    return dedup_days_overdue if is_overdue else dedup_days


def was_sent_within_dedup_window(
    sent_state: Dict[str, str],
    state_key: str,
    today: date,
    dedup_days: int,
) -> bool:
    if dedup_days <= 0:
        return False
    last_s = sent_state.get(state_key)
    if not last_s:
        return False
    last_d = parse_iso_date(last_s)
    if not last_d:
        return False
    return (today - last_d).days < dedup_days
