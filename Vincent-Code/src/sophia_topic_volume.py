"""Inventory embeddable text volume for a Sophia topic.

Shared by `scripts/map_topic_embedding_volume.py` and the Vincent MCP `map_topic` tool.
Resolves VIDEO/AUDIO transcripts and TEXT documents (PDF / EPUB).
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Optional

from src.embeddings.chunking import count_tokens
from src.embeddings.openai_embed import DEFAULT_EMBEDDING_MODEL
from src.sophia_topic_text import resolve_media_text, resolve_topic_description
from src.sophia_topics import SophiaTopicsClient
from src.sophia_transcript_ingest import SophiaTranscriptIngestClient


def map_topic_volume(
    project_root: str | Path,
    topic_id: int,
    *,
    content_id: Optional[int] = None,
    write_reports: bool = False,
    preview_chars: int = 0,
    topics_client: Optional[SophiaTopicsClient] = None,
    ingest_client: Optional[SophiaTranscriptIngestClient] = None,
) -> dict[str, Any]:
    """
    Resolve text for topic description + contents; return inventory JSON.

    TEXT items use PDF/EPUB extractors via resolve_media_text.
    When content_id is set, only that content row is included (plus description
    is omitted).
    """
    root = Path(project_root)
    topics = topics_client or SophiaTopicsClient()
    ingest = ingest_client or SophiaTranscriptIngestClient()
    topic = topics.get_topic(int(topic_id))

    units = []
    if content_id is None:
        units.append(resolve_topic_description(topic))
        items = topics.list_topic_contents(int(topic_id), include_images=False)
    else:
        items = [
            item
            for item in topics.list_topic_contents(int(topic_id), include_images=False)
            if int(item.get("id") or 0) == int(content_id)
        ]
        if not items:
            return {
                "ok": False,
                "error": f"content_id {content_id} not found in topic {topic_id}",
                "topic_id": int(topic_id),
                "title": topic.get("title"),
            }

    for item in items:
        units.append(
            resolve_media_text(
                project_root=root, item=item, ingest_client=ingest
            )
        )

    rows: list[dict[str, Any]] = []
    totals: dict[str, dict[str, int]] = defaultdict(
        lambda: {"items": 0, "ok": 0, "missing": 0, "skipped": 0, "chars": 0, "words": 0, "tokens_est": 0}
    )
    text_formats = {"pdf": 0, "epub": 0, "other_text": 0}

    for u in units:
        tokens = count_tokens(u.text, model=DEFAULT_EMBEDDING_MODEL) if u.text else 0
        words = len(u.text.split()) if u.text else 0
        bucket = totals[u.media_type]
        bucket["items"] += 1
        bucket[u.status] = bucket.get(u.status, 0) + 1
        bucket["chars"] += len(u.text)
        bucket["words"] += words
        bucket["tokens_est"] += tokens

        if u.media_type == "TEXT" and u.status == "ok":
            src = u.source or ""
            if src.startswith("s3_epub:"):
                text_formats["epub"] += 1
            elif src.startswith("s3_pdf:"):
                text_formats["pdf"] += 1
            else:
                text_formats["other_text"] += 1

        row: dict[str, Any] = {
            "content_id": u.content_id if u.content_id is not None else None,
            "media_type": u.media_type,
            "title": (u.title or "")[:160],
            "author": (u.author or "")[:80],
            "chars": len(u.text),
            "words": words,
            "tokens_est": tokens,
            "status": u.status,
            "text_source": u.source,
            "notes": u.notes,
        }
        if preview_chars > 0 and u.text:
            row["preview"] = u.text[: int(preview_chars)]
        rows.append(row)

    grand_tokens = sum(v["tokens_est"] for v in totals.values())
    summary: dict[str, Any] = {
        "ok": True,
        "topic_id": int(topic_id),
        "title": topic.get("title"),
        "model_for_token_count": DEFAULT_EMBEDDING_MODEL,
        "by_type": {k: dict(v) for k, v in totals.items()},
        "text_document_formats": text_formats,
        "grand_total_tokens_est": grand_tokens,
        "approx_chunks_800tok": round(grand_tokens / 800) if grand_tokens else 0,
        "approx_embedding_cost_usd_3_large": round(grand_tokens / 1_000_000 * 0.13, 4),
        "units": rows,
        "supports": {
            "VIDEO": "transcripts (captions / Whisper / local vault)",
            "AUDIO": "transcripts (Whisper / local vault)",
            "TEXT": "PDF and EPUB via sophia_document_extract",
            "TOPIC_DESCRIPTION": "topic.description from Sophia API",
        },
    }

    if write_reports:
        out_dir = root / "cache" / "topic_embeddings" / "reports"
        out_dir.mkdir(parents=True, exist_ok=True)
        csv_path = out_dir / f"topic_{topic_id}_embedding_volume_map.csv"
        json_path = out_dir / f"topic_{topic_id}_embedding_volume_map.json"
        flat_rows = []
        for row in rows:
            flat = dict(row)
            flat["content_id"] = "" if flat["content_id"] is None else flat["content_id"]
            flat.pop("preview", None)
            flat_rows.append(flat)
        with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
            fieldnames = list(flat_rows[0].keys()) if flat_rows else ["content_id"]
            w = csv.DictWriter(f, fieldnames=fieldnames)
            if flat_rows:
                w.writeheader()
                w.writerows(flat_rows)
        report = {k: v for k, v in summary.items() if k != "units"}
        json_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        summary["csv_path"] = str(csv_path)
        summary["json_path"] = str(json_path)

    return summary
