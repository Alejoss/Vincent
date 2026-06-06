"""
Sync classified Obsidian productivity notes into Notion databases.

Pipeline role
- This is the final transport step in the Slack -> Obsidian -> Notion flow.
- It expects notes already classified by `classify_slack_input_with_ollama.py`.

Routing rules
- `Tarea` / `Idea` -> Tasks DB
- `Aprendizaje` -> Learnings DB

Idempotency / dedup
- `slack_ts` is the stable key.
- If a page with the same `slack_ts` exists, this script updates that page.
- Otherwise, it creates a new page.

Mapped fields (best effort by property name/type)
- Title: `titulo_corto` (fallback to derived first line)
- `tipo`, `proyecto`, `slack_ts`
- Slack full text:
  - preferred: `Slack Procesado (origen)` if rich_text
  - fallback: `Notas` / `Notas (extra)` rich_text
- Dates:
  - `Fecha Slack` (or `message_at` / `Inicio`): calendar date when the Slack message was sent (always set)
  - `fecha_objetivo` / `Fin`: due date only when inferred from text (optional)
- Status default:
  - New `Tarea` rows are created with `Estado = Por hacer` when status prop exists.

Assumptions
- Notion token has access to both target DBs.
- Required schema fields were normalized beforehand (or are mappable by name).
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv
from notion_client import Client

load_dotenv(override=True)

SCRIPTS_DIR = os.path.dirname(__file__)
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPTS_DIR, ".."))
sys.path.insert(0, PROJECT_ROOT)
from src.productivity_dates import anchor_date, clamp_due_iso, infer_due_from_text, safe_date_from_slack_ts

TASKS_DB_ID = "20d793a25b644663bca9641d927171ca"
LEARNINGS_DB_ID = "8e62295d7d514e17a8f3ea39706692b7"

TASKS_IDEAS_FOLDER = "Tareas-Ideas"
LEARNINGS_FOLDER = "Aprendizajes"
DEFAULT_INPUT_REL = os.path.join("0_Diario_Productividad", "Input")
SLACK_BODY_SECTION = "## Contenido completo (Slack)"
NOTION_RICH_TEXT_CHUNK = 2000


def normalize_id(block_id: str) -> str:
    s = (block_id or "").replace("-", "").strip()
    if len(s) == 32:
        return f"{s[0:8]}-{s[8:12]}-{s[12:16]}-{s[16:20]}-{s[20:32]}"
    return block_id or ""


def resolve_tasks_db_id() -> str:
    """NOTION_TASKS_DATABASE_ID env override, or TASKS_DB_ID when unset/empty."""
    return normalize_id((os.getenv("NOTION_TASKS_DATABASE_ID") or "").strip() or TASKS_DB_ID)


def parse_frontmatter(content: str) -> Tuple[Dict[str, str], str]:
    text = content or ""
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end == -1:
        return {}, text
    block = text[4:end]
    body = text[end + 5 :]
    fm: Dict[str, str] = {}
    for line in block.splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        fm[k.strip()] = v.strip().strip('"')
    return fm, body


def _extract_slack_completo(body: str) -> str:
    text = (body or "").strip()
    if SLACK_BODY_SECTION in text:
        return text.split(SLACK_BODY_SECTION, 1)[1].lstrip("\n").strip()
    lines = text.splitlines()
    i = 0
    prefixes = (
        "Tipo de entrada:",
        "Proyecto:",
        "Referencia temporal:",
        "Fecha objetivo:",
        "Titulo:",
        "Recordatorio Slack:",
    )
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue
        if any(line.startswith(p) for p in prefixes):
            i += 1
            continue
        break
    return "\n".join(lines[i:]).strip()


def _rich_text_value(full_text: str) -> Dict[str, Any]:
    t = full_text or ""
    chunks: List[Dict[str, Any]] = []
    for i in range(0, len(t), NOTION_RICH_TEXT_CHUNK):
        part = t[i : i + NOTION_RICH_TEXT_CHUNK]
        chunks.append({"type": "text", "text": {"content": part}})
    if not chunks:
        chunks = [{"type": "text", "text": {"content": ""}}]
    return {"rich_text": chunks}


@dataclass
class NoteItem:
    path: Path
    slack_ts: str
    message_at: str
    source: str
    tipo: str
    proyecto: str
    titulo_corto: str
    referencia_temporal: str
    fecha_objetivo: str
    body: str
    slack_completo: str


def gather_notes(vault_path: str) -> List[NoteItem]:
    diario_root = Path(vault_path) / "0_Diario_Productividad"
    roots = [diario_root / TASKS_IDEAS_FOLDER, diario_root / LEARNINGS_FOLDER]
    out: List[NoteItem] = []
    for root in roots:
        if not root.exists():
            continue
        for path in sorted(root.glob("slack-*.md")):
            raw = path.read_text(encoding="utf-8")
            fm, body = parse_frontmatter(raw)
            slack_ts = (fm.get("slack_ts") or "").strip()
            tipo = (fm.get("tipo") or "").strip()
            if not slack_ts or not tipo:
                continue
            body_stripped = (body or "").strip()
            slack_completo = _extract_slack_completo(body_stripped) or body_stripped
            titulo_corto = (fm.get("titulo_corto") or "").strip()
            out.append(
                NoteItem(
                    path=path,
                    slack_ts=slack_ts,
                    message_at=(fm.get("message_at") or "").strip(),
                    source=(fm.get("source") or "").strip(),
                    tipo=tipo,
                    proyecto=(fm.get("proyecto") or "General - Otros").strip(),
                    titulo_corto=titulo_corto,
                    referencia_temporal=(fm.get("referencia_temporal") or "").strip(),
                    fecha_objetivo=(fm.get("fecha_objetivo") or "").strip(),
                    body=body_stripped,
                    slack_completo=slack_completo,
                )
            )
    return out


def get_ds_and_props(client: Client, database_id: str) -> Tuple[str, Dict[str, Any]]:
    db = client.databases.retrieve(database_id=database_id)
    data_sources = db.get("data_sources", []) or []
    ds_id = data_sources[0]["id"] if data_sources else database_id
    if ds_id == database_id:
        props = db.get("properties", {}) or {}
    else:
        ds = client.data_sources.retrieve(data_source_id=ds_id)
        props = ds.get("properties", {}) or {}
    return ds_id, props


def ensure_property(
    client: Client,
    database_id: str,
    ds_id: str,
    name: str,
    prop_type: str,
    dry_run: bool,
) -> None:
    if prop_type == "rich_text":
        payload = {name: {"type": "rich_text", "rich_text": {}}}
    elif prop_type == "date":
        payload = {name: {"type": "date", "date": {}}}
    elif prop_type == "url":
        payload = {name: {"type": "url", "url": {}}}
    else:
        raise RuntimeError(f"Unsupported ensure property type: {prop_type}")
    if dry_run:
        print(f"[dry-run] ensure property {name} ({prop_type})")
        return
    if ds_id == database_id:
        client.databases.update(database_id=database_id, properties=payload)
    else:
        client.data_sources.update(data_source_id=ds_id, properties=payload)


def pick_prop(
    props: Dict[str, Any],
    candidates: List[str],
    prop_types: List[str],
    *,
    exclude_name_substrings: Optional[List[str]] = None,
) -> Optional[str]:
    """
    Map a Notion property by ordered candidates (first match wins).
    `exclude_name_substrings` avoids confusing e.g. 'Fecha' with 'Fecha objetivo' / 'Fin'.
    """
    cands = [c.lower() for c in candidates]
    exclude = [e.lower() for e in (exclude_name_substrings or [])]
    ranked: List[Tuple[int, int, str]] = []
    for name, spec in props.items():
        t = (spec or {}).get("type")
        if t not in prop_types:
            continue
        n = name.lower()
        if any(e in n for e in exclude):
            continue
        for idx, c in enumerate(cands):
            if n == c:
                ranked.append((idx, 10_000, name))
                break
            if c in n:
                ranked.append((idx, len(c), name))
                break
    if not ranked:
        return None
    ranked.sort(key=lambda x: (x[0], -x[1]))
    return ranked[0][2]


_DUE_DATE_NAME_EXCLUDE = ["objetivo", "fin", "due", "vencim", "deadline", "recordatorio", "slack"]
_SLACK_DATE_NAME_EXCLUDE = ["objetivo", "fin", "due", "vencim", "deadline", "recordatorio"]


def slack_message_date_iso(item: NoteItem) -> str:
    """Calendar date (YYYY-MM-DD) when the Slack message was sent."""
    return anchor_date(item.message_at, item.slack_ts).isoformat()


def find_page_by_slack_ts(
    client: Client,
    database_id: str,
    ds_id: str,
    slack_prop: str,
    slack_ts: str,
) -> Optional[str]:
    flt = {"property": slack_prop, "rich_text": {"equals": slack_ts}}
    if ds_id == database_id:
        resp = client.databases.query(database_id=database_id, filter=flt, page_size=1)
    else:
        resp = client.data_sources.query(data_source_id=ds_id, filter=flt, page_size=1)
    results = resp.get("results", []) or []
    if not results:
        return None
    return results[0].get("id")


def safe_iso_from_slack_ts(ts: str) -> str:
    return safe_date_from_slack_ts(ts).isoformat()


def infer_due_date(item: NoteItem) -> str:
    anchor = anchor_date(item.message_at, item.slack_ts)
    if item.fecha_objetivo:
        fixed = clamp_due_iso(item.fecha_objetivo, anchor)
        if fixed:
            return fixed
    blob = " ".join(
        [
            item.referencia_temporal or "",
            item.slack_completo or "",
            item.body or "",
        ]
    )
    return infer_due_from_text(blob, anchor)


def title_from_body(body: str) -> str:
    for line in (body or "").splitlines():
        t = line.strip()
        if t.startswith("Titulo:"):
            return t.split(":", 1)[1].strip()[:200] or "Entrada Slack"
    for line in (body or "").splitlines():
        t = line.strip()
        if not t:
            continue
        if t.startswith("Tipo de entrada:") or t.startswith("Proyecto:") or t.startswith("Referencia temporal:") or t.startswith("Fecha objetivo:") or t.startswith("Titulo:") or t.startswith("Recordatorio Slack:"):
            continue
        words = t.split()
        return " ".join(words[:14]) if len(words) > 14 else t
    return "Entrada Slack"


def build_props(prop_map: Dict[str, str], item: NoteItem, set_default_status: bool) -> Dict[str, Any]:
    props: Dict[str, Any] = {}
    title_text = (item.titulo_corto or title_from_body(item.body)).strip() or "Entrada Slack"
    if len(title_text) > 2000:
        title_text = title_text[:1997] + "..."
    props[prop_map["title"]] = {"title": [{"text": {"content": title_text}}]}
    props[prop_map["tipo"]] = {"select": {"name": item.tipo}}
    props[prop_map["proyecto"]] = {"select": {"name": item.proyecto}}
    props[prop_map["slack_ts"]] = {"rich_text": [{"type": "text", "text": {"content": item.slack_ts}}]}

    if prop_map.get("source") and item.source:
        if prop_map.get("source_type") == "url":
            props[prop_map["source"]] = {"url": item.source}
        else:
            props[prop_map["source"]] = {"rich_text": [{"type": "text", "text": {"content": item.source}}]}
    slack_date = slack_message_date_iso(item)
    date_cell = {"date": {"start": slack_date}}
    if prop_map.get("slack_fecha"):
        props[prop_map["slack_fecha"]] = date_cell
    if prop_map.get("message_at") and prop_map["message_at"] != prop_map.get("slack_fecha"):
        props[prop_map["message_at"]] = date_cell
    if prop_map.get("inicio") and prop_map["inicio"] not in {
        prop_map.get("slack_fecha"),
        prop_map.get("message_at"),
    }:
        props[prop_map["inicio"]] = date_cell

    due_date = infer_due_date(item)
    if prop_map.get("fecha_objetivo") and due_date:
        if prop_map["fecha_objetivo_type"] == "date":
            props[prop_map["fecha_objetivo"]] = {"date": {"start": due_date}}
        else:
            props[prop_map["fecha_objetivo"]] = {"rich_text": [{"type": "text", "text": {"content": due_date}}]}
    if prop_map.get("fin") and due_date:
        if prop_map["fin_type"] == "date":
            props[prop_map["fin"]] = {"date": {"start": due_date}}
        else:
            props[prop_map["fin"]] = {"rich_text": [{"type": "text", "text": {"content": due_date}}]}
    if prop_map.get("referencia_temporal") and item.referencia_temporal:
        props[prop_map["referencia_temporal"]] = {
            "rich_text": [{"type": "text", "text": {"content": item.referencia_temporal}}]
        }
    if set_default_status and item.tipo == "Tarea" and prop_map.get("estado"):
        default_status = prop_map.get("estado_default") or "Por Hacer"
        props[prop_map["estado"]] = {"status": {"name": default_status}}
    if item.slack_completo:
        if prop_map.get("slack_procesado"):
            props[prop_map["slack_procesado"]] = _rich_text_value(item.slack_completo)
        elif prop_map.get("notas"):
            props[prop_map["notas"]] = _rich_text_value(item.slack_completo)
    return props


def build_prop_map(props: Dict[str, Any]) -> Dict[str, str]:
    title = pick_prop(props, ["name", "titulo", "title", "tarea", "aprendizaje"], ["title"])
    tipo = pick_prop(props, ["tipo", "type"], ["select"])
    proyecto = pick_prop(props, ["proyecto", "project"], ["select"])
    slack_ts = pick_prop(props, ["slack_ts", "slackts", "ts"], ["rich_text"])
    source = pick_prop(props, ["source", "fuente", "url"], ["url", "rich_text"])
    slack_fecha = pick_prop(
        props,
        [
            "fecha slack",
            "fecha mensaje",
            "fecha del mensaje",
            "message_at",
            "inicio",
            "fecha creacion",
            "creado en slack",
            "fecha",
        ],
        ["date"],
        exclude_name_substrings=_SLACK_DATE_NAME_EXCLUDE,
    )
    message_at = pick_prop(
        props,
        ["message_at", "fecha mensaje"],
        ["date"],
        exclude_name_substrings=_DUE_DATE_NAME_EXCLUDE,
    )
    inicio = pick_prop(
        props,
        ["inicio", "start"],
        ["date"],
        exclude_name_substrings=_DUE_DATE_NAME_EXCLUDE,
    )
    fin = pick_prop(
        props,
        ["fin", "fecha fin", "end", "due", "deadline", "vencimiento"],
        ["date", "rich_text"],
        exclude_name_substrings=["slack", "mensaje", "inicio", "creacion"],
    )
    fecha_obj = pick_prop(
        props,
        ["fecha objetivo", "fecha_objetivo"],
        ["date", "rich_text"],
        exclude_name_substrings=["slack", "mensaje", "inicio", "creacion", "fin"],
    )
    ref_temp = pick_prop(props, ["referencia_temporal", "referencia temporal", "timeframe"], ["rich_text"])
    estado = pick_prop(props, ["estado", "status"], ["status"])
    notas = pick_prop(props, ["notas (extra)", "notas", "descripcion", "body"], ["rich_text"])
    slack_procesado = pick_prop(
        props,
        ["slack procesado (origen)", "slack procesado", "slack procesado origen"],
        ["rich_text"],
    )

    if not title or not tipo or not proyecto or not slack_ts:
        raise RuntimeError(
            "Missing required properties in Notion DB. Need title + tipo(select) + proyecto(select) + slack_ts(rich_text)."
        )

    result: Dict[str, str] = {
        "title": title,
        "tipo": tipo,
        "proyecto": proyecto,
        "slack_ts": slack_ts,
    }
    if source:
        result["source"] = source
        result["source_type"] = (props.get(source) or {}).get("type") or "url"
    if slack_fecha:
        result["slack_fecha"] = slack_fecha
    if message_at:
        result["message_at"] = message_at
    if inicio:
        result["inicio"] = inicio
    if fin:
        result["fin"] = fin
        result["fin_type"] = (props.get(fin) or {}).get("type") or "date"
    if fecha_obj:
        result["fecha_objetivo"] = fecha_obj
        result["fecha_objetivo_type"] = (props.get(fecha_obj) or {}).get("type") or "rich_text"
    if ref_temp:
        result["referencia_temporal"] = ref_temp
    if estado:
        result["estado"] = estado
        # Prefer "Por Hacer" exact if available; otherwise case-insensitive match.
        status_opts = (((props.get(estado) or {}).get("status") or {}).get("options") or [])
        names = [str(o.get("name", "")).strip() for o in status_opts]
        chosen = ""
        if "Por Hacer" in names:
            chosen = "Por Hacer"
        else:
            for n in names:
                if n.lower() == "por hacer" or n.lower() == "por hacer".lower():
                    chosen = n
                    break
            if not chosen:
                for n in names:
                    if n.lower() == "por hacer" or n.lower() == "por hacer":
                        chosen = n
                        break
            if not chosen:
                for n in names:
                    if n.lower() in {"por hacer", "todo", "to do"}:
                        chosen = n
                        break
        if chosen:
            result["estado_default"] = chosen
    if notas:
        result["notas"] = notas
    if slack_procesado:
        result["slack_procesado"] = slack_procesado
    return result


def upsert_items(
    client: Client,
    database_id: str,
    items: List[NoteItem],
    dry_run: bool,
) -> Tuple[int, int, int]:
    ds_id, props = get_ds_and_props(client, database_id)
    if not pick_prop(props, ["slack_ts", "slackts", "ts"], ["rich_text"]):
        ensure_property(client, database_id, ds_id, "slack_ts", "rich_text", dry_run)
        if dry_run:
            props = dict(props)
            props["slack_ts"] = {"type": "rich_text"}
        else:
            ds_id, props = get_ds_and_props(client, database_id)
    prop_map = build_prop_map(props)
    if not prop_map.get("slack_fecha"):
        ensure_property(client, database_id, ds_id, "Fecha Slack", "date", dry_run)
        if dry_run:
            prop_map = dict(prop_map)
            prop_map["slack_fecha"] = "Fecha Slack"
        else:
            ds_id, props = get_ds_and_props(client, database_id)
            prop_map = build_prop_map(props)
            if not prop_map.get("slack_fecha"):
                prop_map["slack_fecha"] = "Fecha Slack"
    created = 0
    updated = 0
    skipped = 0

    for item in items:
        existing = find_page_by_slack_ts(client, database_id, ds_id, prop_map["slack_ts"], item.slack_ts)
        payload = build_props(prop_map, item, set_default_status=(existing is None))
        if dry_run:
            action = "update" if existing else "create"
            print(f"[dry-run] {action} {item.path.name} -> db {database_id}")
            if existing:
                updated += 1
            else:
                created += 1
            continue
        if existing:
            client.pages.update(page_id=existing, properties=payload)
            updated += 1
            continue
        parent = {"type": "database_id", "database_id": database_id} if ds_id == database_id else {"type": "data_source_id", "data_source_id": ds_id}
        client.pages.create(parent=parent, properties=payload)
        created += 1

    return created, updated, skipped


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync local productivity notes to Notion")
    parser.add_argument("--dry-run", action="store_true", help="Preview only")
    args = parser.parse_args()

    token = os.getenv("NOTION_API_TOKEN")
    vault = os.getenv("OBSIDIAN_VAULT_PATH")
    if not token:
        raise SystemExit("Missing NOTION_API_TOKEN")
    if not vault:
        raise SystemExit("Missing OBSIDIAN_VAULT_PATH")

    client = Client(auth=token, notion_version="2025-09-03")
    notes = gather_notes(vault)
    tasks_items = [n for n in notes if n.tipo in {"Tarea", "Idea"}]
    learn_items = [n for n in notes if n.tipo == "Aprendizaje"]

    print(f"Local notes ready: tasks/ideas={len(tasks_items)} learnings={len(learn_items)}")

    t_created, t_updated, t_skipped = upsert_items(client, normalize_id(TASKS_DB_ID), tasks_items, args.dry_run)
    l_created, l_updated, l_skipped = upsert_items(client, normalize_id(LEARNINGS_DB_ID), learn_items, args.dry_run)

    print(
        "Done. "
        f"tasks(created={t_created}, updated={t_updated}, skipped={t_skipped}) "
        f"learnings(created={l_created}, updated={l_updated}, skipped={l_skipped})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

