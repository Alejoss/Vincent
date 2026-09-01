"""HTTP client for Sophia embedding-ingest API (external embed worker ack).

Same auth as transcript-ingest: X-Transcript-Ingest-Key / Bearer
TRANSCRIPT_INGEST_API_KEY.

Base: SOPHIA_API_BASE → /content/embedding-ingest/
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional
from urllib.parse import urljoin

import requests

from src.sophia_transcript_ingest import (
    SophiaTranscriptIngestError,
    resolve_api_base,
    resolve_ingest_key,
)

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 60.0

# Re-export for callers that only import this module
SophiaEmbeddingIngestError = SophiaTranscriptIngestError


class SophiaEmbeddingIngestClient:
    """Machine-to-machine client for /api/content/embedding-ingest/."""

    def __init__(
        self,
        *,
        api_base: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: float = DEFAULT_TIMEOUT,
        session: Optional[requests.Session] = None,
    ):
        self.api_base = resolve_api_base(api_base)
        self.api_key = resolve_ingest_key(api_key)
        self.timeout = timeout
        self.session = session or requests.Session()

    @property
    def ingest_root(self) -> str:
        return urljoin(self.api_base.rstrip("/") + "/", "content/embedding-ingest/")

    def _headers(self) -> dict[str, str]:
        return {
            "X-Transcript-Ingest-Key": self.api_key,
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": (
                os.getenv("SOPHIA_HTTP_USER_AGENT")
                or "VincentTopicEmbeddingWorker/1.0 (+https://www.academiablockchain.com)"
            ),
        }

    def _request(
        self,
        method: str,
        url: str,
        *,
        params: Optional[dict[str, Any]] = None,
        json_body: Optional[dict[str, Any]] = None,
    ) -> Any:
        response = self.session.request(
            method,
            url,
            headers=self._headers(),
            params=params,
            json=json_body,
            timeout=self.timeout,
        )
        if response.status_code >= 400:
            detail: Any
            try:
                detail = response.json()
            except Exception:
                detail = (response.text or "").strip()[:800]
            raise SophiaEmbeddingIngestError(
                f"{method} {url} → {response.status_code}: {detail}",
                status_code=response.status_code,
                body=detail,
            )
        if response.status_code == 204 or not (response.content or b"").strip():
            return None
        return response.json()

    def list_queue(
        self,
        *,
        topic_id: Optional[int] = None,
        include_completed: bool = False,
        media_type: Optional[str] = None,
        content_id: Optional[int] = None,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "limit": max(1, min(int(limit), 500)),
            "offset": max(0, int(offset)),
        }
        if topic_id is not None:
            params["topic_id"] = int(topic_id)
        if include_completed:
            params["include_completed"] = "true"
        if media_type:
            params["media_type"] = media_type
        if content_id is not None:
            params["content_id"] = int(content_id)
        if status:
            params["status"] = status
        return self._request("GET", self.ingest_root, params=params)

    def list_queue_all(
        self,
        *,
        topic_id: Optional[int] = None,
        include_completed: bool = False,
        media_type: Optional[str] = None,
        content_id: Optional[int] = None,
        status: Optional[str] = None,
        page_size: int = 100,
    ) -> list[dict[str, Any]]:
        """Paginate until all queue items are fetched."""
        items: list[dict[str, Any]] = []
        offset = 0
        while True:
            page = self.list_queue(
                topic_id=topic_id,
                include_completed=include_completed,
                media_type=media_type,
                content_id=content_id,
                status=status,
                limit=page_size,
                offset=offset,
            )
            batch = list(page.get("items") or [])
            items.extend(batch)
            count = int(page.get("count") or 0)
            offset += len(batch)
            if not batch or offset >= count:
                break
        return items

    def get_item(self, content_id: int) -> dict[str, Any]:
        url = urljoin(self.ingest_root, f"{int(content_id)}/")
        return self._request("GET", url)

    def is_available(self) -> bool:
        """True if embedding-ingest responds (not 404)."""
        try:
            self.list_queue(limit=1)
            return True
        except SophiaEmbeddingIngestError as exc:
            if exc.status_code == 404:
                return False
            # 403 / other errors mean the route exists but auth/config failed
            if exc.status_code in {401, 403}:
                return True
            raise

    def ack(
        self,
        content_id: int,
        *,
        status: str,
        embedding_model: str = "",
        embedding_dims: Optional[int] = None,
        chunk_count: Optional[int] = None,
        embedded_text_hash: str = "",
        embedding_error: str = "",
        embedded_at: Optional[str] = None,
    ) -> dict[str, Any]:
        """PUT ack after vectors are upserted to Qdrant (or failed/skipped)."""
        payload: dict[str, Any] = {"status": status}
        if embedding_model:
            payload["embedding_model"] = embedding_model
        if embedding_dims is not None:
            payload["embedding_dims"] = int(embedding_dims)
        if chunk_count is not None:
            payload["chunk_count"] = int(chunk_count)
        if embedded_text_hash:
            payload["embedded_text_hash"] = embedded_text_hash
        if embedding_error:
            payload["embedding_error"] = embedding_error
        if embedded_at:
            payload["embedded_at"] = embedded_at
        url = urljoin(self.ingest_root, f"{int(content_id)}/")
        return self._request("PUT", url, json_body=payload)

    def ack_indexed(
        self,
        content_id: int,
        *,
        embedding_model: str,
        embedding_dims: int,
        chunk_count: int,
        embedded_text_hash: str = "",
    ) -> dict[str, Any]:
        return self.ack(
            content_id,
            status="indexed",
            embedding_model=embedding_model,
            embedding_dims=embedding_dims,
            chunk_count=chunk_count,
            embedded_text_hash=embedded_text_hash,
        )

    def ack_failed(
        self,
        content_id: int,
        *,
        embedding_error: str,
        embedding_model: str = "",
        embedding_dims: Optional[int] = None,
    ) -> dict[str, Any]:
        return self.ack(
            content_id,
            status="failed",
            embedding_error=embedding_error,
            embedding_model=embedding_model,
            embedding_dims=embedding_dims,
        )

    def ack_skipped(
        self,
        content_id: int,
        *,
        embedding_error: str = "",
        embedding_model: str = "",
    ) -> dict[str, Any]:
        return self.ack(
            content_id,
            status="skipped",
            embedding_error=embedding_error,
            embedding_model=embedding_model,
        )
