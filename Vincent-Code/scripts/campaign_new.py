"""
Create a new editorial campaign folder from templates.

  python scripts/campaign_new.py --slug mi-campana-2026 --title "Mi Campaña" --year 2026
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from datetime import date
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPTS_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.campaigns.editorial import EDITORIAL_SUBDIR, NEWSLETTERS_SUBDIR, POSTS_SUBDIR, campaigns_root


def _slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-")


def main() -> int:
    parser = argparse.ArgumentParser(description="Crear carpeta de campaña editorial en Obsidian")
    parser.add_argument("--slug", required=True, help="ID único, ej. seminario-cypherpunk-2026")
    parser.add_argument("--title", required=True, help="Título visible")
    parser.add_argument("--year", default=str(date.today().year), help="Año (carpeta)")
    parser.add_argument("--folder-name", help="Nombre de carpeta (default: derivado del título)")
    args = parser.parse_args()

    templates = campaigns_root() / "_templates"
    if not templates.is_dir():
        print(f"Faltan plantillas en {templates}", file=sys.stderr)
        return 1

    folder_name = args.folder_name or _slugify(args.title).replace("-", " ").title().replace(" ", "-")
    dest = campaigns_root() / args.year / folder_name
    if dest.exists():
        print(f"Ya existe: {dest}", file=sys.stderr)
        return 1

    dest.mkdir(parents=True)
    (dest / "assets").mkdir()
    (dest / EDITORIAL_SUBDIR).mkdir()
    (dest / NEWSLETTERS_SUBDIR).mkdir()
    (dest / POSTS_SUBDIR).mkdir()

    campaign_text = (templates / "campaign.md").read_text(encoding="utf-8")
    campaign_text = campaign_text.replace("campaign-slug-2026", args.slug)
    campaign_text = campaign_text.replace("Título de la campaña", args.title)
    campaign_text = campaign_text.replace("created: 2026-01-01", f"created: {date.today().isoformat()}")
    campaign_text = campaign_text.replace(
        "newsletters/01-plantilla.md",
        "newsletters/01-primer-envio.md",
    )
    (dest / "campaign.md").write_text(campaign_text, encoding="utf-8")

    shutil.copy2(templates / NEWSLETTERS_SUBDIR / "01-plantilla.md", dest / NEWSLETTERS_SUBDIR / "01-primer-envio.md")
    if (templates / EDITORIAL_SUBDIR / "outline.md").is_file():
        shutil.copy2(templates / EDITORIAL_SUBDIR / "outline.md", dest / EDITORIAL_SUBDIR / "outline.md")
        shutil.copy2(templates / EDITORIAL_SUBDIR / "essay.md", dest / EDITORIAL_SUBDIR / "essay.md")

    analytics_stub = "# Analytics\n\n| Canal | Métrica | Valor |\n|-------|---------|-------|\n"
    (dest / "analytics.md").write_text(analytics_stub, encoding="utf-8")
    (dest / "lessons_learned.md").write_text("# Lecciones\n\n", encoding="utf-8")

    print(f"Campaña creada: {dest}")
    print("Siguiente: edita campaign.md y archivos en newsletters/ y posts/.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
