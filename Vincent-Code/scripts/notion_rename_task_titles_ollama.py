"""
Regenerar títulos de filas en la base de Notion de tareas/ideas usando la misma
lógica que `classify_slack_input_with_ollama.py` (`_resolve_titulo_corto`).

Fuentes de texto por fila:
  1) Rich text Slack Procesado (origen) si existe en la BD
  2) Sin eso → Notas / Notas (extra)
  3) Opcionalmente la nota Obsidian `slack-<ts>.md` si `OBSIDIAN_VAULT_PATH` está configurada

Requiere LLM accesible (mismo comportamiento que el clasificador):
  LLM_PROVIDER=auto|openai|groq|ollama
  OPENAI_API_KEY / GROQ_API_KEY / Ollama local (OLLAMA_URL)

  NOTION_API_TOKEN
  Opcional NOTION_TASKS_DATABASE_ID (default igual que sync)
  Opcional LLM_MODEL, OLLAMA_MODEL, OLLAMA_URL, OBSIDIAN_VAULT_PATH
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from notion_client import Client

load_dotenv(override=True)

SCRIPTS_DIR = os.path.dirname(__file__)
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPTS_DIR, ".."))
sys.path.insert(0, SCRIPTS_DIR)
sys.path.insert(0, PROJECT_ROOT)

import classify_slack_input_with_ollama as clf  # noqa: E402
from src.llm_client import build_llm_config, validate_llm_config  # noqa: E402
from sync_productivity_obsidian_to_notion import (  # noqa: E402
    TASKS_DB_ID,
    TASKS_IDEAS_FOLDER,
    _extract_slack_completo,
    build_prop_map,
    get_ds_and_props,
    normalize_id,
    parse_frontmatter,
)


def _require_env(name: str) -> str:
    v = (os.getenv(name) or "").strip()
    if not v:
        raise SystemExit(f"Missing required env var: {name}")
    return v


def _rich_text_plain(pprops: Dict[str, Any], prop_name: Optional[str]) -> str:
    if not prop_name:
        return ""
    block = (pprops.get(prop_name) or {}).get("rich_text") or []
    parts: List[str] = []
    for seg in block:
        if seg.get("type") == "text":
            parts.append((seg.get("text") or {}).get("content") or "")
    return "".join(parts).strip()


def _title_plain(pprops: Dict[str, Any], title_prop: str) -> str:
    block = (pprops.get(title_prop) or {}).get("title") or []
    parts: List[str] = []
    for seg in block:
        if seg.get("type") == "text":
            parts.append((seg.get("text") or {}).get("content") or "")
    return "".join(parts).strip()


def _select_name(props: Dict[str, Any], prop: Optional[str]) -> str:
    if not prop:
        return ""
    sel = (props.get(prop) or {}).get("select") or {}
    return str(sel.get("name") or "").strip()


def _slack_ts_stem(ts: str) -> str:
    s = (ts or "").strip()
    return re.sub(r"[^\w.-]+", "_", s) or "unknown"


def _slack_plain_from_obsidian(vault_root: Path, slack_ts: str) -> str:
    name = f"slack-{_slack_ts_stem(slack_ts)}.md"
    roots = (
        vault_root / "0_Diario_Productividad" / TASKS_IDEAS_FOLDER,
        vault_root / "0_Diario_Productividad" / "Input",
    )
    for folder in roots:
        p = folder / name
        if p.is_file():
            try:
                raw = p.read_text(encoding="utf-8")
                fm, body = parse_frontmatter(raw)
                return _extract_slack_completo(body) or body.strip()
            except OSError:
                return ""
    return ""


def _gather_slack_plain(
    vault_path: Optional[str],
    slack_ts_val: str,
    pprops: Dict[str, Any],
    pmap: Dict[str, str],
) -> str:
    sp = pmap.get("slack_procesado")
    nt = pmap.get("notas")
    blob = ""
    if sp:
        blob = _rich_text_plain(pprops, sp)
    if not blob and nt:
        blob = _rich_text_plain(pprops, nt)
    if not blob and vault_path:
        vr = Path(vault_path.strip().strip('"').strip("'"))
        if vr.is_dir():
            blob = _slack_plain_from_obsidian(vr, slack_ts_val)
    return blob.strip()


def _query_all_pages(client: Client, database_id: str, ds_id: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    cursor: Optional[str] = None
    while True:
        kw: Dict[str, Any] = {"page_size": 100}
        if cursor:
            kw["start_cursor"] = cursor
        if ds_id == database_id:
            resp = client.databases.query(database_id=database_id, **kw)
        else:
            resp = client.data_sources.query(data_source_id=ds_id, **kw)
        out.extend(resp.get("results") or [])
        if not resp.get("has_more"):
            break
        cursor = resp.get("next_cursor")
    return out


def _allowed_tipo(tipo_val: str, include_aprendizaje: bool) -> bool:
    allowed = {"Tarea", "Idea", "Aprendizaje"} if include_aprendizaje else {"Tarea", "Idea"}
    if not tipo_val:
        return True
    return tipo_val in allowed


def _patch_title_prop(title_prop_name: str, new_title: str) -> Dict[str, Any]:
    if len(new_title) > 2000:
        new_title = new_title[:1997] + "..."
    return {title_prop_name: {"title": [{"type": "text", "text": {"content": new_title}}]}}


def main() -> int:
    parser = argparse.ArgumentParser(description="Renombrar filas Notion usando LLM (misma lógica que classify)")
    parser.add_argument("--dry-run", action="store_true", help="Calcular pero no PATCH en Notion")
    parser.add_argument("--limit", type=int, default=0, help="Máximo de filas a procesar (0 = todas)")
    parser.add_argument("--include-aprendizaje", action="store_true", help="Incluir tipo Aprendizaje")
    parser.add_argument("--sleep-s", type=float, default=0.15, help="Pausa entre requests Notion/update")
    parser.add_argument(
        "--llm-provider",
        choices=("openai", "groq", "ollama", "auto"),
        default=None,
    )
    parser.add_argument("--model", default=None)
    parser.add_argument("--ollama-url", default=os.getenv("OLLAMA_URL", "http://127.0.0.1:11434"))
    parser.add_argument("--timeout", type=int, default=120, help="Timeout por llamada LLM (s)")
    args = parser.parse_args()

    llm = build_llm_config(args.llm_provider, args.model, args.ollama_url)
    try:
        validate_llm_config(llm)
    except ValueError as e:
        raise SystemExit(str(e)) from e

    _require_env("NOTION_API_TOKEN")
    db_raw = os.getenv("NOTION_TASKS_DATABASE_ID", TASKS_DB_ID)
    database_id = normalize_id(db_raw)
    vault = (os.getenv("OBSIDIAN_VAULT_PATH") or "").strip()

    client = Client(auth=os.getenv("NOTION_API_TOKEN"), notion_version="2025-09-03")
    ds_id, props = get_ds_and_props(client, database_id)
    pmap = build_prop_map(props)
    title_prop = pmap["title"]
    tipo_prop = pmap["tipo"]
    slack_prop = pmap["slack_ts"]

    all_pages = _query_all_pages(client, database_id, ds_id)
    pages: List[Dict[str, Any]] = []
    for page in all_pages:
        pprops = page.get("properties") or {}
        tipo_val = _select_name(pprops, tipo_prop)
        if not _allowed_tipo(tipo_val, args.include_aprendizaje):
            continue
        pages.append(page)
    if args.limit > 0:
        pages = pages[: args.limit]

    print(f"DB {database_id} — {len(pages)} fila(s) a procesar (de {len(all_pages)} en la BD). dry_run={args.dry_run}")

    renamed = 0
    skipped_same = 0
    skipped_no_body = 0
    errors = 0

    for idx, page in enumerate(pages):
        pid = page.get("id") or ""
        pprops = page.get("properties") or {}
        current = _title_plain(pprops, title_prop)
        tipo_val = _select_name(pprops, tipo_prop)
        tipo = tipo_val or "Idea"
        slack_ts_val = _rich_text_plain(pprops, slack_prop)
        if not slack_ts_val:
            print(f"[skip] {pid} sin slack_ts")
            errors += 1
            continue

        blob = _gather_slack_plain(vault, slack_ts_val, pprops, pmap)
        if not blob:
            skipped_no_body += 1
            print(f"[skip] {pid} sin texto (Slack procesado/Notas/vault) — título actual: {current!r}")
            continue

        try:
            new_title = clf._resolve_titulo_corto(
                llm,
                blob,
                tipo,
                current,
                args.timeout,
            )
        except Exception as e:
            errors += 1
            print(f"[error] {pid}: {e}")
            continue

        if not new_title or new_title.strip() == current.strip():
            skipped_same += 1
            print(f"[same] {idx + 1}/{len(pages)} {current!r}")
            continue

        if args.dry_run:
            print(f"[dry-run] {idx + 1}/{len(pages)} {current!r} -> {new_title!r}")
            renamed += 1
            continue

        try:
            client.pages.update(page_id=pid, properties=_patch_title_prop(title_prop, new_title))
            print(f"[ok] {idx + 1}/{len(pages)} {current!r} -> {new_title!r}")
            renamed += 1
        except Exception as e:
            errors += 1
            print(f"[error] PATCH {pid}: {e}")
        time.sleep(max(0.0, args.sleep_s))

    print(
        f"Listo. renombradas={renamed} iguales={skipped_same} sin_cuerpo={skipped_no_body} "
        f"errores={errors}"
    )
    return 0 if errors == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
