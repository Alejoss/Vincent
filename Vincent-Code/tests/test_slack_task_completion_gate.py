"""Tests for strict Slack task completion phrase gate (Fase 0 golden set + Fase 1)."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from src.slack_task_completion_gate import (
    GATE_SKIP_REASON,
    message_requests_complete,
    normalize_for_gate,
)

FIXTURES = Path(__file__).parent / "fixtures" / "slack_completion_gate_cases.json"


class TestNormalizeForGate(unittest.TestCase):
    def test_strips_accents_and_lowercases(self) -> None:
        self.assertEqual(
            normalize_for_gate("Marca como completada la métrica"),
            "marca como completada la metrica",
        )


class TestMessageRequestsComplete(unittest.TestCase):
    def test_positive_phrases(self) -> None:
        positives = [
            "Marca como completada la tarea de redactar la newsletter.",
            "Marcar como completado el envío del newsletter.",
            "Por favor marcar como completada la tarea del club.",
            "Quedó marcado como completada la tarea de impuestos.",
        ]
        for text in positives:
            with self.subTest(text=text):
                self.assertTrue(message_requests_complete(text))

    def test_negative_phrases(self) -> None:
        negatives = [
            "Ya terminé de publicar el primer podcast.",
            "Debo anunciar el club de lectura del secuestro de Bitcoin.",
            "Debo terminar el esqueleto de la línea de tiempo de Bitcoin.",
            "Ya creé el script que extrae audio de videos.",
            "Ya está hecho lo del podcast.",
            "[transcript dry-run]",
            "",
        ]
        for text in negatives:
            with self.subTest(text=text):
                self.assertFalse(message_requests_complete(text))


class TestGoldenSetFromFixtures(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cases = json.loads(FIXTURES.read_text(encoding="utf-8"))

    def test_fixture_count(self) -> None:
        self.assertGreaterEqual(len(self.cases), 8)

    def test_all_fixture_cases(self) -> None:
        for case in self.cases:
            with self.subTest(label=case["label"], slack_ts=case["slack_ts"]):
                got = message_requests_complete(case["text"])
                self.assertEqual(
                    got,
                    case["expect_gate"],
                    msg=f"text={case['text']!r}",
                )


class TestGateSkipReason(unittest.TestCase):
    def test_reason_is_non_empty(self) -> None:
        self.assertIn("marcar", GATE_SKIP_REASON.lower())


if __name__ == "__main__":
    unittest.main()
