"""
Fase 0+1: inventariar portadas/PDFs y emparejar por nombre (fuzzy).

Uso:
  python phase1_filename.py
  python phase1_filename.py --covers "D:\\...\\Libros FALTANTES" --pdfs "D:\\...\\Biblioteca Acracia"
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import unicodedata
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from rapidfuzz import fuzz, process

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff"}
PDF_EXT = ".pdf"

# Camera / phone dump names — skip filename matching (need visual/OCR later)
CAMERA_RE = re.compile(
    r"^(IMG|DSC|PXL|PIC|PHOTO|WA|Screenshot|Captura|image|imagen)[-_]?\d",
    re.IGNORECASE,
)
ISBN_RE = re.compile(r"\b(\d{9}[\dXx]|\d{13})\b")

NOISE_TOKENS = {
    "pdf",
    "epub",
    "scan",
    "retail",
    "complete",
    "edition",
    "edicion",
    "edición",
    "vol",
    "volume",
    "tomo",
    "parte",
    "part",
    "the",
    "and",
    "del",
    "de",
    "la",
    "las",
    "los",
    "el",
    "un",
    "una",
    "y",
    "en",
    "a",
    "por",
    "para",
    "con",
    "sin",
}


def strip_accents(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def normalize_name(stem: str) -> str:
    s = strip_accents(stem).lower()
    s = s.replace("&", " and ")
    s = re.sub(r"[\[\]\(\)\{\}]", " ", s)
    s = re.sub(r"[_\-.]+", " ", s)
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def meaningful_tokens(norm: str) -> set[str]:
    return {t for t in norm.split() if len(t) >= 3 and t not in NOISE_TOKENS}


def find_faltantes_dir(library_root: Path) -> Path:
    for p in library_root.iterdir():
        if p.is_dir() and "FALTANTES" in p.name.upper():
            return p
    raise FileNotFoundError(f"No se encontró carpeta *FALTANTES* en {library_root}")


@dataclass
class CoverItem:
    path: str
    name: str
    stem: str
    norm: str
    kind: str  # title | camera | isbn | other


@dataclass
class PdfItem:
    path: str
    name: str
    stem: str
    norm: str


def classify_cover(stem: str) -> str:
    if CAMERA_RE.match(stem):
        return "camera"
    if ISBN_RE.search(stem.replace("-", "")):
        return "isbn"
    if normalize_name(stem):
        return "title"
    return "other"


def inventory_covers(covers_root: Path) -> list[CoverItem]:
    items: list[CoverItem] = []
    for p in covers_root.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in IMAGE_EXTS:
            continue
        stem = p.stem
        items.append(
            CoverItem(
                path=str(p),
                name=p.name,
                stem=stem,
                norm=normalize_name(stem),
                kind=classify_cover(stem),
            )
        )
    items.sort(key=lambda x: x.path.lower())
    return items


def inventory_pdfs(pdfs_root: Path, skip_under: Path | None = None) -> list[PdfItem]:
    items: list[PdfItem] = []
    skip_resolved = skip_under.resolve() if skip_under else None
    for p in pdfs_root.rglob("*.pdf"):
        if not p.is_file():
            continue
        if skip_resolved and skip_resolved in p.resolve().parents:
            continue
        stem = p.stem
        items.append(
            PdfItem(
                path=str(p),
                name=p.name,
                stem=stem,
                norm=normalize_name(stem),
            )
        )
    items.sort(key=lambda x: x.path.lower())
    return items


def best_matches(
    cover: CoverItem,
    pdfs: list[PdfItem],
    pdf_norms: list[str],
    top_n: int = 3,
) -> list[tuple[PdfItem, float, str]]:
    """Return top PDF candidates with score 0-100 and score type."""
    if not cover.norm:
        return []

    # Primary: token_set_ratio over all norms (rapidfuzz is fast enough)
    results = process.extract(
        cover.norm,
        pdf_norms,
        scorer=fuzz.token_set_ratio,
        limit=top_n * 4,
    )

    # Also try partial_ratio on the shortlist to catch subtitle noise
    scored: dict[int, tuple[float, str]] = {}
    for _choice, score, idx in results:
        partial = fuzz.partial_ratio(cover.norm, pdf_norms[idx])
        token_sort = fuzz.token_sort_ratio(cover.norm, pdf_norms[idx])
        best = max(score, partial, token_sort)
        method = "token_set"
        if best == partial and partial > score:
            method = "partial"
        elif best == token_sort and token_sort > score:
            method = "token_sort"
        scored[idx] = (float(best), method)

    # Token overlap boost for shared rare-ish tokens
    cover_tokens = meaningful_tokens(cover.norm)
    for idx, (score, method) in list(scored.items()):
        pdf_tokens = meaningful_tokens(pdf_norms[idx])
        if not cover_tokens or not pdf_tokens:
            continue
        overlap = cover_tokens & pdf_tokens
        if len(overlap) >= 2:
            boost = min(8.0, 2.0 * len(overlap))
            scored[idx] = (min(100.0, score + boost), method + "+overlap")

    ranked = sorted(scored.items(), key=lambda x: x[1][0], reverse=True)[:top_n]
    return [(pdfs[idx], score, method) for idx, (score, method) in ranked]


def decide_status(score: float, auto_threshold: float, review_threshold: float) -> str:
    if score >= auto_threshold:
        return "auto"
    if score >= review_threshold:
        return "review"
    return "no_match"


def run(args: argparse.Namespace) -> int:
    library = Path(args.pdfs)
    covers_root = Path(args.covers) if args.covers else find_faltantes_dir(library)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Covers root: {covers_root}")
    print(f"PDFs root:   {library}")
    print(f"Output:      {out_dir}")
    print("Inventariando portadas…")
    covers = inventory_covers(covers_root)
    print(f"  Portadas: {len(covers)}")
    by_kind: dict[str, int] = {}
    for c in covers:
        by_kind[c.kind] = by_kind.get(c.kind, 0) + 1
    for k, v in sorted(by_kind.items()):
        print(f"    {k}: {v}")

    print("Inventariando PDFs…")
    pdfs = inventory_pdfs(library, skip_under=covers_root)
    print(f"  PDFs: {len(pdfs)}")

    pdf_norms = [p.norm for p in pdfs]

    matches: list[dict] = []
    auto_n = review_n = no_match_n = camera_skip_n = 0

    print("Matching por nombre (fase 1)…")
    for i, cover in enumerate(covers, 1):
        if cover.kind == "camera":
            camera_skip_n += 1
            matches.append(
                {
                    "cover_path": cover.path,
                    "cover_name": cover.name,
                    "cover_kind": cover.kind,
                    "cover_norm": cover.norm,
                    "status": "skip_camera",
                    "score": 0,
                    "method": "none",
                    "pdf_path": "",
                    "pdf_name": "",
                    "candidate_2": "",
                    "score_2": "",
                    "candidate_3": "",
                    "score_3": "",
                }
            )
            continue

        cands = best_matches(cover, pdfs, pdf_norms, top_n=3)
        if not cands:
            status, score, method = "no_match", 0.0, "none"
            best_pdf = None
        else:
            best_pdf, score, method = cands[0]
            status = decide_status(score, args.auto_threshold, args.review_threshold)

        if status == "auto":
            auto_n += 1
        elif status == "review":
            review_n += 1
        else:
            no_match_n += 1

        row = {
            "cover_path": cover.path,
            "cover_name": cover.name,
            "cover_kind": cover.kind,
            "cover_norm": cover.norm,
            "status": status,
            "score": round(score, 1),
            "method": method,
            "pdf_path": best_pdf.path if best_pdf else "",
            "pdf_name": best_pdf.name if best_pdf else "",
            "candidate_2": cands[1][0].name if len(cands) > 1 else "",
            "score_2": round(cands[1][1], 1) if len(cands) > 1 else "",
            "candidate_3": cands[2][0].name if len(cands) > 2 else "",
            "score_3": round(cands[2][1], 1) if len(cands) > 2 else "",
        }
        matches.append(row)

        if i % 50 == 0 or i == len(covers):
            print(f"  {i}/{len(covers)}…")

    # Persist
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    csv_path = out_dir / f"phase1_matches_{stamp}.csv"
    json_path = out_dir / f"phase1_matches_{stamp}.json"
    summary_path = out_dir / f"phase1_summary_{stamp}.txt"
    latest_csv = out_dir / "phase1_matches_latest.csv"
    latest_json = out_dir / "phase1_matches_latest.json"

    fieldnames = list(matches[0].keys()) if matches else []
    with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(matches)

    payload = {
        "generated_at": stamp,
        "covers_root": str(covers_root),
        "pdfs_root": str(library),
        "auto_threshold": args.auto_threshold,
        "review_threshold": args.review_threshold,
        "counts": {
            "covers": len(covers),
            "pdfs": len(pdfs),
            "auto": auto_n,
            "review": review_n,
            "no_match": no_match_n,
            "skip_camera": camera_skip_n,
            "by_kind": by_kind,
        },
        "matches": matches,
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    latest_csv.write_text(csv_path.read_text(encoding="utf-8-sig"), encoding="utf-8-sig")
    latest_json.write_text(json_path.read_text(encoding="utf-8"), encoding="utf-8")

    matchable = len(covers) - camera_skip_n
    summary = f"""Fase 1 — match por nombre
