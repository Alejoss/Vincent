"""
Copia pares portada+PDF candidatos a una carpeta de revisión en Vincent.

Uso:
  python export_review_folder.py
  python export_review_folder.py --statuses auto review
"""

from __future__ import annotations

import argparse
import csv
import re
import shutil
import sys
from pathlib import Path


INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_name(text: str, max_len: int = 60) -> str:
    s = INVALID.sub("_", text)
    s = re.sub(r"\s+", " ", s).strip(" .")
    # Windows forbids trailing dots/spaces even after truncation
    if len(s) > max_len:
        root, dot, ext = s.rpartition(".")
        if dot and len(ext) <= 8 and root:
            s = root[: max_len - len(ext) - 1].rstrip(" .") + "." + ext
        else:
            s = s[:max_len].rstrip(" .")
    return s.rstrip(" .") or "unnamed"


def run(args: argparse.Namespace) -> int:
    csv_path = Path(args.csv)
    out_root = Path(args.out)
    statuses = set(args.statuses)

    rows = list(csv.DictReader(csv_path.open(encoding="utf-8-sig")))
    selected = [
        r
        for r in rows
        if r.get("status") in statuses and r.get("pdf_path") and r.get("cover_path")
    ]
    # Sort: auto first, then score desc
    selected.sort(
        key=lambda r: (0 if r["status"] == "auto" else 1, -float(r.get("score") or 0))
    )

    if out_root.exists() and args.clean:
        print(f"Limpiando {out_root}…")
        shutil.rmtree(out_root)

    out_root.mkdir(parents=True, exist_ok=True)
    index_rows: list[dict] = []

    copied = 0
    errors = 0
    for i, r in enumerate(selected, 1):
        status = r["status"]
        score = r.get("score") or "0"
        cover_src = Path(r["cover_path"])
        pdf_src = Path(r["pdf_path"])

        # Keep folder names short/safe; full titles live in 00_INFO.txt
        folder_name = f"{i:03d}_s{safe_name(str(score), 6)}_{safe_name(cover_src.stem, 40)}"
        dest_dir = out_root / status / folder_name
        dest_dir.mkdir(parents=True, exist_ok=True)

        cover_dst = dest_dir / f"01_COVER__{safe_name(cover_src.name)}"
        pdf_dst = dest_dir / f"02_PDF__{safe_name(pdf_src.name)}"

        # Optional alts as text only (no copy of alt PDFs — keeps size down)
        alts = []
        if r.get("candidate_2"):
            alts.append(f"2) [{r.get('score_2')}] {r['candidate_2']}")
        if r.get("candidate_3"):
            alts.append(f"3) [{r.get('score_3')}] {r['candidate_3']}")

        note = dest_dir / "00_INFO.txt"
        note.write_text(
            "\n".join(
                [
                    f"status: {status}",
                    f"score: {score}",
                    f"method: {r.get('method', '')}",
                    f"cover_src: {cover_src}",
                    f"pdf_src: {pdf_src}",
                    "",
                    "¿Es el PDF correcto para esta portada?",
                    "  - Si SÍ: deja la carpeta (o renómbrala a OK_...)",
                    "  - Si NO: renombra la carpeta a NO_... o bórrala",
                    "",
                    "Alternativas del matcher:",
                    *(alts or ["(ninguna)"]),
                ]
            ),
            encoding="utf-8",
        )

        try:
            if not cover_src.exists():
                raise FileNotFoundError(f"cover missing: {cover_src}")
            if not pdf_src.exists():
                raise FileNotFoundError(f"pdf missing: {pdf_src}")
            shutil.copy2(cover_src, cover_dst)
            shutil.copy2(pdf_src, pdf_dst)
            copied += 1
            ok = True
            err = ""
        except Exception as e:  # noqa: BLE001 — collect and continue
            errors += 1
            ok = False
            err = str(e)
            print(f"ERROR {i}: {e}")

        index_rows.append(
            {
                "n": i,
                "status": status,
                "score": score,
                "folder": str(dest_dir.relative_to(out_root)),
                "cover_name": cover_src.name,
                "pdf_name": pdf_src.name,
                "cover_src": str(cover_src),
                "pdf_src": str(pdf_src),
                "copied_ok": ok,
                "error": err,
                "your_verdict": "",  # fill: OK / NO / OTHER
            }
        )

        if i % 25 == 0 or i == len(selected):
            print(f"  {i}/{len(selected)}…")

    index_path = out_root / "index.csv"
    with index_path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(index_rows[0].keys()) if index_rows else [])
        if index_rows:
            w.writeheader()
            w.writerows(index_rows)

    readme = out_root / "README.txt"
    readme.write_text(
        f"""Revisión visual Fase 1 — portada vs PDF propuesto

Cómo usar:
1. Abre las subcarpetas auto\\ y review\\
2. En cada carpeta numerada verás:
   - 01_COVER__...  (la portada)
   - 02_PDF__...    (el PDF candidato — ábrelo para confirmar)
   - 00_INFO.txt    (score, rutas originales, alternativas)
3. Marca tu veredicto:
   - Renombra carpeta a OK_001__... o NO_001__...
   - O rellena la columna your_verdict en index.csv (OK / NO)

Pares exportados: {copied}  |  errores: {errors}
Fuente: {csv_path}
""",
        encoding="utf-8",
    )

    print()
    print(f"Listo: {out_root}")
    print(f"  copiados: {copied}")
    print(f"  errores:  {errors}")
    print(f"  index:    {index_path}")
    return 0 if errors == 0 else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--csv",
        default=str(
            Path(__file__).resolve().parent / "output" / "phase1_matches_latest.csv"
        ),
    )
    p.add_argument(
        "--out",
        default=r"E:\Vincent\book_cover_review_phase1",
    )
    p.add_argument(
        "--statuses",
        nargs="+",
        default=["auto", "review"],
        help="Estados a exportar (default: auto review)",
    )
    p.add_argument(
        "--clean",
        action="store_true",
        help="Borrar carpeta de salida antes de copiar",
    )
    return p


if __name__ == "__main__":
    sys.exit(run(build_parser().parse_args()))
