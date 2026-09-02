"""Unit tests for Vincent MCP helpers (no live APIs)."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.embeddings.query import cosine, hits_to_sources, retrieve
from src.knowledge_engine_state import (
    insert_knowledge_items,
    mark_extraction_done,
    open_engine,
    search_knowledge_items,
    upsert_video,
)
from src.mcp.confirm import REFUSE_MESSAGE, write_gate


class TestWriteGate(unittest.TestCase):
    def test_refuse_without_confirm(self):
        out = write_gate(confirm=False, dry_run=False)
        self.assertIsNotNone(out)
        self.assertFalse(out["ok"])
        self.assertIn("confirm", out["error"])

    def test_allow_dry_run_without_confirm(self):
        self.assertIsNone(write_gate(confirm=False, dry_run=True))

    def test_allow_confirm(self):
        self.assertIsNone(write_gate(confirm=True, dry_run=False))


class TestRetrieve(unittest.TestCase):
    def test_cosine_identical(self):
        self.assertAlmostEqual(cosine([1.0, 0.0], [1.0, 0.0]), 1.0)

    def test_retrieve_dedupes_content(self):
        chunks = [
            {"content_id": 1, "embedding": [1.0, 0.0], "text": "a", "title": "A", "chunk_index": 0, "media_type": "VIDEO"},
            {"content_id": 1, "embedding": [0.99, 0.01], "text": "b", "title": "A", "chunk_index": 1, "media_type": "VIDEO"},
            {"content_id": 1, "embedding": [0.98, 0.02], "text": "c", "title": "A", "chunk_index": 2, "media_type": "VIDEO"},
            {"content_id": 2, "embedding": [0.0, 1.0], "text": "other", "title": "B", "chunk_index": 0, "media_type": "AUDIO"},
        ]
        hits = retrieve(chunks, [1.0, 0.0], top_k=4, max_chunks_per_content=2)
        content_ids = [h[1]["content_id"] for h in hits]
        self.assertEqual(content_ids.count(1), 2)
        sources = hits_to_sources(hits)
        self.assertEqual(sources[0]["index"], 1)
        self.assertTrue(sources[0]["excerpt"])


class TestKnowledgeSearch(unittest.TestCase):
    def test_search_matches_payload_and_title(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            conn = open_engine(root)
            upsert_video(
                conn,
                video_id="vid-1",
                source_kind="local",
                title="Paragon Solutions y Epstein",
                source_url="",
                source_path="x.md",
                transcript_path=str(root / "x.md"),
                transcript_hash="abc",
                word_count=10,
                language_code="es",
                published_at=None,
            )
            Path(root / "x.md").write_text("hi", encoding="utf-8")
            mark_extraction_done(
                conn,
                extraction_id="ex-1",
                video_id="vid-1",
                model="test",
                transcript_hash="abc",
                summary="Notas sobre vigilancia",
                output_md_path=str(root / "out.md"),
                output_json_path=str(root / "out.json"),
                prompt_tokens=1,
                completion_tokens=1,
            )
            insert_knowledge_items(
                conn,
                extraction_id="ex-1",
                video_id="vid-1",
                items=[
                    {
                        "item_type": "claim",
                        "item_key": "k1",
                        "payload": {"text": "Paragon vende spyware a gobiernos"},
                        "anchor_text": "spyware",
                    }
                ],
            )
            hits = search_knowledge_items(conn, "spyware paragon", limit=5)
            conn.close()
            self.assertGreaterEqual(len(hits), 1)
            self.assertEqual(hits[0]["item_type"], "claim")


class TestExtractLimitGuard(unittest.TestCase):
    def test_unbounded_extract_refused(self):
        from src.mcp.knowledge import extract_knowledge

        out = extract_knowledge(confirm=True, dry_run=False, limit=0, transcript_id=None)
        self.assertFalse(out["ok"])
        self.assertIn("unbounded", out["error"].lower())

    def test_extract_requires_confirm(self):
        from src.mcp.knowledge import extract_knowledge

        out = extract_knowledge(confirm=False, dry_run=False, limit=1)
        self.assertFalse(out["ok"])
        self.assertTrue(out.get("needs_confirm"))


class TestMcpServerImport(unittest.TestCase):
    def test_server_lists_expected_tools(self):
        try:
            from mcp.server import MCPServer  # noqa: F401
        except ImportError:
            self.skipTest("mcp package not installed")
        from src.mcp.server import mcp

        names = {t.name for t in mcp._tool_manager.list_tools()}
        expected = {
            "vincent_health",
            "search_topic",
            "search_knowledge",
            "knowledge_status",
            "list_open_tasks",
            "extract_knowledge",
            "complete_task",
            "embed_topic",
            "sync_topic",
            "run_topic_pipeline",
            "run_productivity_pipeline",
        }
        self.assertTrue(expected.issubset(names), msg=f"missing {expected - names}; have {names}")


if __name__ == "__main__":
    unittest.main()
