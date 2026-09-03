#!/usr/bin/env python3
"""
Local RAG over topic embeddings in SQLite, matching Sophia topic chat.

Retrieval: OpenAI text-embedding-3-large (same as indexing / Sophia).
Answer: OpenAI gpt-4o-mini by default (Sophia OPENAI_CHAT_MODEL). Ollama/Groq
are optional overrides — do not embed the query with Ollama.

Sophia production searches Qdrant; this script searches local SQLite so you can
test embeddings before/without the cluster. Prompt and top_k follow
docs/operations/topic-rag-chat.md in the Sophia repo.

Examples (from Vincent-Code root):
  python scripts/query_topic_embeddings.py --topic-id 2
  python scripts/query_topic_embeddings.py --topic-id 2 "¿Quién mató a Bitcoin?"
  python scripts/query_topic_embeddings.py --topic-id 2 --retrieve-only "tamaño de bloques"
"""

from __future__ import annotations

import argparse
import logging
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
from src.embeddings.query import (  # noqa: E402
    CHAT_TEMPERATURE,
    DEFAULT_TOP_K,
    NO_CONTEXT_ANSWER,
    SYSTEM_PROMPT,
    build_user_prompt,
    default_embeddings_db,
    format_context,
    hits_to_sources,
    load_chunks,
    retrieve,
    topic_title_from_store,
)
from src.embeddings.store import EmbeddingStore  # noqa: E402
from src.llm_client import (  # noqa: E402
    build_llm_config,
    call_text,
    ollama_is_reachable,
)
from src.pipeline_logging import setup_pipeline_logging  # noqa: E402

DEFAULT_DB = default_embeddings_db(PROJECT_ROOT)


def format_hits_debug(hits: list[tuple[float, dict[str, Any]]]) -> str:
    """Operator view with scores — not sent to the model."""
    lines: list[str] = []
    for i, (score, ch) in enumerate(hits, start=1):
        title = (ch.get("title") or "").strip() or "(sin título)"
        lines.append(
            f"[{i}] score={score:.4f} | {ch.get('media_type') or '?'} | "
            f"{title} | content_id={ch.get('content_id')} | chunk={ch.get('chunk_index')}"
        )
    return "\n".join(lines)


def answer_question(
    *,
    question: str,
    topic_title: str,
    chunks: list[dict[str, Any]],
    embed_client: EmbeddingClient,
    llm_config,
    top_k: int,
    retrieve_only: bool,
    dump_prompt: bool,
    log: logging.Logger,
) -> None:
    q = question.strip()
    if not q:
        return

    log.info("Embedding query with %s …", embed_client.label)
    query_vec = embed_client.embed_texts([q])[0]
    hits = retrieve(chunks, query_vec, top_k=top_k)
    sources = hits_to_sources(hits)
    context = format_context(sources)
    user_prompt = build_user_prompt(topic_title, q, context)

    log.info("")
    log.info("=== Retrieval (top %s, Sophia dedupe) ===", len(hits))
    log.info("%s", format_hits_debug(hits))
    log.info("")

    if retrieve_only or dump_prompt:
        print("=== SYSTEM_PROMPT ===\n")
        print(SYSTEM_PROMPT)
        print("\n=== user_prompt ===\n")
        print(user_prompt)
        print()
        if retrieve_only:
            return

    if not context.strip():
        print(NO_CONTEXT_ANSWER)
        return

    log.info("Generating answer with %s (temperature=%s) …", llm_config.label, CHAT_TEMPERATURE)
    text = call_text(
        system=SYSTEM_PROMPT,
        user=user_prompt,
        config=llm_config,
        timeout_s=300,
        temperature=CHAT_TEMPERATURE,
    )
    log.info("")
    log.info("=== Respuesta ===\n")
    print(text)
    log.info("")


def interactive_loop(
    *,
    topic_title: str,
    chunks: list[dict[str, Any]],
    embed_client: EmbeddingClient,
    llm_config,
    top_k: int,
    retrieve_only: bool,
    dump_prompt: bool,
    log: logging.Logger,
) -> int:
    print(
        "Chat local del tema (misma interfaz Sophia).\n"
        f"Tema: {topic_title}\n"
        "Escribe una pregunta (o 'salir' / Ctrl+C).\n"
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
                topic_title=topic_title,
                chunks=chunks,
                embed_client=embed_client,
                llm_config=llm_config,
                top_k=top_k,
                retrieve_only=retrieve_only,
                dump_prompt=dump_prompt,
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
        topic_title = topic_title_from_store(store, topic_id=topic_id, chunks=chunks)
    finally:
        store.close()

    log.info("Topic %s — %s | DB %s", topic_id, topic_title, db_path)
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

    provider = (args.llm_provider or "openai").strip().lower()
    llm_config = build_llm_config(provider, args.llm_model, args.ollama_url)

    if not args.retrieve_only and provider == "ollama":
        url = llm_config.ollama_url
        if not ollama_is_reachable(url):
            log.error("Ollama no responde en %s. Arranca: ollama serve", url)
            log.error("O usa --llm-provider openai (default, igual que Sophia).")
            return 1

    embed_client = EmbeddingClient(model=model)

    question: Optional[str] = (args.question or "").strip() or None
    if question:
        answer_question(
            question=question,
            topic_title=topic_title,
            chunks=chunks,
            embed_client=embed_client,
            llm_config=llm_config,
            top_k=top_k,
            retrieve_only=args.retrieve_only,
            dump_prompt=args.dump_prompt,
            log=log,
        )
        log.info("Finished. Log: %s", log_file)
        return 0

    rc = interactive_loop(
        topic_title=topic_title,
        chunks=chunks,
        embed_client=embed_client,
        llm_config=llm_config,
        top_k=top_k,
        retrieve_only=args.retrieve_only,
        dump_prompt=args.dump_prompt,
        log=log,
    )
    log.info("Finished. Log: %s", log_file)
    return rc


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Query local topic embeddings (SQLite) + answer with OpenAI (Sophia-compatible)"
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
        help="Print Sophia SYSTEM_PROMPT + user_prompt (no LLM answer)",
    )
    parser.add_argument(
        "--dump-prompt",
        action="store_true",
        help="Also print SYSTEM_PROMPT + user_prompt when generating an answer",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Embedding model (must match indexed chunks)",
    )
    parser.add_argument("--db", default=None, help="Path to state.sqlite3")
    parser.add_argument(
        "--llm-provider",
        default="openai",
        choices=("openai", "ollama", "groq", "auto"),
        help="Answer model. Default openai (gpt-4o-mini) to match Sophia topic chat.",
    )
    parser.add_argument("--llm-model", default=None)
    parser.add_argument("--ollama-url", default=None)
    parser.add_argument("-v", "--verbose", action="store_true")
    return run(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
