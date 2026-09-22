"""Coverage regressions: an empty Sophia queue is not full embedding coverage."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from contextlib import closing
from unittest.mock import Mock, patch

from src.topic_embedding_status import (
    classify, match_topic, read_local, read_qdrant, topic_embedding_status,
)
from src.sophia_topics import SophiaTopicsClient


class CoverageTests(unittest.TestCase):
    def setUp(self):
        self.item = {"id": 5464, "media_type": "TEXT", "original_title": "El Libro De Satoshi",
                     "has_file_available": True, "has_transcript": False}
        self.key = "topic:2:TEXT:5464"
        self.local = {"documents": {self.key: {"status": "done", "text_hash": "abc", "chunk_count": 2}},
                      "chunks": {self.key: [0, 1]}}
        self.remote = {self.key: [{"chunk_index": i, "text_hash": "abc"} for i in range(2)]}

    def test_pdf_vectors_without_sophia_ack_are_embedded_but_untracked(self):
        row = classify(self.item, 2, self.local, self.remote, {})
        self.assertEqual(row["status"], "embedded")
        self.assertEqual(row["qdrant_chunks"], 2)
        self.assertIn("sophia_status_untracked", row["issues"])

    def test_empty_queue_does_not_hide_missing_articles_and_audio(self):
        for media, text in [("TEXT", "web_extraction_needed"), ("AUDIO", "transcript_needed")]:
            item = {"id": 55, "media_type": media, "url": "https://example.test/item", "has_transcript": False}
            row = classify(item, 2, {}, {}, {})
            self.assertEqual(row["status"], "missing_text")
            self.assertEqual(row["text_status"], text)

    def test_local_only_vectors_need_upload(self):
        self.assertEqual(classify(self.item, 2, self.local, {}, {})["status"], "missing_upload")

    def test_unknown_sources_never_become_zero(self):
        row = classify(self.item, 2, self.local, None, None)
        self.assertEqual(row["status"], "unknown")
        self.assertIsNone(row["qdrant_chunks"])
        self.assertNotIn("sophia_status_untracked", row["issues"])
        row = classify(self.item, 2, None, {}, {})
        self.assertEqual(row["status"], "missing_in_qdrant")
        self.assertIsNone(row["local_chunks"])

    def test_partial_or_stale_upload_detected(self):
        row = classify(self.item, 2, self.local, {self.key: self.remote[self.key][:1]}, {})
        self.assertEqual(row["status"], "upload_mismatch")
        self.remote[self.key][0]["text_hash"] = "old"
        row = classify(self.item, 2, self.local, self.remote, {})
        self.assertIn("upload_hash_mismatch", row["issues"])

    def test_sophia_indexed_without_vectors(self):
        row = classify(self.item, 2, {}, {}, {5464: {"embedding_status": "indexed"}})
        self.assertIn("sophia_indexed_without_vectors", row["issues"])

    def test_images_excluded_even_during_outage(self):
        row = classify({"id": 1, "media_type": "IMAGE"}, 2, None, None, None)
        self.assertEqual(row["status"], "excluded")

    def test_sophia_other_model_is_not_a_false_missing_vector_alarm(self):
        row = classify(self.item, 2, {}, {}, {5464: {"embedding_status": "indexed", "embedding_model": "other"}})
        self.assertIn("sophia_model_differs", row["issues"])
        self.assertNotIn("sophia_indexed_without_vectors", row["issues"])

    def test_topic_and_content_pagination_and_invalid_response(self):
        client = SophiaTopicsClient()
        with patch.object(client, "_get", side_effect=[
            {"results": [{"id": 1}], "next": "next"}, {"results": [{"id": 2}], "next": None}
        ]):
            self.assertEqual([x["id"] for x in client.list_topics()], [1, 2])
        with patch.object(client, "_get", side_effect=[
            {"contents": [{"id": 1}], "has_next": True}, {"contents": [{"id": 2}], "has_next": False}
        ]):
            self.assertEqual(len(client.list_content_by_type(2, "TEXT")), 2)
        with patch.object(client, "_get", return_value={"unexpected": []}):
            with self.assertRaises(ValueError):
                client.list_content_by_type(2, "TEXT")

    def test_approximate_and_accent_insensitive_names(self):
        topics = [{"id": 2, "title": "El Secuestro de Bitcoin y el tamaño de los bloques"},
                  {"id": 9, "title": "Geoingeniería, Chemtrails y Control del Clima"}]
        self.assertEqual(match_topic("El secuestro de Bitcoin y el tamaño de la cadena de bloques", topics)["topic_id"], 2)
        self.assertEqual(match_topic("geoingenieria", topics)["topic_id"], 9)
        topics.append({"id": 10, "title": "El Secuestro de Bitcoin: otro tema"})
        self.assertFalse(match_topic("Bitcoin", topics)["ok"])
        self.assertFalse(match_topic("unrelated words", topics)["ok"])

    def test_local_read_counts_real_chunks_for_requested_model_without_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertFalse(read_local(root, 2, "model")["database_exists"])
            self.assertEqual(list(root.iterdir()), [])
            path = root / "cache/topic_embeddings/state.sqlite3"
            path.parent.mkdir(parents=True)
            with closing(sqlite3.connect(path)) as conn:
                conn.executescript("CREATE TABLE documents(doc_key,topic_id,content_id,status,char_count,chunk_count,text_hash,notes);"
                                   "CREATE TABLE chunks(doc_key,topic_id,chunk_index,embedding_model);")
                conn.execute("INSERT INTO documents VALUES(?,2,5464,'done',100,99,'abc','')", (self.key,))
                conn.executemany("INSERT INTO chunks VALUES(?,2,?,?)", [(self.key, 0, "model"), (self.key, 1, "other")])
                conn.commit()
            before = path.read_bytes()
            result = read_local(root, 2, "model")
            self.assertEqual(result["chunks"][self.key], [0])
            self.assertEqual(path.read_bytes(), before)

    def test_qdrant_pagination_is_metadata_only_and_model_filtered(self):
        store = Mock(collection="test")
        store._request.side_effect = [
            {"result": {"points": [{"payload": {"doc_key": self.key, "chunk_index": 0}}], "next_page_offset": 0}},
            {"result": {"points": [{"payload": {"doc_key": self.key, "chunk_index": 1}}], "next_page_offset": None}},
        ]
        self.assertEqual(len(read_qdrant(store, 2, "model")[self.key]), 2)
        body = store._request.call_args.kwargs["json_body"]
        self.assertEqual(body["offset"], 0)
        self.assertFalse(body["with_vector"])
        self.assertIn({"key": "embedding_model", "match": {"value": "model"}}, body["filter"]["must"])
        store.ensure_collection.assert_not_called()

    @patch("src.topic_embedding_status.SophiaEmbeddingIngestClient")
    @patch("src.topic_embedding_status.read_qdrant")
    @patch("src.topic_embedding_status.QdrantStore")
    @patch("src.topic_embedding_status.read_local")
    @patch("src.topic_embedding_status.SophiaTopicsClient")
    def test_partial_failure_is_explicit_and_sensitive_errors_are_not_returned(self, topics, local, store, remote, ingest):
        topics.return_value.get_topic.return_value = {"title": "Bitcoin"}
        topics.return_value.list_topic_contents.return_value = [self.item]
        local.return_value = self.local
        remote.side_effect = RuntimeError("SECRET response body")
        ingest.return_value.list_queue_all.return_value = []
        out = topic_embedding_status(".", topic_id=2)
        self.assertTrue(out["ok"])
        self.assertFalse(out["complete"])
        self.assertIsNone(out["summary"]["missing_in_qdrant"])
        self.assertNotIn("SECRET", str(out))
        ingest.return_value.list_queue_all.assert_called_once_with(topic_id=2, include_completed=True)

    def test_selector_validation(self):
        for kwargs in ({}, {"topic_id": 2, "topic_name": "Bitcoin"}, {"topic_id": 0}):
            self.assertFalse(topic_embedding_status(".", **kwargs)["ok"])


if __name__ == "__main__":
    unittest.main()
