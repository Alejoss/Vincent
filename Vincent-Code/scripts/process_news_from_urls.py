#!/usr/bin/env python3
"""
Lee URLs desde 30_News/News_URLS.md, infiere el título desde el slug de la URL,
asigna temas según la nota 30_News/Taxonomia_Temas_Noticias.md (sin HTTP: útil
tras Cloudflare u otros bloqueos).

Ejecución (desde la raíz de Vincent-Code):
  python scripts/process_news_from_urls.py
  python scripts/process_news_from_urls.py --limit 5 --dry-run

Requiere OBSIDIAN_VAULT_PATH en .env apuntando al vault (ej. Cerebro-Vincent).
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv(PROJECT_ROOT / ".env", override=True)

logger = logging.getLogger(__name__)

DEFAULT_URLS_REL = Path("30_News") / "News_URLS.md"
DEFAULT_TAXONOMY_NOTE_REL = Path("30_News") / "Taxonomia_Temas_Noticias.md"
NOTICIAS_SUBDIR = Path("30_News") / "Noticias"
TEMAS_SUBDIR = Path("Temas")
MAX_TEMAS = 6


def parse_urls_from_markdown(text: str) -> list[str]:
    urls: list[str] = []
    link_re = re.compile(r"\[([^\]]*)\]\((https?://[^)]+)\)")
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m_link = link_re.search(line)
        if m_link:
            urls.append(m_link.group(2).strip())
            continue
        if line.startswith("http://") or line.startswith("https://"):
            urls.append(line)
    return urls


def url_slug(url: str) -> str:
    path = urlparse(url).path.rstrip("/")
    if not path:
        return "articulo"
    seg = unquote(path.split("/")[-1])
    return seg if seg else "articulo"


def slug_to_title(slug: str) -> str:
    s = unquote(slug).replace("-", " ").strip()
    if not s:
        return "Sin título"
    return " ".join(w.capitalize() for w in s.split())


def safe_filename_slug(slug: str, max_len: int = 180) -> str:
    s = re.sub(r'[<>:"/\\|?*]', "_", slug)
    s = re.sub(r"\s+", "-", s).strip("._-") or "articulo"
    return s[:max_len]


def load_taxonomy_from_obsidian_note(path: Path) -> list[dict[str, Any]]:
    """
    Formato: bloques ## Nombre del tema y debajo líneas - palabra clave.
    Todo lo que va antes del primer ## (título, instrucciones) se ignora.
    """
    if not path.is_file():
        logger.warning("No existe la nota de taxonomía: %s — sin temas", path)
        return []
    text = path.read_text(encoding="utf-8")
    parts = re.split(r"(?m)^##\s+", text)
    out: list[dict[str, Any]] = []
    for part in parts[1:]:
        lines = [ln.rstrip() for ln in part.splitlines()]
        if not lines:
            continue
        name = lines[0].strip()
        if not name:
            continue
        kws: list[str] = []
        for ln in lines[1:]:
            ln_st = ln.strip()
            if not ln_st:
                continue
            if ln_st.startswith("---"):
                break
            if ln_st.startswith("#"):
                break
            if ln_st.startswith(("-", "*")):
                kw = ln_st[1:].strip()
                if kw:
                    kws.append(kw)
        out.append({"name": name, "keywords": kws})
    return out


def _count_keyword(blob: str, kw: str) -> int:
    kw_l = kw.lower().strip()
    if not kw_l:
        return 0
    if " " in kw_l:
        return blob.count(kw_l)
    if len(kw_l) <= 3:
        return len(re.findall(rf"(?<![a-z0-9]){re.escape(kw_l)}(?![a-z0-9])", blob))
    return len(re.findall(rf"(?<![a-z0-9]){re.escape(kw_l)}(?![a-z0-9])", blob))


def score_categories(
    categories: list[dict[str, Any]], blob: str
) -> list[tuple[str, int]]:
    blob_l = blob.lower()
    scored: list[tuple[str, int]] = []
    for cat in categories:
        name = cat.get("name")
        kws = cat.get("keywords") or []
        if not name:
            continue
        total = 0
        for kw in kws:
            if isinstance(kw, str):
                total += _count_keyword(blob_l, kw.lower())
        if total > 0:
            scored.append((str(name), total))
    scored.sort(key=lambda x: -x[1])
    return scored


def ensure_tema_stub(vault: Path, tema_name: str, dry_run: bool) -> None:
    temas_dir = vault / TEMAS_SUBDIR
    path = temas_dir / f"{tema_name}.md"
    if path.exists():
        return
    body = (
        f"---\n"
        f"type: tema\n"
        f"---\n\n"
        f"# {tema_name}\n\n"
        f"## Descripción\n"
        f"_Definición pendiente._\n"
    )
    if dry_run:
        logger.info("[dry-run] crearía tema: %s", path)
        return
    temas_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    logger.info("Tema creado: %s", path)


def yaml_quote_simple(s: str) -> str:
    """Valor escalar seguro para YAML en una línea."""
    if "\n" in s:
        s = s.split("\n", 1)[0]
    if '"' in s:
        return "'" + s.replace("'", "''") + "'"
    if any(c in s for c in (":", "#", "%", "'", " ")) or not s:
        return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return s


def build_note_frontmatter(
    *,
    url: str,
    titulo: str,
    fuente: str,
    temas_wikilinks: list[str],
) -> str:
    lines = [
        "---",
        "type: noticia",
        f"url: {yaml_quote_simple(url)}",
        f"titulo: {yaml_quote_simple(titulo)}",
    ]
    lines.append(f"fuente: {yaml_quote_simple(fuente)}")
    lines.append("temas:")
    for t in temas_wikilinks:
        lines.append(f"  - \"[[{t}]]\"")
    lines.append("---")
    return "\n".join(lines) + "\n"


def existing_url_in_note(path: Path, url: str) -> bool:
    if not path.is_file():
        return False
    text = path.read_text(encoding="utf-8")
    q = yaml_quote_simple(url)
    return f"url: {q}" in text or f"url: {url}" in text


def main() -> int:
    parser = argparse.ArgumentParser(
        description="URLs de News_URLS.md → notas (título desde URL; temas desde Taxonomia_Temas_Noticias.md)"
    )
    parser.add_argument(
        "--vault",
        default=os.getenv("OBSIDIAN_VAULT_PATH", ""),
        help="Ruta al vault Obsidian (por defecto OBSIDIAN_VAULT_PATH)",
    )
    parser.add_argument(
        "--urls-note",
        default="",
        help="Ruta al fichero con URLs (absoluta o relativa al vault)",
    )
    parser.add_argument(
        "--taxonomy-note",
        default="",
        help="Ruta a la nota de taxonomía (por defecto 30_News/Taxonomia_Temas_Noticias.md)",
    )
    parser.add_argument("--limit", type=int, default=0, help="Máximo de URLs (0 = todas)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    vault = Path(args.vault).expanduser().resolve()
    if not vault.is_dir():
        logger.error(
            "Vault no encontrado: %s — define OBSIDIAN_VAULT_PATH o usa --vault",
            vault,
        )
        return 1

    urls_note = (
        Path(args.urls_note).expanduser().resolve()
        if args.urls_note
        else (vault / DEFAULT_URLS_REL)
    )
    if not urls_note.is_file():
        logger.error("No existe la nota de URLs: %s", urls_note)
        return 1

    taxonomy_note = (
        Path(args.taxonomy_note).expanduser().resolve()
        if args.taxonomy_note
        else (vault / DEFAULT_TAXONOMY_NOTE_REL)
    )
    categories = load_taxonomy_from_obsidian_note(taxonomy_note)

    raw = urls_note.read_text(encoding="utf-8")
    urls = parse_urls_from_markdown(raw)
    if args.limit and args.limit > 0:
        urls = urls[: args.limit]

    if not urls:
        logger.warning("No se encontraron URLs en %s", urls_note)
        return 0

    noticias_dir = vault / NOTICIAS_SUBDIR
    if not args.dry_run:
        noticias_dir.mkdir(parents=True, exist_ok=True)

    for i, url in enumerate(urls, 1):
        url = url.strip()
        if not url:
            continue
        slug = url_slug(url)
        safe_name = safe_filename_slug(slug)
        out_path = vault / NOTICIAS_SUBDIR / f"{safe_name}.md"
        parsed = urlparse(url)
        fuente = (parsed.netloc or "desconocido").replace("www.", "")

        if not args.force and existing_url_in_note(out_path, url):
            logger.info("[%s/%s] Ya existe nota para URL — omitiendo: %s", i, len(urls), url[:80])
            continue

        titulo = slug_to_title(slug)

        blob_for_cats = " " + slug.lower().replace("-", " ") + " " + titulo.lower() + " "
        scored = score_categories(categories, blob_for_cats)
        chosen = [name for name, sc in scored if sc >= 1][:MAX_TEMAS]
        temas_wikilinks = chosen

        fm = build_note_frontmatter(
            url=url,
            titulo=titulo,
            fuente=fuente,
            temas_wikilinks=temas_wikilinks,
        )
        note_body = (
            f"{fm}\n"
            f"# {titulo}\n\n"
            f"## Enlace\n[Abrir en la fuente]({url})\n"
        )

        if args.dry_run:
            logger.info(
                "[dry-run] %s → %s | temas: %s",
                url[:72],
                out_path.name,
                temas_wikilinks or "(ninguno)",
            )
            continue

        out_path.write_text(note_body, encoding="utf-8")
        logger.info("Escrito: %s (temas: %s)", out_path, temas_wikilinks or "(ninguno)")

        for tema in temas_wikilinks:
            ensure_tema_stub(vault, tema, args.dry_run)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
