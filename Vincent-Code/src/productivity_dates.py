"""
Shared due-date inference for Slack productivity notes (Obsidian + Notion).

Anchor date = message_at (ISO) if valid, else date from Slack ts (UTC).
Never returns a due date in a year before the anchor year, nor long before the anchor day.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone


def safe_date_from_slack_ts(ts: str) -> date:
    try:
        secs = float((ts or "").strip())
    except Exception:
        secs = datetime.now(tz=timezone.utc).timestamp()
    return datetime.fromtimestamp(secs, tz=timezone.utc).date()


def anchor_date(message_at_iso: str, slack_ts: str) -> date:
    s = (message_at_iso or "").strip().strip('"')
    if s:
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
        except Exception:
            pass
    return safe_date_from_slack_ts(slack_ts)


def clamp_due_iso(iso: str, anchor: date) -> str:
    """Return YYYY-MM-DD only if plausible vs anchor; else empty string."""
    if not (iso or "").strip():
        return ""
    raw = iso.strip()[:10]
    try:
        d = date.fromisoformat(raw)
    except ValueError:
        return ""
    if d.year < anchor.year:
        return ""
    if d < anchor - timedelta(days=1):
        return ""
    if d > anchor + timedelta(days=1100):
        return ""
    return d.isoformat()


_MONTHS = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "setiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}


def weekday_on_or_after(anchor: date, weekday: int) -> date:
    """First occurrence of weekday (Mon=0) on or after anchor (same day counts)."""
    delta = (weekday - anchor.weekday()) % 7
    return anchor + timedelta(days=delta)


def weekday_in_following_week(anchor: date, weekday: int) -> date:
    """That weekday in the calendar week after the week that contains anchor (Mon-Sun weeks)."""
    week_monday = anchor - timedelta(days=anchor.weekday())
    following_week_monday = week_monday + timedelta(days=7)
    return weekday_on_or_after(following_week_monday, weekday)


def end_of_week_friday(week_monday: date) -> date:
    """Friday (Mon=0 week) of the calendar week that starts on week_monday."""
    return week_monday + timedelta(days=4)


def infer_due_from_text(text_raw: str, anchor: date) -> str:
    """
    Relative / Spanish natural dates anchored to message day.
    Does not parse arbitrary past years from pasted articles.
    """
    text = (text_raw or "").lower()

    if "pasado mañana" in text or "pasado manana" in text:
        return clamp_due_iso((anchor + timedelta(days=2)).isoformat(), anchor)
    if re.search(r"\bmañana\b", text) or re.search(r"\bmanana\b", text):
        return clamp_due_iso((anchor + timedelta(days=1)).isoformat(), anchor)
    if re.search(r"\bhoy\b", text):
        return clamp_due_iso(anchor.isoformat(), anchor)

    weekday_names = [
        ("lunes", 0),
        ("martes", 1),
        ("miercoles", 2),
        ("miércoles", 2),
        ("jueves", 3),
        ("viernes", 4),
        ("sabado", 5),
        ("sábado", 5),
        ("domingo", 6),
    ]
    # "el próximo viernes" / "viernes que viene" -> that weekday in the *following* week
    for name, idx in weekday_names:
        if re.search(rf"\b(?:el\s+)?(?:próximo|proximo)\s+{re.escape(name)}\b", text):
            d = weekday_in_following_week(anchor, idx)
            return clamp_due_iso(d.isoformat(), anchor)
        if re.search(rf"\bel\s+{re.escape(name)}\s+que\s+viene\b", text):
            d = weekday_in_following_week(anchor, idx)
            return clamp_due_iso(d.isoformat(), anchor)
        if re.search(rf"\bpara\s+el\s+(?:próximo|proximo)\s+{re.escape(name)}\b", text):
            d = weekday_in_following_week(anchor, idx)
            return clamp_due_iso(d.isoformat(), anchor)

    # "el viernes" / "hasta el viernes" -> that weekday in the current week if still ahead, else next occurrence
    for name, idx in weekday_names:
        if (
            f"hasta el {name}" in text
            or f"para el {name}" in text
            or f"para este {name}" in text
            or re.search(rf"\beste\s+{re.escape(name)}\b", text)
            or re.search(rf"\bel\s+{re.escape(name)}\b", text)
        ):
            d = weekday_on_or_after(anchor, idx)
            return clamp_due_iso(d.isoformat(), anchor)

    m = re.search(
        r"\b(\d{1,2})\s+de\s+(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|setiembre|octubre|noviembre|diciembre)\s+de\s+(\d{4})\b",
        text,
    )
    if m:
        day, mon_name, y = int(m.group(1)), m.group(2), int(m.group(3))
        if y >= anchor.year:
            try:
                d = date(y, _MONTHS[mon_name], day)
                return clamp_due_iso(d.isoformat(), anchor)
            except Exception:
                pass

    m2 = re.search(
        r"\b(\d{1,2})\s+de\s+(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|setiembre|octubre|noviembre|diciembre)\b",
        text,
    )
    if m2:
        day = int(m2.group(1))
        mo = _MONTHS[m2.group(2)]
        y = anchor.year
        try:
            cand = date(y, mo, day)
        except Exception:
            cand = None
        if cand and cand < anchor:
            try:
                cand = date(y + 1, mo, day)
            except Exception:
                cand = None
        if cand:
            return clamp_due_iso(cand.isoformat(), anchor)

    if "esta semana" in text:
        week_monday = anchor - timedelta(days=anchor.weekday())
        d = end_of_week_friday(week_monday)
        return clamp_due_iso(d.isoformat(), anchor)

    if re.search(r"\b(?:la\s+)?(?:pr[oó]xima|siguiente)\s+semana\b", text):
        week_monday = anchor - timedelta(days=anchor.weekday())
        d = end_of_week_friday(week_monday + timedelta(days=7))
        return clamp_due_iso(d.isoformat(), anchor)

    if "próximo mes" in text or "proximo mes" in text:
        y = anchor.year + (1 if anchor.month == 12 else 0)
        m3 = 1 if anchor.month == 12 else anchor.month + 1
        d = date(y, m3, 1)
        return clamp_due_iso(d.isoformat(), anchor)

    return ""
