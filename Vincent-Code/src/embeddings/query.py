"""Local SQLite topic retrieval (Sophia-compatible ranking).

Shared by ``scripts/query_topic_embeddings.py`` and the Vincent MCP server.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any, Optional

from src.embeddings.openai_embed import DEFAULT_EMBEDDING_MODEL, EmbeddingClient
from src.embeddings.store import EmbeddingStore
from src.llm_client import build_llm_config, call_text

DEFAULT_TOP_K = 8
MAX_CONTEXT_CHARS = 12000
MAX_CHUNKS_PER_CONTENT = 2
CHAT_TEMPERATURE = 0.2

SYSTEM_PROMPT = (
    "Eres un asistente de Academia Blockchain. Respondes preguntas sobre un tema "
    "usando ÚNICAMENTE los fragmentos de transcripciones proporcionados como contexto.\n"
    "Reglas:\n"
    "- Si el contexto no contiene la información, di claramente que no la encuentras "
    "en las transcripciones del tema. No inventes.\n"
    "- Cita fuentes con [n] donde n es el número del fragmento.\n"
    "- Responde en español, de forma clara y educativa.\n"
    "- No inventes citas, títulos ni hechos fuera del contexto."
)
NO_CONTEXT_ANSWER = (
    "No encontré fragmentos indexados de transcripciones para este tema "
    "que respondan a tu pregunta. Puede que aún no haya embeddings o que "
    "la pregunta no coincida con el material disponible."
)


def default_embeddings_db(project_root: str | Path) -> Path:
    return Path(project_root) / "cache" / "topic_embeddings" / "state.sqlite3"


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
    max_chunks_per_content: int = MAX_CHUNKS_PER_CONTENT,
) -> list[tuple[float, dict[str, Any]]]:
    scored: list[tuple[float, dict[str, Any]]] = []
    for ch in chunks:
        score = cosine(query_vec, ch["embedding"])
        scored.append((score, ch))
    scored.sort(key=lambda x: x[0], reverse=True)
    pool = scored[: max(1, top_k * 2)]
    per_content: dict[Any, int] = {}
    selected: list[tuple[float, dict[str, Any]]] = []
    for score, ch in pool:
        key = ch.get("content_id")
        if key is None:
            key = id(ch)
        count = per_content.get(key, 0)
        if count >= max_chunks_per_content:
            continue
        per_content[key] = count + 1
        selected.append((score, ch))
    return selected[: max(1, top_k)]


def hits_to_sources(hits: list[tuple[float, dict[str, Any]]]) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    for index, (score, ch) in enumerate(hits, start=1):
        text = (ch.get("text") or "").strip()
        excerpt = text[:400] + ("…" if len(text) > 400 else "")
        sources.append(
            {
                "index": index,
                "content_id": ch.get("content_id"),
                "title": (ch.get("title") or "").strip(),
                "media_type": ch.get("media_type") or "",
                "chunk_index": ch.get("chunk_index"),
                "score": round(float(score), 4),
                "excerpt": excerpt,
                "text": text,
            }
        )
    return sources


def format_context(sources: list[dict[str, Any]], *, max_chars: int = MAX_CONTEXT_CHARS) -> str:
    blocks: list[str] = []
    used = 0
    budget = max(1000, int(max_chars))
    for src in sources:
        text = (src.get("text") or src.get("excerpt") or "").strip()
        if not text:
            continue
        title = src.get("title") or f"contenido {src.get('content_id') or '?'}"
        header = f"[{src['index']}] {title}"
        if src.get("chunk_index") is not None:
            header += f" (chunk {src['chunk_index']})"
        block = f"{header}\n{text}"
        if used + len(block) > budget and blocks:
            break
        blocks.append(block)
        used += len(block) + 2
    return "\n\n".join(blocks)


def build_user_prompt(topic_title: str, message: str, context: str) -> str:
    return (
        f"Tema: {topic_title}\n\n"
        f"Contexto (fragmentos de transcripciones):\n{context}\n\n"
        f"Pregunta del usuario:\n{message}"
    )


def topic_title_from_store(
    store: EmbeddingStore,
    *,
    topic_id: int,
    chunks: list[dict[str, Any]],
) -> str:
    title_row = store.conn.execute(
        """
        SELECT title FROM documents
        WHERE topic_id = ? AND media_type = 'TOPIC_DESCRIPTION'
        LIMIT 1
        """,
        (int(topic_id),),
    ).fetchone()
    topic_title = ""
    if title_row and title_row["title"]:
        topic_title = str(title_row["title"]).strip()
    if not topic_title and chunks:
        topic_title = str(chunks[0].get("title") or "").strip()
    if not topic_title:
        topic_title = f"topic-{topic_id}"
    return topic_title


def search_topic_local(
    *,
    question: str,
    topic_id: int,
    project_root: str | Path,
    db_path: Optional[str | Path] = None,
    model: Optional[str] = None,
    top_k: int = DEFAULT_TOP_K,
    answer: bool = False,
    llm_provider: str = "openai",
    llm_model: Optional[str] = None,
) -> dict[str, Any]:
    """Retrieve topic chunks from local SQLite. Optionally generate a Sophia-style answer."""
    q = (question or "").strip()
    if not q:
        return {"ok": False, "error": "question is empty"}

    model_name = (model or os.getenv("EMBEDDING_MODEL") or DEFAULT_EMBEDDING_MODEL).strip()
    path = Path(db_path) if db_path else default_embeddings_db(project_root)
    if not path.is_file():
        return {
            "ok": False,
            "error": f"Embeddings DB not found: {path}. Run embed_topic.py first.",
            "db_path": str(path),
            "topic_id": int(topic_id),
        }

    store = EmbeddingStore(path)
    try:
        stats = store.topic_stats(int(topic_id))
        chunks = load_chunks(store, topic_id=int(topic_id), model=model_name)
        topic_title = topic_title_from_store(store, topic_id=int(topic_id), chunks=chunks)
    finally:
        store.close()

    if not chunks:
        return {
            "ok": False,
            "error": (
                f"No chunks for topic_id={topic_id} model={model_name}. "
                "Run embed_topic.py first."
            ),
            "topic_id": int(topic_id),
            "topic_title": topic_title,
            "stats": stats,
            "db_path": str(path),
        }

    embed_client = EmbeddingClient(model=model_name)
    query_vec = embed_client.embed_texts([q])[0]
    hits = retrieve(chunks, query_vec, top_k=int(top_k))
    sources = hits_to_sources(hits)
    context = format_context(sources)

    result: dict[str, Any] = {
        "ok": True,
        "topic_id": int(topic_id),
        "topic_title": topic_title,
        "model": model_name,
        "db_path": str(path),
        "chunk_count": len(chunks),
        "stats": stats,
        "sources": [
            {k: v for k, v in src.items() if k != "text"}
            for src in sources
        ],
        "context": context,
    }

    if not answer:
        return result

    if not context.strip():
        result["answer"] = NO_CONTEXT_ANSWER
        return result

    llm_config = build_llm_config(llm_provider, llm_model, None)
    user_prompt = build_user_prompt(topic_title, q, context)
    result["answer"] = call_text(
        system=SYSTEM_PROMPT,
        user=user_prompt,
        config=llm_config,
        timeout_s=300,
        temperature=CHAT_TEMPERATURE,
    )
    result["llm"] = llm_config.label
    return result
