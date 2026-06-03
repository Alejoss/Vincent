"""
Cliente mínimo para la API de Perplexity (Sonar).

Nota: La documentación pública no expone un endpoint documentado para el saldo
de créditos/tokens de la cuenta; solo el panel web (console.perplexity.ai).
Este módulo intenta rutas habituales y, si no hay saldo, devuelve el uso de
una petición mínima (tokens de esa llamada, no el saldo total).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import requests

BASE_URL = "https://api.perplexity.ai"


@dataclass
class PerplexityClient:
    api_key: str
    base_url: str = BASE_URL
    timeout: float = 60.0

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def try_balance_endpoints(self) -> List[Dict[str, Any]]:
        """Prueba GETs no documentados; la mayoría devolverá 404."""
        paths = [
            "/v1/account",
            "/v1/account/balance",
            "/v1/billing",
            "/v1/billing/balance",
            "/v1/credits",
            "/v1/usage",
            "/v1/usage/balance",
        ]
        results: List[Dict[str, Any]] = []
        for path in paths:
            url = f"{self.base_url}{path}"
            try:
                r = requests.get(
                    url, headers=self._headers(), timeout=self.timeout
                )
                entry: Dict[str, Any] = {
                    "path": path,
                    "status": r.status_code,
                }
                if r.headers.get("content-type", "").startswith("application/json"):
                    try:
                        entry["body"] = r.json()
                    except json.JSONDecodeError:
                        entry["body"] = r.text[:500]
                else:
                    entry["body_preview"] = (r.text or "")[:500]
                results.append(entry)
            except requests.RequestException as e:
                results.append({"path": path, "error": str(e)})
        return results

    def minimal_completion_usage(
        self,
        model: str = "sonar",
    ) -> tuple[Optional[Dict[str, Any]], Dict[str, str]]:
        """
        Una llamada mínima (sin búsqueda web) para obtener usage de esa petición.
        No es el saldo de la cuenta.
        """
        url = f"{self.base_url}/chat/completions"
        payload: Dict[str, Any] = {
            "model": model,
            "messages": [{"role": "user", "content": "Hi"}],
            "max_tokens": 1,
            "disable_search": True,
        }
        r = requests.post(
            url,
            headers=self._headers(),
            json=payload,
            timeout=self.timeout,
        )
        usage: Optional[Dict[str, Any]] = None
        if r.status_code == 200:
            try:
                data = r.json()
                usage = data.get("usage")
            except json.JSONDecodeError:
                pass
        hdrs = {k: v for k, v in r.headers.items()}
        return usage, hdrs


def _load_key() -> str:
    key = os.getenv("PERPLEXITY_API_KEY")
    if not key:
        raise SystemExit(
            "Falta PERPLEXITY_API_KEY en el entorno (p. ej. archivo .env)."
        )
    return key


def main() -> None:
    from pathlib import Path

    from dotenv import load_dotenv

    # Cargar .env del proyecto aunque el cwd no sea Vincent-Code
    env_path = Path(__file__).resolve().parent.parent / ".env"
    load_dotenv(env_path)
    client = PerplexityClient(api_key=_load_key())

    print("=== Intentos GET (saldo de cuenta; suelen no existir en la API pública) ===")
    for row in client.try_balance_endpoints():
        print(json.dumps(row, ensure_ascii=False, indent=2))

    print("\n=== Petición mínima POST /chat/completions (usage de esta llamada) ===")
    usage, headers = client.minimal_completion_usage()
    print("usage (JSON de la respuesta):", json.dumps(usage, ensure_ascii=False))
    print("Cabeceras de respuesta (por si indican límites/saldo):")
    for k in sorted(headers.keys()):
        print(f"  {k}: {headers[k]}")


if __name__ == "__main__":
    main()
