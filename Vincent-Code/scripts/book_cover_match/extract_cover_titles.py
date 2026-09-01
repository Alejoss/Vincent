"""
Extrae título/autor de portadas con OpenAI Vision (gpt-4o-mini).

Requiere OPENAI_API_KEY en Vincent-Code/.env

Uso:
  python extract_cover_titles.py --limit 5          # prueba
  python extract_cover_titles.py                   # todas (~517)
  python extract_cover_titles.py --resume          # continúa checkpoint
"""

from __future__ import annotations

import argparse
import base64
import csv
import io
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from PIL import Image

SCRIPTS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPTS_DIR.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.llm_client import build_llm_config, call_json_vision, validate_llm_config  # noqa: E402

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff"}

PROMPT = """Eres un catalogador de libros. Mira la portada (imagen) y extrae los datos visibles.

Devuelve SOLO un JSON con estas claves:
{
  "title": "título principal del libro (sin subtítulo si es claramente aparte)",
  "subtitle": "subtítulo si aparece, si no cadena vacía",
  "author": "autor o autores como aparecen; si hay varios, sepáralos con '; '",
  "publisher": "editorial si se lee con claridad, si no cadena vacía",
  "language": "código corto: es, en, fr, it, de, pt, tr, nl, other",
  "confidence": 0.0 a 1.0 (qué tan seguro estás de title+author),
  "is_book_cover": true/false,
  "notes": "breve, solo si algo es dudoso o ilegible"
}

Reglas:
- No inventes autor ni título. Si no se lee, usa "" y baja confidence.
- Ignora sellos de librería, precios, marcas de agua, códigos de barras.
- Si es foto sesgada/borrosa, lee lo que puedas y baja confidence.
- title y author en el idioma de la portada (no traduzcas).
"""


def find_faltantes(library: Path) -> Path:
    for p in library.iterdir():
        if p.is_dir() and "FALTANTES" in p.name.upper():
            return p
    raise FileNotFoundError(f"No *FALTANTES* under {library}")


def list_covers(covers_root: Path) -> list[Path]:
    items = [
        p
        for p in covers_root.rglob("*")
        if p.is_file() and p.suffix.lower() in IMAGE_EXTS
    ]
    items.sort(key=lambda p: str(p).lower())
    return items


def image_to_data_url(path: Path, max_side: int = 1280, quality: int = 80) -> str:
    with Image.open(path) as im:
        im = im.convert("RGB")
        w, h = im.size
        scale = min(1.0, max_side / max(w, h))
        if scale < 1.0:
            im = im.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=quality, optimize=True)
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{b64}"


