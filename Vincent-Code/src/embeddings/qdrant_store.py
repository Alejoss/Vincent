"""Qdrant Cloud client for Sophia topic chunk embeddings."""

from __future__ import annotations

import hashlib
import logging
import os
import uuid
from typing import Any, Optional, Sequence

import requests

logger = logging.getLogger(__name__)

DEFAULT_COLLECTION = "sophia_acbc_topic_chunks"
DEFAULT_TIMEOUT = 60.0


class QdrantStoreError(RuntimeError):
    def __init__(self, message: str, *, status_code: Optional[int] = None, body: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


def resolve_qdrant_url(explicit: Optional[str] = None) -> str:
    raw = (explicit or os.getenv("QDRANT_URL") or "").strip().rstrip("/")
    if not raw:
        raise ValueError(
            "QDRANT_URL is required (e.g. https://xxxxx.us-west-2-0.aws.cloud.qdrant.io)"
        )
    return raw


def resolve_qdrant_api_key(explicit: Optional[str] = None) -> str:
    key = (explicit or os.getenv("QDRANT_API_KEY") or "").strip()
    if not key:
        raise ValueError("QDRANT_API_KEY is required")
    return key


def resolve_collection(explicit: Optional[str] = None) -> str:
    return (explicit or os.getenv("QDRANT_COLLECTION") or DEFAULT_COLLECTION).strip()


def point_uuid(doc_key: str, chunk_index: int, model: str) -> str:
    """Stable UUID for a chunk point (Qdrant accepts UUID string ids)."""
    digest = hashlib.sha256(f"{doc_key}|{chunk_index}|{model}".encode("utf-8")).hexdigest()
    return str(uuid.UUID(digest[:32]))


class QdrantStore:
    """Minimal REST client: ensure collection + upsert/delete topic chunks."""

    def __init__(
        self,
        *,
        url: Optional[str] = None,
        api_key: Optional[str] = None,
        collection: Optional[str] = None,
        timeout: float = DEFAULT_TIMEOUT,
        session: Optional[requests.Session] = None,
    ):
        self.base_url = resolve_qdrant_url(url)
        self.api_key = resolve_qdrant_api_key(api_key)
        self.collection = resolve_collection(collection)
        self.timeout = timeout
        self.session = session or requests.Session()
        self._ensured_dims: Optional[int] = None

    def _headers(self) -> dict[str, str]:
        return {
            "api-key": self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: Optional[dict[str, Any]] = None,
    ) -> Any:
        url = f"{self.base_url}{path}"
        response = self.session.request(
            method,
            url,
            headers=self._headers(),
            json=json_body,
            timeout=self.timeout,
        )
        if response.status_code >= 400:
            detail: Any
            try:
                detail = response.json()
            except Exception:
                detail = (response.text or "").strip()[:800]
            raise QdrantStoreError(
                f"{method} {path} → {response.status_code}: {detail}",
                status_code=response.status_code,
                body=detail,
            )
        if response.status_code == 204 or not (response.content or b"").strip():
            return None
        return response.json()

    def ensure_collection(self, vector_size: int) -> None:
        if self._ensured_dims == vector_size:
            return
        # GET collection — 404 means create
        check = self.session.get(
            f"{self.base_url}/collections/{self.collection}",
            headers=self._headers(),
            timeout=self.timeout,
        )
        if check.status_code == 200:
            self._ensure_payload_indexes()
            self._ensured_dims = vector_size
            return
        if check.status_code not in (404, 400):
            detail: Any
            try:
                detail = check.json()
            except Exception:
                detail = (check.text or "").strip()[:800]
            raise QdrantStoreError(
                f"GET /collections/{self.collection} → {check.status_code}: {detail}",
                status_code=check.status_code,
                body=detail,
            )
        logger.info(
            "Creating Qdrant collection %s (size=%s)",
            self.collection,
            vector_size,
        )
        self._request(
            "PUT",
            f"/collections/{self.collection}",
            json_body={
                "vectors": {
                    "size": int(vector_size),
                    "distance": "Cosine",
                }
            },
        )
        self._ensure_payload_indexes()
        self._ensured_dims = vector_size

    def _ensure_payload_indexes(self) -> None:
        """Qdrant Cloud strict mode requires indexes before filtering on payload keys."""
        indexes = (
            ("doc_key", "keyword"),
            ("embedding_model", "keyword"),
            ("media_type", "keyword"),
            ("text_hash", "keyword"),
            ("topic_id", "integer"),
            ("content_id", "integer"),
            ("chunk_index", "integer"),
        )
        for field_name, field_schema in indexes:
            response = self.session.put(
                f"{self.base_url}/collections/{self.collection}/index",
                headers=self._headers(),
                json={"field_name": field_name, "field_schema": field_schema},
                timeout=self.timeout,
            )
            # 200 ok; 409 / already exists variants are fine
            if response.status_code in (200, 201, 409):
                continue
            detail: Any
            try:
                detail = response.json()
            except Exception:
                detail = (response.text or "").strip()[:400]
            # Some clusters return 400 with "already exists"
            text = str(detail).lower()
            if response.status_code == 400 and (
                "already" in text or "exist" in text
            ):
                continue
            raise QdrantStoreError(
                f"PUT index {field_name} → {response.status_code}: {detail}",
                status_code=response.status_code,
                body=detail,
            )

    def delete_by_doc_key(self, doc_key: str, *, model: str) -> None:
        self._request(
            "POST",
            f"/collections/{self.collection}/points/delete",
            json_body={
                "filter": {
                    "must": [
                        {"key": "doc_key", "match": {"value": doc_key}},
                        {"key": "embedding_model", "match": {"value": model}},
                    ]
                }
            },
        )

    def upsert_chunks(
        self,
        *,
        doc_key: str,
        topic_id: int,
        content_id: Optional[int],
        media_type: str,
        text_hash: str,
        model: str,
        chunks: Sequence[dict[str, Any]],
        title: str = "",
        author: str = "",
    ) -> int:
        """
        Replace all points for doc_key+model with the given chunks.

        chunks: [{chunk_index, text, token_count, embedding: list[float]}, ...]
        """
        if not chunks:
            self.delete_by_doc_key(doc_key, model=model)
            return 0

        dims = len(chunks[0]["embedding"])
        self.ensure_collection(dims)
        self.delete_by_doc_key(doc_key, model=model)

        points = []
        for ch in chunks:
            emb = ch["embedding"]
            if len(emb) != dims:
                raise QdrantStoreError(
                    f"Inconsistent embedding dims for {doc_key}: {len(emb)} vs {dims}"
                )
            points.append(
                {
                    "id": point_uuid(doc_key, int(ch["chunk_index"]), model),
                    "vector": emb,
                    "payload": {
                        "doc_key": doc_key,
                        "topic_id": int(topic_id),
                        "content_id": content_id,
                        "media_type": media_type,
                        "chunk_index": int(ch["chunk_index"]),
                        "token_count": int(ch["token_count"]),
                        "text_hash": text_hash,
                        "embedding_model": model,
                        "embedding_dims": dims,
                        "title": title or "",
                        "author": author or "",
                        "text": ch["text"],
                    },
                }
            )

        # Batch upsert (Qdrant accepts large batches; keep modest)
        batch_size = 64
        for i in range(0, len(points), batch_size):
            batch = points[i : i + batch_size]
            self._request(
                "PUT",
                f"/collections/{self.collection}/points?wait=true",
                json_body={"points": batch},
            )
        return len(points)

    def count_topic(self, topic_id: int) -> int:
        data = self._request(
            "POST",
            f"/collections/{self.collection}/points/count",
            json_body={
                "filter": {
                    "must": [{"key": "topic_id", "match": {"value": int(topic_id)}}]
                },
                "exact": True,
            },
        )
        result = (data or {}).get("result") or {}
        return int(result.get("count") or 0)

    def ping(self) -> dict[str, Any]:
        """Health check: cluster root + collection exists (or will be creatable)."""
        root = self.session.get(
            self.base_url,
            headers=self._headers(),
            timeout=self.timeout,
        )
        if root.status_code >= 400:
            raise QdrantStoreError(
                f"GET / → {root.status_code}: {(root.text or '')[:300]}",
                status_code=root.status_code,
                body=(root.text or "")[:300],
            )
        root_body: Any
        try:
            root_body = root.json()
        except Exception:
            root_body = {"raw": (root.text or "")[:200]}

        coll = self.session.get(
            f"{self.base_url}/collections/{self.collection}",
            headers=self._headers(),
            timeout=self.timeout,
        )
        return {
            "url": self.base_url,
            "collection": self.collection,
            "version": (root_body or {}).get("version"),
            "collection_status": coll.status_code,
            "collection_exists": coll.status_code == 200,
            "points_count": (
                ((coll.json().get("result") or {}).get("points_count"))
                if coll.status_code == 200
                else None
            ),
        }
