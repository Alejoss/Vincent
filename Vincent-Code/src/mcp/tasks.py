"""Vincent Notion task list + complete."""

from __future__ import annotations

import os
from typing import Any, Optional

from notion_client import Client

from src.notion_task_complete import (
    best_completion_match,
    choose_complete_status,
    list_open_tasks,
    mark_task_hecho,
)
from src.mcp.confirm import write_gate


def _normalize_id(block_id: str) -> str:
    s = (block_id or "").replace("-", "").strip()
    if len(s) == 32:
        return f"{s[0:8]}-{s[8:12]}-{s[12:16]}-{s[16:20]}-{s[20:32]}"
    return block_id or ""


def _pick_prop(props: dict[str, Any], candidates: list[str], types: list[str]) -> str:
    cands = [c.lower() for c in candidates]
    ranked: list[tuple[int, int, str]] = []
    for name, spec in props.items():
        t = (spec or {}).get("type")
        if t not in types:
            continue
        n = name.lower()
        for idx, c in enumerate(cands):
            if n == c:
                ranked.append((idx, 10_000, name))
                break
            if c in n:
                ranked.append((idx, len(c), name))
                break
    if not ranked:
        return ""
    ranked.sort(key=lambda x: (x[0], -x[1]))
    return ranked[0][2]


def _status_options(props: dict[str, Any], status_prop: str) -> list[str]:
    if not status_prop:
        return []
    opts = (((props.get(status_prop) or {}).get("status") or {}).get("options") or [])
    return [str(o.get("name", "")).strip() for o in opts if str(o.get("name", "")).strip()]


def _task_context() -> dict[str, Any]:
    token = (os.getenv("NOTION_API_TOKEN") or "").strip()
    raw_db = (os.getenv("NOTION_TASKS_DATABASE_ID") or "").strip()
    if not token:
        raise RuntimeError("Missing NOTION_API_TOKEN")
    if not raw_db:
        raise RuntimeError("Missing NOTION_TASKS_DATABASE_ID")
    database_id = _normalize_id(raw_db)
    client = Client(auth=token, notion_version="2025-09-03")
    db = client.databases.retrieve(database_id=database_id)
    data_sources = db.get("data_sources", []) or []
    ds_id = data_sources[0]["id"] if data_sources else database_id
    if ds_id == database_id:
        props = db.get("properties", {}) or {}
    else:
        ds = client.data_sources.retrieve(data_source_id=ds_id)
        props = ds.get("properties", {}) or {}
    title = _pick_prop(props, ["name", "titulo", "title", "tarea", "item"], ["title"])
    tipo = _pick_prop(props, ["tipo", "type"], ["select"])
    estado = _pick_prop(props, ["estado", "status"], ["status", "select"])
    notes = _pick_prop(
        props,
        ["slack procesado", "notas", "descripcion", "resumen"],
        ["rich_text"],
    )
    if not title:
        raise RuntimeError("Could not find the Notion title property.")
    return {
        "client": client,
        "database_id": database_id,
        "ds_id": ds_id,
        "title_prop": title,
        "tipo_prop": tipo,
        "status_prop": estado,
        "notes_prop": notes,
        "complete_name": choose_complete_status(_status_options(props, estado)),
    }


def _task_row(t) -> dict[str, Any]:
    return {
        "page_id": t.page_id,
        "title": t.title,
        "status": t.status,
        "text": (t.text or "")[:300],
        "score": getattr(t, "score", 0),
    }


def list_tasks(*, query: Optional[str] = None, limit: int = 20) -> dict[str, Any]:
    ctx = _task_context()
    open_tasks = list_open_tasks(
        ctx["client"],
        database_id=ctx["database_id"],
        ds_id=ctx["ds_id"],
        title_prop=ctx["title_prop"],
        status_prop=ctx["status_prop"],
        tipo_prop=ctx["tipo_prop"],
        notes_prop=ctx["notes_prop"],
    )
    q = (query or "").strip()
    if q:
        from src.notion_task_complete import rank_open_tasks

        ranked = rank_open_tasks(q, open_tasks, limit=int(limit))
        rows = [_task_row(t) for t in ranked]
    else:
        rows = [_task_row(t) for t in open_tasks[: max(1, int(limit))]]
    return {
        "ok": True,
        "count": len(rows),
        "open_total": len(open_tasks),
        "query": q or None,
        "tasks": rows,
    }


def complete_task(
    *,
    query: Optional[str] = None,
    page_id: Optional[str] = None,
    confirm: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    refused = write_gate(confirm, dry_run)
    if refused:
        return refused
    ctx = _task_context()
    if not ctx["status_prop"] or not ctx["complete_name"]:
        return {
            "ok": False,
            "error": "Cannot complete: Notion Estado / Hecho option not found.",
        }

    open_tasks = list_open_tasks(
        ctx["client"],
        database_id=ctx["database_id"],
        ds_id=ctx["ds_id"],
        title_prop=ctx["title_prop"],
        status_prop=ctx["status_prop"],
        tipo_prop=ctx["tipo_prop"],
        notes_prop=ctx["notes_prop"],
    )

    target = None
    pid = (page_id or "").strip()
    if pid:
        for t in open_tasks:
            if t.page_id.replace("-", "") == pid.replace("-", ""):
                target = t
                break
        if target is None:
            return {"ok": False, "error": f"No open task with page_id={pid}"}
    else:
        q = (query or "").strip()
        if not q:
            return {"ok": False, "error": "Pass query or page_id to complete a task."}
        target = best_completion_match(q, open_tasks, min_score=4)
        if target is None:
            from src.notion_task_complete import rank_open_tasks

            candidates = [_task_row(t) for t in rank_open_tasks(q, open_tasks, limit=5)]
            return {
                "ok": False,
                "error": "No confident match. Pass page_id from list_open_tasks.",
                "candidates": candidates,
            }

    ok, detail = mark_task_hecho(
        ctx["client"],
        page_id=target.page_id,
        status_prop=ctx["status_prop"],
        status_name=ctx["complete_name"],
        dry_run=dry_run,
    )
    return {
        "ok": ok,
        "detail": detail,
        "dry_run": dry_run,
        "task": _task_row(target),
        "status_name": ctx["complete_name"],
    }
