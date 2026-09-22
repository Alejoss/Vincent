"""Unit tests for Vincent MCP helpers (no live APIs)."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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
            "map_topic",
            "topic_embedding_status",
            "search_knowledge",
            "knowledge_status",
            "list_open_tasks",
            "extract_knowledge",
            "complete_task",
            "embed_topic",
            "sync_topic",
            "run_topic_pipeline",
            "run_productivity_pipeline",
            "transcribe_local_video",
            "extract_local_audio",
            "generate_podcast_covers",
        }
        self.assertTrue(expected.issubset(names), msg=f"missing {expected - names}; have {names}")


class TestTranscribeLocalVideo(unittest.TestCase):
    def test_requires_confirm(self):
        from src.mcp.local_video import transcribe_local_video

        out = transcribe_local_video(video="E:/missing.mp4", confirm=False)
        self.assertFalse(out["ok"])
        self.assertTrue(out.get("needs_confirm"))

    def test_missing_file(self):
        from src.mcp.local_video import transcribe_local_video

        out = transcribe_local_video(
            video="E:/no-such-video-vincent-test.mp4", confirm=True
        )
        self.assertFalse(out["ok"])
        self.assertIn("not found", out["error"].lower())

    def test_empty_path(self):
        from src.mcp.local_video import transcribe_local_video

        out = transcribe_local_video(video="  ", dry_run=True)
        self.assertFalse(out["ok"])
        self.assertIn("empty", out["error"].lower())

    def test_unsupported_extension(self):
        from src.mcp.local_video import transcribe_local_video

        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as handle:
            path = Path(handle.name)
        try:
            out = transcribe_local_video(video=str(path), dry_run=True)
            self.assertFalse(out["ok"])
            self.assertIn("extension", out["error"].lower())
        finally:
            path.unlink(missing_ok=True)

    def test_dry_run_invokes_script(self):
        from src.mcp.local_video import transcribe_local_video

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as handle:
            path = Path(handle.name)
        try:
            with mock.patch("src.mcp.local_video.run_script") as run:
                run.return_value = {"ok": True, "dry_run": True, "job": "transcribe_local_video"}
                out = transcribe_local_video(video=str(path), dry_run=True)
            self.assertTrue(out["ok"])
            job, script, args = run.call_args.args[:3]
            self.assertEqual(job, "transcribe_local_video")
            self.assertEqual(script, "transcribe_one_local_video.py")
            self.assertIn("--dry-run", args)
            self.assertIn("--chunk-long-audio", args)
            self.assertEqual(run.call_args.kwargs["wait"], False)
        finally:
            path.unlink(missing_ok=True)


class TestExtractLocalAudio(unittest.TestCase):
    def test_requires_confirm(self):
        from src.mcp.local_video import extract_local_audio

        out = extract_local_audio(video="E:/missing.mp4", confirm=False)
        self.assertFalse(out["ok"])
        self.assertTrue(out.get("needs_confirm"))

    def test_dry_run_invokes_script(self):
        from src.mcp.local_video import extract_local_audio

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as handle:
            path = Path(handle.name)
        try:
            with mock.patch("src.mcp.local_video.run_script") as run:
                run.return_value = {"ok": True, "dry_run": True, "job": "extract_local_audio"}
                out = extract_local_audio(video=str(path), dry_run=True)
            self.assertTrue(out["ok"])
            job, script, args = run.call_args.args[:3]
            self.assertEqual(job, "extract_local_audio")
            self.assertEqual(script, "extract_one_video_audio.py")
            self.assertIn("--dry-run", args)
            self.assertIn("--output-dir", args)
            self.assertTrue(out["output_mp3"].endswith(".mp3"))
        finally:
            path.unlink(missing_ok=True)


class TestGeneratePodcastCovers(unittest.TestCase):
    def test_requires_confirm(self):
        from src.mcp.local_video import generate_podcast_covers

        out = generate_podcast_covers(confirm=False, limit=1)
        self.assertFalse(out["ok"])
        self.assertTrue(out.get("needs_confirm"))

    def test_limit_must_be_positive(self):
        from src.mcp.local_video import generate_podcast_covers

        out = generate_podcast_covers(confirm=True, limit=0)
        self.assertFalse(out["ok"])
        self.assertIn("limit", out["error"].lower())

    def test_dry_run_invokes_script(self):
        from src.mcp.local_video import generate_podcast_covers

        with mock.patch("src.mcp.local_video.run_script") as run:
            run.return_value = {"ok": True, "dry_run": True, "job": "generate_podcast_covers"}
            out = generate_podcast_covers(
                dry_run=True,
                limit=1,
                episode_id="noticias_guerra_cripto_final.mp4",
            )
        self.assertTrue(out["ok"])
        job, script, args = run.call_args.args[:3]
        self.assertEqual(job, "generate_podcast_covers")
        self.assertEqual(script, "generate_podcast_covers.py")
        self.assertIn("--dry-run", args)
        self.assertIn("--limit", args)
        self.assertIn("1", args)
        self.assertIn("--episode-id", args)
        self.assertEqual(run.call_args.kwargs["wait"], False)
        self.assertEqual(out["episode_id"], "noticias_guerra_cripto_final.mp4")


class TestMapTopicHelper(unittest.TestCase):
    def test_map_topic_volume_offline_units(self):
        from src.sophia_topic_text import ResolvedText
        from src.sophia_topic_volume import map_topic_volume

        class FakeTopics:
            def get_topic(self, topic_id):
                return {"id": topic_id, "title": "Demo", "description": "Hello topic"}

            def list_topic_contents(self, topic_id, include_images=False):
                return [
                    {
                        "id": 9,
                        "media_type": "TEXT",
                        "original_title": "Book",
                        "original_author": "A",
                        "file_details": {"file": "https://cdn.example/x.epub"},
                    }
                ]

        resolved = ResolvedText(
            content_id=9,
            media_type="TEXT",
            title="Book",
            author="A",
            text="Chapter one from an EPUB.",
            source="s3_epub:x.epub",
            status="ok",
            notes="spine_docs=1",
        )
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch(
                "src.sophia_topic_volume.resolve_media_text", return_value=resolved
            ):
                out = map_topic_volume(
                    Path(tmp),
                    1,
                    topics_client=FakeTopics(),
                    ingest_client=object(),
                )
        self.assertTrue(out["ok"])
        self.assertEqual(out["text_document_formats"]["epub"], 1)
        self.assertEqual(out["units"][-1]["text_source"], "s3_epub:x.epub")


if __name__ == "__main__":
    unittest.main()
