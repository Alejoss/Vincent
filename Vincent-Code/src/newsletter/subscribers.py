"""Load subscribers from Obsidian markdown table (primary) or CSV segments (fallback)."""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path

from .config import DEFAULT_MD_DIR, SEGMENTS_DIR, load_config

TABLE_ROW_RE = re.compile(r"^\|.+\|$")
ACTIVE_TRUE = {"1", "true", "yes", "y", "si", "sí", "s", "activo", "active"}
ACTIVE_FALSE = {"0", "false", "no", "n", "inactivo", "inactive"}


@dataclass
class Subscriber:
    email: str
    name: str = ""
    segment: str = "general"
    active: bool = True
    notes: str = ""
    extra: dict[str, str] = field(default_factory=dict)


def default_subscribers_path(md_dir: Path | None = None) -> Path:
    root = md_dir or load_config().md_dir
    return root / "suscriptores.md"


def _normalize_header(value: str) -> str:
    return value.strip().lower().replace(" ", "_")


def _column_map(headers: list[str]) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for idx, raw in enumerate(headers):
        key = _normalize_header(raw)
        mapping[key] = idx
        if key in ("correo", "e-mail", "mail"):
            mapping.setdefault("email", idx)
        if key in ("name", "nombre"):
            mapping.setdefault("name", idx)
        if key in ("segment", "segmento", "lista"):
            mapping.setdefault("segment", idx)
        if key in ("active", "activo"):
            mapping.setdefault("active", idx)
        if key in ("notes", "notas", "comentarios"):
            mapping.setdefault("notes", idx)
    return mapping


def _parse_active(value: str) -> bool:
    v = (value or "").strip().lower()
    if not v:
        return True
    if v in ACTIVE_TRUE:
        return True
    if v in ACTIVE_FALSE:
        return False
    return True


def _cell(row: list[str], col_map: dict[str, int], key: str) -> str:
    idx = col_map.get(key)
    if idx is None or idx >= len(row):
        return ""
    return row[idx].strip()


def parse_markdown_tables(text: str) -> list[list[dict[str, str]]]:
    """Extract all pipe tables from markdown."""
    tables: list[list[dict[str, str]]] = []
    headers: list[str] | None = None
    current_rows: list[dict[str, str]] = []

    def flush() -> None:
        nonlocal headers, current_rows
        if headers and current_rows:
            tables.append(current_rows)
        headers = None
        current_rows = []

    for line in text.splitlines():
        line = line.strip()
        if not TABLE_ROW_RE.match(line):
            flush()
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if not any(cells):
            continue
        if all(set(c) <= {"-", ":", " "} for c in cells):
            continue
        if headers is None:
            headers = cells
            current_rows = []
            continue
        row_dict = {headers[i]: cells[i] if i < len(cells) else "" for i in range(len(headers))}
        current_rows.append(row_dict)

    flush()
    return tables


def parse_markdown_table(text: str) -> list[dict[str, str]]:
    """Return rows from the first pipe table that includes an email column."""
    for table in parse_markdown_tables(text):
        if not table:
            continue
        headers = list(table[0].keys())
        if "email" in {_normalize_header(h) for h in headers}:
            return table
        if any(_normalize_header(h) in ("correo", "e-mail", "mail") for h in headers):
            return table
    return []


