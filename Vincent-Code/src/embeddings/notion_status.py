"""Notion board for Sophia topic embedding status (agent-queryable).

One row per public topic. Keyed by numeric Topic ID.
Do not reuse the old Processed Transcripts "Embeddings Ready" checkbox —
that is a different pipeline (YouTube/Obsidian transcripts).
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Optional

from notion_client import Client

from src.notion_vincent import normalize_id

BUCKET_OPTIONS = (
    "needs_embeddings",
    "ready",
    "needs_transcripts",
    "partial",
    "skipped_only",
    "no_av",
)

# Logical name → (Notion property name, type)
SCHEMA: dict[str, tuple[str, str]] = {
    "title": ("Name", "title"),
    "topic_id": ("Topic ID", "number"),
    "bucket": ("Bucket", "select"),
    "needs_embeddings": ("Needs embeddings", "checkbox"),
    "needs_transcripts": ("Needs transcripts", "checkbox"),
    "ready": ("Ready", "checkbox"),
    "indexed": ("Indexed", "number"),
    "pending": ("Pending", "number"),
    "stale": ("Stale", "number"),
    "failed": ("Failed", "number"),
    "skipped": ("Skipped", "number"),
    "av_count": ("AV count", "number"),
    "transcribed": ("Transcribed", "number"),
    "missing_transcripts": ("Missing transcripts", "number"),
    "chat_enabled": ("Chat enabled", "checkbox"),
    "chat_can_enable": ("Chat can enable", "checkbox"),
    "last_synced": ("Last synced", "date"),
}

DATABASE_TITLE = "Sophia Topic Embeddings"


def _now_iso_date() -> str:
    return datetime.now(tz=timezone.utc).date().isoformat()


def title_property_payload(text: str) -> dict[str, Any]:
    return {"title": [{"type": "text", "text": {"content": (text or "")[:2000]}}]}


def row_to_properties(row: dict[str, Any]) -> dict[str, Any]:
    """Map a topic_summary_row to Notion property values (canonical names)."""
    bucket = row.get("bucket") or "no_av"
    if bucket not in BUCKET_OPTIONS:
        bucket = "no_av"
    return {
        "Name": title_property_payload(str(row.get("title") or f"topic-{row.get('topic_id')}")),
        "Topic ID": {"number": int(row["topic_id"])},
        "Bucket": {"select": {"name": bucket}},
        "Needs embeddings": {"checkbox": bool(row.get("needs_embeddings"))},
        "Needs transcripts": {"checkbox": bool(row.get("needs_transcripts"))},
        "Ready": {"checkbox": bool(row.get("ready"))},
        "Indexed": {"number": int(row.get("indexed") or 0)},
        "Pending": {"number": int(row.get("pending") or 0)},
        "Stale": {"number": int(row.get("stale") or 0)},
        "Failed": {"number": int(row.get("failed") or 0)},
        "Skipped": {"number": int(row.get("skipped") or 0)},
        "AV count": {"number": int(row.get("av_count") or 0)},
        "Transcribed": {"number": int(row.get("transcribed_count") or 0)},
        "Missing transcripts": {"number": int(row.get("missing_transcripts") or 0)},
        "Chat enabled": {"checkbox": bool(row.get("chat_enabled"))},
        "Chat can enable": {"checkbox": bool(row.get("chat_can_enable"))},
        "Last synced": {"date": {"start": _now_iso_date()}},
    }


def schema_create_properties() -> dict[str, Any]:
    """Properties payload for databases.create (includes title)."""
    return {
        "Name": {"title": {}},
        "Topic ID": {"number": {}},
        "Bucket": {
            "select": {"options": [{"name": name} for name in BUCKET_OPTIONS]}
        },
        "Needs embeddings": {"checkbox": {}},
        "Needs transcripts": {"checkbox": {}},
        "Ready": {"checkbox": {}},
        "Indexed": {"number": {}},
        "Pending": {"number": {}},
        "Stale": {"number": {}},
        "Failed": {"number": {}},
        "Skipped": {"number": {}},
        "AV count": {"number": {}},
        "Transcribed": {"number": {}},
        "Missing transcripts": {"number": {}},
        "Chat enabled": {"checkbox": {}},
        "Chat can enable": {"checkbox": {}},
        "Last synced": {"date": {}},
    }


def missing_schema_properties(existing: dict[str, Any]) -> dict[str, Any]:
    """Return create payload for properties not already present (skip title)."""
    have = {name.lower() for name in existing}
    payload: dict[str, Any] = {}
    for name, spec in schema_create_properties().items():
        if name == "Name":
            continue
        if name.lower() in have:
            continue
        payload[name] = spec
    return payload


class EmbeddingStatusNotionClient:
    def __init__(
        self,
        *,
        api_token: Optional[str] = None,
        database_id: Optional[str] = None,
        notion_version: str = "2025-09-03",
    ):
        token = (api_token or os.getenv("NOTION_API_TOKEN") or "").strip()
        if not token:
            raise ValueError("NOTION_API_TOKEN is required")
        raw_id = (
            database_id or os.getenv("NOTION_EMBEDDING_STATUS_DATABASE_ID") or ""
        ).strip()
        if not raw_id:
            raise ValueError("NOTION_EMBEDDING_STATUS_DATABASE_ID is required")
        self.client = Client(auth=token, notion_version=notion_version)
        self.database_id = normalize_id(raw_id)
        self._data_source_id: Optional[str] = None

    def _data_source_id(self) -> str:
        if self._data_source_id is not None:
            return self._data_source_id
        db = self.client.databases.retrieve(database_id=self.database_id)
        sources = db.get("data_sources") or []
        self._data_source_id = sources[0]["id"] if sources else self.database_id
        return self._data_source_id

    def _properties(self) -> dict[str, Any]:
        ds_id = self._data_source_id()
        if ds_id == self.database_id:
            db = self.client.databases.retrieve(database_id=self.database_id)
            return db.get("properties") or {}
        ds = self.client.data_sources.retrieve(data_source_id=ds_id)
        return ds.get("properties") or {}

    def _update_properties(self, payload: dict[str, Any]) -> None:
        if not payload:
            return
        ds_id = self._data_source_id()
        if ds_id == self.database_id:
            self.client.databases.update(database_id=self.database_id, properties=payload)
        else:
            self.client.data_sources.update(data_source_id=ds_id, properties=payload)

    def ensure_schema(self) -> list[str]:
        payload = missing_schema_properties(self._properties())
        self._update_properties(payload)
        return list(payload.keys())

    def _query(self, **kwargs: Any) -> dict[str, Any]:
        ds_id = self._data_source_id()
        if ds_id == self.database_id:
            return self.client.databases.query(database_id=self.database_id, **kwargs)
        return self.client.data_sources.query(data_source_id=ds_id, **kwargs)

    def find_page_id(self, topic_id: int) -> Optional[str]:
        resp = self._query(
            filter={
                "property": "Topic ID",
                "number": {"equals": int(topic_id)},
            },
            page_size=1,
        )
        results = resp.get("results") or []
        if not results:
            return None
        return results[0].get("id")

    def upsert_topic(self, row: dict[str, Any]) -> str:
        props = row_to_properties(row)
        page_id = self.find_page_id(int(row["topic_id"]))
        if page_id:
            self.client.pages.update(page_id=page_id, properties=props)
            return page_id
        ds_id = self._data_source_id()
        parent = (
            {"type": "database_id", "database_id": self.database_id}
            if ds_id == self.database_id
            else {"type": "data_source_id", "data_source_id": ds_id}
        )
        created = self.client.pages.create(parent=parent, properties=props)
        return created["id"]


def create_database(
    *,
    api_token: str,
    parent_page_id: str,
    title: str = DATABASE_TITLE,
) -> str:
    """Create the status database under a Notion page. Returns database id."""
    client = Client(auth=api_token, notion_version="2025-09-03")
    parent_id = normalize_id(parent_page_id)
    created = client.databases.create(
        parent={"type": "page_id", "page_id": parent_id},
        title=[{"type": "text", "text": {"content": title}}],
        properties=schema_create_properties(),
    )
    return created["id"]
