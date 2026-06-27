"""
Strict phrase gate for Slack -> Notion task completion.

Completion runs only when the message (text or audio transcript) contains an
explicit instruction like "marcar como completada" / "marca como completado".
"""

from __future__ import annotations

import re
import unicodedata

# Normalized text: marcar|marca|marcado|marcada + como + completad(o|a|os|as)
COMPLETE_GATE_RE = re.compile(
    r"\bmarc(?:a|ar|ado|ada|ados|adas)\s+como\s+completad(?:o|a|os|as)\b"
)

GATE_SKIP_REASON = (
    "Sin frase explícita 'marcar/marca como completada/o'; "
    "no se aplica completado automático."
)


def normalize_for_gate(text: str) -> str:
    """Lowercase ASCII-ish text for deterministic phrase matching."""
    raw = unicodedata.normalize("NFKD", text or "")
    stripped = "".join(ch for ch in raw if not unicodedata.combining(ch))
    return stripped.lower()


def message_requests_complete(text: str) -> bool:
    """True only if the user explicitly asked to mark a task complete."""
    norm = normalize_for_gate(text)
    if not norm.strip():
        return False
    return COMPLETE_GATE_RE.search(norm) is not None
