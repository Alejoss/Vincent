"""
Notion (base de tareas) -> Slack: recordatorios por fecha de vencimiento cercana.

Lee la misma base de tareas que `sync_productivity_obsidian_to_notion.py`, detecta filas con
`Fin` / `fecha objetivo` (fecha) en ventana configurable y envía un mensaje a Slack.

Dedup: como máximo un aviso por (página Notion, día de vencimiento) por día natural local,
guardado en `cache/notion_slack_reminders/sent_state.json`.

Con `OBSIDIAN_VAULT_PATH`, busca la nota `slack-<ts>.md` (Tareas-Ideas o Input) y usa el frontmatter
`recordatorio_slack` generado al clasificar. Si no hay vault, nota o campo, fallback a partir del título en Notion.

Env:
  NOTION_API_TOKEN
  SLACK_BOT_TOKEN
  SLACK_DM_CHANNEL_ID   (mismo canal/DM que la ingesta Slack -> Obsidian)
  Opcional: OBSIDIAN_VAULT_PATH — para enlazar filas Notion (slack_ts) con la nota Obsidian
  Opcional: NOTION_TASKS_DATABASE_ID (por defecto la misma constante que el sync de tareas)
  Opcional: SLACK_REMINDER_EXCLUDE_STATUS — nombres de estado a ignorar, separados por coma
            (por defecto: Hecho,Terminado,Listo,Done)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import requests
from dotenv import load_dotenv
from notion_client import Client

load_dotenv(override=True)

SCRIPTS_DIR = os.path.dirname(__file__)
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPTS_DIR, ".."))
sys.path.insert(0, SCRIPTS_DIR)
sys.path.insert(0, PROJECT_ROOT)

from sync_productivity_obsidian_to_notion import (  # noqa: E402
    TASKS_IDEAS_FOLDER,
    get_ds_and_props,
    parse_frontmatter,
    pick_prop,
    normalize_id,
    resolve_tasks_db_id,
)


def _require_env(name: str) -> str:
    v = os.getenv(name)
    if not v:
        raise SystemExit(f"Missing required env var: {name}")
    return v


def slack_api_post(token: str, method: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    r = requests.post(
        f"https://slack.com/api/{method}",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"},
        json=payload,
        timeout=30,
    )
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(f"Slack API {method} failed: {data}")
    return data


def _local_today() -> date:
    return datetime.now().astimezone().date()


def _parse_iso_date(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    t = str(s).strip()
    if not t:
        return None
    if "T" in t:
        t = t.split("T", 1)[0]
    try:
        y, m, d = t.split("-", 2)
        return date(int(y), int(m), int(d))
    except Exception:
        return None


def _title_plain(props: Dict[str, Any], title_prop: str) -> str:
    block = (props.get(title_prop) or {}).get("title") or []
    parts: List[str] = []
    for seg in block:
        if seg.get("type") == "text":
            parts.append((seg.get("text") or {}).get("content") or "")
    return "".join(parts).strip() or "(sin título)"


def _status_name(props: Dict[str, Any], estado_prop: Optional[str]) -> str:
    if not estado_prop:
        return ""
    st = (props.get(estado_prop) or {}).get("status") or {}
    return str(st.get("name") or "").strip()


def _select_name(props: Dict[str, Any], prop: Optional[str]) -> str:
    if not prop:
        return ""
    sel = (props.get(prop) or {}).get("select") or {}
    return str(sel.get("name") or "").strip()


def _date_start(props: Dict[str, Any], date_prop: Optional[str]) -> Optional[str]:
    if not date_prop:
        return None
    cell = (props.get(date_prop) or {}).get("date")
    if not cell:
        return None
    return cell.get("start")


def _pick_due_prop(props: Dict[str, Any]) -> Optional[str]:
    """Prefer explicit due/end; else fecha objetivo if date type."""
    fin = pick_prop(props, ["fin", "end", "due", "deadline", "fecha fin"], ["date", "rich_text"])
    if fin and (props.get(fin) or {}).get("type") == "date":
        return fin
    fecha_obj = pick_prop(props, ["fecha_objetivo", "fecha objetivo", "due", "deadline"], ["date", "rich_text"])
    if fecha_obj and (props.get(fecha_obj) or {}).get("type") == "date":
        return fecha_obj
    if fin:
        return fin
    if fecha_obj:
        return fecha_obj
    return None


def _rich_text_plain(pprops: Dict[str, Any], prop_name: Optional[str]) -> str:
    if not prop_name:
        return ""
    block = (pprops.get(prop_name) or {}).get("rich_text") or []
    parts: List[str] = []
    for seg in block:
        if seg.get("type") == "text":
            parts.append((seg.get("text") or {}).get("content") or "")
    return "".join(parts).strip()


def _slack_ts_note_stem(slack_ts: str) -> str:
    s = (slack_ts or "").strip()
    s = re.sub(r"[^\w.-]+", "_", s)
    return s or "unknown"


def _read_recordatorio_from_vault(vault_path: str, slack_ts: str) -> str:
    """Load recordatorio_slack from classified Obsidian note matching slack_ts."""
    root = Path(vault_path) / "0_Diario_Productividad"
    stem = _slack_ts_note_stem(slack_ts)
    name = f"slack-{stem}.md"
    for sub in (TASKS_IDEAS_FOLDER, "Input"):
        p = root / sub / name
        if p.is_file():
            try:
                fm, _ = parse_frontmatter(p.read_text(encoding="utf-8"))
                return (fm.get("recordatorio_slack") or "").strip()
            except OSError:
                return ""
    return ""


def _fallback_reminder_line(title: str) -> str:
    t = (title or "").strip()
    if not t:
        return "¿Avanzaste con esta tarea?"
    if "?" not in t:
        return f"¿Avanzaste con: {t}?"
    return t


def _compact_text(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def _truncate_words(s: str, max_len: int = 180) -> str:
    txt = _compact_text(s)
    if len(txt) <= max_len:
        return txt
    cut = txt[:max_len].rstrip()
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut + "..."


def _best_description(
    pprops: Dict[str, Any],
    title: str,
    due_d: date,
    prop_map: Dict[str, Optional[str]],
) -> str:
    """
    Build a descriptive reminder line from the richest available text.
    Priority:
      1) Slack Procesado (origen)
      2) Notas / Notas (extra)
      3) Titulo de la tarea
    """
    raw_candidates: List[str] = []
    for key in ("slack_procesado", "notas"):
        pn = prop_map.get(key)
        if pn:
            val = _rich_text_plain(pprops, pn)
            if val:
                raw_candidates.append(val)
    if title:
        raw_candidates.append(title)

    base = ""
    for c in raw_candidates:
        cleaned = _compact_text(c)
        if cleaned:
            base = cleaned
            break
    if not base:
        base = "esta tarea"

    # Prefer a conversational and concise line in second person.
    summary = _truncate_words(base, max_len=190)
    return f"Para {due_d.isoformat()}: {summary}"


def _load_sent_state(path: Path) -> Dict[str, str]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {str(k): str(v) for k, v in data.items()}
    except Exception:
        pass
    return {}


def _save_sent_state(path: Path, state: Dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _query_pages_due_window(
    client: Client,
    database_id: str,
    ds_id: str,
    due_prop: str,
    start: date,
    end: date,
) -> List[Dict[str, Any]]:
    start_s = start.isoformat()
    end_s = end.isoformat()
    flt: Dict[str, Any] = {
        "and": [
            {"property": due_prop, "date": {"on_or_after": start_s}},
            {"property": due_prop, "date": {"on_or_before": end_s}},
        ]
    }
    results: List[Dict[str, Any]] = []
    cursor: Optional[str] = None
    while True:
        kwargs: Dict[str, Any] = {"filter": flt, "page_size": 100}
        if cursor:
            kwargs["start_cursor"] = cursor
        if ds_id == database_id:
            resp = client.databases.query(database_id=database_id, **kwargs)
        else:
            resp = client.data_sources.query(data_source_id=ds_id, **kwargs)
        results.extend(resp.get("results") or [])
        if not resp.get("has_more"):
            break
        cursor = resp.get("next_cursor")
    return results


def _exclude_statuses() -> Set[str]:
    raw = os.getenv("SLACK_REMINDER_EXCLUDE_STATUS", "Hecho,Terminado,Listo,Done")
    out: Set[str] = set()
    for part in raw.split(","):
        p = part.strip()
        if p:
            out.add(p.lower())
    return out


def _build_message(reminder_lines: List[str], _within_days: int) -> str:
    """Short conversational digest: one bullet per precomputed reminder line."""
    lines = [":speech_balloon: *Recordatorios*", ""]
    for line in reminder_lines:
        q = (line or "").strip()
        if not q:
            continue
        lines.append(f"• {q}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Send Slack reminders for Notion tasks due soon")
    parser.add_argument("--within-days", type=int, default=3, help="Include due dates from today through today+N days")
    parser.add_argument(
        "--include-overdue",
        action="store_true",
        help="Also include tasks whose due date is before today (still not in a terminal status)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print actions without Slack or state writes")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Ignore per-day dedup (still useful with --dry-run for debugging)",
    )
    args = parser.parse_args()

    if args.within_days < 0:
        raise SystemExit("--within-days must be >= 0")

    notion_token = _require_env("NOTION_API_TOKEN")
    slack_token = _require_env("SLACK_BOT_TOKEN")
    slack_channel = _require_env("SLACK_DM_CHANNEL_ID")

    database_id = resolve_tasks_db_id()

    today = _local_today()
    window_end = today + timedelta(days=args.within_days)
    window_start = today if not args.include_overdue else today - timedelta(days=3650)

    state_path = Path(PROJECT_ROOT) / "cache" / "notion_slack_reminders" / "sent_state.json"
    sent_state = {} if args.force else _load_sent_state(state_path)
    today_str = today.isoformat()

    client = Client(auth=notion_token, notion_version="2025-09-03")
    ds_id, props = get_ds_and_props(client, database_id)
    due_prop = _pick_due_prop(props)
    if not due_prop:
        raise SystemExit("No due date property found (need date-typed Fin / fecha objetivo / similar).")

    title_prop = pick_prop(props, ["name", "titulo", "title", "tarea"], ["title"])
    if not title_prop:
        raise SystemExit("Missing title property in Notion tasks DB.")

    estado_prop = pick_prop(props, ["estado", "status"], ["status"])
    tipo_prop = pick_prop(props, ["tipo", "type"], ["select"])
    slack_ts_prop = pick_prop(props, ["slack_ts", "slackts", "ts"], ["rich_text"])
    notas_prop = pick_prop(props, ["notas (extra)", "notas", "descripcion", "body"], ["rich_text"])
    slack_procesado_prop = pick_prop(
        props,
        ["slack procesado (origen)", "slack procesado", "slack procesado origen"],
        ["rich_text"],
    )
    vault_path = (os.getenv("OBSIDIAN_VAULT_PATH") or "").strip().strip('"').strip("'")

    exclude = _exclude_statuses()
    pages = _query_pages_due_window(client, database_id, ds_id, due_prop, window_start, window_end)

    candidates: List[Tuple[str, str, date, str]] = []
    # tuple: page_id, state_key, due_date, reminder_line (pregunta o fallback)
    for page in pages:
        pid = page.get("id") or ""
        pprops = page.get("properties") or {}
        estado = _status_name(pprops, estado_prop)
        if estado and estado.lower() in exclude:
            continue
        if tipo_prop:
            tipo = _select_name(pprops, tipo_prop)
            if tipo and tipo not in {"Tarea", "Idea"}:
                continue
        due_s = _date_start(pprops, due_prop)
        due_d = _parse_iso_date(due_s)
        if not due_d:
            continue
        if not args.include_overdue and due_d < today:
            continue
        title = _title_plain(pprops, title_prop)
        slack_ts_val = _rich_text_plain(pprops, slack_ts_prop) if slack_ts_prop else ""
        from_obs = _read_recordatorio_from_vault(vault_path, slack_ts_val) if vault_path and slack_ts_val else ""
        reminder_line = (from_obs or "").strip()
        if not reminder_line:
            reminder_line = _best_description(
                pprops,
                title,
                due_d,
                {"notas": notas_prop, "slack_procesado": slack_procesado_prop},
            )
        if not reminder_line:
            reminder_line = _fallback_reminder_line(title)
        state_key = f"{pid}|{due_d.isoformat()}"
        if not args.force and sent_state.get(state_key) == today_str:
            continue
        candidates.append((pid, state_key, due_d, reminder_line))

    candidates.sort(key=lambda x: (x[2], x[3].lower()))

    if not candidates:
        print("No tasks to remind (window empty, all excluded, or already notified today).")
        return 0

    reminder_lines = [line for (_pid, _sk, _d, line) in candidates]
    text = _build_message(reminder_lines, args.within_days)

    if args.dry_run:
        print(f"[dry-run] Would post to Slack channel {slack_channel}:")
        print(text)
        print(f"[dry-run] Would mark {len(candidates)} keys in {state_path}")
        return 0

    slack_api_post(
        slack_token,
        "chat.postMessage",
        {"channel": slack_channel, "text": text, "mrkdwn": True, "link_names": True},
    )

    for _pid, sk, _d, _line in candidates:
        sent_state[sk] = today_str
    _save_sent_state(state_path, sent_state)

    print(f"Posted Slack reminder for {len(candidates)} task(s). State updated at {state_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
