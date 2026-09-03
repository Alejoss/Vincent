"""Topic / knowledge embeddings (OpenAI text-embedding-3-large)."""

from __future__ import annotations

from typing import Any

__all__ = [
    "TextChunk",
    "chunk_text",
    "EmbeddingClient",
    "DEFAULT_EMBEDDING_MODEL",
    "EmbeddingStore",
    "search_topic_local",
]


def __getattr__(name: str) -> Any:
    if name in {"TextChunk", "chunk_text"}:
        from src.embeddings.chunking import TextChunk, chunk_text

        return {"TextChunk": TextChunk, "chunk_text": chunk_text}[name]
    if name in {"EmbeddingClient", "DEFAULT_EMBEDDING_MODEL"}:
        from src.embeddings.openai_embed import DEFAULT_EMBEDDING_MODEL, EmbeddingClient

        return {
            "EmbeddingClient": EmbeddingClient,
            "DEFAULT_EMBEDDING_MODEL": DEFAULT_EMBEDDING_MODEL,
        }[name]
    if name == "EmbeddingStore":
        from src.embeddings.store import EmbeddingStore

        return EmbeddingStore
    if name == "search_topic_local":
        from src.embeddings.query import search_topic_local

        return search_topic_local
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
