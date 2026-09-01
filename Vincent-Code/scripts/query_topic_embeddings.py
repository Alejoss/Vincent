#!/usr/bin/env python3
"""
Local RAG over topic embeddings in SQLite + answer via Ollama (or OpenAI/Groq).

Retrieval uses the SAME embedding model as indexing (default: text-embedding-3-large
via OpenAI). Ollama is for generation only — do not embed the query with Ollama.

Examples (from Vincent-Code root):
  python scripts/query_topic_embeddings.py --topic-id 2
  python scripts/query_topic_embeddings.py --topic-id 2 "¿Quién mató a Bitcoin?"
  python scripts/query_topic_embeddings.py --topic-id 2 --retrieve-only "tamaño de bloques"
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sys
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv(PROJECT_ROOT / ".env", override=True)

from src.embeddings.openai_embed import (  # noqa: E402
    DEFAULT_EMBEDDING_MODEL,
    EmbeddingClient,
)
from src.embeddings.store import EmbeddingStore  # noqa: E402
from src.llm_client import (  # noqa: E402
    build_llm_config,
    call_text,
    ollama_is_reachable,
)
from src.pipeline_logging import setup_pipeline_logging  # noqa: E402

DEFAULT_DB = PROJECT_ROOT / "cache" / "topic_embeddings" / "state.sqlite3"
DEFAULT_TOP_K = 5
SYSTEM_PROMPT = (
    "Eres un asistente de Academia Blockchain. Responde SOLO con la evidencia "
    "del contexto recuperado del tema. Si el contexto no alcanza, dilo "
    "claramente. Cita fuentes por título / media_type cuando puedas. "
    "Responde en el mismo idioma que la pregunta."
)


def cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b) or not a:
        return -1.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0.0 or nb <= 0.0:
        return -1.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


def load_chunks(
    store: EmbeddingStore,
    *,
    topic_id: int,
    model: str,
) -> list[dict[str, Any]]:
    rows = store.conn.execute(
        """
        SELECT
            c.id,
            c.doc_key,
            c.topic_id,
            c.content_id,
            c.media_type,
            c.chunk_index,
            c.text,
            c.token_count,
            c.embedding_model,
            c.embedding_dims,
            c.embedding_json,
            d.title,
            d.author,
            d.source
        FROM chunks c
        LEFT JOIN documents d ON d.doc_key = c.doc_key
        WHERE c.topic_id = ? AND c.embedding_model = ?
        ORDER BY c.id
        """,
        (int(topic_id), model),
    ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["embedding"] = json.loads(item.pop("embedding_json"))
        out.append(item)
    return out


def retrieve(
    chunks: list[dict[str, Any]],
    query_vec: list[float],
    *,
    top_k: int,
) -> list[tuple[float, dict[str, Any]]]:
    scored: list[tuple[float, dict[str, Any]]] = []
    for ch in chunks:
        score = cosine(query_vec, ch["embedding"])
        scored.append((score, ch))
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[: max(1, top_k)]


def format_hits(hits: list[tuple[float, dict[str, Any]]]) -> str:
    blocks: list[str] = []
    for i, (score, ch) in enumerate(hits, start=1):
        title = (ch.get("title") or "").strip() or "(sin título)"
        media = ch.get("media_type") or "?"
        cid = ch.get("content_id")
        src = f"content_id={cid}" if cid is not None else ch.get("doc_key", "")
        header = (
            f"[{i}] score={score:.4f} | {media} | {title} | "
            f"{src} | chunk={ch.get('chunk_index')}"
        )
        body = (ch.get("text") or "").strip()
        blocks.append(f"{header}\n{body}")
    return "\n\n---\n\n".join(blocks)


def build_user_prompt(question: str, hits: list[tuple[float, dict[str, Any]]]) -> str:
    context = format_hits(hits)
    return (
        f"Pregunta:\n{question.strip()}\n\n"
        f"Contexto recuperado del tema (top-{len(hits)}):\n\n{context}\n\n"
        "Respuesta:"
    )


def answer_question(
    *,
    question: str,
    chunks: list[dict[str, Any]],
    embed_client: EmbeddingClient,
    llm_config,
    top_k: int,
    retrieve_only: bool,
    log: logging.Logger,
) -> None:
    q = question.strip()
    if not q:
        return

    log.info("Embedding query with %s …", embed_client.label)
    query_vec = embed_client.embed_texts([q])[0]
    hits = retrieve(chunks, query_vec, top_k=top_k)

    log.info("")
    log.info("=== Retrieval (top %s) ===", len(hits))
    for i, (score, ch) in enumerate(hits, start=1):
        title = (ch.get("title") or "")[:70]
        log.info(
            "  %s. %.4f | %s | %s | chunk %s",
            i,
            score,
            ch.get("media_type"),
            title,
            ch.get("chunk_index"),
        )
    log.info("")

    if retrieve_only:
        log.info("=== Chunks ===\n")
        print(format_hits(hits))
        return

    log.info("Generating answer with %s …", llm_config.label)
    text = call_text(
        system=SYSTEM_PROMPT,
        user=build_user_prompt(q, hits),
        config=llm_config,
        timeout_s=300,
        temperature=0.3,
    )
    log.info("")
    log.info("=== Respuesta ===\n")
    print(text)
    log.info("")


def interactive_loop(
    *,
    chunks: list[dict[str, Any]],
    embed_client: EmbeddingClient,
    llm_config,
    top_k: int,
    retrieve_only: bool,
    log: logging.Logger,
) -> int:
    print(
        "Chat local del tema. Escribe una pregunta (o 'salir' / Ctrl+C).\n"
        f"Retrieval: {embed_client.label} | LLM: "
        f"{'off (--retrieve-only)' if retrieve_only else llm_config.label} | top_k={top_k}\n"
    )
    while True:
        try:
            question = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not question:
            continue
        if question.lower() in {"salir", "exit", "quit", "q"}:
            return 0
        try:
            answer_question(
                question=question,
                chunks=chunks,
                embed_client=embed_client,
                llm_config=llm_config,
                top_k=top_k,
                retrieve_only=retrieve_only,
                log=log,
            )
        except Exception as exc:
            log.error("Error: %s", exc)
    return 0


def run(args: argparse.Namespace) -> int:
    log, log_file = setup_pipeline_logging("query_topic", verbose=args.verbose)
    topic_id = int(args.topic_id)
    model = (args.model or os.getenv("EMBEDDING_MODEL") or DEFAULT_EMBEDDING_MODEL).strip()
    db_path = Path(args.db) if args.db else DEFAULT_DB
    top_k = int(args.top_k)

    if not db_path.is_file():
        log.error("No existe la DB de embeddings: %s", db_path)
        log.error("Primero: python scripts/embed_topic.py --topic-id %s", topic_id)
        return 1

    store = EmbeddingStore(db_path)
    try:
        stats = store.topic_stats(topic_id)
        chunks = load_chunks(store, topic_id=topic_id, model=model)
    finally:
        store.close()

    log.info("Topic %s | DB %s", topic_id, db_path)
    log.info(
        "Docs: %s | chunks (%s): %s",
        stats.get("documents_by_status"),
        model,
        len(chunks),
    )
    if not chunks:
        log.error(
            "No hay chunks para topic_id=%s model=%s. Corre embed_topic.py primero.",
            topic_id,
            model,
        )
        return 1

    # Force Ollama by default for this MVP unless user overrides.
    provider = (args.llm_provider or "ollama").strip().lower()
    llm_config = build_llm_config(provider, args.llm_model, args.ollama_url)

    if not args.retrieve_only and provider == "ollama":
        url = llm_config.ollama_url
        if not ollama_is_reachable(url):
            log.error("Ollama no responde en %s. Arranca: ollama serve", url)
            log.error("O usa --retrieve-only para solo ver chunks.")
            return 1

    embed_client = EmbeddingClient(model=model)

    question: Optional[str] = (args.question or "").strip() or None
    if question:
        answer_question(
            question=question,
            chunks=chunks,
            embed_client=embed_client,
            llm_config=llm_config,
            top_k=top_k,
            retrieve_only=args.retrieve_only,
            log=log,
        )
        log.info("Finished. Log: %s", log_file)
        return 0

    rc = interactive_loop(
        chunks=chunks,
        embed_client=embed_client,
        llm_config=llm_config,
        top_k=top_k,
        retrieve_only=args.retrieve_only,
        log=log,
    )
    log.info("Finished. Log: %s", log_file)
    return rc


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Query local topic embeddings (SQLite) + answer with Ollama"
    )
    parser.add_argument("--topic-id", type=int, required=True)
    parser.add_argument(
        "question",
        nargs="?",
        default=None,
        help="One-shot question; omit for interactive chat",
    )
    parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K)
    parser.add_argument(
        "--retrieve-only",
        action="store_true",
        help="Only show similar chunks (no LLM answer)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Embedding model (must match indexed chunks)",
    )
    parser.add_argument("--db", default=None, help="Path to state.sqlite3")
    parser.add_argument(
        "--llm-provider",
        default="ollama",
        choices=("ollama", "openai", "groq", "auto"),
    )
    parser.add_argument("--llm-model", default=None)
    parser.add_argument("--ollama-url", default=None)
    parser.add_argument("-v", "--verbose", action="store_true")
    return run(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
