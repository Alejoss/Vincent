#!/usr/bin/env python3
"""
Marca en 40_News/Temas/ el directo de origen de cada link que ya aparece en
40_News/fuentes_directos_pasados.md (ej. "ACBC Directo 8").

También migra el bloque de fuentes manuales a tabla:

  | Título | Link | Estado |
  |--------|------|--------|
  | ...    | url  | ACBC Directo 8 |

Ejecución (desde Vincent-Code):
  python scripts/mark_vistos_temas.py --vault ../Cerebro-Vincent
  python scripts/mark_vistos_temas.py --vault ../Cerebro-Vincent --dry-run
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse, urlunparse

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv(PROJECT_ROOT / ".env", override=True)

logger = logging.getLogger(__name__)

DEFAULT_TEMAS_REL = Path("40_News") / "Temas"
DEFAULT_FUENTES_REL = Path("40_News") / "fuentes_directos_pasados.md"

URL_RE = re.compile(r"https?://[^\s\)\]\>\"']+")
MD_LINK_RE = re.compile(r"\[([^\]]*)\]\((https?://[^)]+)\)")
TABLE_SEP_RE = re.compile(r"^\|[\s\-:|]+\|$")
ACBC_DIRECTO_RE = re.compile(r"ACBC\s+Directo\s+\d+", re.I)

TRACKING_PARAMS = {
    "s",
    "si",
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "fbclid",
    "gclid",
    "ref",
    "ref_src",
}


def normalize_url(url: str) -> str:
    """Clave estable para comparar URLs entre Temas y Fuentes."""
    url = url.strip().rstrip(".,;")
    try:
        p = urlparse(url)
    except Exception:
        return url.lower().rstrip("/")

    scheme = (p.scheme or "https").lower()
    host = (p.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if host in {"twitter.com", "mobile.twitter.com", "www.twitter.com"}:
        host = "x.com"
    if host in {"youtu.be", "www.youtu.be", "m.youtube.com"}:
        host = "youtube.com"

    path = p.path or ""
    query = p.query or ""

    # youtu.be/ID → youtube.com/watch?v=ID
    if host == "youtube.com" and path.startswith("/") and "watch" not in path:
        vid = path.strip("/").split("/")[0]
        if vid and vid not in {"watch", "shorts", "results", "playlist"}:
            if "shorts" in path:
                path = f"/shorts/{path.strip('/').split('/')[-1]}"
            else:
                path = "/watch"
                query = f"v={vid}"

    # Keep only meaningful query params
    keep: list[str] = []
    if query:
        qs = parse_qs(query, keep_blank_values=False)
        for key, values in qs.items():
            kl = key.lower()
            if kl in TRACKING_PARAMS:
                continue
            if host == "youtube.com" and kl == "v" and values:
                keep.append(f"v={values[0]}")
            elif host == "youtube.com" and kl == "list" and values:
                keep.append(f"list={values[0]}")
            elif kl not in TRACKING_PARAMS and values:
                # drop most search noise; keep short significant ones
                if host not in {"www.google.com", "google.com"}:
                    keep.append(f"{key}={values[0]}")

    path = path.rstrip("/") or ""
    new_query = "&".join(keep)
    return urlunparse((scheme, host, path, "", new_query, "")).lower()


def short_directo_label(raw: str) -> str:
    """Normaliza el nombre de sección a una etiqueta corta para la columna Estado."""
    text = re.sub(r"\s+", " ", raw).strip()
    m = ACBC_DIRECTO_RE.search(text)
    if m:
        # Canonical: "ACBC Directo N"
        parts = m.group(0).split()
        return f"ACBC Directo {parts[-1]}"
    if text.upper().startswith("EN VIVO:"):
        # "EN VIVO: Anthropic. Las tontas..." → "EN VIVO: Anthropic"
        rest = text[8:].strip()
        first = rest.split(".")[0].strip()
        return f"EN VIVO: {first}" if first else "EN VIVO"
    if len(text) > 48:
        return text[:45].rstrip() + "..."
    return text


def extract_url_directo_map(text: str) -> dict[str, str]:
    """
    Mapa URL normalizada → etiqueta de directo.

    Formato preferido:
      ## ACBC Directo 8
      - [url](url)

    También soporta el formato viejo de tablas markdown.
    """
    url_to_labels: dict[str, list[str]] = {}

    def add_url(url: str, label: str) -> None:
        key = normalize_url(url)
        if not key.startswith("http"):
            return
        labels = url_to_labels.setdefault(key, [])
        if label not in labels:
            labels.append(label)

    # Formato: ## ACBC Directo N (o # ACBC Directo N) + lista de links
    # Ignora el H1 del documento (# Fuentes...)
    parts = re.split(r"(?m)^#{1,3}\s+(?=ACBC\s+Directo\b|EN VIVO:)", text, flags=re.I)
    for part in parts[1:]:
        lines = part.splitlines()
        if not lines:
            continue
        label = short_directo_label(lines[0].strip())
        body = "\n".join(lines[1:])
        # No cruzar a la siguiente sección ACBC/EN VIVO
        body = re.split(
            r"(?m)^#{1,3}\s+(?=ACBC\s+Directo\b|EN VIVO:)", body, flags=re.I
        )[0]
        for m in MD_LINK_RE.finditer(body):
            href = m.group(2).strip()
            if href.startswith(("file://", "chrome://", "brave://")):
                continue
            add_url(href, label)
        for m in URL_RE.finditer(body):
            raw = m.group(0).rstrip(".,;")
            if raw.startswith(("file://", "chrome://", "brave://")):
                continue
            if re.search(rf"\]\({re.escape(raw)}\)", body):
                continue
            add_url(raw, label)

    # Formato viejo: tablas (por si queda algo)
    current_label = "Directo"
    for raw in text.splitlines():
        line = raw.strip()
        if not line.startswith("|"):
            continue
        if TABLE_SEP_RE.match(line):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if not cells:
            continue
        first = cells[0].strip()
        if not first:
            continue

        urls_in_row: list[str] = []
        for cell in cells:
            for m in MD_LINK_RE.finditer(cell):
                urls_in_row.append(m.group(2).strip())
            if not MD_LINK_RE.search(cell):
                for m in URL_RE.finditer(cell):
                    urls_in_row.append(m.group(0).rstrip(".,;"))

        if not urls_in_row:
            current_label = short_directo_label(first)
            continue

        for url in urls_in_row:
            add_url(url, current_label)

    return {k: ", ".join(v) for k, v in url_to_labels.items()}


def is_url_line(line: str) -> str | None:
    s = line.strip()
    m = MD_LINK_RE.search(s)
    if m:
        return m.group(2).strip()
    m2 = URL_RE.search(s)
    if m2 and (s.startswith("http") or s.startswith("[")):
        return m2.group(0).rstrip(".,;")
    return None


def escape_cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ").strip()


def md_link(url: str) -> str:
    return f"[{url}]({url})"


def _looks_like_sep_cell(text: str) -> bool:
    t = text.replace("\\", "").replace("|", "").strip()
    if not t:
        return True
    return bool(re.fullmatch(r"[\s\-:]+", t))


def parse_table_rows(lines: list[str]) -> list[dict[str, str]]:
    """Parse markdown table rows into {titulo, url, estado}."""
    rows: list[dict[str, str]] = []
    header_seen = False
    for line in lines:
        s = line.strip()
        if not s.startswith("|"):
            continue
        # Separators (incl. Obsidian Advanced Tables padding)
        if TABLE_SEP_RE.match(s) or re.fullmatch(r"\|[\s\-:|\\]+\|", s):
            header_seen = True
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        cells = [c.replace("\\|", "|").strip() for c in cells]
        if not cells:
            continue
        # Skip separator-like or nested-header garbage rows
        if all(_looks_like_sep_cell(c) for c in cells):
            continue
        first_l = re.sub(r"\s+", " ", cells[0]).strip().lower()
        if first_l in {"título", "titulo", "title"} or first_l.startswith("título |"):
            header_seen = True
            continue

        # Find URL in any cell (robust to reformatted tables)
        url = ""
        url_cell_idx = -1
        for i, cell in enumerate(cells):
            m = MD_LINK_RE.search(cell)
            if m:
                url = m.group(2).strip()
                url_cell_idx = i
                break
            m2 = URL_RE.search(cell)
            if m2 and ("http://" in cell or "https://" in cell):
                url = m2.group(0).rstrip(".,;")
                url_cell_idx = i
                break

        titulo = cells[0] if cells else ""
        if _looks_like_sep_cell(titulo) or titulo.startswith("|"):
            titulo = ""

        estado = ""
        # Prefer last non-url cell after the link as estado
        for i in range(len(cells) - 1, -1, -1):
            if i == url_cell_idx or i == 0:
                continue
            cand = cells[i].strip()
            if not cand or _looks_like_sep_cell(cand):
                continue
            if MD_LINK_RE.search(cand) or URL_RE.search(cand):
                continue
            estado = cand
            break

        if not url and not titulo:
            continue

        rows.append(
            {
                "titulo": titulo,
                "url": url,
                "estado": estado.strip(),
            }
        )
    return rows


def parse_legacy_entries(body: str) -> list[dict[str, str]]:
    """
    Formato legado:
      Título
      https://...
      https://...

      Otro título
      https://...
    """
    entries: list[dict[str, str]] = []
    current_title = ""
    pending_urls: list[str] = []

    def flush() -> None:
        nonlocal current_title, pending_urls
        if pending_urls:
            for u in pending_urls:
                entries.append({"titulo": current_title, "url": u, "estado": ""})
        elif current_title:
            entries.append({"titulo": current_title, "url": "", "estado": ""})
        current_title = ""
        pending_urls = []

    for raw in body.splitlines():
        line = raw.strip()
        if not line:
            flush()
            continue
        url = is_url_line(line)
        if url:
            pending_urls.append(url)
            continue
        # New title: flush previous
        if pending_urls or current_title:
            flush()
        current_title = line.rstrip(":")
    flush()
    return entries


def split_tema_note(text: str) -> tuple[str, str, str]:
    """
    Returns (prefix_before_manual_sources, manual_body, suffix_after).
    Manual sources = content after dataview block, or after ## Noticias if no dataview.
    Prefers a ## Fuentes manuales section if present.
    """
    # Explicit section
    m_fuentes = re.search(
        r"(?m)^##\s+Fuentes manuales\s*$", text
    )
    if m_fuentes:
        prefix = text[: m_fuentes.start()]
        rest = text[m_fuentes.end() :]
        m_next = re.search(r"(?m)^##\s+", rest)
        if m_next:
            return prefix, rest[: m_next.start()], rest[m_next.start() :]
        return prefix, rest, ""

    # After dataview fence
    m_dv = re.search(r"```dataview\s*\n.*?```", text, re.S)
    if m_dv:
        prefix = text[: m_dv.end()]
        rest = text[m_dv.end() :]
        return prefix, rest, ""

    # After ## Noticias
    m_not = re.search(r"(?m)^##\s+Noticias\s*$", text)
    if m_not:
        # Keep ## Noticias + anything until first blank-then-content after header area
        # Put dataview-less noticias header in prefix, body after
        after = text[m_not.end() :]
        return text[: m_not.end()], after, ""

    return text, "", ""


def render_table(rows: list[dict[str, str]]) -> str:
    lines = [
        "## Fuentes manuales",
        "",
        "| Título | Link | Estado |",
        "| --- | --- | --- |",
    ]
    for r in rows:
        titulo = escape_cell(r.get("titulo", ""))
        url = (r.get("url") or "").strip()
        estado = escape_cell(r.get("estado", ""))
        link = md_link(url) if url else ""
        lines.append(f"| {titulo} | {link} | {estado} |")
    lines.append("")
    return "\n".join(lines)


def fix_dataview_path(text: str) -> str:
    return text.replace('FROM "30_News/Noticias"', 'FROM "40_News/Noticias"')


def _split_md_row(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def update_estados_inplace(
    text: str, url_directo: dict[str, str]
) -> tuple[str, int, int]:
    """
    Actualiza solo la columna Estado en filas de tabla, sin reescribir títulos.
    Evita romper tablas reformateadas por Obsidian Advanced Tables.
    """
    updated = 0
    already = 0
    out_lines: list[str] = []

    for line in text.splitlines():
        raw = line
        s = line.strip()
        if not s.startswith("|") or TABLE_SEP_RE.match(s) or re.fullmatch(
            r"\|[\s\-:|\\]+\|", s
        ):
            out_lines.append(raw)
            continue

        cells = _split_md_row(s)
        if not cells:
            out_lines.append(raw)
            continue
        first_l = re.sub(r"\s+", " ", cells[0]).strip().lower()
        if first_l in {"título", "titulo", "title"}:
            out_lines.append(raw)
            continue

        url = ""
        for cell in cells:
            m = MD_LINK_RE.search(cell)
            if m:
                url = m.group(2).strip()
                break
            m2 = URL_RE.search(cell)
            if m2 and ("http://" in cell or "https://" in cell):
                url = m2.group(0).rstrip(".,;")
                break

        if not url:
            out_lines.append(raw)
            continue

        key = normalize_url(url)
        label = url_directo.get(key)
        if not label:
            out_lines.append(raw)
            continue

        # Ensure at least 3 columns: Título | Link | Estado
        while len(cells) < 3:
            cells.append("")

        current = cells[-1].strip()
        if current == label:
            already += 1
            out_lines.append(raw)
            continue

        cells[-1] = label
        updated += 1
        out_lines.append("| " + " | ".join(cells) + " |")

    return "\n".join(out_lines) + ("\n" if text.endswith("\n") else ""), updated, already


def process_tema_file(
    path: Path,
    url_directo: dict[str, str],
    dry_run: bool,
) -> tuple[int, int]:
    """
    Returns (updated, already_ok).
    """
    original = path.read_text(encoding="utf-8")
    text = fix_dataview_path(original)

    has_table = (
        "| Título |" in text
        or "| Titulo |" in text
        or "| Title |" in text
        or re.search(r"(?m)^\|\s*Título\s*\|", text) is not None
    )

    # Tabla ya existente: solo tocar Estado (seguro con Obsidian)
    if has_table and "## Fuentes manuales" in text:
        new_body, updated, already = update_estados_inplace(text, url_directo)
        row_count = len(re.findall(r"(?m)^\|", text))
    else:
        prefix, manual, suffix = split_tema_note(text)
        if has_table:
            rows = parse_table_rows(manual.splitlines())
            # Abort rewrite if parse looks corrupted (Obsidian padding mishap)
            bad = sum(
                1
                for r in rows
                if _looks_like_sep_cell(r.get("titulo", ""))
                or str(r.get("titulo", "")).startswith("|")
            )
            if rows and bad >= max(1, len(rows) // 2):
                logger.error(
                    "%s — tabla corrupta o ilegible (%s/%s); no se reescribe. "
                    "Revisa el archivo manualmente.",
                    path.name,
                    bad,
                    len(rows),
                )
                return 0, 0
        else:
            rows = parse_legacy_entries(manual)

        updated = 0
        already = 0
        for row in rows:
            url = (row.get("url") or "").strip()
            estado = (row.get("estado") or "").strip()
            if not url:
                continue
            key = normalize_url(url)
            label = url_directo.get(key)
            if not label:
                continue
            if estado == label:
                already += 1
            else:
                row["estado"] = label
                updated += 1

        new_manual = (
            "\n\n" + render_table(rows)
            if rows
            else ("\n" if not manual.strip() else "\n\n")
        )
        if not rows and not manual.strip():
            new_body = fix_dataview_path(prefix.rstrip() + "\n") + (
                ("\n" + suffix.lstrip()) if suffix else "\n"
            )
        else:
            new_body = (
                fix_dataview_path(prefix.rstrip())
                + "\n"
                + new_manual
                + (suffix if suffix else "")
            )
            if not new_body.endswith("\n"):
                new_body += "\n"
        row_count = len(rows)

    if new_body != original:
        if dry_run:
            logger.info(
                "[dry-run] %s — actualizaría %s, ya ok %s, filas~%s",
                path.name,
                updated,
                already,
                row_count,
            )
        else:
            path.write_text(new_body, encoding="utf-8")
            logger.info(
                "%s — actualizados %s, ya ok %s, filas~%s",
                path.name,
                updated,
                already,
                row_count,
            )
    else:
        logger.info("%s — sin cambios (filas~%s)", path.name, row_count)

    return updated, already


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Marca el directo de origen en Temas según fuentes_directos_pasados.md"
    )
    parser.add_argument(
        "--vault",
        default=os.getenv("OBSIDIAN_VAULT_PATH", ""),
        help="Ruta al vault Obsidian (OBSIDIAN_VAULT_PATH)",
    )
    parser.add_argument(
        "--temas-dir",
        default="",
        help="Carpeta Temas (default: 40_News/Temas)",
    )
    parser.add_argument(
        "--fuentes",
        default="",
        help="Nota Fuentes de Directos pasados",
    )
    parser.add_argument("--dry-run", action="store_true")
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

    temas_dir = (
        Path(args.temas_dir).expanduser().resolve()
        if args.temas_dir
        else vault / DEFAULT_TEMAS_REL
    )
    fuentes_path = (
        Path(args.fuentes).expanduser().resolve()
        if args.fuentes
        else vault / DEFAULT_FUENTES_REL
    )

    if not temas_dir.is_dir():
        logger.error("No existe carpeta Temas: %s", temas_dir)
        return 1
    if not fuentes_path.is_file():
        logger.error("No existe Fuentes: %s", fuentes_path)
        return 1

    fuentes_text = fuentes_path.read_text(encoding="utf-8")
    url_directo = extract_url_directo_map(fuentes_text)
    logger.info("URLs en Fuentes (normalizadas): %s", len(url_directo))
    labels: set[str] = set()
    for v in url_directo.values():
        for part in v.split(", "):
            if part.strip():
                labels.add(part.strip())
    logger.info(
        "Directos detectados: %s",
        ", ".join(sorted(labels)) if labels else "(ninguno)",
    )

    total_updated = 0
    total_already = 0
    for path in sorted(temas_dir.glob("*.md")):
        n, a = process_tema_file(path, url_directo, args.dry_run)
        total_updated += n
        total_already += a

    logger.info(
        "Listo. Actualizados: %s | Ya ok: %s%s",
        total_updated,
        total_already,
        " (dry-run)" if args.dry_run else "",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
