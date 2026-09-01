#!/usr/bin/env python3
"""
Autenticación OAuth para descargar subtítulos de TU canal vía YouTube Data API.

Primera vez (abre el navegador con la cuenta de Google del canal):
  python scripts/youtube_oauth_login.py

Requisitos previos en Google Cloud Console:
  1. Proyecto con YouTube Data API v3 habilitada
  2. Credenciales OAuth 2.0 tipo "Escritorio"
  3. Colocar el JSON en cache/youtube_oauth/client_secret.json
     O define GOOGLE_OAUTH_CLIENT_ID y GOOGLE_OAUTH_SECRET en .env

El token se guarda en cache/youtube_oauth/token.json (no commitear).
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv(PROJECT_ROOT / ".env", override=True)

from src.youtube_oauth import (
    client_secrets_path,
    oauth_cache_dir,
    run_oauth_login,
    token_path,
)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    log = logging.getLogger(__name__)

    cache = oauth_cache_dir(PROJECT_ROOT)
    secrets = client_secrets_path(PROJECT_ROOT)
    log.info("Carpeta OAuth: %s", cache)
    log.info("Client secrets: %s", secrets)

    log.info("")
    log.info("Se abrirá el navegador. Inicia sesión con la cuenta de @AcademiaBlockchain.")
    log.info("")

    try:
        run_oauth_login(PROJECT_ROOT)
    except FileNotFoundError as exc:
        log.error("%s", exc)
        return 1
    except Exception as exc:
        log.error("Error en login OAuth: %s", exc)
        return 1

    log.info("")
    log.info("Listo. Token guardado en: %s", token_path(PROJECT_ROOT))
    log.info("Ahora puedes ejecutar: python scripts/process_youtube_channel.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
