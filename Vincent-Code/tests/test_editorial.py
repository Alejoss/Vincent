"""Tests for editorial loaders and pipeline skip logic."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.campaigns.editorial import get_campaign
from src.editorial.loaders import load_knowledge_bundle, resolve_vault_path, wrap_generated
from src.editorial.pipeline import generate_outline


class TestEditorialLoaders(unittest.TestCase):
    def test_resolve_knowledge_path(self):
        root = PROJECT_ROOT.parent / "Cerebro-Vincent"
        if not root.is_dir():
            self.skipTest("Vault no presente")
        path = resolve_vault_path(
            "20_Extractions/Own_Transcripts/"
            "2026-06-26-archivo-cypherpunk-vol-i-recopilación-de-shorts-de-alejandro-veintimilla-knowledge.md"
        )
        self.assertTrue(path.is_file())

    def test_load_knowledge_bundle_seminario(self):
        root = PROJECT_ROOT.parent / "Cerebro-Vincent" / "Campaigns"
        if not root.is_dir():
            self.skipTest("Campaigns no presente")
        camp = get_campaign("seminario-cypherpunk-2026", root)
        bundle = load_knowledge_bundle(camp)
        self.assertIn("Summary", bundle)
        self.assertNotIn("Sin knowledge_sources", bundle)

    def test_wrap_generated_frontmatter(self):
        out = wrap_generated({"step": "outline", "generated": True}, "## Idea\n\nTest")
        self.assertTrue(out.startswith("---\n"))
        self.assertIn("step: outline", out)
        self.assertIn("## Idea", out)

    def test_generate_outline_skips_existing(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "Campaigns" / "2026" / "Test"
            base.mkdir(parents=True)
            (base / "campaign.md").write_text(
                "---\nid: test-camp\ntitle: Test\n---\n\n## Objetivo\n",
                encoding="utf-8",
            )
            (base / "outline.md").write_text("---\nstatus: draft\n---\n\nexisting", encoding="utf-8")

            import os

            prev = os.environ.get("CAMPAIGNS_DIR")
            os.environ["CAMPAIGNS_DIR"] = str(Path(tmp) / "Campaigns")
            try:
                result = generate_outline("test-camp", force=False)
                self.assertTrue(result.skipped)
            finally:
                if prev is None:
                    os.environ.pop("CAMPAIGNS_DIR", None)
                else:
                    os.environ["CAMPAIGNS_DIR"] = prev


if __name__ == "__main__":
    unittest.main()
