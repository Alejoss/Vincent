"""Topic RAG + embed/sync/pipeline jobs."""

from __future__ import annotations

from typing import Any, Optional

from src.embeddings.query import search_topic_local
from src.mcp.confirm import write_gate
from src.mcp.jobs import run_script
from src.mcp.paths import PROJECT_ROOT
from src.sophia_topic_volume import map_topic_volume


def search_topic(
    question: str,
    topic_id: int,
    *,
    top_k: int = 8,
    answer: bool = False,
) -> dict[str, Any]:
    return search_topic_local(
        question=question,
        topic_id=int(topic_id),
        project_root=PROJECT_ROOT,
        top_k=int(top_k),
        answer=bool(answer),
    )


def map_topic(
    topic_id: int,
    *,
    content_id: Optional[int] = None,
    preview_chars: int = 0,
) -> dict[str, Any]:
    """Inventory embeddable text (incl. TEXT PDF/EPUB resolution status)."""
    return map_topic_volume(
        PROJECT_ROOT,
        int(topic_id),
        content_id=int(content_id) if content_id is not None else None,
        write_reports=False,
        preview_chars=int(preview_chars),
    )


def embed_topic(
    topic_id: int,
    *,
    confirm: bool = False,
    dry_run: bool = False,
    force: bool = False,
    wait: bool = False,
) -> dict[str, Any]:
    refused = write_gate(confirm, dry_run)
    if refused:
        return refused
    args = ["--topic-id", str(int(topic_id))]
    if dry_run:
        args.append("--dry-run")
    if force:
        args.append("--force")
    return run_script(
        "embed_topic",
        "embed_topic.py",
        args,
        wait=wait,
        timeout_s=1800,
        dry_run=dry_run,
    )


def sync_topic(
    topic_id: int,
    *,
    confirm: bool = False,
    dry_run: bool = False,
    force: bool = False,
    mode: str = "queue",
    wait: bool = False,
) -> dict[str, Any]:
    refused = write_gate(confirm, dry_run)
    if refused:
        return refused
    args = ["--topic-id", str(int(topic_id)), "--mode", mode, "--also-sqlite-extras"]
    if dry_run:
        args.append("--dry-run")
    if force:
        args.append("--force")
    return run_script(
        "sync_topic",
        "sync_topic_embeddings_to_qdrant.py",
        args,
        wait=wait,
        timeout_s=1800,
        dry_run=dry_run,
    )


def run_topic_pipeline(
    topic_id: int,
    *,
    confirm: bool = False,
    dry_run: bool = False,
    force: bool = False,
    wait: bool = False,
    skip_map: bool = False,
) -> dict[str, Any]:
    refused = write_gate(confirm, dry_run)
    if refused:
        return refused
    args = ["--topic-id", str(int(topic_id))]
    if dry_run:
        args.append("--dry-run")
    if force:
        args.append("--force")
    if skip_map:
        args.append("--skip-map")
    return run_script(
        "topic_pipeline",
        "run_topic_knowledge_pipeline.py",
        args,
        wait=wait,
        timeout_s=3600,
        dry_run=dry_run,
    )
