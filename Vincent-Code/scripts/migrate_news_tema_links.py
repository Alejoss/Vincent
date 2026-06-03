"""One-off: reemplaza nombres viejos de temas en frontmatter y deduplica lista temas."""
from __future__ import annotations

import sys
from pathlib import Path

# Vincent-Code y Cerebro-Vincent son hermanos bajo el directorio del workspace.
_PROJECT = Path(__file__).resolve().parent.parent
VAULT = _PROJECT.parent / "Cerebro-Vincent" / "30_News" / "Noticias"

REPLACEMENTS: list[tuple[str, str]] = [
    ('[[Inteligencia Artificial]]', "[[Tecnocracia]]"),
    ("[[Cambio climático]]", "[[Control Climático]]"),
    ("[[Geopolítica y conflictos]]", "[[Guerra]]"),
    ("[[Alimentación]]", "[[Alimentos]]"),
    ("[[Salud y farmacéuticas]]", "[[Pandemia]]"),
    ("[[Economía y finanzas]]", "[[Guerra]]"),
    ("[[Elecciones y fraude]]", "[[Guerra]]"),
    ("[[Medios y censura]]", "[[Guerra]]"),
]


def dedupe_temas_in_frontmatter(fm: str) -> str:
    lines = fm.split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.strip() == "temas:":
            out.append(line)
            i += 1
            seen: set[str] = set()
            while i < len(lines) and lines[i].startswith("  - "):
                if lines[i] not in seen:
                    seen.add(lines[i])
                    out.append(lines[i])
                i += 1
            continue
        out.append(line)
        i += 1
    return "\n".join(out)


def process_file(p: Path) -> bool:
    text = p.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return False
    idx = text.find("\n---\n", 4)
    if idx == -1:
        return False
    fm = text[4:idx]
    body = text[idx + 5 :]
    for old, new in REPLACEMENTS:
        fm = fm.replace(old, new)
    fm = dedupe_temas_in_frontmatter(fm)
    new_text = "---\n" + fm + "\n---\n" + body
    if new_text != text:
        p.write_text(new_text, encoding="utf-8")
        return True
    return False


def main() -> int:
    if not VAULT.is_dir():
        print("No existe carpeta:", VAULT, file=sys.stderr)
        return 1
    n = 0
    for p in sorted(VAULT.glob("*.md")):
        if process_file(p):
            n += 1
            print("OK", p.name)
    print("Actualizados:", n)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
