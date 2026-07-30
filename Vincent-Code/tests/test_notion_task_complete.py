"""Tests for Notion open-task matching used by completion sync."""

from __future__ import annotations

import unittest

from src.notion_task_complete import OpenTask, best_completion_match, choose_complete_status


class TestBestCompletionMatch(unittest.TestCase):
    def test_matches_telegram_newsletter_duplicate_case(self) -> None:
        open_tasks = [
            OpenTask(
                page_id="page-old",
                title="Anunciar canal de Telegram en redes y newsletter",
                status="Por hacer",
                text="Debo anunciar mi canal de Telegram como publicidad en mis otras redes y mi newsletter.",
            ),
            OpenTask(
                page_id="page-other",
                title="Cancelar suscripción a Scribd",
                status="Por hacer",
                text="Cancelar Scribd",
            ),
        ]
        query = (
            "Anunciar canal de telegram en redes y newsletter "
            "Ya completé la tarea de anunciar mi canal de telegram en mis redes y en la newsletter."
        )
        match = best_completion_match(query, open_tasks, min_score=4)
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.page_id, "page-old")

    def test_rejects_weak_match(self) -> None:
        open_tasks = [
            OpenTask(
                page_id="page-a",
                title="Revisar impuestos",
                status="Por hacer",
                text="Impuestos",
            )
        ]
        match = best_completion_match(
            "Ya completé la tarea de anunciar telegram",
            open_tasks,
            min_score=4,
        )
        self.assertIsNone(match)


class TestChooseCompleteStatus(unittest.TestCase):
    def test_prefers_hecho(self) -> None:
        self.assertEqual(choose_complete_status(["Por hacer", "En progreso", "Hecho"]), "Hecho")


if __name__ == "__main__":
    unittest.main()
