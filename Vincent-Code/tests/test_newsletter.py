"""Tests for newsletter renderer and subscribers."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.newsletter.renderer import compose_markdown_file, parse_frontmatter, render_markdown
from src.newsletter.subscribers import load_all_subscribers, load_segment, parse_markdown_table

FIXTURE = PROJECT_ROOT / "tests" / "fixtures" / "sample_newsletter.md"
SUBS_FIXTURE = PROJECT_ROOT / "tests" / "fixtures" / "sample_subscribers.md"


class TestRenderer(unittest.TestCase):
    def test_parse_frontmatter(self):
        text = FIXTURE.read_text(encoding="utf-8")
        meta, body = parse_frontmatter(text)
        self.assertEqual(meta["tag"], "club-de-lectura")
        self.assertIn("# Hola", body)

    def test_render_html_contains_content(self):
        rendered = render_markdown(FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(rendered.subject, "Newsletter de prueba")
        self.assertEqual(rendered.tag, "club-de-lectura")
        self.assertIn("Academia Blockchain", rendered.html_body)
        self.assertIn("<strong>newsletter de prueba</strong>", rendered.html_body)
        self.assertIn("academiablockchain.com", rendered.html_body)
        self.assertIn("newsletter de prueba", rendered.text_body)

    def test_subject_override(self):
        rendered = render_markdown(
            FIXTURE.read_text(encoding="utf-8"),
            subject="Otro asunto",
        )
        self.assertEqual(rendered.subject, "Otro asunto")

    def test_strip_leading_note_title(self):
        md = """---
subject: Test
hide_note_title: true
---

# 02 — Título interno Obsidian

Hola mundo.
"""
        rendered = render_markdown(md)
        self.assertNotIn("Título interno", rendered.html_body)
        self.assertIn("Hola mundo", rendered.html_body)

    def test_compose_markdown_file(self):
        composed = compose_markdown_file(
            "# Hola\n\nTexto.",
            subject="Asunto",
            tag="club-de-lectura",
            segment="general",
        )
        meta, body = parse_frontmatter(composed)
        self.assertEqual(meta["subject"], "Asunto")
        self.assertEqual(meta["tag"], "club-de-lectura")
        self.assertIn("# Hola", body)

    def test_parse_markdown_table(self):
        rows = parse_markdown_table(SUBS_FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["email"], "a@test.com")

    def test_load_obsidian_subscribers(self):
        subs = load_all_subscribers(SUBS_FIXTURE)
        self.assertEqual(len(subs), 2)
        active_test = [s for s in subs if s.segment == "test" and s.active]
        self.assertEqual(len(active_test), 1)
        self.assertEqual(active_test[0].email, "a@test.com")

    def test_load_segment_dedupes_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            csv_path = root / "demo.csv"
            csv_path.write_text(
                "email,name\na@test.com,Ana\na@test.com,Ana\nb@test.com,Bob\n",
                encoding="utf-8",
            )
            empty_obsidian = root / "missing.md"
            subs = load_segment("demo", root)
            self.assertEqual(len(subs), 2)


if __name__ == "__main__":
    unittest.main()
