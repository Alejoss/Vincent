"""SQLite store for topic embeddings (vectors as JSON float arrays)."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


class EmbeddingStore:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self._init()

    def close(self) -> None:
        self.conn.close()

    def _init(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS documents (
                doc_key TEXT PRIMARY KEY,
                topic_id INTEGER NOT NULL,
                content_id INTEGER,
                media_type TEXT NOT NULL,
                title TEXT,
                author TEXT,
                source TEXT,
                text_hash TEXT NOT NULL,
                char_count INTEGER,
                token_count INTEGER,
                chunk_count INTEGER,
                status TEXT NOT NULL,
                notes TEXT,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                doc_key TEXT NOT NULL REFERENCES documents(doc_key),
                topic_id INTEGER NOT NULL,
                content_id INTEGER,
                media_type TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,
                text TEXT NOT NULL,
                token_count INTEGER NOT NULL,
                embedding_model TEXT NOT NULL,
                embedding_dims INTEGER NOT NULL,
                embedding_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(doc_key, chunk_index, embedding_model)
            );

            CREATE INDEX IF NOT EXISTS idx_chunks_topic ON chunks(topic_id);
            CREATE INDEX IF NOT EXISTS idx_chunks_content ON chunks(content_id);
            CREATE INDEX IF NOT EXISTS idx_docs_topic ON documents(topic_id);

            CREATE TABLE IF NOT EXISTS qdrant_sync (
                doc_key TEXT PRIMARY KEY,
                topic_id INTEGER NOT NULL,
                content_id INTEGER,
                media_type TEXT NOT NULL,
                text_hash TEXT NOT NULL,
                embedding_model TEXT NOT NULL,
                chunk_count INTEGER NOT NULL DEFAULT 0,
                qdrant_status TEXT NOT NULL DEFAULT 'pending',
                qdrant_synced_at TEXT,
                sophia_ack_status TEXT NOT NULL DEFAULT 'pending',
                sophia_acked_at TEXT,
                error TEXT,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_qdrant_sync_topic ON qdrant_sync(topic_id);
            """
        )
        self.conn.commit()

    def get_document(self, doc_key: str) -> Optional[dict[str, Any]]:
        row = self.conn.execute(
            "SELECT * FROM documents WHERE doc_key = ?", (doc_key,)
        ).fetchone()
        return dict(row) if row else None

    def document_is_current(self, doc_key: str, text_hash: str, model: str) -> bool:
        doc = self.get_document(doc_key)
        if not doc or doc.get("status") != "done":
            return False
        if doc.get("text_hash") != text_hash:
            return False
        row = self.conn.execute(
            """
            SELECT COUNT(*) AS n FROM chunks
            WHERE doc_key = ? AND embedding_model = ?
            """,
            (doc_key, model),
        ).fetchone()
        return int(row["n"] or 0) > 0

    def upsert_document(
        self,
        *,
        doc_key: str,
        topic_id: int,
        content_id: Optional[int],
        media_type: str,
        title: str,
        author: str,
        source: str,
        text_hash: str,
        char_count: int,
        token_count: int,
        chunk_count: int,
        status: str,
        notes: str = "",
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO documents (
                doc_key, topic_id, content_id, media_type, title, author, source,
                text_hash, char_count, token_count, chunk_count, status, notes, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(doc_key) DO UPDATE SET
                topic_id=excluded.topic_id,
                content_id=excluded.content_id,
                media_type=excluded.media_type,
                title=excluded.title,
                author=excluded.author,
                source=excluded.source,
                text_hash=excluded.text_hash,
                char_count=excluded.char_count,
                token_count=excluded.token_count,
                chunk_count=excluded.chunk_count,
                status=excluded.status,
                notes=excluded.notes,
                updated_at=excluded.updated_at
            """,
            (
                doc_key,
                int(topic_id),
                content_id,
                media_type,
                title,
                author,
                source,
                text_hash,
                int(char_count),
                int(token_count),
                int(chunk_count),
                status,
                notes,
                _now(),
            ),
        )
        self.conn.commit()

    def replace_chunks(
        self,
        *,
        doc_key: str,
        topic_id: int,
        content_id: Optional[int],
        media_type: str,
        model: str,
        chunks: list[dict[str, Any]],
    ) -> None:
        """chunks: [{chunk_index, text, token_count, embedding: list[float]}…]"""
        self.conn.execute("DELETE FROM chunks WHERE doc_key = ? AND embedding_model = ?", (doc_key, model))
        now = _now()
        for ch in chunks:
            emb = ch["embedding"]
            self.conn.execute(
                """
                INSERT INTO chunks (
                    doc_key, topic_id, content_id, media_type, chunk_index, text,
                    token_count, embedding_model, embedding_dims, embedding_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    doc_key,
                    int(topic_id),
                    content_id,
                    media_type,
                    int(ch["chunk_index"]),
                    ch["text"],
                    int(ch["token_count"]),
                    model,
                    len(emb),
                    json.dumps(emb),
                    now,
                ),
            )
        self.conn.commit()

    def topic_stats(self, topic_id: int) -> dict[str, Any]:
        docs = self.conn.execute(
            """
            SELECT status, COUNT(*) AS n FROM documents
            WHERE topic_id = ? GROUP BY status
            """,
            (int(topic_id),),
        ).fetchall()
        chunks = self.conn.execute(
            "SELECT COUNT(*) AS n FROM chunks WHERE topic_id = ?",
            (int(topic_id),),
        ).fetchone()
        return {
            "documents_by_status": {r["status"]: r["n"] for r in docs},
            "chunks": int(chunks["n"] or 0),
        }

    def list_done_documents(self, topic_id: int) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT * FROM documents
            WHERE topic_id = ? AND status = 'done'
            ORDER BY media_type, content_id
            """,
            (int(topic_id),),
        ).fetchall()
        return [dict(r) for r in rows]

    def list_chunks_for_doc(self, doc_key: str, model: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT chunk_index, text, token_count, embedding_json, embedding_dims
            FROM chunks
            WHERE doc_key = ? AND embedding_model = ?
            ORDER BY chunk_index
            """,
            (doc_key, model),
        ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["embedding"] = json.loads(item.pop("embedding_json"))
            out.append(item)
        return out

    def get_qdrant_sync(self, doc_key: str) -> Optional[dict[str, Any]]:
        row = self.conn.execute(
            "SELECT * FROM qdrant_sync WHERE doc_key = ?", (doc_key,)
        ).fetchone()
        return dict(row) if row else None

    def upsert_qdrant_sync(
        self,
        *,
        doc_key: str,
        topic_id: int,
        content_id: Optional[int],
        media_type: str,
        text_hash: str,
        embedding_model: str,
        chunk_count: int,
        qdrant_status: str,
        qdrant_synced_at: Optional[str] = None,
        sophia_ack_status: str = "pending",
        sophia_acked_at: Optional[str] = None,
        error: str = "",
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO qdrant_sync (
                doc_key, topic_id, content_id, media_type, text_hash, embedding_model,
                chunk_count, qdrant_status, qdrant_synced_at, sophia_ack_status,
                sophia_acked_at, error, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(doc_key) DO UPDATE SET
                topic_id=excluded.topic_id,
                content_id=excluded.content_id,
                media_type=excluded.media_type,
                text_hash=excluded.text_hash,
                embedding_model=excluded.embedding_model,
                chunk_count=excluded.chunk_count,
                qdrant_status=excluded.qdrant_status,
                qdrant_synced_at=excluded.qdrant_synced_at,
                sophia_ack_status=excluded.sophia_ack_status,
                sophia_acked_at=excluded.sophia_acked_at,
                error=excluded.error,
                updated_at=excluded.updated_at
            """,
            (
                doc_key,
                int(topic_id),
                content_id,
                media_type,
                text_hash,
                embedding_model,
                int(chunk_count),
                qdrant_status,
                qdrant_synced_at,
                sophia_ack_status,
                sophia_acked_at,
                error,
                _now(),
            ),
        )
        self.conn.commit()

    def qdrant_sync_stats(self, topic_id: int) -> dict[str, Any]:
        rows = self.conn.execute(
            """
            SELECT qdrant_status, sophia_ack_status, COUNT(*) AS n
            FROM qdrant_sync
            WHERE topic_id = ?
            GROUP BY qdrant_status, sophia_ack_status
            """,
            (int(topic_id),),
        ).fetchall()
        return [dict(r) for r in rows]
