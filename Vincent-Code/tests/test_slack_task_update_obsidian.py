"""Tests for task-update Obsidian helpers (intent-aware classify/sync)."""

from __future__ import annotations

import unittest

from src.slack_task_intent import INTENT_COMPLETAR, message_requests_complete
from src.slack_task_update_obsidian import (
    is_task_update_processed,
    note_intent,
    should_skip_notion_create,
    should_skip_productivity_classify,
    slack_plain_for_gate,
)


class TestTaskUpdateProcessedFlag(unittest.TestCase):
    def test_recognizes_skip_statuses(self) -> None:
        for value in ("true", "unmatched", "ignored", "failed", "applied", '"yes"'):
            self.assertTrue(is_task_update_processed(value))

    def test_not_processed(self) -> None:
        self.assertFalse(is_task_update_processed(""))
        self.assertFalse(is_task_update_processed("false"))


class TestShouldSkipClassify(unittest.TestCase):
    def test_skips_when_frontmatter_set(self) -> None:
        fm = {"task_update_processed": '"true"'}
        self.assertTrue(should_skip_productivity_classify(fm, "anything"))

    def test_does_not_skip_completion_text_without_frontmatter(self) -> None:
        """Classifier must see completion messages to set intencion=completar."""
        fm: dict = {}
        body = "Ya completé la tarea de anunciar mi canal de telegram."
        self.assertFalse(should_skip_productivity_classify(fm, body))
        self.assertTrue(message_requests_complete(body))

    def test_does_not_skip_normal_task(self) -> None:
        fm: dict = {}
        body = "Debo anunciar el club de lectura del secuestro de Bitcoin esta semana."
        self.assertFalse(should_skip_productivity_classify(fm, body))


class TestShouldSkipNotionCreate(unittest.TestCase):
    def test_skips_completar_intent(self) -> None:
        fm = {"intencion": "completar"}
        self.assertTrue(should_skip_notion_create(fm, "Ya completé la tarea X"))
        self.assertEqual(note_intent(fm), INTENT_COMPLETAR)

    def test_allows_nueva(self) -> None:
        fm = {"intencion": "nueva"}
        self.assertFalse(should_skip_notion_create(fm, "Debo anunciar X"))


class TestSlackBodySection(unittest.TestCase):
    def test_extracts_plain(self) -> None:
        body = (
            "## Contenido completo (Slack)\n\n"
            "Marcar como completado el envío del newsletter."
        )
        plain = slack_plain_for_gate(body)
        self.assertTrue(message_requests_complete(plain))


if __name__ == "__main__":
    unittest.main()
