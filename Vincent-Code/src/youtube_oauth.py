"""OAuth 2.0 helpers for YouTube Data API (own-channel captions)."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]
TOKEN_FILENAME = "token.json"
CLIENT_SECRETS_FILENAME = "client_secret.json"


def oauth_cache_dir(project_root: str | Path) -> Path:
    path = Path(project_root) / "cache" / "youtube_oauth"
    path.mkdir(parents=True, exist_ok=True)
    return path


def token_path(project_root: str | Path) -> Path:
    return oauth_cache_dir(project_root) / TOKEN_FILENAME


def client_secrets_path(project_root: str | Path) -> Path:
    env_path = (os.getenv("YOUTUBE_OAUTH_CLIENT_SECRETS") or "").strip()
    if env_path:
        return Path(env_path).expanduser().resolve()
    return oauth_cache_dir(project_root) / CLIENT_SECRETS_FILENAME


def _env_oauth_client_id() -> str:
    return (
        (os.getenv("GOOGLE_OAUTH_CLIENT_ID") or "").strip()
        or (os.getenv("YOUTUBE_OAUTH_CLIENT_ID") or "").strip()
    )


def _env_oauth_client_secret() -> str:
    return (
        (os.getenv("GOOGLE_OAUTH_SECRET") or "").strip()
        or (os.getenv("GOOGLE_OAUTH_CLIENT_SECRET") or "").strip()
        or (os.getenv("YOUTUBE_OAUTH_CLIENT_SECRET") or "").strip()
    )


def _client_config_from_env() -> Optional[dict]:
    client_id = _env_oauth_client_id()
    client_secret = _env_oauth_client_secret()
    if not client_id or not client_secret:
        return None
    return {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }


def load_credentials(project_root: str | Path) -> Optional[Credentials]:
    """Load stored OAuth credentials, refreshing if expired."""
    path = token_path(project_root)
    if not path.is_file():
        return None

    creds = Credentials.from_authorized_user_file(str(path), SCOPES)
    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            save_credentials(project_root, creds)
            return creds
        except Exception as exc:
            logger.error("No se pudo refrescar el token OAuth: %s", exc)
            return None

    return None


def save_credentials(project_root: str | Path, creds: Credentials) -> Path:
    path = token_path(project_root)
    path.write_text(creds.to_json(), encoding="utf-8")
    logger.info("Token OAuth guardado en %s", path)
    return path


def run_oauth_login(project_root: str | Path, *, open_browser: bool = True) -> Credentials:
    """
    Run interactive OAuth login (opens browser on first run).
    Requires client_secret.json or GOOGLE_OAUTH_CLIENT_ID + GOOGLE_OAUTH_SECRET in .env.
    """
    client_config = _client_config_from_env()
    secrets_path = client_secrets_path(project_root)

    if client_config:
        flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
    elif secrets_path.is_file():
        flow = InstalledAppFlow.from_client_secrets_file(str(secrets_path), SCOPES)
    else:
        raise FileNotFoundError(
            "Faltan credenciales OAuth. Coloca client_secret.json en "
            f"{oauth_cache_dir(project_root)} o define GOOGLE_OAUTH_CLIENT_ID y "
            "GOOGLE_OAUTH_SECRET en .env"
        )

    creds = flow.run_local_server(port=0, open_browser=open_browser)
    save_credentials(project_root, creds)
    return creds


def get_authenticated_youtube_service(project_root: str | Path):
    """Return a YouTube API service using OAuth credentials."""
    creds = load_credentials(project_root)
    if not creds:
        raise RuntimeError(
            "No hay sesión OAuth. Ejecuta: python scripts/youtube_oauth_login.py"
        )
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def credentials_available(project_root: str | Path) -> bool:
    return load_credentials(project_root) is not None
