"""
Unified JSON LLM client: OpenAI, Groq, or local Ollama.

Env:
  LLM_PROVIDER=openai|groq|ollama|auto   (default auto)
  LLM_MODEL                              (default per provider)
  OPENAI_API_KEY, OPENAI_API_BASE        (openai; default base https://api.openai.com/v1)
  GROQ_API_KEY, GROQ_API_BASE            (groq; default https://api.groq.com/openai/v1)
  OLLAMA_URL, OLLAMA_MODEL               (ollama; default http://127.0.0.1:11434)

Auto resolution (LLM_PROVIDER=auto):
  1) OPENAI_API_KEY  -> openai
  2) GROQ_API_KEY    -> groq
  3) otherwise       -> ollama
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Dict, Optional

import requests

DEFAULT_OPENAI_BASE = "https://api.openai.com/v1"
DEFAULT_GROQ_BASE = "https://api.groq.com/openai/v1"
DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"


@dataclass(frozen=True)
class LLMConfig:
    provider: str
    model: str
    ollama_url: str = DEFAULT_OLLAMA_URL
    openai_api_key: str = ""
    openai_base_url: str = DEFAULT_OPENAI_BASE
    groq_api_key: str = ""
    groq_base_url: str = DEFAULT_GROQ_BASE

    @property
    def label(self) -> str:
        return f"{self.provider}:{self.model}"


def resolve_llm_provider(explicit: Optional[str] = None) -> str:
    raw = (explicit or os.getenv("LLM_PROVIDER") or "auto").strip().lower()
    if raw in {"openai", "gpt"}:
        return "openai"
    if raw == "groq":
        return "groq"
    if raw == "ollama":
        return "ollama"
    if os.getenv("OPENAI_API_KEY", "").strip():
        return "openai"
    if os.getenv("GROQ_API_KEY", "").strip():
        return "groq"
    return "ollama"


def needs_local_ollama(explicit_provider: Optional[str] = None) -> bool:
    return resolve_llm_provider(explicit_provider) == "ollama"


def default_model_for_provider(provider: str) -> str:
    explicit = (os.getenv("LLM_MODEL") or "").strip()
    if explicit:
        return explicit
    if provider == "openai":
        return (os.getenv("OPENAI_MODEL") or "gpt-4o-mini").strip()
    if provider == "groq":
        return (os.getenv("GROQ_MODEL") or "llama-3.3-70b-versatile").strip()
    return (os.getenv("OLLAMA_MODEL") or "dolphin-llama3:8b").strip()


def build_llm_config(
    provider: Optional[str] = None,
    model: Optional[str] = None,
    ollama_url: Optional[str] = None,
) -> LLMConfig:
    resolved = resolve_llm_provider(provider)
    model_name = (model or "").strip() or default_model_for_provider(resolved)
    return LLMConfig(
        provider=resolved,
        model=model_name,
        ollama_url=(ollama_url or os.getenv("OLLAMA_URL") or DEFAULT_OLLAMA_URL).strip(),
        openai_api_key=(os.getenv("OPENAI_API_KEY") or "").strip(),
        openai_base_url=(os.getenv("OPENAI_API_BASE") or DEFAULT_OPENAI_BASE).rstrip("/"),
        groq_api_key=(os.getenv("GROQ_API_KEY") or "").strip(),
        groq_base_url=(os.getenv("GROQ_API_BASE") or DEFAULT_GROQ_BASE).rstrip("/"),
    )


def validate_llm_config(config: LLMConfig) -> None:
    if config.provider == "openai" and not config.openai_api_key:
        raise ValueError("OPENAI_API_KEY is required when LLM_PROVIDER=openai")
    if config.provider == "groq" and not config.groq_api_key:
        raise ValueError("GROQ_API_KEY is required when LLM_PROVIDER=groq")


def ollama_is_reachable(ollama_url: str = DEFAULT_OLLAMA_URL, timeout: float = 2.0) -> bool:
    try:
        response = requests.get(f"{ollama_url.rstrip('/')}/api/tags", timeout=timeout)
        return response.status_code == 200
    except Exception:
        return False


def _parse_json_response(raw: str, source: str) -> Dict[str, object]:
    text = (raw or "").strip()
    if not text:
        raise ValueError(f"{source} returned empty response")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
        raise


def _call_openai_compatible(
    *,
    api_key: str,
    base_url: str,
    model: str,
    prompt: str,
    timeout_s: int,
    source: str,
) -> Dict[str, object]:
    response = requests.post(
        f"{base_url.rstrip('/')}/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
            "response_format": {"type": "json_object"},
        },
        timeout=timeout_s,
    )
    if response.status_code >= 400:
        detail = (response.text or "").strip()[:500]
        raise RuntimeError(f"{source} error {response.status_code}: {detail}")
    data = response.json()
    choices = data.get("choices") or []
    if not choices:
        raise ValueError(f"{source} returned no choices")
    content = ((choices[0].get("message") or {}).get("content") or "").strip()
    return _parse_json_response(content, source)


def _call_ollama(config: LLMConfig, prompt: str, timeout_s: int) -> Dict[str, object]:
    response = requests.post(
        f"{config.ollama_url.rstrip('/')}/api/generate",
        json={
            "model": config.model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0},
        },
        timeout=timeout_s,
    )
    response.raise_for_status()
    raw = (response.json().get("response") or "").strip()
    return _parse_json_response(raw, "Ollama")


def call_json(prompt: str, config: LLMConfig, timeout_s: int = 90) -> Dict[str, object]:
    validate_llm_config(config)
    if config.provider == "openai":
        return _call_openai_compatible(
            api_key=config.openai_api_key,
            base_url=config.openai_base_url,
            model=config.model,
            prompt=prompt,
            timeout_s=timeout_s,
            source="OpenAI",
        )
    if config.provider == "groq":
        return _call_openai_compatible(
            api_key=config.groq_api_key,
            base_url=config.groq_base_url,
            model=config.model,
            prompt=prompt,
            timeout_s=timeout_s,
            source="Groq",
        )
    return _call_ollama(config, prompt, timeout_s)
