"""Tests for Notion → Slack reminder dedup (Fase 5)."""

from __future__ import annotations

import unittest
from datetime import date

from src.notion_slack_reminders_dedup import (
    effective_dedup_days,
    was_sent_within_dedup_window,
)


class TestEffectiveDedupDays(unittest.TestCase):
    def test_upcoming_uses_standard_window(self) -> None:
        self.assertEqual(effective_dedup_days(False, 3, 2), 3)

    def test_overdue_uses_shorter_window(self) -> None:
        self.assertEqual(effective_dedup_days(True, 3, 2), 2)


class TestWasSentWithinDedupWindow(unittest.TestCase):
    def test_not_sent_allows_reminder(self) -> None:
        today = date(2026, 6, 26)
        self.assertFalse(
            was_sent_within_dedup_window({}, "page|2026-06-26", today, 2)
        )

    def test_sent_yesterday_blocks_with_2_day_window(self) -> None:
        today = date(2026, 6, 26)
        state = {"page|2026-06-26": "2026-06-25"}
        self.assertTrue(
            was_sent_within_dedup_window(state, "page|2026-06-26", today, 2)
        )

    def test_sent_two_days_ago_allows_with_2_day_window(self) -> None:
        today = date(2026, 6, 26)
        state = {"page|2026-06-26": "2026-06-24"}
        self.assertFalse(
            was_sent_within_dedup_window(state, "page|2026-06-26", today, 2)
        )

    def test_sent_two_days_ago_still_blocked_with_3_day_window(self) -> None:
        today = date(2026, 6, 26)
        state = {"page|2026-06-26": "2026-06-24"}
        self.assertTrue(
            was_sent_within_dedup_window(state, "page|2026-06-26", today, 3)
        )


if __name__ == "__main__":
    unittest.main()