def load_all_subscribers(subscribers_path: Path | None = None) -> list[Subscriber]:
    path = subscribers_path or default_subscribers_path()
    if not path.is_file():
        return []

    text = path.read_text(encoding="utf-8")
    table_rows = parse_markdown_table(text)
    if not table_rows:
        return []

    headers = list(table_rows[0].keys())
    col_map = _column_map(headers)
    if "email" not in col_map:
        raise ValueError(f"La tabla en {path} debe tener columna 'email'.")

    subscribers: list[Subscriber] = []
    seen: set[tuple[str, str]] = set()

    for row_dict in table_rows:
        cells = [row_dict.get(h, "") for h in headers]
        email = _cell(cells, col_map, "email").lower()
        if not email or "@" not in email:
            continue

        name = _cell(cells, col_map, "name")
        segment = (_cell(cells, col_map, "segment") or "general").strip().lower()
        active = _parse_active(_cell(cells, col_map, "active"))
        notes = _cell(cells, col_map, "notes")

        key = (email, segment)
        if key in seen:
            continue
        seen.add(key)

        known = {"email", "name", "nombre", "segment", "segmento", "lista", "active", "activo", "notes", "notas", "comentarios"}
        extra: dict[str, str] = {}
        for h in headers:
            nk = _normalize_header(h)
            if nk in known or nk.replace("_", "") in {k.replace("_", "") for k in known}:
                continue
            val = row_dict.get(h, "").strip()
            if val:
                extra[h] = val

        subscribers.append(
            Subscriber(
                email=email,
                name=name,
                segment=segment,
                active=active,
                notes=notes,
                extra=extra,
            )
        )

    return subscribers


def load_segment(segment: str, segments_dir: Path | None = None) -> list[Subscriber]:
    """Active subscribers for a segment. Obsidian table first, then CSV fallback."""
    obsidian_path = default_subscribers_path()
    if obsidian_path.is_file():
        all_subs = load_all_subscribers(obsidian_path)
        filtered = [s for s in all_subs if s.active and s.segment == segment]
        if filtered:
            return filtered
        if any(s.segment == segment for s in all_subs):
            return filtered
        if segment == "test" and not filtered:
            raise FileNotFoundError(
                f"Segmento '{segment}' sin suscriptores activos en {obsidian_path}"
            )

    return _load_segment_csv(segment, segments_dir)


def _load_segment_csv(segment: str, segments_dir: Path | None = None) -> list[Subscriber]:
    root = segments_dir or load_config().segments_dir
    path = root / f"{segment}.csv"
    if not path.is_file():
        raise FileNotFoundError(
            f"Segmento no encontrado: '{segment}'. "
            f"Añade filas en newsletters/suscriptores.md o crea {path}"
        )

    subscribers: list[Subscriber] = []
    seen: set[str] = set()

    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames or "email" not in [f.lower() for f in reader.fieldnames]:
            raise ValueError(f"CSV debe tener columna 'email': {path}")

        email_key = next(f for f in reader.fieldnames if f.lower() == "email")
        name_key = next((f for f in reader.fieldnames if f.lower() == "name"), None)

        for row in reader:
            email = (row.get(email_key) or "").strip().lower()
            if not email or "@" not in email or email in seen:
                continue
            seen.add(email)
            name = (row.get(name_key) or "").strip() if name_key else ""
            subscribers.append(Subscriber(email=email, name=name, segment=segment))

    return subscribers


def list_segments(segments_dir: Path | None = None) -> list[str]:
    obsidian_path = default_subscribers_path()
    if obsidian_path.is_file():
        segments = sorted({s.segment for s in load_all_subscribers(obsidian_path) if s.active})
        if segments:
            return segments

    root = segments_dir or SEGMENTS_DIR
    if not root.is_dir():
        return []
    return sorted(p.stem for p in root.glob("*.csv"))


def list_segment_counts(segments_dir: Path | None = None) -> dict[str, int]:
    obsidian_path = default_subscribers_path()
    if obsidian_path.is_file():
        counts: dict[str, int] = {}
        for sub in load_all_subscribers(obsidian_path):
            if not sub.active:
                continue
            counts[sub.segment] = counts.get(sub.segment, 0) + 1
        if counts:
            return dict(sorted(counts.items()))

    root = segments_dir or SEGMENTS_DIR
    counts = {}
    if not root.is_dir():
        return counts
    for csv_path in sorted(root.glob("*.csv")):
        try:
            counts[csv_path.stem] = len(_load_segment_csv(csv_path.stem, root))
        except (ValueError, FileNotFoundError):
            counts[csv_path.stem] = 0
    return counts


def subscriber_source_label() -> str:
    if default_subscribers_path().is_file():
        return str(default_subscribers_path())
    return str(SEGMENTS_DIR)
