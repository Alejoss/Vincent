"""
Construye una tabla: archivo PDF → título/autor extraídos.

Fuentes (en orden de confianza para best_title):
  1. Metadata PDF limpia (Title/Author)
  2. Texto de la página 1 (heurística)
  3. Título parseado del nombre de archivo (Autor - Título.pdf)

Uso:
  python build_pdf_title_table.py
  python build_pdf_title_table.py --limit 50
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import fitz  # PyMuPDF
from pypdf import PdfReader

BAD_TITLE_PATTERNS = [
    re.compile(p, re.I)
    for p in [
        r"^microsoft word",
        r"\.indb$",
        r"^untitled",
        r"^document$",
        r"^pdf$",
        r"^scan",
        r"^image",
        r"^\d+$",
        r"^sk\s*-",
        r"^final$",
        r"^layout",
        r"^export",
    ]
]

BAD_AUTHOR_PATTERNS = [
    re.compile(p, re.I)
    for p in [
        r"^mega\s*pc$",
        r"^user$",
        r"^admin",
        r"^unknown",
        r"^judythommesen$",
        r"^simon\s*ocampo$",  # often publisher dump, not author — keep soft
    ]
]


def strip_accents(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def clean_ws(text: str) -> str:
    text = text.replace("\x00", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def looks_bad_title(title: str) -> bool:
    t = title.strip()
    if not t or len(t) < 3:
        return True
    if len(t) > 250:
        return True
    if any(p.search(t) for p in BAD_TITLE_PATTERNS):
        return True
    # Mostly filename-like garbage
    if t.lower().endswith((".pdf", ".doc", ".docx", ".indd")):
        return True
    return False


def looks_bad_author(author: str) -> bool:
    a = author.strip()
    if not a or len(a) < 2:
        return True
    if len(a) > 120:
        return True
    if any(p.search(a) for p in BAD_AUTHOR_PATTERNS):
        return True
    return False


def parse_filename(stem: str) -> tuple[str, str]:
    """
    Heurística: 'Autor - Título' o 'YYYY. Título (Autor)'.
    Returns (author_guess, title_guess)
    """
    s = stem.strip(" ._")
    s = re.sub(r"^\d{4}\.\s*", "", s)  # leading year.

    # Title (Author) at end
    m = re.match(r"^(?P<title>.+?)\s*\((?P<author>[^()]{3,80})\)\s*$", s)
    if m and " - " not in m.group("author"):
        return m.group("author").strip(), m.group("title").strip(" _.-")

    if " - " in s:
        left, right = s.split(" - ", 1)
        left, right = left.strip(" _.-"), right.strip(" _.-")
        # Prefer short left as author
        if 1 <= len(left.split()) <= 5 and len(right) >= 3:
            return left, right

    return "", s


def extract_meta(path: Path) -> tuple[str, str, str]:
    """Returns title, author, error."""
    try:
        reader = PdfReader(str(path), strict=False)
        meta = reader.metadata
        if not meta:
            return "", "", ""
        title = clean_ws(str(meta.title or ""))
        author = clean_ws(str(meta.author or ""))
        # pypdf sometimes returns literal "None"
        if title.lower() == "none":
            title = ""
        if author.lower() == "none":
            author = ""
        return title, author, ""
    except Exception as e:  # noqa: BLE001
        return "", "", str(e)[:200]


def extract_page1_text(path: Path, max_chars: int = 1200) -> tuple[str, str]:
    try:
        doc = fitz.open(path)
        try:
            if doc.page_count < 1:
                return "", ""
            text = doc[0].get_text("text") or ""
        finally:
            doc.close()
        text = clean_ws(text)
        return text[:max_chars], ""
    except Exception as e:  # noqa: BLE001
        return "", str(e)[:200]


def guess_title_from_page1(text: str) -> str:
    if not text or text.startswith("[ERR]"):
        return ""
    lines = [clean_ws(ln) for ln in text.splitlines()]
    lines = [ln for ln in lines if ln]

    # Drop very short / numeric / footer-ish
    candidates: list[str] = []
    for ln in lines[:25]:
        if len(ln) < 4:
            continue
        if re.fullmatch(r"[\d\W]+", ln):
            continue
        if ln.lower() in {"índice", "indice", "contents", "prólogo", "prologo", "prefacio"}:
            continue
        if len(ln) > 120:
            # maybe a long title; keep first clause
            ln = ln[:120].rstrip()
        candidates.append(ln)

    if not candidates:
        return ""

    # Prefer mid-length lines in the upper third that look like titles
    scored: list[tuple[float, str]] = []
    for i, ln in enumerate(candidates[:12]):
        words = ln.split()
        score = 0.0
        score += max(0, 8 - i)  # earlier is better
        if 2 <= len(words) <= 12:
            score += 5
        if ln.isupper() and 4 <= len(ln) <= 80:
            score += 3
        if ln.istitle():
            score += 2
        if len(ln) < 8:
            score -= 3
        scored.append((score, ln))

    scored.sort(key=lambda x: -x[0])
    best = scored[0][1]

    # Sometimes title is split across 2 lines: ALL CAPS + ALL CAPS
    if len(candidates) >= 2 and candidates[0].isupper() and candidates[1].isupper():
        combo = f"{candidates[0]} {candidates[1]}"
        if len(combo) <= 120:
            return combo
    return best


def choose_best(
    meta_title: str,
    meta_author: str,
    page_title: str,
    file_author: str,
    file_title: str,
) -> tuple[str, str, str]:
    """
    Returns (best_title, best_author, title_source)
    """
    title = ""
    source = ""
    if meta_title and not looks_bad_title(meta_title):
        title, source = meta_title, "meta"
    elif page_title and not looks_bad_title(page_title):
        title, source = page_title, "page1"
    elif file_title:
        title, source = file_title, "filename"

    author = ""
    if meta_author and not looks_bad_author(meta_author):
        author = meta_author
    elif file_author:
        author = file_author

    return title, author, source


def find_faltantes(library: Path) -> Path | None:
    for p in library.iterdir():
        if p.is_dir() and "FALTANTES" in p.name.upper():
            return p
    return None


def iter_pdfs(library: Path, skip: Path | None) -> list[Path]:
    skip_res = skip.resolve() if skip else None
    out: list[Path] = []
    for p in library.rglob("*.pdf"):
        if not p.is_file():
            continue
        if skip_res and skip_res in p.resolve().parents:
            continue
        out.append(p)
    out.sort(key=lambda x: str(x).lower())
    return out


def run(args: argparse.Namespace) -> int:
    library = Path(args.pdfs)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    skip = find_faltantes(library)

    print(f"Library: {library}")
    print("Listing PDFs…")
    pdfs = iter_pdfs(library, skip)
    if args.limit:
        pdfs = pdfs[: args.limit]
    print(f"To process: {len(pdfs)}")

    rows: list[dict] = []
    source_counts: dict[str, int] = {}
    errors = 0

    for i, path in enumerate(pdfs, 1):
        stem = path.stem
        file_author, file_title = parse_filename(stem)
        meta_title, meta_author, meta_err = extract_meta(path)
        page_text, page_err = extract_page1_text(path)
        page_title = guess_title_from_page1(page_text)

        best_title, best_author, title_source = choose_best(
            meta_title, meta_author, page_title, file_author, file_title
        )
        source_counts[title_source or "none"] = source_counts.get(title_source or "none", 0) + 1
        if meta_err or page_err:
            errors += 1

        rel = str(path.relative_to(library)) if path.is_relative_to(library) else str(path)
        rows.append(
            {
                "filename": path.name,
                "rel_path": rel,
                "abs_path": str(path),
                "size_bytes": path.stat().st_size if path.exists() else 0,
                "best_title": best_title,
                "best_author": best_author,
                "title_source": title_source,
                "meta_title": meta_title,
                "meta_author": meta_author,
                "page1_title_guess": page_title,
                "filename_title": file_title,
                "filename_author": file_author,
                "page1_text_preview": page_text[:300].replace("\n", " | "),
                "meta_error": meta_err,
                "page_error": page_err,
            }
        )

        if i % 100 == 0 or i == len(pdfs):
            print(f"  {i}/{len(pdfs)}…")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    csv_path = out_dir / f"pdf_title_table_{stamp}.csv"
    json_path = out_dir / f"pdf_title_table_{stamp}.json"
    latest_csv = out_dir / "pdf_title_table_latest.csv"
    latest_json = out_dir / "pdf_title_table_latest.json"

    fieldnames = list(rows[0].keys()) if rows else []
    with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    payload = {
        "generated_at": stamp,
        "library": str(library),
        "count": len(rows),
        "title_source_counts": source_counts,
        "rows_with_errors": errors,
        "rows": rows,
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    latest_csv.write_bytes(csv_path.read_bytes())
    latest_json.write_text(json_path.read_text(encoding="utf-8"), encoding="utf-8")

    # Compact view: just the link table
    compact = out_dir / "pdf_title_table_compact_latest.csv"
    with compact.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "filename",
                "best_title",
                "best_author",
                "title_source",
                "rel_path",
            ],
        )
        w.writeheader()
        for r in rows:
            w.writerow({k: r[k] for k in w.fieldnames})

    print()
    print(f"PDFs: {len(rows)}")
    print("title_source:", source_counts)
    print(f"rows_with_any_error_flag: {errors}")
    print(f"CSV full:     {csv_path}")
    print(f"CSV compact:  {compact}")
    print(f"JSON:         {json_path}")
    print()
    print("--- sample ---")
    for r in rows[:8]:
        print(f"{r['filename'][:60]}")
        print(f"  -> [{r['title_source']}] {r['best_title'][:80]} | {r['best_author'][:40]}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Tabla archivo PDF ↔ título extraído")
    p.add_argument(
        "--pdfs",
        default=r"D:\Documentos\Acracia\Biblioteca Acracia",
    )
    p.add_argument(
        "--out",
        default=str(Path(__file__).resolve().parent / "output"),
    )
    p.add_argument("--limit", type=int, default=0, help="Solo N PDFs (prueba)")
    return p


if __name__ == "__main__":
    # Quiet pypdf noise a bit
    import logging

    logging.getLogger("pypdf").setLevel(logging.ERROR)
    sys.exit(run(build_parser().parse_args()))
