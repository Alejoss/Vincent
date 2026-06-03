"""
OCR de un solo uso: PDF escaneado -> archivo .txt fijo en esta carpeta.
Requisitos (una vez):
  pip install --target e:\\Vincent\\.deps pymupdf easyocr
Ejecutar (PowerShell):
  $env:PYTHONPATH='e:\\Vincent\\.deps'
  $env:PYTHONUTF8='1'
  python ocr_maciejko_pdf_a_texto.py
Evitar suspensión: Configuración de Windows -> Energía -> no suspender al enchufado.
"""
from __future__ import annotations

import os
import sys
import time

# EasyOCR imprime barras de progreso con Unicode; cp1252 de la consola rompe la descarga de modelos.
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

# Paquetes instalados con --target (evita rutas largas del site-packages del Store)
_DEPS = r"e:\Vincent\.deps"
if os.path.isdir(_DEPS) and _DEPS not in sys.path:
    sys.path.insert(0, _DEPS)

PDF_PATH = r"f:\Documentos\The_Rabbi_and_the_Jesuit_On_Rabbi_Jonath.pdf"
OUT_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "The_Rabbi_and_the_Jesuit - OCR.txt",
)
# 2.0 = mejor lectura, más lento; 1.5 equilibrio; 1.0 más rápido
ZOOM = 2.0


def main() -> None:
    import fitz  # pymupdf
    import easyocr

    if not os.path.isfile(PDF_PATH):
        raise SystemExit(f"No existe el PDF: {PDF_PATH}")

    t0 = time.perf_counter()
    doc = fitz.open(PDF_PATH)
    reader = easyocr.Reader(["en"], gpu=False)
    chunks: list[str] = []

    for i in range(doc.page_count):
        page = doc[i]
        pix = page.get_pixmap(matrix=fitz.Matrix(ZOOM, ZOOM))
        tmp = os.path.join(os.environ.get("TEMP", "."), f"_ocr_maciejko_p{i + 1}.png")
        pix.save(tmp)
        lines = reader.readtext(tmp, detail=0, paragraph=True)
        text = "\n".join(lines) if lines else ""
        chunks.append(f"--- PAGE {i + 1} ---\n{text}\n")
        try:
            os.remove(tmp)
        except OSError:
            pass
        elapsed = time.perf_counter() - t0
        print(f"Página {i + 1}/{doc.page_count} OK ({elapsed:.0f}s transcurridos)", flush=True)

    doc.close()
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(chunks))

    total = time.perf_counter() - t0
    n = sum(len(c) for c in chunks)
    print(f"Listo: {OUT_PATH}", flush=True)
    print(f"Caracteres (aprox.): {n}, tiempo total: {total / 60:.1f} min", flush=True)


if __name__ == "__main__":
    main()
