"""Tests for task-update Obsidian skip helpers (Fase 3)."""

from __future__ import annotations

import unittest

from src.slack_task_completion_gate import message_requests_complete
from src.slack_task_update_obsidian import (
    is_task_update_processed,
    should_skip_productivity_classify,
    slack_plain_for_gate,
)


class TestTaskUpdateProcessedFlag(unittest.TestCase):
    def test_recognizes_skip_statuses(self) -> None:
        for value in ("true", "unmatched", "ignored", "failed", '"yes"'):
            self.assertTrue(is_task_update_processed(value))

    def test_not_processed(self) -> None:
        self.assertFalse(is_task_update_processed(""))
        self.assertFalse(is_task_update_processed("false"))


class TestShouldSkipClassify(unittest.TestCase):
    def test_skips_when_frontmatter_set(self) -> None:
        fm = {"task_update_processed": '"true"'}
        self.assertTrue(should_skip_productivity_classify(fm, "anything"))

    def test_skips_completion_instruction_without_frontmatter(self) -> None:
        fm: dict = {}
        body = "Marca como completada la tarea de redactar la newsletter."
        self.assertTrue(should_skip_productivity_classify(fm, body))

    def test_does_not_skip_normal_task(self) -> None:
        fm: dict = {}
        body = "Debo anunciar el club de lectura del secuestro de Bitcoin esta semana."
        self.assertFalse(should_skip_productivity_classify(fm, body))

    def test_slack_body_section(self) -> None:
        fm: dict = {}
        body = (
            "## Contenido completo (Slack)\n\n"
            "Marcar como completado el envío del newsletter."
        )
        self.assertTrue(should_skip_productivity_classify(fm, body))
        plain = slack_plain_for_gate(body)
        self.assertTrue(message_requests_complete(plain))


if __name__ == "__main__":
    unittest.main()
