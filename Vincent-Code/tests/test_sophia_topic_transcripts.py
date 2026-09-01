"""Lightweight tests for Sophia topic transcript helpers (no network)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.sophia_local_transcript_lookup import find_local_transcript
from src.sophia_transcript_state import (
    get_row,
    mark_done,
    mark_failed,
    open_sophia_state,
    summary_counts_for_topic,
    sync_topic_coverage_exports,
    upsert_discovered,
)
from src.sophia_youtube_captions import cues_to_srt, extract_youtube_video_id
from src.video_transcript_state import mark_done as mark_video_done
from src.video_transcript_state import open_state


class YoutubeHelpersTests(unittest.TestCase):
    def test_extract_video_id(self):
        self.assertEqual(
            extract_youtube_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
            "dQw4w9WgXcQ",
        )
        self.assertEqual(extract_youtube_video_id("dQw4w9WgXcQ"), "dQw4w9WgXcQ")
        self.assertEqual(
            extract_youtube_video_id("https://www.youtube.com/live/BS3fbSVn8c0"),
            "BS3fbSVn8c0",
        )

    def test_cues_to_srt(self):
        srt = cues_to_srt(
            [
                {"text": "Hola", "start": 0.0, "duration": 1.5},
                {"text": "mundo", "start": 1.5, "duration": 2.0},
            ]
        )
        self.assertIn("1\n00:00:00,000 --> 00:00:01,500\nHola", srt)
        self.assertIn("2\n00:00:01,500 --> 00:00:03,500\nmundo", srt)


class SophiaStateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "cache" / "video_transcripts").mkdir(parents=True)
        self.conn = open_sophia_state(self.root)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_topic_ids_merge_and_transcribed_at(self):
        upsert_discovered(
            self.conn,
            content_id=10,
            topic_id=1,
            title="Demo",
            media_type="VIDEO",
            source_url="https://youtu.be/x",
        )
        upsert_discovered(
            self.conn,
            content_id=10,
            topic_id=2,
            title="Demo",
            media_type="VIDEO",
        )
        row = get_row(self.conn, 10)
        self.assertEqual(row["topic_ids"], [1, 2])
        self.assertEqual(row["status"], "pending")

        mark_done(
            self.conn,
            content_id=10,
            topic_id=2,
            method="youtube_captions",
            transcribed_at="2026-07-24T12:00:00+00:00",
            text_hash="abc",
        )
        row = get_row(self.conn, 10)
        self.assertEqual(row["status"], "done")
        self.assertEqual(row["transcribed_at"], "2026-07-24T12:00:00+00:00")
        self.assertEqual(row["primary_topic_id"], 2)
        self.assertEqual(row["text_hash"], "abc")

        mark_failed(self.conn, content_id=10, topic_id=3, error="should not overwrite done")
        row = get_row(self.conn, 10)
        self.assertEqual(row["status"], "done")
        self.assertIn(3, row["topic_ids"])

        counts = summary_counts_for_topic(self.conn, 1)
        self.assertEqual(counts.get("done"), 1)

        out = self.root / "reports"
        json_path, md_path = sync_topic_coverage_exports(
            self.conn,
            topic_id=1,
            vault_output_dir=out,
            remote_pending=0,
            remote_completed=1,
            remote_total=1,
            project_root=self.root,
        )
        self.assertTrue(json_path.is_file())
        self.assertTrue(md_path.is_file())
        self.assertIn("transcribed_at", md_path.read_text(encoding="utf-8"))


class LocalTranscriptLookupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "cache" / "video_transcripts").mkdir(parents=True)
        self.vault = self.root / "vault" / "10_Sources" / "Own_Transcripts"
        self.vault.mkdir(parents=True)
        self.note = self.vault / "2024-01-01-demo.md"
        self.note.write_text(
            "---\n"
            'title: "Demo"\n'
            'source_url: "https://www.youtube.com/watch?v=UaMEeL-A-ok"\n'
            'language_code: "es"\n'
            "---\n\n"
            "Hola mundo local.\n",
            encoding="utf-8",
        )
        conn = open_state(str(self.root))
        mark_video_done(
            conn,
            video_id="UaMEeL-A-ok",
            title="Demo",
            source_url="https://www.youtube.com/watch?v=UaMEeL-A-ok",
            output_path=str(self.note),
            language_code="es",
        )
        conn.close()

    def tearDown(self):
        self.tmp.cleanup()

    def test_find_by_youtube_id(self):
        hit = find_local_transcript(
            project_root=self.root,
            youtube_video_id="UaMEeL-A-ok",
            vault_transcripts_dir=self.vault,
        )
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertEqual(hit.match_via, "video_id")
        self.assertIn("Hola mundo local", hit.plain_text)
        self.assertEqual(hit.language_code, "es")


if __name__ == "__main__":
    unittest.main()