Covers: {len(covers)}  |  PDFs: {len(pdfs)}
  camera (skip): {camera_skip_n}
  matchable:     {matchable}

Resultados (umbrales auto>={args.auto_threshold}, review>={args.review_threshold}):
  AUTO:      {auto_n}  ({100 * auto_n / matchable if matchable else 0:.1f}% de matchable)
  REVIEW:    {review_n}  ({100 * review_n / matchable if matchable else 0:.1f}%)
  NO_MATCH:  {no_match_n}  ({100 * no_match_n / matchable if matchable else 0:.1f}%)

Cobertura total portadas (auto+review / all):
  {(auto_n + review_n)}/{len(covers)} = {100 * (auto_n + review_n) / len(covers) if covers else 0:.1f}%

CSV: {csv_path}
JSON: {json_path}
"""
    summary_path.write_text(summary, encoding="utf-8")
    print()
    print(summary)

    # Show sample autos and reviews
    autos = [m for m in matches if m["status"] == "auto"][:8]
    reviews = [m for m in matches if m["status"] == "review"][:8]
    print("--- Ejemplos AUTO ---")
    for m in autos:
        print(f"  [{m['score']}] {m['cover_name']}")
        print(f"       -> {m['pdf_name']}")
    print("--- Ejemplos REVIEW ---")
    for m in reviews:
        print(f"  [{m['score']}] {m['cover_name']}")
        print(f"       -> {m['pdf_name']}")
        if m["candidate_2"]:
            print(f"       alt: {m['candidate_2']} ({m['score_2']})")

    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Fase 1: match portadas↔PDFs por nombre")
    p.add_argument(
        "--pdfs",
        default=r"D:\Documentos\Acracia\Biblioteca Acracia",
        help="Raíz de la biblioteca (PDFs)",
    )
    p.add_argument(
        "--covers",
        default="",
        help="Carpeta de portadas (default: *FALTANTES* bajo --pdfs)",
    )
    p.add_argument(
        "--out",
        default=str(Path(__file__).resolve().parent / "output"),
        help="Carpeta de salida",
    )
    p.add_argument("--auto-threshold", type=float, default=90.0)
    p.add_argument("--review-threshold", type=float, default=75.0)
    return p


if __name__ == "__main__":
    sys.exit(run(build_parser().parse_args()))
