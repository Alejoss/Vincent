"""Write-tool gates: confirm + dry-run."""

from __future__ import annotations

from typing import Any, Optional


REFUSE_MESSAGE = (
    "Write refused. Set confirm=true to run for real, or dry_run=true to preview."
)


def write_gate(confirm: bool, dry_run: bool) -> Optional[dict[str, Any]]:
    """Return an error payload if the write should not proceed."""
    if dry_run:
        return None
    if confirm:
        return None
    return {"ok": False, "error": REFUSE_MESSAGE, "needs_confirm": True}
