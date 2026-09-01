"""

Newsletter CLI: preview, test send, campaign send.



Examples:

  python scripts/newsletter_cli.py preview --editorial seminario-cypherpunk-2026

  python scripts/newsletter_cli.py test --editorial seminario-cypherpunk-2026

  python scripts/newsletter_cli.py send --editorial seminario-cypherpunk-2026 --dry-run

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



from src.campaigns.editorial import EditorialCampaign

from src.campaigns.newsletter_bridge import render_overrides_from_campaign, resolve_newsletter_for_editorial

from src.campaigns.registry import record_channel_send, sync_editorial_campaigns

from src.newsletter.config import PREVIEW_DIR, load_config, validate_config

from src.newsletter.send_client import send_campaign, send_test

from src.newsletter.renderer import render_markdown_file, save_preview_html

from src.newsletter.campaign_log import record_campaign_send

from src.newsletter.send_log import append_send_log

from src.newsletter.subscribers import load_segment





def _resolve_md(path_str: str, config) -> Path:

    path = Path(path_str)

    if path.is_file():

        return path.resolve()

    candidate = config.md_dir / path

    if candidate.is_file():

        return candidate.resolve()

    raise FileNotFoundError(f"Archivo markdown no encontrado: {path_str}")





def _resolve_source(

    args: argparse.Namespace,

    config,

) -> tuple[Path, EditorialCampaign | None]:

    if args.editorial:

        return resolve_newsletter_for_editorial(args.editorial)

    if not args.md:

        raise ValueError("Indica --editorial <slug> o --md <archivo>")

    return _resolve_md(args.md, config), None





def _render_from_args(args: argparse.Namespace, md_path: Path, editorial: EditorialCampaign | None):

    overrides: dict[str, str | None] = {

        "subject": args.subject,

        "tag": args.tag,

        "segment": getattr(args, "segment_name", None) or getattr(args, "segment", None),

    }

    if editorial:

        for key, value in render_overrides_from_campaign(editorial).items():

            if overrides.get(key) in (None, ""):

                overrides[key] = value

    return render_markdown_file(md_path, **{k: v for k, v in overrides.items() if v})





def cmd_preview(args: argparse.Namespace) -> int:

    config = load_config()

    md_path, editorial = _resolve_source(args, config)

    rendered = _render_from_args(args, md_path, editorial)

    out = save_preview_html(rendered, PREVIEW_DIR)

    print(f"Asunto: {rendered.subject}")

    print(f"Tag: {rendered.tag}")

    print(f"Segmento: {rendered.segment}")

    if editorial:

        print(f"Campaña editorial: {editorial.slug}")

    print(f"Preview HTML: {out}")

    return 0





def cmd_test(args: argparse.Namespace) -> int:

    config = load_config()

    errors = validate_config(config)

    if errors:

        for err in errors:

            print(f"Error: {err}", file=sys.stderr)

        return 1



    md_path, editorial = _resolve_source(args, config)

    rendered = _render_from_args(args, md_path, editorial)

    to_email = args.to or config.test_email

    result = send_test(config, rendered, to_email)

    append_send_log(rendered, result, send_type="test", to_email=to_email)



    if result.ok:

        print(f"Correo de prueba enviado a {to_email} (tag: {rendered.tag})")

        return 0

    print(f"Error: {result.error}", file=sys.stderr)

    return 1





def cmd_send(args: argparse.Namespace) -> int:

    config = load_config()

    errors = validate_config(config)

    if errors:

        for err in errors:

            print(f"Error: {err}", file=sys.stderr)

        return 1



    md_path, editorial = _resolve_source(args, config)

    rendered = _render_from_args(args, md_path, editorial)

    segment = args.segment_name or rendered.segment

    subscribers = load_segment(segment)



    print(f"Asunto: {rendered.subject}")

    print(f"Tag: {rendered.tag}")

    print(f"Segmento: {segment} ({len(subscribers)} destinatarios)")

    if editorial:

        print(f"Campaña editorial: {editorial.slug}")



    if args.dry_run:

        print("Dry-run: no se envió nada.")

        return 0



    if not args.yes:

        answer = input("¿Enviar newsletter? [y/N]: ").strip().lower()

        if answer not in ("y", "yes", "s", "si", "sí"):

            print("Cancelado.")

            return 0



    sync_editorial_campaigns()

    result = send_campaign(config, rendered, subscribers)

    append_send_log(rendered, result, send_type="campaign", segment=segment)



    editorial_slug = editorial.slug if editorial else None

    send_id = None

    if result.ok:

        send_id = record_campaign_send(

            rendered,

            result,

            subscribers,

            segment=segment,

            editorial_slug=editorial_slug,

        )

        if editorial_slug:

            record_channel_send(

                editorial_slug=editorial_slug,

                channel="newsletter",

                newsletter_send_id=send_id,

                ok=True,

                method=result.method,

                external_id=result.bulk_id,

            )

        print(f"Registro guardado en data/newsletter.db (envío #{send_id})")



    if result.ok:

        print(f"Enviado vía {result.method} a {result.recipient_count} destinatarios.")

        if result.bulk_id:

            print(f"Bulk ID: {result.bulk_id}")

        print(f"Ver estadísticas ({config.provider}) — tag: {rendered.tag}")

        return 0

    print(f"Error: {result.error}", file=sys.stderr)

    return 1





def _add_source_args(parser: argparse.ArgumentParser) -> None:

    group = parser.add_mutually_exclusive_group(required=True)

    group.add_argument("--editorial", help="Slug de campaña editorial (lee newsletter.md)")

    group.add_argument("--md", help="Archivo markdown (legacy)")





def main() -> int:

    parser = argparse.ArgumentParser(description="Newsletter Academia Blockchain (SMTP2GO)")

    sub = parser.add_subparsers(dest="command", required=True)



    p_preview = sub.add_parser("preview", help="Generar HTML de vista previa")

    _add_source_args(p_preview)

    p_preview.add_argument("--subject", help="Override asunto")

    p_preview.add_argument("--tag", help="Override tag (stats / tracking)")

    p_preview.add_argument("--segment", help="Override segmento")

    p_preview.set_defaults(func=cmd_preview)



    p_test = sub.add_parser("test", help="Enviar correo de prueba")

    _add_source_args(p_test)

    p_test.add_argument("--to", help="Email destino (default: NEWSLETTER_TEST_EMAIL)")

    p_test.add_argument("--subject")

    p_test.add_argument("--tag")

    p_test.set_defaults(func=cmd_test)



    p_send = sub.add_parser("send", help="Enviar newsletter a un segmento")

    _add_source_args(p_send)

    p_send.add_argument("--segment", dest="segment_name", help="Override segmento de suscriptores")

    p_send.add_argument("--subject")

    p_send.add_argument("--tag")

    p_send.add_argument("--dry-run", action="store_true")

    p_send.add_argument("--yes", "-y", action="store_true", help="Sin confirmación interactiva")

    p_send.set_defaults(func=cmd_send)



    args = parser.parse_args()

    return args.func(args)





if __name__ == "__main__":

    raise SystemExit(main())


