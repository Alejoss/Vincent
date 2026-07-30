"""
Intent detection for Slack productivity messages.

Classification owns `nueva` vs `completar`. Deterministic signals resolve
ambiguous LLM labels so completion messages never become new Notion rows.
"""

from __future__ import annotations

import re
import unicodedata

INTENT_NUEVA = "nueva"
INTENT_COMPLETAR = "completar"
VALID_INTENTS = frozenset({INTENT_NUEVA, INTENT_COMPLETAR})

# Explicit close of an existing task (past tense / imperative close).
_COMPLETE_PATTERNS = (
    re.compile(
        r"\bmarc(?:a|ar|ado|ada|ados|adas)\s+como\s+completad(?:o|a|os|as)\b"
    ),
    re.compile(r"\bmarc(?:a|ar)\s+como\s+hech(?:o|a)\b"),
    re.compile(r"\b(?:ya\s+)?complet(?:e|é)\s+la\s+tarea\b"),
    re.compile(r"\b(?:ya\s+)?termin(?:e|é)\s+la\s+tarea\b"),
    re.compile(r"\b(?:ya\s+)?finalic(?:e|é)\s+la\s+tarea\b"),
    re.compile(r"\bla\s+tarea\b.{0,80}\b(?:ya\s+)?(?:esta|está|quedo|quedó)\s+completad"),
    re.compile(r"\bla\s+tarea\b.{0,80}\b(?:ya\s+)?(?:esta|está|quedo|quedó)\s+hech"),
    re.compile(r"\bdar\s+por\s+(?:hecha|hecho|completada|completado)\b"),
)

# Future commitment — never treat as completion even if "completar" appears.
_NEW_COMMITMENT_RE = re.compile(
    r"\b(?:debo|tengo\s+que|hay\s+que|necesito|pendiente(?:\s+de)?)\b"
)


def normalize_for_intent(text: str) -> str:
    """Lowercase ASCII-ish text for deterministic phrase matching."""
    raw = unicodedata.normalize("NFKD", text or "")
    stripped = "".join(ch for ch in raw if not unicodedata.combining(ch))
    return stripped.lower()


def is_explicit_completion(text: str) -> bool:
    """True when the message clearly closes an existing task."""
    norm = normalize_for_intent(text)
    if not norm.strip():
        return False
    if _NEW_COMMITMENT_RE.search(norm) and not any(p.search(norm) for p in _COMPLETE_PATTERNS):
        # "Debo completar la newsletter" — commitment, not a close.
        return False
    return any(p.search(norm) for p in _COMPLETE_PATTERNS)


def is_explicit_new_commitment(text: str) -> bool:
    """True when the message is clearly a new pending action."""
    norm = normalize_for_intent(text)
    if not norm.strip():
        return False
    if is_explicit_completion(norm):
        return False
    return _NEW_COMMITMENT_RE.search(norm) is not None


def normalize_intent(value: str) -> str:
    raw = (value or "").strip().lower()
    if raw in VALID_INTENTS:
        return raw
    aliases = {
        "crear": INTENT_NUEVA,
        "create": INTENT_NUEVA,
        "new": INTENT_NUEVA,
        "nuevo": INTENT_NUEVA,
        "nueva_tarea": INTENT_NUEVA,
        "complete": INTENT_COMPLETAR,
        "completed": INTENT_COMPLETAR,
        "completion": INTENT_COMPLETAR,
        "cerrar": INTENT_COMPLETAR,
        "cerrada": INTENT_COMPLETAR,
        "hecho": INTENT_COMPLETAR,
        "done": INTENT_COMPLETAR,
    }
    return aliases.get(raw, "")


def resolve_intent(text: str, llm_intent: str = "") -> str:
    """
    Final intent for a Slack note.

    Deterministic completion/new signals win over the LLM so natural phrases
    like "Ya completé la tarea de…" close tasks instead of creating duplicates.
    """
    if is_explicit_completion(text):
        return INTENT_COMPLETAR
    if is_explicit_new_commitment(text):
        return INTENT_NUEVA
    normalized = normalize_intent(llm_intent)
    if normalized:
        return normalized
    return INTENT_NUEVA


# Back-compat aliases used by older call sites / docs.
def message_requests_complete(text: str) -> bool:
    """True only for explicit completion intent (replaces the old narrow gate)."""
    return is_explicit_completion(text)


GATE_SKIP_REASON = (
    "Sin intención de completar tarea existente "
    "(p. ej. 'completé la tarea' / 'marcar como completada'); "
    "no se aplica completado automático."
)

normalize_for_gate = normalize_for_intent
