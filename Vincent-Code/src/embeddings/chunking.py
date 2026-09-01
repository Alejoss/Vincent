"""Token-aware text chunking for embedding models."""

from __future__ import annotations

from dataclasses import dataclass

import tiktoken

# text-embedding-3-large input limit is 8192 tokens; stay well below.
DEFAULT_MAX_TOKENS = 800
DEFAULT_OVERLAP_TOKENS = 100


@dataclass(frozen=True)
class TextChunk:
    chunk_index: int
    text: str
    token_count: int


def _encoding(model: str = "text-embedding-3-large"):
    try:
        return tiktoken.encoding_for_model(model)
    except KeyError:
        return tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str, *, model: str = "text-embedding-3-large") -> int:
    return len(_encoding(model).encode(text or ""))


def chunk_text(
    text: str,
    *,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    overlap_tokens: int = DEFAULT_OVERLAP_TOKENS,
    model: str = "text-embedding-3-large",
) -> list[TextChunk]:
    """
    Split text into overlapping token windows.

    Uses tiktoken (cl100k-compatible) so chunks respect model limits.
    """
    cleaned = (text or "").strip()
    if not cleaned:
        return []
    if max_tokens < 32:
        raise ValueError("max_tokens too small")
    overlap_tokens = max(0, min(overlap_tokens, max_tokens // 2))

    enc = _encoding(model)
    tokens = enc.encode(cleaned)
    if len(tokens) <= max_tokens:
        return [TextChunk(chunk_index=0, text=cleaned, token_count=len(tokens))]

    chunks: list[TextChunk] = []
    start = 0
    step = max_tokens - overlap_tokens
    while start < len(tokens):
        end = min(start + max_tokens, len(tokens))
        window = tokens[start:end]
        piece = enc.decode(window).strip()
        if piece:
            chunks.append(
                TextChunk(
                    chunk_index=len(chunks),
                    text=piece,
                    token_count=len(window),
                )
            )
        if end >= len(tokens):
            break
        start += step
    return chunks
