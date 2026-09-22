"""Read-only coverage audit. No extraction, embedding calls, ACKs, or database writes."""

from __future__ import annotations

import sqlite3
import unicodedata
from collections import Counter, defaultdict
from contextlib import closing
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

from src.embeddings.qdrant_store import QdrantStore
from src.sophia_embedding_ingest import SophiaEmbeddingIngestClient
from src.sophia_topics import SophiaTopicsClient


def _normalize(value: str) -> str:
    return " ".join("".join(c for c in unicodedata.normalize("NFKD", value.lower())
                            if not unicodedata.combining(c)).split())


def match_topic(query: str, topics: list[dict]) -> dict:
    """Resolve a confident name match; return candidates rather than guess on ambiguity."""
    needle = _normalize(query)
    if not needle:
        return {"ok": False, "error": "Provide a topic name or topic_id."}
    ranked = []
    for topic in topics:
        title = _normalize(topic.get("title") or "")
        score = 1.0 if needle == title else (
            0.95 if needle in title else SequenceMatcher(None, needle, title).ratio())
        ranked.append({"id": topic["id"], "title": topic.get("title"), "score": round(score, 3)})
    ranked.sort(key=lambda row: (-row["score"], row["id"]))
    if ranked and ranked[0]["score"] >= 0.65 and (
        len(ranked) == 1 or ranked[0]["score"] - ranked[1]["score"] >= 0.12
    ):
        return {"ok": True, "topic_id": ranked[0]["id"]}
    return {"ok": False, "error": "Topic name is ambiguous or unmatched. Choose a topic_id.",
            "candidates": ranked[:5]}


def read_local(root: Path, topic_id: int, model: str) -> dict:
    path = root / "cache/topic_embeddings/state.sqlite3"
    if not path.exists():
        return {"documents": {}, "chunks": {}, "database_exists": False}
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        docs = {r["doc_key"]: dict(r) for r in conn.execute(
            "SELECT doc_key, content_id, status, char_count, chunk_count, text_hash, notes "
            "FROM documents WHERE topic_id=?", (topic_id,))}
        chunks = defaultdict(list)
        for row in conn.execute(
            "SELECT doc_key, chunk_index FROM chunks WHERE topic_id=? AND embedding_model=?",
            (topic_id, model),
        ):
            chunks[row["doc_key"]].append(row["chunk_index"])
    return {"documents": docs, "chunks": dict(chunks), "database_exists": True}


def read_qdrant(store: QdrantStore, topic_id: int, model: str) -> dict:
    """Scroll metadata only, using read-only POST; never ensure/create a collection."""
    grouped = defaultdict(list)
    offset = None
    seen = set()
    while True:
        body = {"filter": {"must": [
            {"key": "topic_id", "match": {"value": topic_id}},
            {"key": "embedding_model", "match": {"value": model}},
        ]}, "limit": 256, "with_vector": False,
            "with_payload": ["doc_key", "content_id", "chunk_index", "text_hash"]}
        if offset is not None:
            body["offset"] = offset
        result = store._request("POST", f"/collections/{store.collection}/points/scroll",
                                json_body=body)["result"]
        for point in result["points"]:
            payload = point["payload"]
            grouped[payload["doc_key"]].append(payload)
        offset = result.get("next_page_offset")
        if offset is None:
            return dict(grouped)
        if str(offset) in seen:
            raise ValueError("Qdrant returned a repeated pagination offset")
        seen.add(str(offset))


