"""Knowledge extraction search, status, and job wrappers."""

from __future__ import annotations

from typing import Any, Optional

from src.knowledge_engine_state import (
    list_extractions,
    open_engine,
    search_knowledge_items,
    state_db_path,
    summary_counts,
)
from src.mcp.confirm import write_gate
from src.mcp.jobs import run_script
from src.mcp.paths import PROJECT_ROOT

DEFAULT_EXTRACT_LIMIT = 3
MAX_EXTRACT_LIMIT = 20


def knowledge_status(*, limit: int = 15) -> dict[str, Any]:
    db = state_db_path(PROJECT_ROOT)
    if not db.is_file():
        return {
            "ok": False,
            "error": f"Knowledge engine DB not found: {db}",
            "db_path": str(db),
        }
    conn = open_engine(PROJECT_ROOT)
    try:
        counts = summary_counts(conn)
        recent = list_extractions(conn)[: max(1, int(limit))]
    finally:
        conn.close()
    return {
        "ok": True,
        "db_path": str(db.resolve()),
        "counts": counts,
        "recent": [
            {
                "video_id": row.get("video_id"),
                "title": row.get("title"),
                "status": row.get("status"),
                "summary": (row.get("summary") or "")[:240],
                "output_md_path": row.get("output_md_path"),
                "error": row.get("error"),
                "updated_at": row.get("updated_at"),
            }
            for row in recent
        ],
    }


def search_knowledge(
    query: str,
    *,
    limit: int = 12,
    item_type: Optional[str] = None,
) -> dict[str, Any]:
    q = (query or "").strip()
    if not q:
        return {"ok": False, "error": "query is empty"}
    db = state_db_path(PROJECT_ROOT)
    if not db.is_file():
        return {
            "ok": False,
            "error": f"Knowledge engine DB not found: {db}",
            "db_path": str(db),
        }
    conn = open_engine(PROJECT_ROOT)
    try:
        rows = search_knowledge_items(
            conn, q, limit=int(limit), item_type=item_type or None
        )
    finally:
        conn.close()
    hits = []
    for row in rows:
        payload = row.get("payload") or ""
        hits.append(
            {
                "item_id": row.get("item_id"),
                "item_type": row.get("item_type"),
                "item_key": row.get("item_key"),
                "title": row.get("title"),
                "video_id": row.get("video_id"),
                "summary": (row.get("summary") or "")[:240],
                "anchor_text": (row.get("anchor_text") or "")[:240],
                "payload_excerpt": payload[:500] + ("…" if len(payload) > 500 else ""),
                "output_md_path": row.get("output_md_path"),
            }
        )
    return {
        "ok": True,
        "query": q,
        "count": len(hits),
        "hits": hits,
        "db_path": str(db.resolve()),
    }


def extract_knowledge(
    *,
    confirm: bool = False,
    dry_run: bool = False,
    limit: int = DEFAULT_EXTRACT_LIMIT,
    transcript_id: Optional[str] = None,
    retry_failed: bool = False,
    wait: bool = True,
) -> dict[str, Any]:
    refused = write_gate(confirm, dry_run)
    if refused:
        return refused
    if not transcript_id and (not limit or int(limit) <= 0):
        return {
            "ok": False,
            "error": (
                "Refusing unbounded extract. Pass a positive limit "
                f"(max {MAX_EXTRACT_LIMIT}) or transcript_id."
            ),
        }
    if not transcript_id and int(limit) > MAX_EXTRACT_LIMIT:
        return {
            "ok": False,
            "error": f"limit={limit} exceeds max {MAX_EXTRACT_LIMIT} for MCP.",
        }

    args: list[str] = []
    if transcript_id:
        args.extend(["--id", transcript_id])
    elif limit:
        args.extend(["--limit", str(int(limit))])
    if retry_failed:
        args.append("--retry-failed")
    if dry_run:
        args.append("--dry-run")
    return run_script(
        "extract_knowledge",
        "extract_own_transcript_knowledge.py",
        args,
        wait=wait,
        timeout_s=900,
        dry_run=dry_run,
    )
