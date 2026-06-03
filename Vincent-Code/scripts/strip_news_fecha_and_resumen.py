"""Quita `fecha:` del frontmatter y el bloque ## Resumen estándar en 30_News/Noticias."""
from __future__ import annotations

import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PROJECT = _HERE.parent
NOTICIAS = _PROJECT.parent / "Cerebro-Vincent" / "30_News" / "Noticias"

RESUMEN_STD = re.compile(
    r"\n## Resumen\n"
    r"_Título inferido solo desde la URL \(último segmento del path\)\. "
    r"No se descarga el artículo \(p\. ej\. muros tipo Cloudflare\)\._\s*\n",
)
RESUMEN_ANY = re.compile(r"\n## Resumen\n.*?\n+(?=\n## Enlace)", re.DOTALL)


def strip_file(path: Path) -> bool:
    raw = path.read_text(encoding="utf-8")
    text = raw.replace("\r\n", "\n")
    if not text.startswith("---\n"):
        return False
    idx = text.find("\n---\n", 4)
    if idx == -1:
        return False
    fm, body = text[4:idx], text[idx + 5 :]
    fm_lines = [ln for ln in fm.split("\n") if not ln.strip().lower().startswith("fecha:")]
    fm2 = "\n".join(fm_lines)
    body2 = RESUMEN_STD.sub("\n", body, count=1)
    if "## Resumen" in body2 and "## Enlace" in body2:
        body2 = RESUMEN_ANY.sub("\n", body2, count=1)
    out = "---\n" + fm2 + "\n---\n" + body2
    if out != text:
        path.write_text(out, encoding="utf-8")
        return True
    return False


def main() -> int:
    if not NOTICIAS.is_dir():
        print("No existe:", NOTICIAS, file=sys.stderr)
        return 1
    n = 0
    for p in sorted(NOTICIAS.glob("*.md")):
        if strip_file(p):
            n += 1
    print("Notas actualizadas:", n)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
