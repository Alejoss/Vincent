"""
Script para imprimir la estructura de la base de datos de Notion
'Instrucciones Emails diarios desde Vincent'.

Usa el mismo cliente y versión de API que el resto del proyecto.
Requiere NOTION_API_TOKEN en .env (o variable de entorno).

Conexión "Ramdau" en Notion:
  - El token debe ser el de la integración Ramdau ("Copiar token de integración interna").
  - Poner en .env: NOTION_API_TOKEN=ntn_...
  - La página/base debe tener "Ramdau" en Conexiones.
"""

import os
import sys
import json
import logging
import traceback

# Añadir raíz del proyecto al path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
from notion_client import Client

load_dotenv(override=True)

# ID desde la URL de Notion (puede ser página o base de datos)
# https://www.notion.so/Instrucciones-Emails-diarios-desde-Vincent-81b05041de7448fc921aec4ad9ca5900
NOTION_EMAILS_DATABASE_ID = "81b05041de7448fc921aec4ad9ca5900"

# Salida UTF-8 en Windows para evitar UnicodeEncodeError con emojis en Notion
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Logging para debug (solo ASCII para evitar errores en consola)
logging.basicConfig(
    level=logging.DEBUG,
    format="[%(levelname)s] %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger(__name__)


def normalize_id(block_id: str) -> str:
    """Formatear ID de Notion con guiones si viene sin ellos (32 caracteres)."""
    s = block_id.replace("-", "").strip()
    if len(s) == 32:
        return f"{s[0:8]}-{s[8:12]}-{s[12:16]}-{s[16:20]}-{s[20:32]}"
    return block_id


def mask_token(token: str) -> str:
    """Muestra solo inicio y longitud del token para logs (no exponer secreto)."""
    if not token or len(token) < 8:
        return "(vacío o muy corto)"
    return f"{token[:7]}...{token[-4:]} (len={len(token)})"


def rich_text_to_plain(rich_text: list) -> str:
    """Extrae texto plano de un array rich_text de Notion."""
    if not rich_text:
        return ""
    return "".join(
        item.get("plain_text") or item.get("text", {}).get("content", "") or ""
        for item in rich_text
    )


def block_to_markdown(block: dict) -> str:
    """Convierte un bloque de Notion a una o más líneas en Markdown."""
    btype = block.get("type", "")
    content = block.get(btype, {})
    rich = content.get("rich_text", [])
    text = rich_text_to_plain(rich).strip()
    if not text and btype not in ("divider", "table_of_contents"):
        return ""

    if btype == "paragraph":
        return text + "\n"
    if btype == "heading_1":
        return f"# {text}\n\n"
    if btype == "heading_2":
        return f"## {text}\n\n"
    if btype == "heading_3":
        return f"### {text}\n\n"
    if btype == "bulleted_list_item":
        return f"- {text}\n"
    if btype == "numbered_list_item":
        return f"1. {text}\n"
    if btype == "to_do":
        checked = content.get("checked", False)
        box = "[x]" if checked else "[ ]"
        return f"- {box} {text}\n"
    if btype == "code":
        lang = content.get("language", "")
        return f"```{lang}\n{text}\n```\n\n"
    if btype == "quote":
        return f"> {text}\n\n"
    if btype == "callout":
        return f"> {text}\n\n"
    if btype == "divider":
        return "---\n\n"
    if btype == "toggle":
        return f"**{text}**\n\n"
    # Por defecto: tratar como párrafo
    return text + "\n" if text else ""


def fetch_all_blocks(client: Client, block_id: str) -> list:
    """Obtiene todos los bloques hijos (con paginación)."""
    results = []
    start_cursor = None
    while True:
        resp = client.blocks.children.list(
            block_id=block_id, page_size=100, start_cursor=start_cursor
        )
        batch = resp.get("results") or []
        results.extend(batch)
        next_cursor = resp.get("next_cursor")
        if not next_cursor:
            break
        start_cursor = next_cursor
    return results


def page_to_markdown(client: Client, page: dict, block_id: str) -> str:
    """Construye el contenido Markdown de una página Notion (título + bloques)."""
    title = ""
    props = page.get("properties", {})
    if "title" in props:
        title_prop = props["title"]
        if title_prop.get("type") == "title":
            title = rich_text_to_plain(title_prop.get("title", []))
    if not title:
        title = "Instrucciones: Emails diarios (desde Vincent)"

    url = page.get("url", "")
    last_edited = page.get("last_edited_time", "")

    lines = [
        "---",
        f"title: \"{title}\"",
        f"source: {url}",
        f"last_edited: \"{last_edited}\"",
        "---",
        "",
        f"# {title}",
        "",
    ]
    blocks = fetch_all_blocks(client, block_id)
    log.info("Bloques obtenidos: %d", len(blocks))
    for blk in blocks:
        md = block_to_markdown(blk)
        if md:
            lines.append(md)
    return "\n".join(lines).replace("\n\n\n", "\n\n").strip() + "\n"


def main():
    log.debug("Cargando variables de entorno desde .env")
    api_token = os.getenv("NOTION_API_TOKEN")
    if not api_token:
        log.error("NOTION_API_TOKEN no está definido (ni en .env ni en entorno)")
        print("\nPara Ramdau: Notion → Todas las conexiones → Ramdau → ... → Copiar token de integración interna.")
        sys.exit(1)
    log.info("Token cargado: %s", mask_token(api_token))

    raw_id = NOTION_EMAILS_DATABASE_ID.replace("-", "")
    block_id = normalize_id(raw_id)
    log.debug("ID crudo: %s -> ID normalizado: %s", raw_id, block_id)

    log.info("Creando cliente Notion (notion_version=2025-09-03)")
    client = Client(auth=api_token, notion_version="2025-09-03")

    print("\n" + "=" * 60)
    print("Estructura de la base de datos de Notion")
    print("Instrucciones Emails diarios desde Vincent")
    print("=" * 60)

    # [1] Probar como página
    print(f"\n[1] GET pages.retrieve(page_id={block_id})")
    try:
        log.debug("Llamando client.pages.retrieve(page_id=%s)", block_id)
        page = client.pages.retrieve(page_id=block_id)
        obj_type = page.get("object")
        log.info("pages.retrieve OK -> object=%s", obj_type)
        print(f"    OK: El ID es una PÁGINA (object={obj_type}).")
        try:
            log.debug("Llamando client.blocks.children.list(block_id=%s)", block_id)
            children = client.blocks.children.list(block_id=block_id, page_size=50)
            results = children.get("results") or []
            log.debug("blocks.children.list OK -> %d bloques", len(results))
            for blk in results:
                btype = blk.get("type")
                if btype == "child_database":
                    log.info("Encontrada child_database: id=%s", blk.get("id"))
                    print(f"    Base de datos embebida: id={blk.get('id')}")
                    db = client.databases.retrieve(database_id=blk["id"])
                    print("\n--- database.retrieve() (base embebida) ---\n")
                    print(json.dumps(db, indent=2, ensure_ascii=False, default=str))
                    data_sources = db.get("data_sources") or []
                    if data_sources:
                        ds_id = data_sources[0].get("id")
                        if ds_id:
                            ds = client.data_sources.retrieve(data_source_id=ds_id)
                            print("\n--- data_sources.retrieve() ---\n")
                            print(json.dumps(ds, indent=2, ensure_ascii=False, default=str))
                    break
            else:
                # Guardar página en Markdown
                out_dir = os.path.join(os.path.dirname(__file__), "..")
                out_path = os.path.join(out_dir, "plan_inicial_emails_diarios.md")
                try:
                    md_content = page_to_markdown(client, page, block_id)
                    with open(out_path, "w", encoding="utf-8") as f:
                        f.write(md_content)
                    log.info("Guardado: %s", out_path)
                    print(f"    Guardado en: {out_path}")
                except Exception as e_save:
                    log.exception("Error guardando MD: %s", e_save)
                    print(f"    Error al guardar MD: {e_save}")
                print("\n--- page.retrieve() ---\n")
                print(json.dumps(page, indent=2, ensure_ascii=False, default=str))
        except Exception as e2:
            log.exception("blocks.children.list o database falló: %s", e2)
            print(f"    Listar bloques falló: {e2}")
            print("\n--- page.retrieve() ---\n")
            print(json.dumps(page, indent=2, ensure_ascii=False, default=str))
    except Exception as e_page:
        log.debug("pages.retrieve falló: %s", e_page)
        log.debug("Traceback: %s", traceback.format_exc())
        print(f"    pages.retrieve falló: {e_page}")

        # [2] Probar como base de datos
        print(f"\n[2] GET databases.retrieve(database_id={block_id})")
        try:
            log.debug("Llamando client.databases.retrieve(database_id=%s)", block_id)
            db = client.databases.retrieve(database_id=block_id)
            log.info("databases.retrieve OK")
            print("    OK: El ID es una BASE DE DATOS.")
            print("\n--- database.retrieve() ---\n")
            print(json.dumps(db, indent=2, ensure_ascii=False, default=str))
            data_sources = db.get("data_sources") or []
            if data_sources:
                ds_id = data_sources[0].get("id")
                if ds_id:
                    ds = client.data_sources.retrieve(data_source_id=ds_id)
                    print("\n--- data_sources.retrieve() ---\n")
                    print(json.dumps(ds, indent=2, ensure_ascii=False, default=str))
        except Exception as e_db:
            log.exception("databases.retrieve falló: %s", e_db)
            print(f"    Error: {e_db}")
            print("\n--- Traceback completo ---")
            traceback.print_exc()
            print("\n--- Cómo corregir ---")
            print("1. Token: Ramdau -> ... -> 'Copiar token de integracion interna' -> pegar en .env como NOTION_API_TOKEN=...")
            print("2. Página/base: debe tener 'Ramdau' en Conexiones (⋯ → Conexiones → Ramdau).")
            sys.exit(1)

    print("\n" + "=" * 60)
    print("Listo.")
    print("=" * 60)


if __name__ == "__main__":
    main()
