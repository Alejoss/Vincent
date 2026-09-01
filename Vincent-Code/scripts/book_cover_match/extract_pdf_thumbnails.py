"""
Extrae thumbnail de portada = render de la primera página del PDF.

Salida por defecto (sidecar):
  Libro.pdf  →  Libro.cover.jpg  (junto al PDF)

También puede espejar la estructura bajo --out-dir.

Uso:
  python extract_pdf_thumbnails.py --limit 20
  python extract_pdf_thumbnails.py --mode sidecar
  python extract_pdf_thumbnails.py --mode mirror --out-dir "E:\\Vincent\\pdf_thumbs"
  python extract_pdf_thumbnails.py --resume
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import fitz  # PyMuPDF

OUT_DEFAULT = Path(__file__).resolve().parent / "output"


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


def dest_path(pdf: Path, library: Path, mode: str, out_dir: Path | None) -> Path:
    if mode == "sidecar":
        return pdf.with_suffix(".cover.jpg")
    # mirror
    assert out_dir is not None
    try:
        rel = pdf.relative_to(library)
    except ValueError:
        rel = Path(pdf.name)
    return (out_dir / rel).with_suffix(".jpg")


def render_first_page(
    pdf: Path,
    dest: Path,
    *,
    max_side: int,
    jpeg_quality: int,
) -> tuple[int, int]:
    """Render page 0 → JPEG. Returns (width, height)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(pdf)
    try:
        if doc.page_count < 1:
            raise ValueError("PDF sin páginas")
        page = doc[0]
        # Scale so longest side ~= max_side
        rect = page.rect
        scale = max_side / max(rect.width, rect.height)
        if scale <= 0:
            scale = 1.0
        # Cap absurd upscales for tiny pages; allow modest upscale
        scale = min(scale, 3.0)
        mat = fitz.Matrix(scale, scale)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        # PyMuPDF jpeg via pil or save with jpg
        pix.save(str(dest), jpg_quality=jpeg_quality)
        return pix.width, pix.height
    finally:
        doc.close()


def load_done(checkpoint: Path) -> set[str]:
    if not checkpoint.exists():
        return set()
    data = json.loads(checkpoint.read_text(encoding="utf-8"))
    return {r["pdf"] for r in data.get("rows", []) if r.get("ok")}


def run(args: argparse.Namespace) -> int:
    library = Path(args.pdfs)
    skip = None if args.include_faltantes else find_faltantes(library)
    out_dir = Path(args.out_dir) if args.out_dir else None
    if args.mode == "mirror" and not out_dir:
        raise SystemExit("--mode mirror requiere --out-dir")

    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    checkpoint = report_dir / "pdf_thumbs_checkpoint.json"

    pdfs = iter_pdfs(library, skip)
    if args.limit:
        pdfs = pdfs[: args.limit]

    done = load_done(checkpoint) if args.resume else set()
    print(f"Library: {library}")
    print(f"Mode: {args.mode}  max_side={args.max_side}")
    print(f"PDFs: {len(pdfs)}  resume_skip={len(done)}")

    rows: list[dict] = []
    # keep previous ok rows when resuming
    if args.resume and checkpoint.exists():
        prev = json.loads(checkpoint.read_text(encoding="utf-8"))
        rows.extend(prev.get("rows") or [])

    ok = fail = skip_n = 0
    pending = [p for p in pdfs if str(p) not in done]
    print(f"Pending: {len(pending)}")

    for i, pdf in enumerate(pending, 1):
        dest = dest_path(pdf, library, args.mode, out_dir)
        row = {
            "pdf": str(pdf),
            "thumb": str(dest),
            "ok": False,
            "error": "",
            "width": 0,
            "height": 0,
            "bytes": 0,
        }
        try:
            if dest.exists() and not args.force:
                skip_n += 1
                row["ok"] = True
                row["error"] = "exists"
                row["bytes"] = dest.stat().st_size
                ok += 1
            else:
                w, h = render_first_page(
                    pdf,
                    dest,
                    max_side=args.max_side,
                    jpeg_quality=args.quality,
                )
                row["ok"] = True
                row["width"] = w
                row["height"] = h
                row["bytes"] = dest.stat().st_size
                ok += 1
        except Exception as e:  # noqa: BLE001
            row["error"] = str(e)[:300]
            fail += 1

        rows.append(row)
        if i % 25 == 0 or i == len(pending) or not row["ok"]:
            status = "OK" if row["ok"] else "FAIL"
            print(f"[{i}/{len(pending)}] {status} {pdf.name[:60]}", flush=True)

        if i % 50 == 0 or i == len(pending):
            _save(report_dir, checkpoint, rows, library, args)

    _save(report_dir, checkpoint, rows, library, args)
    print()
    print(f"Done. ok={ok} fail={fail} skipped_existing≈{skip_n}")
    print(f"Report: {report_dir / 'pdf_thumbs_latest.csv'}")
    return 0 if fail == 0 else 1


def _save(report_dir: Path, checkpoint: Path, rows: list[dict], library: Path, args) -> None:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    # dedupe by pdf path keeping last
    by_pdf: dict[str, dict] = {}
    for r in rows:
        by_pdf[r["pdf"]] = r
    deduped = list(by_pdf.values())

    payload = {
        "generated_at": stamp,
        "library": str(library),
        "mode": args.mode,
        "max_side": args.max_side,
        "count": len(deduped),
        "ok": sum(1 for r in deduped if r.get("ok")),
        "rows": deduped,
    }
    checkpoint.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    csv_path = report_dir / "pdf_thumbs_latest.csv"
    with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(
            f,
            fieldnames=["pdf", "thumb", "ok", "width", "height", "bytes", "error"],
        )
        w.writeheader()
        w.writerows(deduped)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Thumbnails = primera página del PDF")
    p.add_argument("--pdfs", default=r"D:\Documentos\Acracia\Biblioteca Acracia")
    p.add_argument(
        "--mode",
        choices=("sidecar", "mirror"),
        default="sidecar",
        help="sidecar: Libro.cover.jpg al lado del PDF | mirror: copia árbol en --out-dir",
    )
    p.add_argument(
        "--out-dir",
        default="",
        help="Obligatorio en mode=mirror (ej. E:\\Vincent\\pdf_thumbs)",
    )
    p.add_argument("--report-dir", default=str(OUT_DEFAULT))
    p.add_argument("--max-side", type=int, default=600, help="Lado máximo en px (thumbnail)")
    p.add_argument("--quality", type=int, default=82)
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--resume", action="store_true")
    p.add_argument("--force", action="store_true", help="Regenerar aunque exista")
    p.add_argument(
        "--include-faltantes",
        action="store_true",
        help="También procesar PDFs bajo Libros FALTANTES (normalmente 0)",
    )
    return p


if __name__ == "__main__":
    sys.exit(run(build_parser().parse_args()))
