#!/usr/bin/env python3
"""
Sophia embedding worker (Vincent): queue → embed → Qdrant → ack.

Default mode ``auto``:
  1) Try GET /api/content/embedding-ingest/ (Sophia queue)
  2) If 404 (not deployed yet) → fallback: push done rows from local SQLite

Queue flow (Sophia handoff):
  GET queue → resolve/reuse text → chunk+embed (or reuse SQLite) →
  upsert Qdrant sophia_acbc_topic_chunks → PUT ack indexed|failed|skipped

Examples:
  python scripts/sync_topic_embeddings_to_qdrant.py --ping
  python scripts/sync_topic_embeddings_to_qdrant.py --topic-id 2 --dry-run
  python scripts/sync_topic_embeddings_to_qdrant.py --topic-id 2
  python scripts/sync_topic_embeddings_to_qdrant.py --topic-id 2 --mode queue
  python scripts/sync_topic_embeddings_to_qdrant.py --topic-id 2 --mode sqlite
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

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
from src.embeddings.qdrant_store import QdrantStore, QdrantStoreError  # noqa: E402
from src.embeddings.store import EmbeddingStore  # noqa: E402
from src.pipeline_logging import setup_pipeline_logging  # noqa: E402
from src.sophia_embedding_ingest import (  # noqa: E402
    SophiaEmbeddingIngestClient,
    SophiaEmbeddingIngestError,
)
from src.sophia_topic_text import resolve_media_text  # noqa: E402
from src.sophia_transcript_ingest import SophiaTranscriptIngestClient  # noqa: E402

DEFAULT_DB = PROJECT_ROOT / "cache" / "topic_embeddings" / "state.sqlite3"
REPORT_DIR = PROJECT_ROOT / "cache" / "topic_embeddings" / "reports"
SOPHIA_ACK_MEDIA = {"VIDEO", "AUDIO"}


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def local_text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def doc_key(topic_id: int, media_type: str, content_id: Optional[int]) -> str:
    if content_id is None:
        return f"topic:{topic_id}:description"
    return f"topic:{topic_id}:{media_type}:{int(content_id)}"


def needs_qdrant_push(
    sync_row: Optional[dict[str, Any]],
    *,
    text_hash: str,
    model: str,
    chunk_count: int,
    force: bool,
) -> bool:
    if force or not sync_row:
        return True
    if sync_row.get("qdrant_status") != "synced":
        return True
    if sync_row.get("text_hash") != text_hash:
        return True
    if sync_row.get("embedding_model") != model:
        return True
    if int(sync_row.get("chunk_count") or 0) != int(chunk_count):
        return True
    return False


def try_sophia_client(log: logging.Logger) -> Optional[SophiaEmbeddingIngestClient]:
    try:
        return SophiaEmbeddingIngestClient()
    except ValueError as exc:
        log.warning("Sophia client no configurado: %s", exc)
        return None


def resolve_mode(
    requested: str,
    sophia: Optional[SophiaEmbeddingIngestClient],
    log: logging.Logger,
) -> str:
    if requested in {"queue", "sqlite"}:
        return requested
    # auto
    if sophia is None:
        log.info("Mode auto → sqlite (no Sophia credentials)")
        return "sqlite"
    try:
        if sophia.is_available():
            log.info("Mode auto → queue (embedding-ingest available)")
            return "queue"
        log.info(
            "Mode auto → sqlite (embedding-ingest 404; deploy pending). "
            "Re-run later with --mode queue."
        )
        return "sqlite"
    except SophiaEmbeddingIngestError as exc:
        log.warning("Mode auto → sqlite (probe failed: %s)", exc)
        return "sqlite"


def ensure_chunks_for_queue_item(
    *,
    store: EmbeddingStore,
    embed_client: Optional[EmbeddingClient],
    transcript_client: SophiaTranscriptIngestClient,
    topic_id: int,
    item: dict[str, Any],
    model: str,
    force: bool,
    max_tokens: int,
    overlap_tokens: int,
    dry_run: bool,
    log: logging.Logger,
) -> tuple[str, list[dict[str, Any]], str, str]:
    """
    Returns (action, chunks, text_hash_for_payload, error).

    action: reuse | embed | skip | would_embed | would_reuse | error
    text_hash_for_payload: prefer Sophia queue text_hash when present.
    """
    content_id = int(item["id"])
    media_type = str(item.get("media_type") or "").upper()
    title = item.get("original_title") or f"content-{content_id}"
    author = item.get("original_author") or ""
    remote_hash = (item.get("text_hash") or "").strip()
    key = doc_key(topic_id, media_type, content_id)

    local_doc = store.get_document(key)
    local_chunks = store.list_chunks_for_doc(key, model)
    local_hash = (local_doc or {}).get("text_hash") or ""

    can_reuse = bool(local_chunks) and (local_doc or {}).get("status") == "done"
    if force:
        can_reuse = False
    elif remote_hash and local_hash and local_hash != remote_hash:
        # Sophia transcript text changed vs what we embedded locally
        can_reuse = False
    elif not local_chunks:
        can_reuse = False

    if can_reuse and local_chunks:
        payload_hash = remote_hash or local_hash
        if dry_run:
            return "would_reuse", local_chunks, payload_hash, ""
        return "reuse", local_chunks, payload_hash, ""

    resolved = resolve_media_text(
        project_root=PROJECT_ROOT,
        item=item,
        ingest_client=transcript_client,
    )
    if resolved.status != "ok" or not (resolved.text or "").strip():
        reason = resolved.notes or resolved.status or "no transcript text"
        return "skip", [], remote_hash, reason

    th_local = local_text_hash(resolved.text)
    payload_hash = remote_hash or th_local
    pieces = chunk_text(
        resolved.text,
        max_tokens=max_tokens,
        overlap_tokens=overlap_tokens,
        model=model,
    )
    if not pieces:
        return "skip", [], payload_hash, "empty after chunking"

    if dry_run:
        fake = [
            {
                "chunk_index": c.chunk_index,
                "text": c.text,
                "token_count": c.token_count,
                "embedding": [],
                "embedding_dims": 3072,
            }
            for c in pieces
        ]
        return "would_embed", fake, payload_hash, ""

    if embed_client is None:
        return "error", [], payload_hash, "EmbeddingClient required"

    log.info(
        "  Embedding %s (%s chunks) — %s",
        key,
        len(pieces),
        title[:60],
    )
    vectors = embed_client.embed_texts([c.text for c in pieces])
    chunks = [
        {
            "chunk_index": c.chunk_index,
            "text": c.text,
            "token_count": c.token_count,
            "embedding": vectors[i],
            "embedding_dims": len(vectors[i]),
        }
        for i, c in enumerate(pieces)
    ]
    store.replace_chunks(
        doc_key=key,
        topic_id=topic_id,
        content_id=content_id,
        media_type=media_type,
        model=model,
        chunks=chunks,
    )
    store.upsert_document(
        doc_key=key,
        topic_id=topic_id,
        content_id=content_id,
        media_type=media_type,
        title=title,
        author=author,
        source=resolved.source,
        text_hash=th_local,
        char_count=len(resolved.text),
        token_count=count_tokens(resolved.text, model=model),
        chunk_count=len(chunks),
        status="done",
        notes=f"queue_remote_hash={remote_hash}" if remote_hash else resolved.notes,
    )
    return "embed", chunks, payload_hash, ""


def push_and_ack_queue_item(
    *,
    store: EmbeddingStore,
    qdrant: QdrantStore,
    sophia: SophiaEmbeddingIngestClient,
    topic_id: int,
    item: dict[str, Any],
    chunks: list[dict[str, Any]],
    payload_hash: str,
    model: str,
    force: bool,
    dry_run: bool,
    skip_sophia_ack: bool,
    log: logging.Logger,
) -> dict[str, Any]:
    content_id = int(item["id"])
    media_type = str(item.get("media_type") or "").upper()
    title = (item.get("original_title") or "")[:80]
    author = item.get("original_author") or ""
    key = doc_key(topic_id, media_type, content_id)
    sync_row = store.get_qdrant_sync(key)
    dims = int(chunks[0].get("embedding_dims") or len(chunks[0].get("embedding") or []) or 3072)

    result: dict[str, Any] = {
        "doc_key": key,
        "content_id": content_id,
        "media_type": media_type,
        "title": title,
        "chunk_count": len(chunks),
        "text_hash": payload_hash,
    }

    do_push = needs_qdrant_push(
        sync_row,
        text_hash=payload_hash,
        model=model,
        chunk_count=len(chunks),
        force=force,
    )
    result["qdrant_push"] = do_push

    if dry_run:
        result["action"] = "would_push" if do_push else "already_synced"
        result["sophia_ack"] = "skipped_by_flag" if skip_sophia_ack else "would_ack"
        return result

    qdrant_status = (sync_row or {}).get("qdrant_status") or "pending"
    qdrant_synced_at = (sync_row or {}).get("qdrant_synced_at")
    sophia_ack_status = (sync_row or {}).get("sophia_ack_status") or "pending"
    sophia_acked_at = (sync_row or {}).get("sophia_acked_at")
    err = ""

    if do_push:
        try:
            n = qdrant.upsert_chunks(
                doc_key=key,
                topic_id=topic_id,
                content_id=content_id,
                media_type=media_type,
                text_hash=payload_hash,
                model=model,
                chunks=chunks,
                title=item.get("original_title") or "",
                author=author,
            )
            qdrant_status = "synced"
            qdrant_synced_at = _now()
            result["action"] = f"pushed:{n}"
            log.info("PUSHED %s | %s | %s chunks", media_type, title, n)
        except QdrantStoreError as exc:
            qdrant_status = "failed"
            err = str(exc)
            result["action"] = "qdrant_failed"
            result["error"] = err
            log.error("FAIL Qdrant %s | %s | %s", media_type, title, exc)
            if not skip_sophia_ack:
                try:
                    sophia.ack_failed(
                        content_id,
                        embedding_error=err[:2000],
                        embedding_model=model,
                        embedding_dims=dims,
                    )
                    sophia_ack_status = "acked_failed"
                    result["sophia_ack"] = "failed_ack_sent"
                except SophiaEmbeddingIngestError as ack_exc:
                    if ack_exc.status_code == 404:
                        sophia_ack_status = "unavailable"
                        result["sophia_ack"] = "unavailable"
                    else:
                        sophia_ack_status = "failed"
                        result["sophia_ack"] = f"ack_error:{ack_exc}"
            store.upsert_qdrant_sync(
                doc_key=key,
                topic_id=topic_id,
                content_id=content_id,
                media_type=media_type,
                text_hash=payload_hash,
                embedding_model=model,
                chunk_count=len(chunks),
                qdrant_status=qdrant_status,
                qdrant_synced_at=None,
                sophia_ack_status=sophia_ack_status,
                sophia_acked_at=None,
                error=err,
            )
            return result
    else:
        result["action"] = "already_synced"
        log.info("SKIP Qdrant %s | %s (already synced)", media_type, title)

    if skip_sophia_ack:
        sophia_ack_status = "skipped"
        result["sophia_ack"] = "skipped_by_flag"
    elif qdrant_status != "synced":
        result["sophia_ack"] = "skipped_qdrant_not_synced"
    else:
        try:
            # Omit embedded_text_hash so Sophia uses current transcript.text_hash
            # (avoids local vs server hash normalization mismatches).
            sophia.ack_indexed(
                content_id,
                embedding_model=model,
                embedding_dims=dims,
                chunk_count=len(chunks),
                embedded_text_hash="",
            )
            sophia_ack_status = "acked"
            sophia_acked_at = _now()
            result["sophia_ack"] = "acked"
            log.info("  ACK indexed content_id=%s chunks=%s", content_id, len(chunks))
        except SophiaEmbeddingIngestError as ack_exc:
            if ack_exc.status_code == 404:
                sophia_ack_status = "unavailable"
                result["sophia_ack"] = "unavailable"
                log.warning("  Sophia ack 404 — Qdrant ok; re-ack after deploy")
            else:
                sophia_ack_status = "failed"
                result["sophia_ack"] = "ack_failed"
                err = (err + "; " if err else "") + str(ack_exc)
                log.warning("  Sophia ack failed: %s", ack_exc)

    store.upsert_qdrant_sync(
        doc_key=key,
        topic_id=topic_id,
        content_id=content_id,
        media_type=media_type,
        text_hash=payload_hash,
        embedding_model=model,
        chunk_count=len(chunks),
        qdrant_status=qdrant_status,
        qdrant_synced_at=qdrant_synced_at,
        sophia_ack_status=sophia_ack_status,
        sophia_acked_at=sophia_acked_at,
        error=err,
    )
    return result


def sync_queue_mode(args: argparse.Namespace, log: logging.Logger) -> int:
    topic_id = int(args.topic_id)
    model = (args.model or os.getenv("EMBEDDING_MODEL") or DEFAULT_EMBEDDING_MODEL).strip()
    db_path = Path(args.db) if args.db else DEFAULT_DB
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    sophia = try_sophia_client(log)
    if sophia is None:
        log.error("Queue mode requires TRANSCRIPT_INGEST_API_KEY + SOPHIA_API_BASE")
        return 1

    qdrant = QdrantStore()
    try:
        ping = qdrant.ping()
    except (QdrantStoreError, ValueError) as exc:
        log.error("Qdrant ping failed: %s", exc)
        return 1
    log.info(
        "Qdrant %s | collection=%s points=%s",
        ping.get("version"),
        ping.get("collection"),
        ping.get("points_count"),
    )

    try:
        queue_items = sophia.list_queue_all(
            topic_id=topic_id,
            include_completed=bool(args.include_completed),
            status=args.status or None,
        )
    except SophiaEmbeddingIngestError as exc:
        if exc.status_code == 404:
            log.error(
                "embedding-ingest 404 en prod. Usa --mode sqlite o espera el deploy."
            )
            return 1
        raise

    log.info(
        "Topic %s | Sophia queue items: %s | model: %s",
        topic_id,
        len(queue_items),
        model,
    )
    if args.limit:
        queue_items = queue_items[: int(args.limit)]

    store = EmbeddingStore(db_path)
    transcript_client = SophiaTranscriptIngestClient()
    embed_client: Optional[EmbeddingClient] = None
    if not args.dry_run:
        embed_client = EmbeddingClient(model=model)

    report: dict[str, Any] = {
        "mode": "queue",
        "topic_id": topic_id,
        "model": model,
        "dry_run": bool(args.dry_run),
        "started_at": _now(),
        "qdrant": ping,
        "items": [],
        "summary": {},
    }

    counters = {
        "reuse": 0,
        "embed": 0,
        "skip": 0,
        "pushed": 0,
        "qdrant_failed": 0,
        "acked": 0,
        "ack_failed": 0,
        "ack_unavailable": 0,
        "ack_skipped": 0,
    }

    for item in queue_items:
        content_id = int(item["id"])
        title = (item.get("original_title") or "")[:70]
        emb_status = item.get("embedding_status") or "?"
        log.info(
            "QUEUE #%s %s | emb=%s | %s",
            content_id,
            item.get("media_type"),
            emb_status,
            title,
        )

        action, chunks, payload_hash, err = ensure_chunks_for_queue_item(
            store=store,
            embed_client=embed_client,
            transcript_client=transcript_client,
            topic_id=topic_id,
            item=item,
            model=model,
            force=args.force,
            max_tokens=args.max_tokens,
            overlap_tokens=args.overlap_tokens,
            dry_run=args.dry_run,
            log=log,
        )

        if action in {"skip", "error"}:
            counters["skip"] += 1
            row = {
                "content_id": content_id,
                "action": action,
                "error": err,
                "title": title,
            }
            report["items"].append(row)
            log.warning("  SKIP/ERR: %s", err)
            if not args.dry_run and not args.skip_sophia_ack and action == "skip":
                try:
                    sophia.ack_skipped(
                        content_id,
                        embedding_error=err[:2000],
                        embedding_model=model,
                    )
                    row["sophia_ack"] = "skipped"
                    counters["ack_skipped"] += 1
                except SophiaEmbeddingIngestError as ack_exc:
                    row["sophia_ack"] = f"ack_error:{ack_exc.status_code}"
            continue

        if action.startswith("would_"):
            counters["reuse" if "reuse" in action else "embed"] += 1
        elif action == "reuse":
            counters["reuse"] += 1
        elif action == "embed":
            counters["embed"] += 1

        result = push_and_ack_queue_item(
            store=store,
            qdrant=qdrant,
            sophia=sophia,
            topic_id=topic_id,
            item=item,
            chunks=chunks,
            payload_hash=payload_hash,
            model=model,
            force=args.force,
            dry_run=args.dry_run,
            skip_sophia_ack=args.skip_sophia_ack,
            log=log,
        )
        result["prepare"] = action
        report["items"].append(result)

        if str(result.get("action", "")).startswith("pushed"):
            counters["pushed"] += 1
        elif result.get("action") == "qdrant_failed":
            counters["qdrant_failed"] += 1
        ack = result.get("sophia_ack") or ""
        if ack == "acked":
            counters["acked"] += 1
        elif ack == "unavailable":
            counters["ack_unavailable"] += 1
        elif "fail" in ack:
            counters["ack_failed"] += 1
        elif "skip" in ack:
            counters["ack_skipped"] += 1

    # Optional: also push local TEXT / description extras not in Sophia queue
    if args.also_sqlite_extras and not args.dry_run:
        log.info("Also syncing local SQLite extras (TEXT / TOPIC_DESCRIPTION)…")
        extras_rc = sync_sqlite_mode(
            args, log, only_media={"TEXT", "TOPIC_DESCRIPTION"}, nested=True
        )
        report["sqlite_extras_exit"] = extras_rc

    try:
        remote_count = qdrant.count_topic(topic_id)
    except QdrantStoreError:
        remote_count = None

    report["summary"] = {
        **counters,
        "queue_items": len(queue_items),
        "qdrant_points_topic": remote_count,
        "local_sync_rows": store.qdrant_sync_stats(topic_id),
    }
    report["finished_at"] = _now()
    out = REPORT_DIR / f"topic_{topic_id}_qdrant_sync_latest.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("")
    log.info("Summary: %s", json.dumps(report["summary"], ensure_ascii=False))
    log.info("Report: %s", out)
    store.close()
    return 1 if counters["qdrant_failed"] else 0


def sync_sqlite_mode(
    args: argparse.Namespace,
    log: logging.Logger,
    *,
    only_media: Optional[set[str]] = None,
    nested: bool = False,
) -> int:
    """Fallback / extras: push already-embedded local documents to Qdrant."""
    topic_id = int(args.topic_id)
    model = (args.model or os.getenv("EMBEDDING_MODEL") or DEFAULT_EMBEDDING_MODEL).strip()
    db_path = Path(args.db) if args.db else DEFAULT_DB
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    if not db_path.is_file():
        log.error("No existe DB: %s (corre embed_topic.py primero)", db_path)
        return 1

    store = EmbeddingStore(db_path)
    qdrant = QdrantStore()
    try:
        ping = qdrant.ping()
    except (QdrantStoreError, ValueError) as exc:
        log.error("Qdrant ping failed: %s", exc)
        return 1

    if not nested:
        log.info(
            "Qdrant %s | collection=%s points=%s",
            ping.get("version"),
            ping.get("collection"),
            ping.get("points_count"),
        )

    docs = store.list_done_documents(topic_id)
    if only_media:
        docs = [d for d in docs if (d.get("media_type") or "") in only_media]
    log.info(
        "Topic %s | sqlite done docs: %s | model: %s%s",
        topic_id,
        len(docs),
        model,
        f" | filter={sorted(only_media)}" if only_media else "",
    )
    if not docs:
        if not nested:
            log.error("No hay documentos done para topic_id=%s", topic_id)
            return 1
        return 0

    sophia = None if args.skip_sophia_ack else try_sophia_client(log)
    report: dict[str, Any] = {
        "mode": "sqlite",
        "topic_id": topic_id,
        "model": model,
        "dry_run": bool(args.dry_run),
        "started_at": _now(),
        "qdrant": ping,
        "items": [],
        "summary": {},
    }

    pushed = skipped = failed = 0
    acked = ack_skipped = ack_failed = ack_unavailable = 0

    for doc in docs:
        key = doc["doc_key"]
        text_hash = doc.get("text_hash") or ""
        media_type = doc.get("media_type") or ""
        content_id = doc.get("content_id")
        title = (doc.get("title") or "")[:80]
        chunks = store.list_chunks_for_doc(key, model)
        sync_row = store.get_qdrant_sync(key)
        item: dict[str, Any] = {
            "doc_key": key,
            "content_id": content_id,
            "media_type": media_type,
            "title": title,
            "chunk_count": len(chunks),
            "text_hash": text_hash,
        }
        if not chunks:
            item["action"] = "skip_empty"
            skipped += 1
            report["items"].append(item)
            continue

        dims = int(chunks[0].get("embedding_dims") or len(chunks[0]["embedding"]))
        do_push = needs_qdrant_push(
            sync_row,
            text_hash=text_hash,
            model=model,
            chunk_count=len(chunks),
            force=args.force,
        )
        item["qdrant_push"] = do_push

        if args.dry_run:
            item["action"] = "would_push" if do_push else "already_synced"
            if do_push:
                pushed += 1
            else:
                skipped += 1
            if (
                not args.skip_sophia_ack
                and content_id is not None
                and media_type in SOPHIA_ACK_MEDIA
            ):
                item["sophia_ack"] = "would_ack"
            else:
                item["sophia_ack"] = "skip_not_video_audio_or_disabled"
            report["items"].append(item)
            log.info(
                "DRY %s | %s | chunks=%s | %s | sophia=%s",
                media_type,
                title,
                len(chunks),
                item["action"],
                item["sophia_ack"],
            )
            continue

        qdrant_status = (sync_row or {}).get("qdrant_status") or "pending"
        qdrant_synced_at = (sync_row or {}).get("qdrant_synced_at")
        sophia_ack_status = (sync_row or {}).get("sophia_ack_status") or "pending"
        sophia_acked_at = (sync_row or {}).get("sophia_acked_at")
        err = ""

        if do_push:
            try:
                n = qdrant.upsert_chunks(
                    doc_key=key,
                    topic_id=topic_id,
                    content_id=int(content_id) if content_id is not None else None,
                    media_type=media_type,
                    text_hash=text_hash,
                    model=model,
                    chunks=chunks,
                    title=doc.get("title") or "",
                    author=doc.get("author") or "",
                )
                qdrant_status = "synced"
                qdrant_synced_at = _now()
                pushed += 1
                item["action"] = f"pushed:{n}"
                log.info("PUSHED %s | %s | %s chunks", media_type, title, n)
            except QdrantStoreError as exc:
                qdrant_status = "failed"
                err = str(exc)
                failed += 1
                item["action"] = "qdrant_failed"
                item["error"] = err
                log.error("FAIL %s | %s | %s", media_type, title, exc)
                if (
                    sophia
                    and content_id is not None
                    and media_type in SOPHIA_ACK_MEDIA
                    and not args.skip_sophia_ack
                ):
                    try:
                        sophia.ack_failed(
                            int(content_id),
                            embedding_error=err[:2000],
                            embedding_model=model,
                            embedding_dims=dims,
                        )
                        item["sophia_ack"] = "failed_ack_sent"
                    except SophiaEmbeddingIngestError:
                        item["sophia_ack"] = "ack_unavailable_or_error"
                store.upsert_qdrant_sync(
                    doc_key=key,
                    topic_id=topic_id,
                    content_id=int(content_id) if content_id is not None else None,
                    media_type=media_type,
                    text_hash=text_hash,
                    embedding_model=model,
                    chunk_count=len(chunks),
                    qdrant_status=qdrant_status,
                    qdrant_synced_at=None,
                    sophia_ack_status="pending",
                    sophia_acked_at=None,
                    error=err,
                )
                report["items"].append(item)
                continue
        else:
            skipped += 1
            item["action"] = "already_synced"
            log.info("SKIP %s | %s (already in Qdrant)", media_type, title)

        if args.skip_sophia_ack:
            sophia_ack_status = "skipped"
            item["sophia_ack"] = "skipped_by_flag"
            ack_skipped += 1
        elif content_id is None or media_type not in SOPHIA_ACK_MEDIA:
            sophia_ack_status = "skipped"
            item["sophia_ack"] = "skipped_not_applicable"
            ack_skipped += 1
        elif qdrant_status != "synced":
            item["sophia_ack"] = "skipped_qdrant_not_synced"
            ack_skipped += 1
        elif sophia is None:
            sophia_ack_status = "unavailable"
            item["sophia_ack"] = "unavailable_no_client"
            ack_unavailable += 1
        else:
            try:
                sophia.ack_indexed(
                    int(content_id),
                    embedding_model=model,
                    embedding_dims=dims,
                    chunk_count=len(chunks),
                    embedded_text_hash="",
                )
                sophia_ack_status = "acked"
                sophia_acked_at = _now()
                item["sophia_ack"] = "acked"
                acked += 1
            except SophiaEmbeddingIngestError as ack_exc:
                if ack_exc.status_code == 404:
                    sophia_ack_status = "unavailable"
                    item["sophia_ack"] = "unavailable"
                    ack_unavailable += 1
                    log.warning("  Sophia ack 404 (not deployed)")
                else:
                    sophia_ack_status = "failed"
                    item["sophia_ack"] = "ack_failed"
                    ack_failed += 1
                    err = (err + "; " if err else "") + str(ack_exc)

        store.upsert_qdrant_sync(
            doc_key=key,
            topic_id=topic_id,
            content_id=int(content_id) if content_id is not None else None,
            media_type=media_type,
            text_hash=text_hash,
            embedding_model=model,
            chunk_count=len(chunks),
            qdrant_status=qdrant_status,
            qdrant_synced_at=qdrant_synced_at,
            sophia_ack_status=sophia_ack_status,
            sophia_acked_at=sophia_acked_at,
            error=err,
        )
        report["items"].append(item)

    if nested:
        store.close()
        return 1 if failed else 0

    try:
        remote_count = qdrant.count_topic(topic_id)
    except QdrantStoreError:
        remote_count = None

    report["summary"] = {
        "documents": len(docs),
        "qdrant_pushed_or_would": pushed,
        "qdrant_skipped": skipped,
        "qdrant_failed": failed,
        "sophia_acked": acked,
        "sophia_ack_skipped": ack_skipped,
        "sophia_ack_failed": ack_failed,
        "sophia_ack_unavailable": ack_unavailable,
        "qdrant_points_topic": remote_count,
        "local_sync_rows": store.qdrant_sync_stats(topic_id),
    }
    report["finished_at"] = _now()
    out = REPORT_DIR / f"topic_{topic_id}_qdrant_sync_latest.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("")
    log.info("Summary: %s", json.dumps(report["summary"], ensure_ascii=False))
    log.info("Report: %s", out)
    store.close()
    return 1 if failed else 0


def run_ping(log: logging.Logger) -> int:
    try:
        qdrant = QdrantStore()
        ping = qdrant.ping()
    except (QdrantStoreError, ValueError) as exc:
        log.error("Qdrant ping failed: %s", exc)
        return 1
    log.info("OK Qdrant version=%s", ping.get("version"))
    log.info("  url=%s", ping.get("url"))
    log.info(
        "  collection=%s exists=%s points=%s",
        ping.get("collection"),
        ping.get("collection_exists"),
        ping.get("points_count"),
    )

    sophia = try_sophia_client(log)
    if sophia is None:
        log.info("Sophia embedding-ingest: not configured")
        return 0
    try:
        ok = sophia.is_available()
        log.info("Sophia embedding-ingest: %s", "AVAILABLE" if ok else "404 (not deployed)")
    except SophiaEmbeddingIngestError as exc:
        log.info("Sophia embedding-ingest probe: %s", exc)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sophia embedding worker: queue → Qdrant → ack (auto falls back to SQLite)"
    )
    parser.add_argument("--topic-id", type=int, default=None)
    parser.add_argument("--ping", action="store_true", help="Test Qdrant + Sophia ingest availability")
    parser.add_argument(
        "--mode",
        choices=("auto", "queue", "sqlite"),
        default="auto",
        help="auto=queue if API up else sqlite; queue=Sophia handoff; sqlite=local push",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true", help="Re-embed / re-upsert even if unchanged")
    parser.add_argument("--skip-sophia-ack", action="store_true")
    parser.add_argument(
        "--include-completed",
        action="store_true",
        help="Queue mode: also list indexed/skipped items",
    )
    parser.add_argument(
        "--status",
        default="",
        help="Queue mode: override status filter (e.g. pending,stale,failed)",
    )
    parser.add_argument("--limit", type=int, default=0, help="Queue mode: process at most N items")
    parser.add_argument(
        "--also-sqlite-extras",
        action="store_true",
        help="After queue mode, also push local TEXT/description docs",
    )
    parser.add_argument("--model", default=None)
    parser.add_argument("--db", default=None)
    parser.add_argument("--max-tokens", type=int, default=800)
    parser.add_argument("--overlap-tokens", type=int, default=100)
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    log, log_file = setup_pipeline_logging("qdrant_sync", verbose=args.verbose)

    if args.ping and args.topic_id is None:
        rc = run_ping(log)
        log.info("Finished. Log: %s", log_file)
        return rc
    if args.topic_id is None:
        parser.error("--topic-id is required (or use --ping alone)")
    if args.ping:
        rc = run_ping(log)
        if rc != 0:
            log.info("Finished. Log: %s", log_file)
            return rc

    sophia = try_sophia_client(log)
    mode = resolve_mode(args.mode, sophia, log)
    if mode == "queue":
        rc = sync_queue_mode(args, log)
    else:
        rc = sync_sqlite_mode(args, log)
    log.info("Finished. Log: %s", log_file)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
