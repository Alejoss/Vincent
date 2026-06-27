"""Tests for Slack task update audit and cursor rules (Fase 4)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.slack_task_updates_audit import (
    OUTCOME_APPLIED,
    OUTCOME_FAILED,
    OUTCOME_GATE_SKIP,
    OUTCOME_IGNORED,
    OUTCOME_UNMATCHED,
    append_audit_entry,
    build_audit_entry,
    should_advance_cursor,
)


class TestShouldAdvanceCursor(unittest.TestCase):
    def test_advances_on_safe_outcomes(self) -> None:
        for outcome in (OUTCOME_GATE_SKIP, "empty", OUTCOME_APPLIED):
            self.assertTrue(should_advance_cursor(outcome), outcome)

    def test_does_not_advance_on_retry_outcomes(self) -> None:
        for outcome in (OUTCOME_IGNORED, OUTCOME_UNMATCHED, OUTCOME_FAILED):
            self.assertFalse(should_advance_cursor(outcome), outcome)


class TestAuditLog(unittest.TestCase):
    def test_append_writes_jsonl(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "audit.jsonl"
            entry = build_audit_entry(
                slack_ts="1782484198.653939",
                outcome=OUTCOME_APPLIED,
                action="complete",
                gate="phrase_match",
                page_id="abc",
                title="Newsletter",
                confidence=0.92,
                model="openai:gpt-4o-mini",
            )
            append_audit_entry(path, entry)
            lines = path.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(lines), 1)
            obj = json.loads(lines[0])
            self.assertEqual(obj["ts"], "1782484198.653939")
            self.assertEqual(obj["outcome"], OUTCOME_APPLIED)
            self.assertIn("logged_at", obj)


if __name__ == "__main__":
    unittest.main()
