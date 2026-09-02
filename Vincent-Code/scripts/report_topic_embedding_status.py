#!/usr/bin/env python3
"""Report which Sophia topic embeddings are ready vs still need work.

Uses the embedding-ingest queue (source of truth for VIDEO/AUDIO with a
transcript) plus the public topics list. Optionally counts VIDEO/AUDIO on
each topic so contents without a transcript show up as needs_transcripts.

Examples:
  python scripts/report_topic_embedding_status.py
  python scripts/report_topic_embedding_status.py --topic-id 12
  python scripts/report_topic_embedding_status.py --skip-av-count
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv(PROJECT_ROOT / ".env", override=True)

from src.embeddings.status_report import (  # noqa: E402
    collect_topic_status,
    count_embedding_statuses,
)
from src.embeddings.store import EmbeddingStore  # noqa: E402
from src.pipeline_logging import setup_pipeline_logging  # noqa: E402
from src.sophia_embedding_ingest import (  # noqa: E402
    SophiaEmbeddingIngestClient,
    SophiaEmbeddingIngestError,
)
from src.sophia_topics import SophiaTopicsClient  # noqa: E402

REPORT_DIR = PROJECT_ROOT / "cache" / "topic_embeddings" / "reports"
DEFAULT_DB = PROJECT_ROOT / "cache" / "topic_embeddings" / "state.sqlite3"


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _local_overlay(db_path: Path, topic_id: int) -> Optional[dict[str, Any]]:
    if not db_path.is_file():
        return None
    store = EmbeddingStore(db_path)
    try:
        return {
            "documents": store.topic_stats(topic_id),
            "qdrant_sync": store.qdrant_sync_stats(topic_id),
        }
    finally:
        store.close()


def run(args: argparse.Namespace) -> int:
    log, log_file = setup_pipeline_logging(
        "topic_embedding_status", verbose=args.verbose
    )
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    db_path = Path(args.db) if args.db else DEFAULT_DB

    topics_client = SophiaTopicsClient()
    try:
        sophia = SophiaEmbeddingIngestClient()
    except ValueError as exc:
        log.error("Sophia ingest no configurado: %s", exc)
        return 1

    try:
        if not sophia.is_available():
            log.error(
                "embedding-ingest 404. Despliega Sophia o comprueba SOPHIA_API_BASE."
            )
            return 1
    except SophiaEmbeddingIngestError as exc:
        log.error("No se pudo hablar con embedding-ingest: %s", exc)
        return 1

    if args.topic_id is not None:
        topic = topics_client.get_topic(int(args.topic_id))
        topics = [topic]
        log.info("Topic %s — %s", args.topic_id, topic.get("title"))
    else:
        topics = topics_client.list_topics()
        log.info("Public topics: %s", len(topics))

    try:
        topic_rows, content_rows = collect_topic_status(
            topics_client,
            sophia,
            topics,
            skip_av_count=args.skip_av_count,
        )
    except SophiaEmbeddingIngestError as exc:
        log.error("Queue fetch failed: %s", exc)
        return 1

    buckets: dict[str, list[str]] = defaultdict(list)
    for row in topic_rows:
        if args.include_local:
            overlay = _local_overlay(db_path, int(row["topic_id"]))
            if overlay:
                row["local"] = overlay
        title = row.get("title") or f"topic-{row['topic_id']}"
        buckets[row["bucket"]].append(f"#{row['topic_id']} {title}")
        log.info(
            "  [%s] #%s %s | av=%s transcribed=%s indexed=%s pending=%s stale=%s failed=%s missing_tx=%s",
            row["bucket"],
            row["topic_id"],
            title[:50],
            row["av_count"],
            row["transcribed_count"],
            row["indexed"],
            row["pending"],
            row["stale"],
            row["failed"],
            row["missing_transcripts"],
        )

    totals = count_embedding_statuses(
        [{"embedding_status": r["embedding_status"]} for r in content_rows]
    )
    summary = {
        "generated_at": _now(),
        "topic_filter": args.topic_id,
        "topic_count": len(topic_rows),
        "content_count": len(content_rows),
        "by_bucket": {k: len(v) for k, v in sorted(buckets.items())},
        "embedding_status_totals": totals,
        "topics_needing_embeddings": [
            r for r in topic_rows if r["needs_embeddings"]
        ],
        "topics_ready": [r for r in topic_rows if r["ready"]],
        "topics_needing_transcripts": [
            r for r in topic_rows if r["needs_transcripts"] and not r["needs_embeddings"]
        ],
        "topics": topic_rows,
    }

    json_path = REPORT_DIR / "topic_embedding_status_latest.json"
    topics_csv = REPORT_DIR / "topic_embedding_status_topics.csv"
    contents_csv = REPORT_DIR / "topic_embedding_status_contents.csv"
    json_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    csv_topic_rows = [{k: v for k, v in row.items() if k != "local"} for row in topic_rows]
    _write_csv(topics_csv, csv_topic_rows)
    _write_csv(contents_csv, content_rows)

    log.info("")
    log.info("==== Topics that NEED embeddings (pending/stale/failed) ====")
    needing = summary["topics_needing_embeddings"]
    if not needing:
        log.info("  (none)")
    for row in needing:
        log.info(
            "  #%s %s | pending=%s stale=%s failed=%s indexed=%s",
            row["topic_id"],
            row["title"],
            row["pending"],
            row["stale"],
            row["failed"],
            row["indexed"],
        )

    log.info("==== Topics READY (all transcribed AV indexed) ====")
    ready = summary["topics_ready"]
    if not ready:
        log.info("  (none)")
    for row in ready:
        log.info("  #%s %s | indexed=%s", row["topic_id"], row["title"], row["indexed"])

    log.info("==== Topics that need transcripts first (no embed queue yet) ====")
    waiting = summary["topics_needing_transcripts"]
    if not waiting:
        log.info("  (none)")
    for row in waiting:
        log.info(
            "  #%s %s | av=%s missing_tx=%s",
            row["topic_id"],
            row["title"],
            row["av_count"],
            row["missing_transcripts"],
        )

    log.info("Totals by embedding_status: %s", json.dumps(totals))
    log.info("JSON: %s", json_path)
    log.info("Topics CSV: %s", topics_csv)
    log.info("Contents CSV: %s", contents_csv)
    log.info("Finished. Log: %s", log_file)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Report Sophia topic embedding readiness (queue + public topics)"
    )
    parser.add_argument(
        "--topic-id",
        type=int,
        default=None,
        help="Only this topic (default: all public topics)",
    )
    parser.add_argument(
        "--skip-av-count",
        action="store_true",
        help="Do not list VIDEO/AUDIO per topic (faster; cannot detect missing transcripts)",
    )
    parser.add_argument(
        "--include-local",
        action="store_true",
        help="Attach local SQLite document/qdrant_sync stats when the cache exists",
    )
    parser.add_argument("--db", default="", help="Local embedding SQLite path")
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser


if __name__ == "__main__":
    raise SystemExit(run(build_parser().parse_args()))