def load_checkpoint(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data.get("rows") or []
    return {r["abs_path"]: r for r in rows if r.get("abs_path") and r.get("ok")}


def write_outputs(out_dir: Path, rows: list[dict], covers_root: Path, model: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    full_csv = out_dir / f"cover_title_table_{stamp}.csv"
    latest_csv = out_dir / "cover_title_table_latest.csv"
    compact = out_dir / "cover_title_table_compact_latest.csv"
    latest_json = out_dir / "cover_title_table_latest.json"
    checkpoint = out_dir / "cover_title_checkpoint.json"

    fieldnames = [
        "filename",
        "rel_path",
        "abs_path",
        "title",
        "subtitle",
        "author",
        "publisher",
        "language",
        "confidence",
        "is_book_cover",
        "notes",
        "ok",
        "error",
        "model",
    ]
    with full_csv.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    latest_csv.write_bytes(full_csv.read_bytes())

    with compact.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(
            f,
            fieldnames=["filename", "title", "author", "subtitle", "confidence", "language", "rel_path"],
        )
        w.writeheader()
        for r in rows:
            if r.get("ok"):
                w.writerow({k: r.get(k, "") for k in w.fieldnames})

    payload = {
        "generated_at": stamp,
        "covers_root": str(covers_root),
        "model": model,
        "count": len(rows),
        "ok_count": sum(1 for r in rows if r.get("ok")),
        "rows": rows,
    }
    latest_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    checkpoint.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def extract_one(path: Path, covers_root: Path, config, max_side: int) -> dict:
    rel = str(path.relative_to(covers_root)) if path.is_relative_to(covers_root) else path.name
    base = {
        "filename": path.name,
        "rel_path": rel,
        "abs_path": str(path),
        "title": "",
        "subtitle": "",
        "author": "",
        "publisher": "",
        "language": "",
        "confidence": 0.0,
        "is_book_cover": False,
        "notes": "",
        "ok": False,
        "error": "",
        "model": config.model,
    }
    try:
        data_url = image_to_data_url(path, max_side=max_side)
        result = call_json_vision(
            prompt=PROMPT,
            image_data_url=data_url,
            config=config,
            timeout_s=120,
        )
        base["title"] = str(result.get("title") or "").strip()
        base["subtitle"] = str(result.get("subtitle") or "").strip()
        base["author"] = str(result.get("author") or "").strip()
        base["publisher"] = str(result.get("publisher") or "").strip()
        base["language"] = str(result.get("language") or "").strip()
        try:
            base["confidence"] = float(result.get("confidence") or 0)
        except (TypeError, ValueError):
            base["confidence"] = 0.0
        base["is_book_cover"] = bool(result.get("is_book_cover", True))
        base["notes"] = str(result.get("notes") or "").strip()
        base["ok"] = True
    except Exception as e:  # noqa: BLE001
        base["error"] = str(e)[:400]
        base["ok"] = False
    return base


def run(args: argparse.Namespace) -> int:
    load_dotenv(PROJECT_ROOT / ".env", override=True)

    library = Path(args.pdfs)
    covers_root = Path(args.covers) if args.covers else find_faltantes(library)
    out_dir = Path(args.out)

    model = (args.model or os.getenv("COVER_VISION_MODEL") or "gpt-4o-mini").strip()
    config = build_llm_config(provider="openai", model=model)
    validate_llm_config(config)

    covers = list_covers(covers_root)
    if args.limit:
        covers = covers[: args.limit]

    done_map: dict[str, dict] = {}
    if args.resume:
        done_map = load_checkpoint(out_dir / "cover_title_checkpoint.json")
        print(f"Resume: {len(done_map)} ya hechos en checkpoint")

    print(f"Covers root: {covers_root}")
    print(f"Model: {config.label}")
    print(f"To process: {len(covers)} (skip already-ok if --resume)")

    rows_by_path: dict[str, dict] = dict(done_map)
    pending = [p for p in covers if str(p) not in done_map]
    print(f"Pending API calls: {len(pending)}")

    ok_n = sum(1 for r in rows_by_path.values() if r.get("ok"))
    fail_n = 0

    for i, path in enumerate(pending, 1):
        row = extract_one(path, covers_root, config, max_side=args.max_side)
        rows_by_path[str(path)] = row
        if row["ok"]:
            ok_n += 1
            print(
                f"[{i}/{len(pending)}] OK c={row['confidence']:.2f} "
                f"| {row['title'][:50]!r} | {row['author'][:40]!r}",
                flush=True,
            )
        else:
            fail_n += 1
            print(
                f"[{i}/{len(pending)}] FAIL {path.name[:50]!r}: {row['error'][:120]}",
                flush=True,
            )

        # Persist often so a crash doesn't lose work
        if i % 5 == 0 or i == len(pending):
            ordered = [rows_by_path[str(p)] for p in covers if str(p) in rows_by_path]
            # also keep any resume extras not in current list
            write_outputs(out_dir, ordered, covers_root, config.model)

        if args.sleep > 0:
            time.sleep(args.sleep)

    ordered = [rows_by_path[str(p)] for p in covers if str(p) in rows_by_path]
    write_outputs(out_dir, ordered, covers_root, config.model)

    print()
    print(f"Done. ok={sum(1 for r in ordered if r.get('ok'))} fail={sum(1 for r in ordered if not r.get('ok'))}")
    print(f"Compact: {out_dir / 'cover_title_table_compact_latest.csv'}")
    print(f"Full:    {out_dir / 'cover_title_table_latest.csv'}")
    return 0 if fail_n == 0 else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Extraer título/autor de portadas con Vision")
    p.add_argument("--pdfs", default=r"D:\Documentos\Acracia\Biblioteca Acracia")
    p.add_argument("--covers", default="", help="Default: *FALTANTES* bajo --pdfs")
    p.add_argument(
        "--out",
        default=str(SCRIPTS_DIR / "output"),
    )
    p.add_argument("--model", default="", help="Default: gpt-4o-mini")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--resume", action="store_true")
    p.add_argument("--max-side", type=int, default=1280)
    p.add_argument("--sleep", type=float, default=0.15, help="Pausa entre llamadas")
    return p


if __name__ == "__main__":
    sys.exit(run(build_parser().parse_args()))
