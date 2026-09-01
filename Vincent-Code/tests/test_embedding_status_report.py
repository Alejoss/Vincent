"""Unit tests for topic embedding readiness classification."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from src.embeddings.status_report import (
    classify_topic,
    collect_topic_status,
    content_rows_for_topic,
    count_embedding_statuses,
    needing_embed_count,
    topic_summary_row,
)
from src.sophia_topics import SophiaTopicsClient


class CountStatusesTests(unittest.TestCase):
    def test_counts_known_and_unknown(self):
        items = [
            {"embedding_status": "indexed"},
            {"embedding_status": "indexed"},
            {"embedding_status": "pending"},
            {"embedding_status": "STALE"},
            {"embedding_status": None},
        ]
        counts = count_embedding_statuses(items)
        self.assertEqual(counts["indexed"], 2)
        self.assertEqual(counts["pending"], 1)
        self.assertEqual(counts["stale"], 1)
        self.assertEqual(counts["unknown"], 1)
        self.assertEqual(needing_embed_count(counts), 2)


class ClassifyTopicTests(unittest.TestCase):
    def test_no_av(self):
        self.assertEqual(
            classify_topic(av_count=0, transcribed_count=0, status_counts={}),
            "no_av",
        )

    def test_needs_embeddings_beats_indexed(self):
        self.assertEqual(
            classify_topic(
                av_count=5,
                transcribed_count=5,
                status_counts={"indexed": 4, "pending": 1},
            ),
            "needs_embeddings",
        )

    def test_ready(self):
        self.assertEqual(
            classify_topic(
                av_count=3,
                transcribed_count=3,
                status_counts={"indexed": 3},
            ),
            "ready",
        )

    def test_needs_transcripts(self):
        self.assertEqual(
            classify_topic(
                av_count=4,
                transcribed_count=0,
                status_counts={},
            ),
            "needs_transcripts",
        )

    def test_partial_when_some_indexed_and_some_untranscribed(self):
        self.assertEqual(
            classify_topic(
                av_count=5,
                transcribed_count=2,
                status_counts={"indexed": 2},
            ),
            "partial",
        )

    def test_skipped_only(self):
        self.assertEqual(
            classify_topic(
                av_count=2,
                transcribed_count=2,
                status_counts={"skipped": 2},
            ),
            "skipped_only",
        )


class TopicSummaryRowTests(unittest.TestCase):
    def test_row_and_content_export(self):
        topic = {
            "id": 12,
            "title": "Bitcoin",
            "chat_enabled": False,
            "chat_can_enable": True,
            "indexed_transcript_count": 1,
        }
        items = [
            {
                "id": 46,
                "media_type": "VIDEO",
                "original_title": "Halving",
                "embedding_status": "indexed",
                "chunk_count": 7,
                "embedding_model": "text-embedding-3-large",
                "embedded_at": "2026-07-28T18:00:00Z",
                "text_hash": "abc",
            },
            {
                "id": 47,
                "media_type": "AUDIO",
                "original_title": "Podcast",
                "embedding_status": "pending",
            },
        ]
        row = topic_summary_row(topic=topic, av_count=3, items=items)
        self.assertEqual(row["bucket"], "needs_embeddings")
        self.assertTrue(row["needs_embeddings"])
        self.assertTrue(row["needs_transcripts"])
        self.assertEqual(row["indexed"], 1)
        self.assertEqual(row["pending"], 1)
        self.assertEqual(row["missing_transcripts"], 1)
        self.assertFalse(row["ready"])

        contents = content_rows_for_topic(12, items)
        self.assertEqual(len(contents), 2)
        self.assertTrue(contents[1]["needs_embeddings"])
        self.assertFalse(contents[0]["needs_embeddings"])


class ListTopicsClientTests(unittest.TestCase):
    def test_list_topics_accepts_bare_array(self):
        client = SophiaTopicsClient(api_base="https://example.test/api")
        with patch.object(
            client,
            "_get",
            return_value=[
                {"id": 1, "title": "A", "indexed_transcript_count": 3},
                {"id": 2, "title": "B", "indexed_transcript_count": 0},
            ],
        ):
            topics = client.list_topics()
        self.assertEqual(len(topics), 2)
        self.assertEqual(topics[0]["id"], 1)

    def test_list_topics_accepts_results_wrapper(self):
        client = SophiaTopicsClient(api_base="https://example.test/api")
        with patch.object(
            client, "_get", return_value={"results": [{"id": 9, "title": "X"}]}
        ):
            topics = client.list_topics()
        self.assertEqual(topics[0]["title"], "X")


class CollectTopicStatusTests(unittest.TestCase):
    def test_joins_queue_and_av_count(self):
        class Topics:
            def list_topic_contents(self, topic_id, media_types=None):
                return [{"id": 1}, {"id": 2}, {"id": 3}]

        class Embed:
            def list_queue_all(self, topic_id, include_completed=False):
                self.include_completed = include_completed
                return [
                    {
                        "id": 1,
                        "media_type": "VIDEO",
                        "original_title": "One",
                        "embedding_status": "indexed",
                    }
                ]

        topics = [{"id": 12, "title": "Bitcoin", "chat_enabled": False}]
        topic_rows, content_rows = collect_topic_status(
            Topics(), Embed(), topics, skip_av_count=False
        )
        self.assertEqual(len(topic_rows), 1)
        self.assertEqual(topic_rows[0]["bucket"], "partial")
        self.assertEqual(topic_rows[0]["av_count"], 3)
        self.assertEqual(topic_rows[0]["transcribed_count"], 1)
        self.assertEqual(len(content_rows), 1)


class NotionPropertyTests(unittest.TestCase):
    def test_row_to_properties_and_missing_schema(self):
        from src.embeddings.notion_status import (
            missing_schema_properties,
            row_to_properties,
        )

        row = {
            "topic_id": 12,
            "title": "Bitcoin",
            "bucket": "needs_embeddings",
            "needs_embeddings": True,
            "needs_transcripts": False,
            "ready": False,
            "indexed": 1,
            "pending": 2,
            "stale": 0,
            "failed": 0,
            "skipped": 0,
            "av_count": 3,
            "transcribed_count": 3,
            "missing_transcripts": 0,
            "chat_enabled": False,
            "chat_can_enable": True,
        }
        props = row_to_properties(row)
        self.assertEqual(props["Topic ID"]["number"], 12)
        self.assertEqual(props["Bucket"]["select"]["name"], "needs_embeddings")
        self.assertTrue(props["Needs embeddings"]["checkbox"])
        self.assertEqual(props["Name"]["title"][0]["text"]["content"], "Bitcoin")

        missing = missing_schema_properties({"Name": {"type": "title"}})
        self.assertIn("Topic ID", missing)
        self.assertIn("Bucket", missing)
        self.assertNotIn("Name", missing)


if __name__ == "__main__":
    unittest.main()
