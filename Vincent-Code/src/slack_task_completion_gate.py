"""
Backward-compatible exports for Slack task completion detection.

Prefer `src.slack_task_intent` for new code. This module re-exports the shared
intent helpers so older imports keep working.
"""

from __future__ import annotations

from src.slack_task_intent import (  # noqa: F401
    GATE_SKIP_REASON,
    INTENT_COMPLETAR,
    INTENT_NUEVA,
    is_explicit_completion,
    message_requests_complete,
    normalize_for_gate,
    normalize_for_intent,
    resolve_intent,
)

__all__ = [
    "GATE_SKIP_REASON",
    "INTENT_COMPLETAR",
    "INTENT_NUEVA",
    "is_explicit_completion",
    "message_requests_complete",
    "normalize_for_gate",
    "normalize_for_intent",
    "resolve_intent",
]
