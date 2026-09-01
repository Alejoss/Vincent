"""Public Sophia Topics API client (no JWT required for public topics).

Endpoints used:
  GET /content/topics/{id}/
  GET /content/topics/{id}/content/{MEDIA_TYPE}/
"""

from __future__ import annotations

import os
from typing import Any, Optional
from urllib.parse import urljoin

import requests

DEFAULT_API_BASE = "https://www.academiablockchain.com/api"
DEFAULT_UA = "VincentTopicEmbeddings/1.0 (+https://www.academiablockchain.com)"
MEDIA_TYPES = ("VIDEO", "AUDIO", "TEXT", "IMAGE", "LINK")


def resolve_api_base(explicit: Optional[str] = None) -> str:
    raw = (explicit or os.getenv("SOPHIA_API_BASE") or DEFAULT_API_BASE).strip().rstrip("/")
    if not raw:
        raise ValueError("SOPHIA_API_BASE is required")
    if raw.endswith("/api"):
        return raw
    return f"{raw}/api"


class SophiaTopicsClient:
    def __init__(
        self,
        *,
        api_base: Optional[str] = None,
        timeout: float = 60.0,
        session: Optional[requests.Session] = None,
    ):
        self.api_base = resolve_api_base(api_base)
        self.timeout = timeout
        self.session = session or requests.Session()

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "User-Agent": os.getenv("SOPHIA_HTTP_USER_AGENT") or DEFAULT_UA,
        }

    def _get(self, path: str, *, params: Optional[dict[str, Any]] = None) -> Any:
        url = urljoin(self.api_base.rstrip("/") + "/", path.lstrip("/"))
        response = self.session.get(
            url, headers=self._headers(), params=params, timeout=self.timeout
        )
        if response.status_code >= 400:
            detail = (response.text or "")[:500]
            raise RuntimeError(f"GET {url} → {response.status_code}: {detail}")
        return response.json()

    def get_topic(self, topic_id: int) -> dict[str, Any]:
        return self._get(f"content/topics/{int(topic_id)}/")

    def list_content_by_type(
        self,
        topic_id: int,
        media_type: str,
        *,
        page_size: int = 100,
    ) -> list[dict[str, Any]]:
        media_type = media_type.upper()
        items: list[dict[str, Any]] = []
        page = 1
        while True:
            data = self._get(
                f"content/topics/{int(topic_id)}/content/{media_type}/",
                params={"page": page, "page_size": min(page_size, 100)},
            )
            batch = list(data.get("results") or data.get("contents") or [])
            items.extend(batch)
            if not data.get("has_next"):
                break
            page += 1
            if page > 50:
                break
        return items

    def list_topic_contents(
        self,
        topic_id: int,
        *,
        media_types: Optional[tuple[str, ...]] = None,
        include_images: bool = False,
    ) -> list[dict[str, Any]]:
        types = media_types or MEDIA_TYPES
        out: list[dict[str, Any]] = []
        for mtype in types:
            if mtype == "IMAGE" and not include_images:
                continue
            out.extend(self.list_content_by_type(topic_id, mtype))
        return out
