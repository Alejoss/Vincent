"""Tests for editorial campaign discovery."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.campaigns.editorial import discover_campaigns, get_campaign, list_campaign_choices


class TestEditorialCampaigns(unittest.TestCase):
    def test_discover_seminario_cypherpunk(self):
        root = PROJECT_ROOT.parent / "Cerebro-Vincent" / "Campaigns"
        if not root.is_dir():
            self.skipTest("Vault Campaigns/ no presente en este entorno")

        campaigns = discover_campaigns(root)
        slugs = {c.slug for c in campaigns}
        self.assertIn("seminario-cypherpunk-2026", slugs)

    def test_get_campaign_by_slug(self):
        root = PROJECT_ROOT.parent / "Cerebro-Vincent" / "Campaigns"
        if not root.is_dir():
            self.skipTest("Vault Campaigns/ no presente en este entorno")

        camp = get_campaign("seminario-cypherpunk-2026", root)
        self.assertTrue((camp.newsletters_dir / "01-lanzamiento-lista-general.md").is_file())
        self.assertTrue(camp.newsletter_path.is_file())

    def test_list_campaign_choices(self):
        root = PROJECT_ROOT.parent / "Cerebro-Vincent" / "Campaigns"
        if not root.is_dir():
            self.skipTest("Vault Campaigns/ no presente en este entorno")

        choices = list_campaign_choices()
        self.assertTrue(any(slug == "seminario-cypherpunk-2026" for slug, _ in choices))


if __name__ == "__main__":
    unittest.main()
