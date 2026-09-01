"""Shared writer utilities."""

from __future__ import annotations

from pathlib import Path

from src.llm_client import LLMConfig, call_text

from src.editorial.paths import PROMPTS_DIR


def load_prompt(name: str) -> str:
    path = PROMPTS_DIR / name
    if not path.is_file():
        raise FileNotFoundError(f"Prompt no encontrado: {path}")
    return path.read_text(encoding="utf-8")


def run_writer(
    *,
    system_prompt: str,
    user_prompt: str,
    config: LLMConfig,
    temperature: float = 0.7,
) -> str:
    return call_text(
        system=system_prompt,
        user=user_prompt,
        config=config,
        temperature=temperature,
    )
