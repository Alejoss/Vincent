"""Classify Sophia topic/content embedding readiness (no I/O)."""

from __future__ import annotations

from collections import Counter
from typing import Any, Optional

NEEDING_EMBED_STATUSES = frozenset({"pending", "stale", "failed"})
ALL_EMBED_STATUSES = ("pending", "stale", "failed", "indexed", "skipped")


def normalize_status(raw: Any) -> str:
    value = str(raw or "unknown").strip().lower()
    return value or "unknown"


def count_embedding_statuses(items: list[dict[str, Any]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for item in items:
        counts[normalize_status(item.get("embedding_status"))] += 1
    return {status: int(counts.get(status, 0)) for status in ALL_EMBED_STATUSES} | {
        status: n for status, n in counts.items() if status not in ALL_EMBED_STATUSES
    }


def needing_embed_count(status_counts: dict[str, int]) -> int:
    return sum(int(status_counts.get(status, 0) or 0) for status in NEEDING_EMBED_STATUSES)


def classify_topic(
    *,
    av_count: int,
    transcribed_count: int,
    status_counts: dict[str, int],
) -> str:
    """
    Bucket for one topic.

    ready — transcribed VIDEO/AUDIO are all indexed; none pending/stale/failed
    needs_embeddings — at least one pending/stale/failed
    needs_transcripts — VIDEO/AUDIO exist but none have a transcript yet
    partial — some indexed, but other AV still lack transcripts
    skipped_only — worker skipped everything; nothing left to index
    no_av — no VIDEO/AUDIO on the topic
    """
    av_count = max(0, int(av_count))
    transcribed_count = max(0, int(transcribed_count))
    needing = needing_embed_count(status_counts)
    indexed = int(status_counts.get("indexed", 0) or 0)
    skipped = int(status_counts.get("skipped", 0) or 0)
    missing_transcripts = max(0, av_count - transcribed_count)

    if av_count == 0:
        return "no_av"
    if needing > 0:
        return "needs_embeddings"
    if transcribed_count == 0:
        return "needs_transcripts"
    if missing_transcripts > 0:
        return "partial"
    if indexed > 0:
        return "ready"
    if skipped > 0:
        return "skipped_only"
    return "needs_embeddings"


def topic_summary_row(
    *,
    topic: dict[str, Any],
    av_count: int,
    items: list[dict[str, Any]],
    status_counts: Optional[dict[str, int]] = None,
) -> dict[str, Any]:
    counts = status_counts or count_embedding_statuses(items)
    transcribed_count = len(items)
    missing_transcripts = max(0, int(av_count) - transcribed_count)
    needing = needing_embed_count(counts)
    indexed = int(counts.get("indexed", 0) or 0)
    bucket = classify_topic(
        av_count=av_count,
        transcribed_count=transcribed_count,
        status_counts=counts,
    )
    return {
        "topic_id": topic.get("id"),
        "title": topic.get("title") or "",
        "chat_enabled": bool(topic.get("chat_enabled")),
        "chat_can_enable": bool(topic.get("chat_can_enable")),
        "indexed_transcript_count_api": topic.get("indexed_transcript_count"),
        "av_count": int(av_count),
        "transcribed_count": transcribed_count,
        "missing_transcripts": missing_transcripts,
        "indexed": indexed,
        "pending": int(counts.get("pending", 0) or 0),
        "stale": int(counts.get("stale", 0) or 0),
        "failed": int(counts.get("failed", 0) or 0),
        "skipped": int(counts.get("skipped", 0) or 0),
        "needing_embeddings": needing,
        "bucket": bucket,
        "needs_embeddings": needing > 0,
        "needs_transcripts": missing_transcripts > 0,
        "ready": bucket == "ready",
    }


def content_rows_for_topic(
    topic_id: int,
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in items:
        status = normalize_status(item.get("embedding_status"))
        rows.append(
            {
                "topic_id": int(topic_id),
                "content_id": item.get("id"),
                "media_type": item.get("media_type") or "",
                "title": (item.get("original_title") or "")[:160],
                "embedding_status": status,
                "needs_embeddings": status in NEEDING_EMBED_STATUSES,
                "chunk_count": item.get("chunk_count"),
                "embedding_model": item.get("embedding_model") or "",
                "embedded_at": item.get("embedded_at") or "",
                "text_hash": item.get("text_hash") or "",
            }
        )
    return rows


def collect_topic_status(
    topics_client: Any,
    embedding_client: Any,
    topics: list[dict[str, Any]],
    *,
    skip_av_count: bool = False,
    av_types: tuple[str, ...] = ("VIDEO", "AUDIO"),
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Fetch embedding-ingest + optional AV counts; return (topic_rows, content_rows)."""
    topic_rows: list[dict[str, Any]] = []
    content_rows: list[dict[str, Any]] = []
    for topic in topics:
        topic_id = int(topic["id"])
        items = embedding_client.list_queue_all(
            topic_id=topic_id,
            include_completed=True,
        )
        av_count = len(items)
        if not skip_av_count:
            av_contents = topics_client.list_topic_contents(
                topic_id, media_types=av_types
            )
            av_count = len(av_contents)
        row = topic_summary_row(topic=topic, av_count=av_count, items=items)
        topic_rows.append(row)
        content_rows.extend(content_rows_for_topic(topic_id, items))
    return topic_rows, content_rows
