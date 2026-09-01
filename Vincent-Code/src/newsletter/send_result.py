"""Shared send result for newsletter providers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class SendResult:
    ok: bool
    method: str
    recipient_count: int
    tag: str
    bulk_id: str | None = None
    message_ids: list[str] | None = None
    error: str | None = None
    details: dict[str, Any] | None = None
