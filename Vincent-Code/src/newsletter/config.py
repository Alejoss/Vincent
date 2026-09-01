"""Newsletter paths and SMTP2GO config from environment and optional local settings."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SETTINGS_PATH = PROJECT_ROOT / "data" / "newsletter_settings.json"
DEFAULT_MD_DIR = PROJECT_ROOT.parent / "Cerebro-Vincent" / "newsletters"
SEGMENTS_DIR = PROJECT_ROOT / "data" / "segments"
PREVIEW_DIR = PROJECT_ROOT.parent / "emails" / "preview"

SMTP2GO_API = "https://api.smtp2go.com/v3"


@dataclass
class NewsletterConfig:
    provider: str  # smtp2go
    api_key: str
    from_email: str
    from_name: str
    reply_to: str
    test_email: str
    md_dir: Path
    segments_dir: Path

    @property
    def from_address(self) -> str:
        if self.from_name:
            return f"{self.from_name} <{self.from_email}>"
        return self.from_email


def _load_settings_file() -> dict[str, Any]:
    if not SETTINGS_PATH.is_file():
        return {}
    try:
        return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_settings(updates: dict[str, str]) -> None:
    """Persist UI overrides (gitignored file)."""
    current = _load_settings_file()
    current.update({k: v for k, v in updates.items() if v is not None})
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(current, indent=2, ensure_ascii=False), encoding="utf-8")


def _env(*names: str, default: str = "") -> str:
    for name in names:
        value = (os.getenv(name) or "").strip()
        if value:
            return value
    return default


def load_config() -> NewsletterConfig:
    load_dotenv(PROJECT_ROOT / ".env", override=True)
    overrides = _load_settings_file()

    def _get(key: str, *env_keys: str, default: str = "") -> str:
        if overrides.get(key):
            return str(overrides[key]).strip()
        return _env(*env_keys, default=default)

    md_raw = _get("md_dir", "NEWSLETTER_MD_DIR", default="")
    md_dir = Path(md_raw) if md_raw else DEFAULT_MD_DIR
    if not md_dir.is_absolute():
        md_dir = (PROJECT_ROOT / md_dir).resolve()

    # Prefer newsletter-specific From; avoid transactional EMAIL_FROM placeholders.
    from_email = _extract_email(
        _get(
            "from_email",
            "NEWSLETTER_FROM_EMAIL",
            default="news@newsletter.academiablockchain.com",
        )
    )
    if not from_email or "tu_email" in from_email or "@" not in from_email:
        from_email = "news@newsletter.academiablockchain.com"
    from_name = _get(
        "from_name",
        "NEWSLETTER_FROM_NAME",
        "EMAIL_FROM_NAME",
        default="Alejandro de Academia Blockchain",
    )
    reply_to = _get(
        "reply_to",
        "NEWSLETTER_REPLY_TO",
        default="alejandro@academiablockchain.com",
    )

    return NewsletterConfig(
        provider="smtp2go",
        api_key=_get("api_key", "SMTP2GO_API_KEY", "SMPT2GO_API_KEY"),
        from_email=from_email,
        from_name=from_name,
        reply_to=reply_to,
        test_email=_get(
            "test_email",
            "NEWSLETTER_TEST_EMAIL",
            "EMAIL_TO",
            default="alejandro@academiablockchain.com",
        ),
        md_dir=md_dir,
        segments_dir=SEGMENTS_DIR,
    )


def validate_config(config: NewsletterConfig) -> list[str]:
    errors: list[str] = []
    if not config.api_key:
        errors.append("Falta SMTP2GO_API_KEY (o SMPT2GO_API_KEY en .env).")
    if not config.from_email:
        errors.append("Falta NEWSLETTER_FROM_EMAIL / EMAIL_FROM.")
    if not config.md_dir.is_dir():
        errors.append(f"Carpeta de newsletters no encontrada: {config.md_dir}")
    return errors


def test_connection(config: NewsletterConfig) -> dict[str, Any]:
    """Ping SMTP2GO."""
    return _test_smtp2go(config)


def _extract_email(raw: str) -> str:
    """Normalize 'Name <addr@host>' or bare addr to just the email."""
    text = (raw or "").strip()
    if "<" in text and ">" in text:
        inner = text[text.rfind("<") + 1 : text.rfind(">")].strip()
        if "@" in inner:
            return inner
    return text


def _test_smtp2go(config: NewsletterConfig) -> dict[str, Any]:
    if not config.api_key:
        return {"ok": False, "error": "Sin SMTP2GO_API_KEY."}
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-Smtp2go-Api-Key": config.api_key,
    }
    try:
        with httpx.Client(timeout=30.0) as client:
            # Auth probe — send-only keys may lack stats permission; that still proves the key is valid.
            resp = client.post(
                f"{SMTP2GO_API}/stats/email_summary",
                headers=headers,
                json={},
            )
            data = resp.json() if resp.content else {}
            if resp.status_code == 401:
                return {"ok": False, "error": "API key inválida."}
            err_text = ""
            if isinstance(data, dict):
                body = data.get("data") if isinstance(data.get("data"), dict) else data
                if isinstance(body, dict):
                    err_text = str(body.get("error") or "")
            permission_denied = "does not have the appropriate permission" in err_text.lower()
            if resp.status_code in {200, 403} or permission_denied:
                return {
                    "ok": True,
                    "provider": "smtp2go",
                    "from": config.from_address,
                    "api_status": resp.status_code,
                    "stats_permission": not permission_denied and resp.status_code == 200,
                    "details": data,
                }
            return {
                "ok": False,
                "error": err_text or str(data or resp.text),
            }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def list_markdown_files(md_dir: Path | None = None) -> list[Path]:
    config = load_config()
    root = md_dir or config.md_dir
    if not root.is_dir():
        return []
    files = sorted(
        p
        for p in root.glob("*.md")
        if p.name not in ("_template.md", "suscriptores.md") and not p.name.startswith(".")
    )
    return files


def list_segments(segments_dir: Path | None = None) -> list[str]:
    from .subscribers import list_segments as _list_segments

    return _list_segments(segments_dir)


def activity_url(tag: str = "") -> str:
    """Stats UI for SMTP2GO."""
    del tag  # Reports are not tag-filtered via URL
    return "https://app.smtp2go.com/reports/email/"
