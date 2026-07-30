"""Tests for Slack task completion intent (classification + Pipeline 3)."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from src.slack_task_intent import (
    GATE_SKIP_REASON,
    INTENT_COMPLETAR,
    INTENT_NUEVA,
    is_explicit_completion,
    message_requests_complete,
    normalize_for_intent,
    resolve_intent,
)

FIXTURES = Path(__file__).parent / "fixtures" / "slack_completion_gate_cases.json"


class TestNormalizeForIntent(unittest.TestCase):
    def test_strips_accents_and_lowercases(self) -> None:
        self.assertEqual(
            normalize_for_intent("Marca como completada la métrica"),
            "marca como completada la metrica",
        )


class TestExplicitCompletion(unittest.TestCase):
    def test_positive_phrases(self) -> None:
        positives = [
            "Marca como completada la tarea de redactar la newsletter.",
            "Marcar como completado el envío del newsletter.",
            "Por favor marcar como completada la tarea del club.",
            "Quedó marcado como completada la tarea de impuestos.",
            "Ya completé la tarea de anunciar mi canal de telegram en mis redes y en la newsletter.",
            "Ya terminé la tarea de enviar el newsletter.",
        ]
        for text in positives:
            with self.subTest(text=text):
                self.assertTrue(is_explicit_completion(text))
                self.assertTrue(message_requests_complete(text))

    def test_negative_phrases(self) -> None:
        negatives = [
            "Ya terminé de publicar el primer podcast.",
            "Debo anunciar el club de lectura del secuestro de Bitcoin.",
            "Debo terminar el esqueleto de la línea de tiempo de Bitcoin.",
            "Debo completar la newsletter esta semana.",
            "Ya creé el script que extrae audio de videos.",
            "Ya está hecho lo del podcast.",
            "[transcript dry-run]",
            "",
        ]
        for text in negatives:
            with self.subTest(text=text):
                self.assertFalse(is_explicit_completion(text))


class TestResolveIntent(unittest.TestCase):
    def test_deterministic_completion_beats_llm_nueva(self) -> None:
        text = "Ya completé la tarea de anunciar mi canal de telegram."
        self.assertEqual(resolve_intent(text, "nueva"), INTENT_COMPLETAR)

    def test_deterministic_new_beats_llm_completar(self) -> None:
        text = "Debo anunciar el club de lectura esta semana."
        self.assertEqual(resolve_intent(text, "completar"), INTENT_NUEVA)

    def test_llm_intent_when_no_signal(self) -> None:
        text = "Responder al correo de Andrés."
        self.assertEqual(resolve_intent(text, "nueva"), INTENT_NUEVA)
        self.assertEqual(resolve_intent(text, "completar"), INTENT_COMPLETAR)


class TestGoldenSetFromFixtures(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cases = json.loads(FIXTURES.read_text(encoding="utf-8"))

    def test_fixture_count(self) -> None:
        self.assertGreaterEqual(len(self.cases), 8)

    def test_all_fixture_cases(self) -> None:
        for case in self.cases:
            expected = case.get("expect_complete", case.get("expect_gate"))
            with self.subTest(label=case["label"], slack_ts=case["slack_ts"]):
                got = message_requests_complete(case["text"])
                self.assertEqual(
                    got,
                    expected,
                    msg=f"text={case['text']!r}",
                )


class TestGateSkipReason(unittest.TestCase):
    def test_reason_is_non_empty(self) -> None:
        self.assertTrue(len(GATE_SKIP_REASON) > 10)


if __name__ == "__main__":
    unittest.main()