def classify(item: dict, topic_id: int, local: dict | None,
             remote: dict | None, sophia: dict | None,
             model: str = "text-embedding-3-large") -> dict:
    cid, media = int(item["id"]), item["media_type"]
    key = f"topic:{topic_id}:{media}:{cid}"
    doc = (local or {}).get("documents", {}).get(key, {})
    indexes = (local or {}).get("chunks", {}).get(key, [])
    points = (remote or {}).get(key, [])
    ack = (sophia or {}).get(cid, {})
    ack_model_matches = not ack.get("embedding_model") or ack["embedding_model"] == model
    row = {"content_id": cid, "title": (item.get("selected_profile") or {}).get("title")
           or item.get("original_title") or item.get("title") or f"content-{cid}",
           "media_type": media, "url": item.get("url"),
           "local_chunks": len(indexes) if local is not None else None,
           "qdrant_chunks": len(points) if remote is not None else None,
           "sophia_embedding_status": ack.get("embedding_status", "unknown"),
           "sophia_embedding_model": ack.get("embedding_model"),
           "issues": []}
    if media == "IMAGE":
        return {**row, "status": "excluded", "text_status": "not_applicable",
                "reason": "Images are excluded by the embedding pipeline."}
    # Metadata evidence only: do not claim an uploaded PDF is already extracted.
    if indexes or doc.get("char_count", 0) or item.get("has_transcript") or ack.get("has_transcript"):
        text_status = "available"
    elif points:
        text_status = "embedded_text_exists"
    elif media in {"VIDEO", "AUDIO"} and item.get("has_transcript") is False:
        text_status = "transcript_needed"
    elif media in {"TEXT", "LINK"} and not item.get("has_file_available") and item.get("url"):
        text_status = "web_extraction_needed"
    else:
        text_status = "unknown"
    row["text_status"] = text_status
    if remote is None:
        row.update(status="unknown", reason="Qdrant could not be checked; coverage is unknown.")
    elif points:
        row.update(status="embedded", reason="Embedding chunks exist in Qdrant.")
        if indexes:
            if {p.get("chunk_index") for p in points} != set(indexes) or len(points) != len(indexes):
                row["issues"].append("upload_chunk_mismatch")
            if doc.get("text_hash") and any(p.get("text_hash") != doc["text_hash"] for p in points):
                row["issues"].append("upload_hash_mismatch")
        if ack_model_matches and ack.get("embedding_status") in {"stale", "failed", "pending", "skipped"}:
            row["issues"].append("sophia_status_not_indexed")
        if sophia is not None and cid not in sophia:
            row["issues"].append("sophia_status_untracked")
        if any(issue.startswith("upload_") for issue in row["issues"]):
            row["status"] = "upload_mismatch"
        elif ack_model_matches and ack.get("embedding_status") == "stale":
            row["status"] = "stale"
    elif indexes:
        row.update(status="missing_upload", reason="Local embeddings exist, but Qdrant has no chunks.")
    elif local is None:
        row.update(status="missing_in_qdrant", reason="No Qdrant chunks; local embeddings could not be checked.")
    elif text_status in {"transcript_needed", "web_extraction_needed"}:
        row.update(status="missing_text", reason=(
            "No Sophia transcript or local embedding text recorded; locate/transcribe audio first."
            if text_status == "transcript_needed" else "External webpage requires text extraction."))
    else:
        row.update(status="missing_embeddings", reason="No local or Qdrant chunks for the requested model.")
    if not ack_model_matches:
        row["issues"].append("sophia_model_differs")
    if remote is not None and not points and ack_model_matches and ack.get("embedding_status") == "indexed":
        row["issues"].append("sophia_indexed_without_vectors")
    if indexes and (doc.get("status") != "done" or len(indexes) != doc.get("chunk_count")):
        row["issues"].append("local_embedding_incomplete")
    return row


def topic_embedding_status(project_root: str | Path, *, topic_id: int | None = None,
                           topic_name: str | None = None,
                           model: str = "text-embedding-3-large") -> dict:
    """Audit a live topic by id/approximate name; unavailable sources remain unknown."""
    if (topic_id is None) == (not bool(topic_name and topic_name.strip())):
        return {"ok": False, "error": "Provide exactly one of topic_id or topic_name."}
    if topic_id is not None and topic_id < 1:
        return {"ok": False, "error": "topic_id must be positive."}
    if not model.strip():
        return {"ok": False, "error": "model must not be empty."}
    sources = {}

    def check(name, operation):
        try:
            result = operation()
            sources[name] = {"ok": True}
            return result
        except Exception as exc:
            # Exception messages from HTTP clients can contain URLs or response bodies.
            sources[name] = {"ok": False, "error_type": type(exc).__name__}
            status = getattr(exc, "status_code", None)
            if status is not None:
                sources[name]["http_status"] = status
            return None

    client = SophiaTopicsClient(timeout=20)
    if topic_id is None:
        topics = check("topic_lookup", client.list_topics)
        if topics is None:
            return {"ok": False, "error": "Sophia topic lookup unavailable; try a topic_id.", "sources": sources}
        match = match_topic(topic_name, topics)
        if not match["ok"]:
            return match
        topic_id = match["topic_id"]
    topic = check("topic", lambda: client.get_topic(topic_id))
    items = check("contents", lambda: client.list_topic_contents(topic_id, include_images=True))
    if topic is None or items is None:
        return {"ok": False, "error": "Cannot audit without Sophia's current topic inventory.", "sources": sources}
    local = check("local", lambda: read_local(Path(project_root), topic_id, model))
    remote = check("qdrant", lambda: read_qdrant(QdrantStore(timeout=20), topic_id, model))
    sophia = check("sophia_embedding_status", lambda: {
        int(x["id"]): x for x in SophiaEmbeddingIngestClient(timeout=20).list_queue_all(
            topic_id=topic_id, include_completed=True)})
    rows = [classify(x, topic_id, local, remote, sophia, model) for x in items]
    counts = Counter(row["status"] for row in rows)
    issues = Counter(issue for row in rows for issue in row["issues"])
    eligible = [r for r in rows if r["status"] != "excluded"]
    return {"ok": True, "complete": all(s["ok"] for s in sources.values()),
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "topic_id": topic_id, "title": topic.get("title"), "model": model,
            "sources": sources, "summary": {"contents": len(rows), "eligible": len(eligible),
                "missing_in_qdrant": sum(r["qdrant_chunks"] == 0 for r in eligible) if remote is not None else None,
                "by_status": dict(counts), "issues": dict(issues)}, "items": rows,
            "limitations": [
                "Chunk presence and local/Qdrant consistency are checked, not vector quality or current source-text freshness.",
                "Text availability uses metadata and embedding records; other transcript caches and source files are not scanned or extracted.",
                "Sophia embedding-ingest currently tracks VIDEO/AUDIO transcripts; TEXT/PDF may be untracked despite Qdrant vectors.",
                "Images are excluded. Topic description vectors are not counted as content files.",
            ]}
