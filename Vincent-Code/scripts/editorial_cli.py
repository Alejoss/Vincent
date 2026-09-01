"""
Motor editorial — outline, ensayo canónico y posts por canal.

  python scripts/editorial_cli.py outline --editorial seminario-cypherpunk-2026
  python scripts/editorial_cli.py essay --editorial seminario-cypherpunk-2026
  python scripts/editorial_cli.py channels --editorial seminario-cypherpunk-2026 --only newsletter,youtube
  python scripts/editorial_cli.py all --editorial seminario-cypherpunk-2026
  python scripts/editorial_cli.py show --editorial seminario-cypherpunk-2026 --channel youtube
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPTS_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / ".env", override=True)

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from src.campaigns.editorial import CHANNEL_FILES, SOCIAL_CHANNELS, get_campaign, list_post_files
from src.editorial.loaders import _strip_frontmatter, read_campaign_doc
from src.editorial.paths import ALL_CHANNELS
from src.editorial.pipeline import generate_all, generate_channels, generate_essay, generate_outline
from src.llm_client import build_editorial_llm_config


def _add_campaign_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--editorial", required=True, help="Slug de campaña")


def _print_results(results) -> int:
    for r in results:
        if r.skipped:
            print(f"  omitido (ya existe): {r.path}")
        else:
            print(f"  generado: {r.path}")
    return 0


def cmd_outline(args: argparse.Namespace) -> int:
    cfg = build_editorial_llm_config()
    print(f"Modelo editorial: {cfg.label}")
    result = generate_outline(args.editorial, config=cfg, force=args.force)
    return _print_results([result])


def cmd_essay(args: argparse.Namespace) -> int:
    cfg = build_editorial_llm_config()
    print(f"Modelo editorial: {cfg.label}")
    result = generate_essay(args.editorial, config=cfg, force=args.force)
    return _print_results([result])


def cmd_channels(args: argparse.Namespace) -> int:
    cfg = build_editorial_llm_config()
    print(f"Modelo editorial: {cfg.label}")
    channels = None
    if args.only:
        channels = tuple(c.strip() for c in args.only.split(",") if c.strip())
    results = generate_channels(args.editorial, channels=channels, config=cfg, force=args.force)
    return _print_results(results)


def cmd_all(args: argparse.Namespace) -> int:
    cfg = build_editorial_llm_config()
    print(f"Modelo editorial: {cfg.label}")
    channels = None
    if args.only:
        channels = tuple(c.strip() for c in args.only.split(",") if c.strip())
    results = generate_all(args.editorial, channels=channels, config=cfg, force=args.force)
    return _print_results(results)


def cmd_show(args: argparse.Namespace) -> int:
    camp = get_campaign(args.editorial)
    channel = args.channel.lower()
    if channel == "outline":
        path = camp.outline_path
    elif channel == "essay":
        path = camp.essay_path
    elif channel == "newsletter":
        from src.campaigns.editorial import list_newsletter_files

        files = list_newsletter_files(camp)
        if not files:
            print(f"No hay newsletters en {camp.newsletters_dir}", file=sys.stderr)
            return 1
        path = files[0]
    else:
        files = list_post_files(camp, channel)
        if not files:
            print(f"No hay posts de {channel} en {camp.posts_dir}", file=sys.stderr)
            return 1
        path = files[-1]
    if not path.is_file():
        print(f"No existe: {path}", file=sys.stderr)
        return 1
    text = read_campaign_doc(camp, path.name) or path.read_text(encoding="utf-8")
    print(_strip_frontmatter(text))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Motor editorial Academia Blockchain")
    sub = parser.add_subparsers(dest="command", required=True)

    for name, func in [
        ("outline", cmd_outline),
        ("essay", cmd_essay),
        ("channels", cmd_channels),
        ("all", cmd_all),
    ]:
        p = sub.add_parser(name)
        _add_campaign_arg(p)
        p.add_argument("--force", action="store_true", help="Sobrescribir archivos existentes")
        if name in ("channels", "all"):
            p.add_argument(
                "--only",
                help=f"Canales separados por coma (default: {','.join(ALL_CHANNELS)})",
            )
        p.set_defaults(func=func)

    p_show = sub.add_parser("show", help="Mostrar contenido generado")
    _add_campaign_arg(p_show)
    p_show.add_argument(
        "--channel",
        required=True,
        choices=["outline", "essay", "newsletter", *SOCIAL_CHANNELS],
    )
    p_show.set_defaults(func=cmd_show)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
