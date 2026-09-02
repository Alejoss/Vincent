#!/usr/bin/env python3
"""
Generate embeddings for a Sophia topic (description + VIDEO/AUDIO transcripts + TEXT).

Uses OpenAI text-embedding-3-large (full dimensions). Reuses local transcripts from
the topic worker / Knowledge Engine / Own_Transcripts when available.

Examples:
  python scripts/embed_topic.py --topic-id 2 --dry-run
  python scripts/embed_topic.py --topic-id 2
  python scripts/embed_topic.py --topic-id 2 --force
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv(PROJECT_ROOT / ".env", override=True)

from src.embeddings.chunking import chunk_text, count_tokens  # noqa: E402
from src.embeddings.openai_embed import (  # noqa: E402
    DEFAULT_EMBEDDING_MODEL,
    EmbeddingClient,
)
from src.embeddings.store import EmbeddingStore  # noqa: E402
from src.pipeline_logging import setup_pipeline_logging  # noqa: E402
from src.sophia_topic_text import (  # noqa: E402
    resolve_media_text,
    resolve_topic_description,
)
from src.sophia_topics import SophiaTopicsClient  # noqa: E402
from src.sophia_transcript_ingest import SophiaTranscriptIngestClient  # noqa: E402

LOG_DIR = PROJECT_ROOT / "logs"
REPORT_DIR = PROJECT_ROOT / "cache" / "topic_embeddings" / "reports"
DEFAULT_DB = PROJECT_ROOT / "cache" / "topic_embeddings" / "state.sqlite3"


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def doc_key(topic_id: int, media_type: str, content_id: int | None) -> str:
    if content_id is None:
        return f"topic:{topic_id}:description"
    return f"topic:{topic_id}:{media_type}:{int(content_id)}"


def run(args: argparse.Namespace) -> int:
    log, log_file = setup_pipeline_logging("embed_topic", verbose=args.verbose)
    topic_id = int(args.topic_id)
    model = (args.model or os.getenv("EMBEDDING_MODEL") or DEFAULT_EMBEDDING_MODEL).strip()
    db_path = Path(args.db) if args.db else DEFAULT_DB
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    topics = SophiaTopicsClient()
    ingest = SophiaTranscriptIngestClient()
    store = EmbeddingStore(db_path)

    topic = topics.get_topic(topic_id)
    log.info("Topic %s — %s", topic_id, topic.get("title"))
    log.info("Model: %s", model)
    log.info("Store: %s", db_path)

    units = []
    wanted = {int(x) for x in (args.content_id or [])}
    if not wanted:
        units.append(resolve_topic_description(topic))
    contents = topics.list_topic_contents(topic_id, include_images=False)
    if wanted:
        contents = [item for item in contents if int(item["id"]) in wanted]
        missing = wanted - {int(item["id"]) for item in contents}
        if missing:
            log.error("Content IDs not on topic %s: %s", topic_id, sorted(missing))
            store.close()
            return 1
        log.info("Filtered to content IDs: %s", sorted(wanted))
    log.info("Contents (no images): %s", len(contents))
    for item in contents:
        units.append(
            resolve_media_text(
                project_root=PROJECT_ROOT, item=item, ingest_client=ingest
            )
        )

    plan_rows: list[dict] = []
    to_embed: list[tuple] = []  # (ResolvedText, doc_key, chunks)

    for unit in units:
        key = doc_key(topic_id, unit.media_type, unit.content_id)
        if unit.status != "ok" or not unit.text.strip():
            store.upsert_document(
                doc_key=key,
                topic_id=topic_id,
                content_id=unit.content_id,
                media_type=unit.media_type,
                title=unit.title,
                author=unit.author,
                source=unit.source,
                text_hash="",
                char_count=0,
                token_count=0,
                chunk_count=0,
                status=unit.status,
                notes=unit.notes,
            )
            plan_rows.append(
                {
                    "doc_key": key,
                    "content_id": unit.content_id,
                    "media_type": unit.media_type,
                    "title": unit.title,
                    "status": unit.status,
                    "source": unit.source,
                    "notes": unit.notes,
                    "chars": 0,
                    "tokens": 0,
                    "chunks": 0,
                    "action": "skip",
                }
            )
            continue

        th = text_hash(unit.text)
        tokens = count_tokens(unit.text, model=model)
        chunks = chunk_text(
            unit.text,
            max_tokens=args.max_tokens,
            overlap_tokens=args.overlap_tokens,
            model=model,
        )
        current = store.document_is_current(key, th, model)
        action = "skip_unchanged" if current and not args.force else "embed"
        plan_rows.append(
            {
                "doc_key": key,
                "content_id": unit.content_id,
                "media_type": unit.media_type,
                "title": unit.title,
                "status": unit.status,
                "source": unit.source,
                "notes": unit.notes,
                "chars": len(unit.text),
                "tokens": tokens,
                "chunks": len(chunks),
                "action": action,
            }
        )
        if action == "embed":
            to_embed.append((unit, key, th, tokens, chunks))

    # Report plan
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    plan_path = REPORT_DIR / f"topic_{topic_id}_embed_plan_{stamp}.json"
    plan_path.write_text(
        json.dumps(
            {
                "topic_id": topic_id,
                "title": topic.get("title"),
                "model": model,
                "dry_run": bool(args.dry_run),
                "rows": plan_rows,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (REPORT_DIR / f"topic_{topic_id}_embed_plan_latest.json").write_text(
        plan_path.read_text(encoding="utf-8"), encoding="utf-8"
    )

    embed_n = sum(1 for r in plan_rows if r["action"] == "embed")
    skip_n = sum(1 for r in plan_rows if r["action"] != "embed")
    chunk_n = sum(r["chunks"] for r in plan_rows if r["action"] == "embed")
    tok_n = sum(r["tokens"] for r in plan_rows if r["action"] == "embed")
    log.info("Plan: embed_docs=%s skip=%s chunks=%s tokens~%s", embed_n, skip_n, chunk_n, tok_n)
    log.info("Plan file: %s", plan_path)
    for r in plan_rows:
        log.info(
            "  [%s] %s cid=%s chunks=%s src=%s | %s",
            r["action"],
            r["media_type"],
            r["content_id"],
            r["chunks"],
            (r["source"] or r["notes"])[:60],
            (r["title"] or "")[:50],
        )

    if args.dry_run:
        log.info("Dry-run only — no API calls.")
        store.close()
        return 0

    if not to_embed:
        log.info("Nothing to embed.")
        store.close()
        return 0

    client = EmbeddingClient(model=model, batch_size=args.batch_size)
    log.info("Embedding with %s …", client.label)

    for unit, key, th, tokens, chunks in to_embed:
        log.info(
            "Embedding %s (%s chunks, %s tokens) — %s",
            key,
            len(chunks),
            tokens,
            unit.title[:60],
        )
        vectors = client.embed_texts([c.text for c in chunks])
        payload = [
            {
                "chunk_index": c.chunk_index,
                "text": c.text,
                "token_count": c.token_count,
                "embedding": vectors[i],
            }
            for i, c in enumerate(chunks)
        ]
        store.replace_chunks(
            doc_key=key,
            topic_id=topic_id,
            content_id=unit.content_id,
            media_type=unit.media_type,
            model=model,
            chunks=payload,
        )
        store.upsert_document(
            doc_key=key,
            topic_id=topic_id,
            content_id=unit.content_id,
            media_type=unit.media_type,
            title=unit.title,
            author=unit.author,
            source=unit.source,
            text_hash=th,
            char_count=len(unit.text),
            token_count=tokens,
            chunk_count=len(chunks),
            status="done",
            notes=unit.notes,
        )

    stats = store.topic_stats(topic_id)
    log.info("Done. stats=%s", stats)
    log.info("Finished. Log: %s", log_file)
    store.close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Embed Sophia topic contents")
    p.add_argument("--topic-id", type=int, required=True)
    p.add_argument(
        "--content-id",
        type=int,
        action="append",
        default=[],
        help="Only embed these Sophia content IDs (repeatable). Skips topic description.",
    )
    p.add_argument("--model", default="", help=f"Default: {DEFAULT_EMBEDDING_MODEL}")
    p.add_argument("--db", default="", help="SQLite path for embedding store")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--force", action="store_true", help="Re-embed even if hash unchanged")
    p.add_argument("--max-tokens", type=int, default=800)
    p.add_argument("--overlap-tokens", type=int, default=100)
    p.add_argument("--batch-size", type=int, default=64)
    p.add_argument("--verbose", action="store_true")
    return p


if __name__ == "__main__":
    sys.exit(run(build_parser().parse_args()))
