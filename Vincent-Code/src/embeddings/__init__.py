"""Topic / knowledge embeddings (OpenAI text-embedding-3-large)."""

from src.embeddings.chunking import TextChunk, chunk_text
from src.embeddings.openai_embed import EmbeddingClient, DEFAULT_EMBEDDING_MODEL
from src.embeddings.store import EmbeddingStore

__all__ = [
    "TextChunk",
    "chunk_text",
    "EmbeddingClient",
    "DEFAULT_EMBEDDING_MODEL",
    "EmbeddingStore",
]
