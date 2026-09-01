"""OpenAI Embeddings API client (best quality: text-embedding-3-large)."""

from __future__ import annotations

import os
import time
from typing import Optional

import requests

DEFAULT_EMBEDDING_MODEL = "text-embedding-3-large"
DEFAULT_OPENAI_BASE = "https://api.openai.com/v1"
# API allows up to 2048 inputs per request; keep batches modest for reliability.
DEFAULT_BATCH_SIZE = 64


class EmbeddingClient:
    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: str = DEFAULT_EMBEDDING_MODEL,
        timeout_s: float = 120.0,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ):
        self.api_key = (api_key or os.getenv("OPENAI_API_KEY") or "").strip()
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY is required for embeddings")
        self.base_url = (
            base_url or os.getenv("OPENAI_API_BASE") or DEFAULT_OPENAI_BASE
        ).rstrip("/")
        self.model = (model or DEFAULT_EMBEDDING_MODEL).strip()
        self.timeout_s = timeout_s
        self.batch_size = max(1, min(int(batch_size), 2048))

    @property
    def label(self) -> str:
        return f"openai:{self.model}"

    def embed_texts(
        self,
        texts: list[str],
        *,
        dimensions: Optional[int] = None,
        max_retries: int = 5,
    ) -> list[list[float]]:
        """Embed texts in order; returns one vector per input string."""
        if not texts:
            return []
        out: list[list[float]] = []
        for i in range(0, len(texts), self.batch_size):
            batch = texts[i : i + self.batch_size]
            out.extend(
                self._embed_batch(
                    batch, dimensions=dimensions, max_retries=max_retries
                )
            )
        return out

    def _embed_batch(
        self,
        texts: list[str],
        *,
        dimensions: Optional[int],
        max_retries: int,
    ) -> list[list[float]]:
        payload: dict = {"model": self.model, "input": texts}
        # Omit dimensions → full native size (3072 for 3-large) = best quality
        if dimensions is not None:
            payload["dimensions"] = int(dimensions)

        url = f"{self.base_url}/embeddings"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        last_err: Optional[Exception] = None
        for attempt in range(max_retries):
            try:
                response = requests.post(
                    url, headers=headers, json=payload, timeout=self.timeout_s
                )
                if response.status_code in {429, 500, 502, 503, 504}:
                    wait = min(60.0, (2**attempt) + 0.25)
                    time.sleep(wait)
                    last_err = RuntimeError(
                        f"OpenAI embeddings {response.status_code}: "
                        f"{(response.text or '')[:300]}"
                    )
                    continue
                if response.status_code >= 400:
                    raise RuntimeError(
                        f"OpenAI embeddings {response.status_code}: "
                        f"{(response.text or '')[:500]}"
                    )
                data = response.json()
                items = sorted(data.get("data") or [], key=lambda x: x.get("index", 0))
                if len(items) != len(texts):
                    raise RuntimeError(
                        f"Expected {len(texts)} embeddings, got {len(items)}"
                    )
                return [list(map(float, it["embedding"])) for it in items]
            except (requests.RequestException, ValueError, KeyError) as exc:
                last_err = exc
                time.sleep(min(60.0, (2**attempt) + 0.25))
        raise RuntimeError(f"Embeddings failed after retries: {last_err}")
