"""Tests for podcast MP3 catalog + RSS matching."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.podcast_catalog import (  # noqa: E402
    apply_rss_matches,
    get_episode,
    ingest_local_mp3s,
    match_episodes,
    migrate_legacy_json,
    parse_rss_episodes,
    record_item,
    sync_from_rss,
)
from src.video_transcript_state import open_state  # noqa: E402


RSS_FIXTURE = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
  <channel>
    <title>Test Show</title>
    <item>
      <title>El Banco de Inglaterra, el HECHICERO y la CONQUISTA del Dinero</title>
      <guid>guid-hechicero</guid>
      <pubDate>Thu, 23 Jul 2026 00:51:00 GMT</pubDate>
      <itunes:duration>00:50:01</itunes:duration>
      <enclosure url="https://example.com/a.mp3" length="72046070" type="audio/mpeg"/>
    </item>
    <item>
      <title>Marxismo vs Bitcoin: un choque inevitable. Los más que errores de Santiago Armesilla.</title>
      <guid>guid-marx</guid>
      <pubDate>Thu, 30 Jul 2026 01:33:00 GMT</pubDate>
      <description>Debate con Armesilla.</description>
      <enclosure url="https://example.com/b.mp3" length="44914157" type="audio/mpeg"/>
    </item>
    <item>
      <title>Un episodio sin MP3 local</title>
      <guid>guid-orphan</guid>
      <pubDate>Mon, 01 Jun 2026 00:00:00 GMT</pubDate>
      <enclosure url="https://example.com/c.mp3" length="123" type="audio/mpeg"/>
    </item>
  </channel>
</rss>
"""


class TestPodcastCatalog(unittest.TestCase):
    def test_parse_rss_episodes(self):
        episodes = parse_rss_episodes(RSS_FIXTURE)
        self.assertEqual(len(episodes), 3)
        self.assertEqual(episodes[0]["rss_enclosure_bytes"], 72046070)
        self.assertTrue(episodes[0]["rss_pub_date"].startswith("2026-07-23"))
        self.assertEqual(episodes[0]["rss_duration"], "00:50:01")

    def test_match_size_exact_and_filename_hint(self):
        episodes = parse_rss_episodes(RSS_FIXTURE)
        locals_ = [
            {"stem": "ACBC Hechicero_Banco_Dinero_final", "mp3": "ACBC Hechicero_Banco_Dinero_final.mp3", "size": 72046070},
            {"stem": "Marx Armesilla", "mp3": "Marx Armesilla.mp3", "size": 77316117},
            {"stem": "Mundial Exit", "mp3": "Mundial Exit.mp3", "size": 53059856},
        ]
        pairs = match_episodes(episodes, locals_)
        by_stem = {loc["stem"]: (ep["rss_title"], reason) for ep, loc, reason in pairs}
        self.assertEqual(by_stem["ACBC Hechicero_Banco_Dinero_final"][1], "size_exact")
        self.assertEqual(by_stem["Marx Armesilla"][1], "filename_hint")
        self.assertNotIn("Mundial Exit", by_stem)
        self.assertEqual(len(pairs), 2)

    def test_record_item_preserves_rss_fields_in_sqlite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            conn = open_state(str(root))
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertIn("video_transcript", tables)
            self.assertIn("podcast_episode", tables)
            video = root / "Marx Armesilla.mp4"
            mp3 = root / "Marx Armesilla.mp3"
            video.write_bytes(b"x")
            mp3.write_bytes(b"y")
            record_item(conn, video, status="done", mp3=mp3)
            conn.execute(
                "UPDATE podcast_episode SET rss_title = ? WHERE episode_id = ?",
                ("Marxismo vs Bitcoin", video.name),
            )
            conn.commit()
            record_item(conn, video, status="done", mp3=mp3, skipped=True)
            entry = get_episode(conn, video.name)
            self.assertEqual(entry["rss_title"], "Marxismo vs Bitcoin")
            self.assertEqual(entry["file_title"], "Marx Armesilla")
            conn.close()

    def test_ingest_apply_and_legacy_migrate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "code"
            catalog = root / "cast"
            mp3_dir = catalog / "mp3"
            mp3_dir.mkdir(parents=True)
            (mp3_dir / "Mundial Exit.mp3").write_bytes(b"abc")
            conn = open_state(str(project))
            added = ingest_local_mp3s(conn, catalog, mp3_dir)
            self.assertEqual(added, 1)
            self.assertIsNotNone(get_episode(conn, "Mundial Exit.mp4"))
            pairs = match_episodes(
                parse_rss_episodes(RSS_FIXTURE),
                [{"stem": "ACBC Hechicero_Banco_Dinero_final", "mp3": "x.mp3", "size": 72046070}],
            )
            apply_rss_matches(conn, pairs)
            hechicero = get_episode(conn, "ACBC Hechicero_Banco_Dinero_final.mp4")
            self.assertEqual(hechicero["rss_guid"], "guid-hechicero")
            conn.close()

            other = root / "code2"
            catalog2 = root / "cast2"
            catalog2.mkdir()
            (catalog2 / "_estado_podcast.json").write_text(
                json.dumps(
                    {
                        "items": {
                            "Anom Privacidad.mp4": {
                                "title": "Anom Privacidad",
                                "video": "Anom Privacidad.mp4",
                                "mp3": "Anom Privacidad.mp3",
                                "status": "done",
                                "processed_at": "2026-07-19T02:10:22+00:00",
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            conn2 = open_state(str(other))
            migrated = migrate_legacy_json(conn2, catalog2)
            self.assertEqual(migrated, 1)
            self.assertEqual(get_episode(conn2, "Anom Privacidad.mp4")["mp3"], "Anom Privacidad.mp3")
            conn2.close()

    def test_sync_dry_run_does_not_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog = root / "cast"
            (catalog / "mp3").mkdir(parents=True)
            result = sync_from_rss(
                catalog,
                project_root=root / "code",
                rss_source=RSS_FIXTURE,
                dry_run=True,
            )
            self.assertTrue(result["dry_run"])
            self.assertEqual(result["matched"], 0)
            db = root / "code" / "cache" / "video_transcripts" / "state.sqlite3"
            self.assertFalse(db.is_file())


if __name__ == "__main__":
    unittest.main()
