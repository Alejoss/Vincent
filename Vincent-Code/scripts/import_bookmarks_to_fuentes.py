#!/usr/bin/env python3
"""
Importa links de carpetas "Nueva carpeta" dentro de bookmarks HTML
(Chrome/Brave Netscape format) hacia 40_News/fuentes_directos_pasados.md.

Ejecución:
  python scripts/import_bookmarks_to_fuentes.py --vault ../Cerebro-Vincent \\
      --html ../Cerebro-Vincent/40_News/bookmarks_brave.html \\
      --label "ACBC Directo 6"

  python scripts/import_bookmarks_to_fuentes.py --vault ../Cerebro-Vincent \\
      --html ../Cerebro-Vincent/40_News/chrome_bookmarks.html \\
      --parent "ACBC Directo 8" --label "ACBC Directo 8"
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv(PROJECT_ROOT / ".env", override=True)

logger = logging.getLogger(__name__)

DEFAULT_FUENTES_REL = Path("40_News") / "fuentes_directos_pasados.md"


def extract_nueva_carpeta_urls(html: str, parent: str | None = None) -> list[str]:
    if parent:
        pat = (
            rf"<H3[^>]*>{re.escape(parent)}</H3>\s*<DL><p>(.*?)</DL><p>"
            rf"\s*(?=<DT><H3|</DL><p>\s*</DL>)"
        )
        m = re.search(pat, html, re.S | re.I)
        if not m:
            raise SystemExit(f"No se encontró carpeta padre: {parent}")
        scope = m.group(1)
    else:
        scope = html

    m2 = re.search(
        r"<H3[^>]*>Nueva carpeta</H3>\s*<DL><p>(.*?)</DL><p>",
        scope,
        re.S | re.I,
    )
    if not m2:
        raise SystemExit('No se encontró "Nueva carpeta"')

    folder = m2.group(1)
    links = re.findall(r'<A HREF="([^"]+)"[^>]*>', folder)
    urls: list[str] = []
    for href in links:
        if href.startswith(("chrome://", "brave://", "file://", "about:")):
            continue
        urls.append(href)
    return urls


def append_section(fuentes_path: Path, label: str, urls: list[str], force: bool) -> int:
    existing = fuentes_path.read_text(encoding="utf-8")
    heading = f"## {label}"
    if heading in existing and not force:
        raise SystemExit(
            f"La sección '{label}' ya existe en {fuentes_path.name}. Usa --force para añadir igual."
        )

    lines = [existing.rstrip(), "", heading, ""]
    for url in urls:
        lines.append(f"- [{url}]({url})")
    lines.append("")
    fuentes_path.write_text("\n".join(lines), encoding="utf-8")
    return len(urls)


def main() -> int:
    parser = argparse.ArgumentParser(
        description='Importa "Nueva carpeta" de bookmarks HTML a fuentes_directos_pasados.md'
    )
    parser.add_argument(
        "--vault",
        default=os.getenv("OBSIDIAN_VAULT_PATH", ""),
        help="Vault Obsidian",
    )
    parser.add_argument("--html", required=True, help="Ruta al bookmarks HTML")
    parser.add_argument(
        "--label",
        required=True,
        help='Etiqueta de sección (ej. "ACBC Directo 6")',
    )
    parser.add_argument(
        "--parent",
        default="",
        help="Carpeta padre opcional (ej. ACBC Directo 8). Si se omite, usa la primera Nueva carpeta.",
    )
    parser.add_argument(
        "--fuentes",
        default="",
        help="Nota de fuentes (default: 40_News/fuentes_directos_pasados.md)",
    )
    parser.add_argument("--force", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    vault = Path(args.vault).expanduser().resolve()
    if not vault.is_dir():
        logger.error("Vault no encontrado: %s", vault)
        return 1

    html_path = Path(args.html).expanduser().resolve()
    if not html_path.is_file():
        logger.error("No existe HTML: %s", html_path)
        return 1

    fuentes_path = (
        Path(args.fuentes).expanduser().resolve()
        if args.fuentes
        else vault / DEFAULT_FUENTES_REL
    )
    if not fuentes_path.is_file():
        logger.error("No existe Fuentes: %s", fuentes_path)
        return 1

    html = html_path.read_text(encoding="utf-8", errors="replace")
    parent = args.parent.strip() or None
    urls = extract_nueva_carpeta_urls(html, parent)
    logger.info("Links en Nueva carpeta: %s", len(urls))
    n = append_section(fuentes_path, args.label.strip(), urls, args.force)
    logger.info("Añadidos %s links bajo '%s' en %s", n, args.label, fuentes_path.name)
    for u in urls:
        logger.info("  %s", u)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
