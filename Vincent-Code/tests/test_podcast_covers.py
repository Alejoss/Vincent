"""Tests for podcast cover prompts and catalog selection (no live Images API)."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.podcast_catalog import record_item  # noqa: E402
from src.podcast_covers import (  # noqa: E402
    DEFAULT_SIZE,
    SPECS_BY_ID,
    build_prompt,
    cover_output_path,
    generate_covers,
    generate_one,
    select_episodes,
    spec_for_episode,
)
from src.video_transcript_state import open_state  # noqa: E402


class TestCoverSpecs(unittest.TestCase):
    def test_first_published_is_perspectiva_square(self):
        spec = SPECS_BY_ID["noticias_guerra_cripto_final.mp4"]
        self.assertEqual(spec.word, "PERSPECTIVA")
        self.assertEqual(DEFAULT_SIZE, "1024x1024")
        prompt = build_prompt(spec, title="Aumentar la PERSPECTIVA: un paso atrás")
        self.assertIn("PERSPECTIVA", prompt)
        self.assertIn("1:1", prompt)
        self.assertIn("Do not copy", prompt)
        self.assertNotIn("headphones", spec.subject)

    def test_select_first_published_episode(self):
        episodes = [
            {
                "episode_id": "later.mp4",
                "rss_title": "Later",
                "rss_pub_date": "2026-08-01T00:00:00+00:00",
            },
            {
                "episode_id": "noticias_guerra_cripto_final.mp4",
                "rss_title": "Aumentar la PERSPECTIVA",
                "rss_pub_date": "2026-06-08T00:00:00+00:00",
            },
            {"episode_id": "draft.mp4", "rss_title": None, "extracted_at": "2026-09-01"},
        ]
        first = select_episodes(episodes, limit=1)
        self.assertEqual(first[0]["episode_id"], "noticias_guerra_cripto_final.mp4")
        unpublished = select_episodes(episodes, include_unpublished=True)
        self.assertEqual(len(unpublished), 3)

    def test_cover_columns_exist_on_existing_db(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = open_state(tmp)
            cols = {row[1] for row in conn.execute("PRAGMA table_info(podcast_episode)")}
            self.assertIn("cover_path", cols)
            self.assertIn("cover_word", cols)
            conn.close()

    def test_dry_run_does_not_call_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "code"
            catalog = root / "VideosParaPodcast"
            mp3 = catalog / "mp3" / "noticias_guerra_cripto_final.mp3"
            mp3.parent.mkdir(parents=True)
            video = catalog / "noticias_guerra_cripto_final.mp4"
            video.write_bytes(b"x")
            mp3.write_bytes(b"y")
            conn = open_state(str(project))
            record_item(conn, video, status="done", mp3=mp3)
            conn.execute(
                "UPDATE podcast_episode SET rss_title=?, rss_pub_date=? WHERE episode_id=?",
                ("Aumentar la PERSPECTIVA", "2026-06-08T00:00:00+00:00", video.name),
            )
            conn.commit()
            conn.close()

            with mock.patch("src.podcast_covers.generate_cover_bytes") as mocked:
                result = generate_covers(
                    project_root=project,
                    repo_root=root,
                    limit=1,
                    dry_run=True,
                )
            mocked.assert_not_called()
            self.assertTrue(result["ok"])
            self.assertEqual(result["items"][0]["cover_word"], "PERSPECTIVA")
            self.assertIn("PERSPECTIVA", result["items"][0]["prompt"])

    def test_generate_one_records_sqlite_when_api_returns_png(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "code"
            covers = root / "covers"
            ref = root / "ref.jpg"
            ref.write_bytes(b"jpeg")
            video = root / "noticias_guerra_cripto_final.mp4"
            mp3 = root / "noticias_guerra_cripto_final.mp3"
            video.write_bytes(b"x")
            mp3.write_bytes(b"y")
            conn = open_state(str(project))
            record_item(conn, video, status="done", mp3=mp3)
            episode = {
                "episode_id": video.name,
                "mp3_filename": mp3.name,
                "rss_title": "Aumentar la PERSPECTIVA",
                "file_title": "noticias_guerra_cripto_final",
            }
            png = b"\x89PNG\r\n\x1a\n" + b"fake"
            with mock.patch(
                "src.podcast_covers.generate_cover_bytes",
                return_value=(png, "gpt-image-2.5-flare"),
            ):
                out = generate_one(
                    conn,
                    episode,
                    covers_dir=covers,
                    reference_path=ref,
                )
            self.assertTrue(out["ok"])
            saved = Path(out["output"])
            self.assertTrue(saved.is_file())
            row = conn.execute(
                "SELECT cover_word, cover_status, cover_path FROM podcast_episode WHERE episode_id=?",
                (video.name,),
            ).fetchone()
            self.assertEqual(row["cover_word"], "PERSPECTIVA")
            self.assertEqual(row["cover_status"], "done")
            self.assertEqual(row["cover_path"], str(saved))
            self.assertEqual(spec_for_episode(episode).word, "PERSPECTIVA")
            self.assertTrue(str(cover_output_path(covers, episode)).endswith(".png"))
            conn.close()


if __name__ == "__main__":
    unittest.main()
