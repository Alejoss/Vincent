"""
Normalize Notion productivity databases schema and values.

Targets:
  - Tasks DB
  - Learnings DB

What it does:
  1) Ensures canonical properties exist:
     - tipo (select): Tarea | Idea | Aprendizaje
     - proyecto (select): 4 local project buckets
  2) Normalizes existing pages to canonical values (best-effort mapping).
  3) Avoids duplicate processing by updating only when a value changes.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv
from notion_client import Client

load_dotenv(override=True)

TASKS_DB_ID = "20d793a25b644663bca9641d927171ca"
LEARNINGS_DB_ID = "8e62295d7d514e17a8f3ea39706692b7"

TYPE_OPTIONS = ["Tarea", "Idea", "Aprendizaje"]
PROJECT_OPTIONS = [
    "Creacion de Contenido",
    "Desarrollo de Software para Academia Blockchain",
    "Desarrollo de Software para Vincent",
    "General - Otros",
]


def normalize_id(block_id: str) -> str:
    s = (block_id or "").replace("-", "").strip()
    if len(s) == 32:
        return f"{s[0:8]}-{s[8:12]}-{s[12:16]}-{s[16:20]}-{s[20:32]}"
    return block_id or ""


def _norm(s: str) -> str:
    return (s or "").strip().lower()


def normalize_type(raw: str, default_value: str) -> str:
    v = _norm(raw)
    if not v:
        return default_value
    if v in {"tarea", "task", "to-do", "todo", "accion", "acción"}:
        return "Tarea"
    if v in {"idea", "ideas"}:
        return "Idea"
    if v in {"aprendizaje", "learning", "aprendizajes", "leccion", "lección"}:
        return "Aprendizaje"
    return default_value


def normalize_project(raw: str) -> str:
    v = _norm(raw)
    if not v:
        return "General - Otros"
    if "contenido" in v:
        return "Creacion de Contenido"
    if "academia" in v or "blockchain" in v:
        return "Desarrollo de Software para Academia Blockchain"
    if "vincent" in v:
        return "Desarrollo de Software para Vincent"
    if "general" in v or "otro" in v:
        return "General - Otros"
    return "General - Otros"


@dataclass
class DbContext:
    db_id: str
    name: str
    default_type: str


def _get_data_source_id(client: Client, database_id: str) -> str:
    db = client.databases.retrieve(database_id=database_id)
    data_sources = db.get("data_sources", []) or []
    if data_sources:
        return data_sources[0]["id"]
    return database_id


def _get_properties(client: Client, database_id: str, data_source_id: str) -> Dict[str, Any]:
    if data_source_id == database_id:
        db = client.databases.retrieve(database_id=database_id)
        return db.get("properties", {}) or {}
    ds = client.data_sources.retrieve(data_source_id=data_source_id)
    return ds.get("properties", {}) or {}


def _find_property_name(
    properties: Dict[str, Any],
    preferred_names: List[str],
    allowed_types: List[str],
) -> Optional[str]:
    preferred_norm = [_norm(x) for x in preferred_names]

    for name, spec in properties.items():
        t = (spec or {}).get("type")
        if t not in allowed_types:
            continue
        n = _norm(name)
        if n in preferred_norm:
            return name
        # Accept close names like "tipo de entrada", "entry type", "project name".
        for candidate in preferred_norm:
            if candidate and candidate in n:
                return name
            if candidate and n in candidate:
                return name
        if "tipo" in n and ("tipo" in preferred_norm or "type" in preferred_norm):
            return name
        if "proyecto" in n and ("proyecto" in preferred_norm or "project" in preferred_norm):
            return name
    return None


def _ensure_property(
    client: Client,
    database_id: str,
    data_source_id: str,
    prop_name: str,
    prop_type: str,
    options: List[str],
    dry_run: bool,
) -> None:
    payload = {
        prop_name: {
            "type": prop_type,
            prop_type: {"options": [{"name": n} for n in options]},
        }
    }
    if dry_run:
        print(f"[dry-run] ensure property '{prop_name}' ({prop_type}) options={options}")
        return

    if data_source_id == database_id:
        client.databases.update(database_id=database_id, properties=payload)
    else:
        client.data_sources.update(data_source_id=data_source_id, properties=payload)


def _query_all_pages(client: Client, database_id: str, data_source_id: str) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    cursor: Optional[str] = None
    while True:
        if data_source_id == database_id:
            resp = client.databases.query(database_id=database_id, start_cursor=cursor, page_size=100)
        else:
            resp = client.data_sources.query(data_source_id=data_source_id, start_cursor=cursor, page_size=100)
        batch = resp.get("results", []) or []
        results.extend(batch)
        cursor = resp.get("next_cursor")
        if not cursor:
            break
    return results


def _read_select_value(page_props: Dict[str, Any], prop_name: str) -> str:
    if not prop_name or prop_name not in page_props:
        return ""
    p = page_props.get(prop_name) or {}
    t = p.get("type")
    if t == "select":
        sel = p.get("select") or {}
        return (sel.get("name") or "").strip()
    if t == "multi_select":
        arr = p.get("multi_select") or []
        if arr:
            return (arr[0].get("name") or "").strip()
    return ""


def _update_page_values(
    client: Client,
    page_id: str,
    type_prop: str,
    project_prop: str,
    type_value: str,
    project_value: str,
    type_mode: str,
    project_mode: str,
    dry_run: bool,
) -> None:
    props: Dict[str, Any] = {}
    if type_mode == "select":
        props[type_prop] = {"select": {"name": type_value}}
    else:
        props[type_prop] = {"multi_select": [{"name": type_value}]}

    if project_mode == "select":
        props[project_prop] = {"select": {"name": project_value}}
    else:
        props[project_prop] = {"multi_select": [{"name": project_value}]}

    if dry_run:
        print(f"[dry-run] update page {page_id}: tipo={type_value}, proyecto={project_value}")
        return

    client.pages.update(page_id=page_id, properties=props)


def normalize_database(client: Client, ctx: DbContext, dry_run: bool) -> Tuple[int, int]:
    db_id = normalize_id(ctx.db_id)
    ds_id = _get_data_source_id(client, db_id)
    props = _get_properties(client, db_id, ds_id)

    type_prop = _find_property_name(props, ["tipo", "type"], ["select", "multi_select"])
    project_prop = _find_property_name(props, ["proyecto", "project"], ["select", "multi_select"])

    if not type_prop:
        type_prop = "tipo"
        _ensure_property(client, db_id, ds_id, type_prop, "select", TYPE_OPTIONS, dry_run)
        props = _get_properties(client, db_id, ds_id)
    else:
        type_mode = (props.get(type_prop) or {}).get("type")
        _ensure_property(client, db_id, ds_id, type_prop, type_mode, TYPE_OPTIONS, dry_run)
        props = _get_properties(client, db_id, ds_id)

    if not project_prop:
        project_prop = "proyecto"
        _ensure_property(client, db_id, ds_id, project_prop, "select", PROJECT_OPTIONS, dry_run)
        props = _get_properties(client, db_id, ds_id)
    else:
        project_mode = (props.get(project_prop) or {}).get("type")
        _ensure_property(client, db_id, ds_id, project_prop, project_mode, PROJECT_OPTIONS, dry_run)
        props = _get_properties(client, db_id, ds_id)

    type_mode = (props.get(type_prop) or {}).get("type") or "select"
    project_mode = (props.get(project_prop) or {}).get("type") or "select"

    pages = _query_all_pages(client, db_id, ds_id)
    changed = 0
    scanned = len(pages)

    for page in pages:
        page_id = page.get("id")
        page_props = page.get("properties", {}) or {}
        current_type = _read_select_value(page_props, type_prop)
        current_project = _read_select_value(page_props, project_prop)

        next_type = normalize_type(current_type, ctx.default_type)
        next_project = normalize_project(current_project)

        if current_type == next_type and current_project == next_project:
            continue

        _update_page_values(
            client=client,
            page_id=page_id,
            type_prop=type_prop,
            project_prop=project_prop,
            type_value=next_type,
            project_value=next_project,
            type_mode=type_mode,
            project_mode=project_mode,
            dry_run=dry_run,
        )
        changed += 1

    return scanned, changed


def main() -> int:
    parser = argparse.ArgumentParser(description="Normalize Notion DB schema/options for productivity flow")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without updating Notion")
    args = parser.parse_args()

    token = os.getenv("NOTION_API_TOKEN")
    if not token:
        raise SystemExit("Missing NOTION_API_TOKEN")

    client = Client(auth=token, notion_version="2025-09-03")
    targets = [
        DbContext(db_id=TASKS_DB_ID, name="Tareas", default_type="Tarea"),
        DbContext(db_id=LEARNINGS_DB_ID, name="Aprendizajes", default_type="Aprendizaje"),
    ]

    total_scanned = 0
    total_changed = 0
    for t in targets:
        print(f"\n== Normalizing {t.name} DB ({t.db_id}) ==")
        scanned, changed = normalize_database(client, t, dry_run=args.dry_run)
        print(f"scanned={scanned} changed={changed}")
        total_scanned += scanned
        total_changed += changed

    print(f"\nDone. scanned={total_scanned} changed={total_changed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

