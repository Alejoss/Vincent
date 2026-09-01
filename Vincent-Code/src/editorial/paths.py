"""Paths for editorial assets."""

from __future__ import annotations

from pathlib import Path

from src.newsletter.config import PROJECT_ROOT

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
BRAND_BOOK_PATH = PROMPTS_DIR / "brand_book.md"

ALL_CHANNELS = ("newsletter", "youtube", "telegram", "x", "instagram")
