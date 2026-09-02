#!/usr/bin/env python3
"""Sync Sophia topic embedding status into a Notion database.

Cursor agents can then query that database via Notion MCP (once authenticated)
without calling Sophia embedding-ingest.

Examples:
  python scripts/sync_topic_embedding_status_to_notion.py --create-under-page PAGE_ID
  python scripts/sync_topic_embedding_status_to_notion.py
  python scripts/sync_topic_embedding_status_to_notion.py --topic-id 12 --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv(PROJECT_ROOT / ".env", override=True)

from src.embeddings.notion_status import (  # noqa: E402
    EmbeddingStatusNotionClient,
    create_database,
    row_to_properties,
)
from src.embeddings.status_report import collect_topic_status  # noqa: E402
from src.pipeline_logging import setup_pipeline_logging  # noqa: E402
from src.sophia_embedding_ingest import (  # noqa: E402
    SophiaEmbeddingIngestClient,
    SophiaEmbeddingIngestError,
)
from src.sophia_topics import SophiaTopicsClient  # noqa: E402


def _load_topics(topics_client: SophiaTopicsClient, topic_id: Any) -> list[dict]:
    if topic_id is not None:
        return [topics_client.get_topic(int(topic_id))]
    return topics_client.list_topics()


def run(args: argparse.Namespace) -> int:
    log, log_file = setup_pipeline_logging(
        "notion_embedding_status", verbose=args.verbose
    )
    token = (os.getenv("NOTION_API_TOKEN") or "").strip()
    if not token:
        log.error("NOTION_API_TOKEN is required")
        return 1

    db_id = (args.database_id or os.getenv("NOTION_EMBEDDING_STATUS_DATABASE_ID") or "").strip()
    if args.create_under_page:
        if db_id and not args.force_create:
            log.error(
                "NOTION_EMBEDDING_STATUS_DATABASE_ID already set (%s). "
                "Pass --force-create to make a new database anyway.",
                db_id,
            )
            return 1
        log.info("Creating Notion database under page %s …", args.create_under_page)
        db_id = create_database(api_token=token, parent_page_id=args.create_under_page)
        log.info("Created database id=%s", db_id)
        log.info("Put this in .env: NOTION_EMBEDDING_STATUS_DATABASE_ID=%s", db_id)

    if not db_id:
        log.error(
            "NOTION_EMBEDDING_STATUS_DATABASE_ID is required "
            "(or pass --create-under-page PAGE_ID)"
        )
        return 1

    topics_client = SophiaTopicsClient()
    try:
        sophia = SophiaEmbeddingIngestClient()
    except ValueError as exc:
        log.error("Sophia ingest no configurado: %s", exc)
        return 1
    try:
        if not sophia.is_available():
            log.error("embedding-ingest 404")
            return 1
    except SophiaEmbeddingIngestError as exc:
        log.error("embedding-ingest: %s", exc)
        return 1

    topics = _load_topics(topics_client, args.topic_id)
    log.info("Topics to sync: %s", len(topics))
    topic_rows, _contents = collect_topic_status(
        topics_client,
        sophia,
        topics,
        skip_av_count=args.skip_av_count,
    )

    needing = [r for r in topic_rows if r["needs_embeddings"]]
    log.info(
        "needs_embeddings=%s ready=%s",
        len(needing),
        sum(1 for r in topic_rows if r["ready"]),
    )
    for row in topic_rows:
        log.info(
            "  [%s] #%s %s | pending=%s indexed=%s missing_tx=%s",
            row["bucket"],
            row["topic_id"],
            (row["title"] or "")[:50],
            row["pending"],
            row["indexed"],
            row["missing_transcripts"],
        )

    if args.dry_run:
        sample = row_to_properties(topic_rows[0]) if topic_rows else {}
        log.info("Dry-run — no Notion writes. Sample properties:\n%s", json.dumps(sample, indent=2))
        log.info("Finished. Log: %s", log_file)
        return 0

    board = EmbeddingStatusNotionClient(api_token=token, database_id=db_id)
    added = board.ensure_schema()
    if added:
        log.info("Added Notion properties: %s", added)

    upserted = 0
    for row in topic_rows:
        page_id = board.upsert_topic(row)
        upserted += 1
        log.info("  upserted topic %s → %s", row["topic_id"], page_id)

    log.info("Upserted %s topic row(s) into %s", upserted, db_id)
    log.info("Finished. Log: %s", log_file)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Sync Sophia topic embedding status to a Notion database"
    )
    parser.add_argument("--topic-id", type=int, default=None)
    parser.add_argument("--database-id", default="", help="Overrides env database id")
    parser.add_argument(
        "--create-under-page",
        default="",
        help="Create the database under this Notion page id, then sync",
    )
    parser.add_argument(
        "--force-create",
        action="store_true",
        help="Create a new database even if NOTION_EMBEDDING_STATUS_DATABASE_ID is set",
    )
    parser.add_argument("--skip-av-count", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser


if __name__ == "__main__":
    raise SystemExit(run(build_parser().parse_args()))
