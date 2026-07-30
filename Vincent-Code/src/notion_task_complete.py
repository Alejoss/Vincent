"""
Match an open Notion task and mark it completed (Hecho).

Used by Obsidian→Notion sync when classification says `intencion=completar`.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from notion_client import Client

STATUS_COMPLETE_CANDIDATES = (
    "Hecho",
    "Completado",
    "Completada",
    "Terminado",
    "Terminada",
    "Listo",
    "Lista",
    "Done",
    "Completed",
)

DEFAULT_TERMINAL = STATUS_COMPLETE_CANDIDATES + (
    "Eliminada",
    "Eliminado",
    "Cancelada",
    "Cancelado",
    "Descartada",
    "Descartado",
    "Archivada",
    "Archivado",
    "Deleted",
    "Cancelled",
    "Canceled",
)


def _normalize_text(value: str) -> str:
    raw = unicodedata.normalize("NFKD", value or "")
    stripped = "".join(ch for ch in raw if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", stripped.lower()).strip()


def _tokens(value: str) -> List[str]:
    return [t for t in re.split(r"[^a-z0-9áéíóúñü]+", _normalize_text(value)) if len(t) > 2]


@dataclass
class OpenTask:
    page_id: str
    title: str
    status: str
    text: str
    score: int = 0


def _prop_plain(props: Dict[str, Any], name: str) -> str:
    if not name:
        return ""
    spec = props.get(name) or {}
    t = spec.get("type")
    if t == "title":
        parts = spec.get("title") or []
        return "".join((p.get("plain_text") or "") for p in parts).strip()
    if t == "rich_text":
        parts = spec.get("rich_text") or []
        return "".join((p.get("plain_text") or "") for p in parts).strip()
    if t == "select":
        sel = spec.get("select") or {}
        return str(sel.get("name") or "").strip()
    if t == "status":
        st = spec.get("status") or {}
        return str(st.get("name") or "").strip()
    return ""


def _score(query: str, title: str, text: str) -> int:
    q_tokens = set(_tokens(query))
    if not q_tokens:
        return 0
    score = len(q_tokens & set(_tokens(text)))
    score += 2 * len(q_tokens & set(_tokens(title)))
    q_norm = _normalize_text(query)
    title_norm = _normalize_text(title)
    if title_norm and title_norm in q_norm:
        score += 8
    if title_norm and q_norm and (title_norm == q_norm or title_norm in q_norm or q_norm in title_norm):
        score += 6
    return score


def list_open_tasks(
    client: Client,
    *,
    database_id: str,
    ds_id: str,
    title_prop: str,
    status_prop: str,
    tipo_prop: str,
    notes_prop: str = "",
    terminal_statuses: Optional[Iterable[str]] = None,
) -> List[OpenTask]:
    terminal = {_normalize_text(s) for s in (terminal_statuses or DEFAULT_TERMINAL)}
    out: List[OpenTask] = []
    cursor = None
    while True:
        kwargs: Dict[str, Any] = {"page_size": 100}
        if cursor:
            kwargs["start_cursor"] = cursor
        if ds_id == database_id:
            resp = client.databases.query(database_id=database_id, **kwargs)
        else:
            resp = client.data_sources.query(data_source_id=ds_id, **kwargs)
        for page in resp.get("results") or []:
            if page.get("archived"):
                continue
            props = page.get("properties") or {}
            tipo = _prop_plain(props, tipo_prop)
            if tipo and tipo not in {"Tarea", "Idea"}:
                continue
            status = _prop_plain(props, status_prop)
            if status and _normalize_text(status) in terminal:
                continue
            title = _prop_plain(props, title_prop)
            notes = _prop_plain(props, notes_prop) if notes_prop else ""
            out.append(
                OpenTask(
                    page_id=str(page.get("id") or ""),
                    title=title,
                    status=status,
                    text=(notes or title)[:500],
                )
            )
        if not resp.get("has_more"):
            break
        cursor = resp.get("next_cursor")
    return out


def rank_open_tasks(query: str, tasks: Sequence[OpenTask], *, limit: int = 8) -> List[OpenTask]:
    ranked: List[OpenTask] = []
    for t in tasks:
        ranked.append(
            OpenTask(
                page_id=t.page_id,
                title=t.title,
                status=t.status,
                text=t.text,
                score=_score(query, t.title, t.text),
            )
        )
    ranked.sort(key=lambda c: (-c.score, c.title.lower()))
    positive = [c for c in ranked if c.score > 0]
    if positive:
        return positive[:limit]
    return list(ranked[: min(limit, 10)])


def choose_complete_status(options: Sequence[str]) -> str:
    normalized = {_normalize_text(o): o for o in options}
    for wanted in STATUS_COMPLETE_CANDIDATES:
        found = normalized.get(_normalize_text(wanted))
        if found:
            return found
    for option in options:
        opt_norm = _normalize_text(option)
        for wanted in STATUS_COMPLETE_CANDIDATES:
            w = _normalize_text(wanted)
            if w in opt_norm or opt_norm in w:
                return option
    return ""


def mark_task_hecho(
    client: Client,
    *,
    page_id: str,
    status_prop: str,
    status_name: str,
    dry_run: bool = False,
) -> Tuple[bool, str]:
    if not page_id or not status_prop or not status_name:
        return False, "Missing page_id/status for completion."
    detail = f"Estado -> {status_name}"
    if dry_run:
        return True, f"[dry-run] would update {page_id}: {detail}"
    client.pages.update(
        page_id=page_id,
        properties={status_prop: {"status": {"name": status_name}}},
    )
    return True, detail


def best_completion_match(
    query: str,
    tasks: Sequence[OpenTask],
    *,
    min_score: int = 4,
) -> Optional[OpenTask]:
    ranked = rank_open_tasks(query, tasks, limit=5)
    if not ranked:
        return None
    top = ranked[0]
    if top.score < min_score:
        return None
    if len(ranked) > 1 and ranked[1].score == top.score and top.score < 10:
        # Ambiguous tie among weak matches.
        return None
    return top
