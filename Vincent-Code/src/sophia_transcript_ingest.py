"""HTTP client for Sophia transcript-ingest API (external worker).

Auth: X-Transcript-Ingest-Key (or Authorization: Bearer) with TRANSCRIPT_INGEST_API_KEY.
Base URL: SOPHIA_API_BASE (e.g. https://www.academiablockchain.com/api).
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional
from urllib.parse import urljoin

import requests

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 60.0


class SophiaTranscriptIngestError(RuntimeError):
    """Raised when the ingest API returns an error response."""

    def __init__(self, message: str, *, status_code: Optional[int] = None, body: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


def resolve_api_base(explicit: Optional[str] = None) -> str:
    raw = (explicit or os.getenv("SOPHIA_API_BASE") or "").strip().rstrip("/")
    if not raw:
        raise ValueError(
            "SOPHIA_API_BASE is required (e.g. https://www.academiablockchain.com/api)"
        )
    # Accept either .../api or site root; normalize to .../api
    if raw.endswith("/api"):
        return raw
    return f"{raw}/api"


def resolve_ingest_key(explicit: Optional[str] = None) -> str:
    key = (explicit or os.getenv("TRANSCRIPT_INGEST_API_KEY") or "").strip()
    if not key:
        raise ValueError("TRANSCRIPT_INGEST_API_KEY is required")
    return key


class SophiaTranscriptIngestClient:
    """Machine-to-machine client for /api/content/transcript-ingest/."""

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
        return urljoin(self.api_base.rstrip("/") + "/", "content/transcript-ingest/")

    def _headers(self) -> dict[str, str]:
        # Cloudflare may block non-browser clients without a User-Agent (error 1010).
        return {
            "X-Transcript-Ingest-Key": self.api_key,
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": (
                os.getenv("SOPHIA_HTTP_USER_AGENT")
                or "VincentTopicTranscriptWorker/1.0 (+https://www.academiablockchain.com)"
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
            raise SophiaTranscriptIngestError(
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
        return self._request("GET", self.ingest_root, params=params)

    def list_queue_all(
        self,
        *,
        topic_id: Optional[int] = None,
        include_completed: bool = False,
        media_type: Optional[str] = None,
        content_id: Optional[int] = None,
        page_size: int = 100,
    ) -> list[dict[str, Any]]:
        """Paginate until all items are fetched."""
        items: list[dict[str, Any]] = []
        offset = 0
        while True:
            page = self.list_queue(
                topic_id=topic_id,
                include_completed=include_completed,
                media_type=media_type,
                content_id=content_id,
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

    def put_transcript(self, content_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        url = urljoin(self.ingest_root, f"{int(content_id)}/")
        return self._request("PUT", url, json_body=payload)
