"""
Notion (base de tareas) -> Slack: recordatorios por fecha de vencimiento cercana.

Lee la misma base de tareas que `sync_productivity_obsidian_to_notion.py`, detecta filas con
`Fin` / `fecha objetivo` (fecha) en ventana configurable y envía un mensaje a Slack.

Ventana por defecto: fecha objetivo entre hoy y hoy+5; vencidas hasta 7 días atrás con texto distinto.

Tareas cuyo título empieza por «Cloudflare»: aviso especial «Tienes un error importante en Cloudflare»
si el estado no es terminado (p. ej. Hecho); no depende de la fecha Fin. Clave de dedup: `{page_id}|cloudflare`.

Dedup: como máximo un aviso por (página Notion, día de vencimiento) cada N días naturales locales,
guardado en `state/notion_slack_reminders_sent.json` (versionado; GHA hace commit tras cada run).
Ventanas por defecto: próximas 3 días (`--dedup-days`); atrasadas pendientes 2 días (`--dedup-days-overdue`).
Tareas en estado terminal (Hecho, etc.) nunca se avisan.

Con `OBSIDIAN_VAULT_PATH`, busca la nota `slack-<ts>.md` (Tareas-Ideas o Input) y usa el frontmatter
`recordatorio_slack` generado al clasificar. Si no hay vault, nota o campo, fallback a partir del título en Notion.

Env:
  NOTION_API_TOKEN
  SLACK_BOT_TOKEN
  SLACK_DM_CHANNEL_ID   (mismo canal/DM que la ingesta Slack -> Obsidian)
  Opcional: OBSIDIAN_VAULT_PATH — para enlazar filas Notion (slack_ts) con la nota Obsidian
  NOTION_TASKS_DATABASE_ID (required; set in .env)
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

from src.notion_slack_reminders_dedup import (  # noqa: E402
    effective_dedup_days,
    parse_iso_date as _parse_iso_date,
    was_sent_within_dedup_window,
)
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


def _task_summary(
    pprops: Dict[str, Any],
    title: str,
    prop_map: Dict[str, Optional[str]],
) -> str:
    """Short label from Slack Procesado, notas o título."""
    raw_candidates: List[str] = []
    for key in ("slack_procesado", "notas"):
        pn = prop_map.get(key)
        if pn:
            val = _rich_text_plain(pprops, pn)
            if val:
                raw_candidates.append(val)
    if title:
        raw_candidates.append(title)

    for c in raw_candidates:
        cleaned = _compact_text(c)
        if cleaned:
            return _truncate_words(cleaned, max_len=190)
    return "esta tarea"


def _best_description(
    pprops: Dict[str, Any],
    title: str,
    due_d: date,
    prop_map: Dict[str, Optional[str]],
) -> str:
    summary = _task_summary(pprops, title, prop_map)
    return f"Para {due_d.isoformat()}: {summary}"


def _overdue_reminder_line(
    pprops: Dict[str, Any],
    title: str,
    prop_map: Dict[str, Optional[str]],
) -> str:
    summary = _task_summary(pprops, title, prop_map)
    return f"Ya deberías haber terminado con: {summary}"


LEGACY_STATE_PATH = Path(PROJECT_ROOT) / "cache" / "notion_slack_reminders" / "sent_state.json"
STATE_PATH = Path(PROJECT_ROOT) / "state" / "notion_slack_reminders_sent.json"


def _load_sent_state(path: Path) -> Dict[str, str]:
    src = path
    if not src.is_file() and LEGACY_STATE_PATH.is_file():
        src = LEGACY_STATE_PATH
    if not src.is_file():
        return {}
    try:
        data = json.loads(src.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            state = {str(k): str(v) for k, v in data.items()}
            if src != path and state:
                _save_sent_state(path, state)
            return state
    except Exception:
        pass
    return {}


def _save_sent_state(path: Path, state: Dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _prune_sent_state(state: Dict[str, str], today: date, keep_days: int = 30) -> Dict[str, str]:
    if keep_days <= 0:
        return state
    cutoff = today - timedelta(days=keep_days)
    pruned: Dict[str, str] = {}
    for key, sent_on in state.items():
        sent_d = _parse_iso_date(sent_on)
        if sent_d is not None and sent_d >= cutoff:
            pruned[key] = sent_on
    return pruned


CLOUDFLARE_TITLE_PREFIX = "Cloudflare"
CLOUDFLARE_REMINDER_LINE = "Tienes un error importante en Cloudflare"


def _is_cloudflare_task(title: str) -> bool:
    return (title or "").strip().startswith(CLOUDFLARE_TITLE_PREFIX)


def _query_pages_title_starts_with(
    client: Client,
    database_id: str,
    ds_id: str,
    title_prop: str,
    prefix: str,
) -> List[Dict[str, Any]]:
    flt: Dict[str, Any] = {
        "property": title_prop,
        "title": {"starts_with": prefix},
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


def _build_message(
    cloudflare_lines: List[str],
    candidates: List[Tuple[date, str, bool]],
    overdue_max_days: int,
) -> str:
    """Digest grouped by Cloudflare alerts, upcoming due, and recently overdue."""
    upcoming = [(d, line) for d, line, is_overdue in candidates if not is_overdue]
    overdue = [(d, line) for d, line, is_overdue in candidates if is_overdue]
    lines: List[str] = []
    if cloudflare_lines:
        lines.extend([":warning: *Cloudflare*", ""])
        for line in cloudflare_lines:
            q = (line or "").strip()
            if q:
                lines.append(f"• {q}")
        lines.append("")
    if upcoming or overdue:
        lines.extend([":speech_balloon: *Recordatorios*", ""])
    if upcoming:
        lines.append("*Próximas:*")
        for _d, line in upcoming:
            q = (line or "").strip()
            if q:
                lines.append(f"• {q}")
        lines.append("")
    if overdue:
        header = "*Atrasadas*"
        if overdue_max_days > 0:
            header += f" (últimos {overdue_max_days} días)"
        header += ":"
        lines.append(header)
        for _d, line in overdue:
            q = (line or "").strip()
            if q:
                lines.append(f"• {q}")
    return "\n".join(lines).rstrip()


def main() -> int:
    parser = argparse.ArgumentParser(description="Send Slack reminders for Notion tasks due soon")
    parser.add_argument(
        "--within-days",
        type=int,
        default=5,
        help="Include due dates from today through today+N days (default: 5)",
    )
    parser.add_argument(
        "--overdue-max-days",
        type=int,
        default=7,
        help="Include overdue tasks up to N days before today; 0 disables overdue (default: 7)",
    )
    parser.add_argument(
        "--include-overdue",
        action="store_true",
        help="Legacy: include all overdue tasks (overrides --overdue-max-days to 3650)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print actions without Slack or state writes")
    parser.add_argument(
        "--dedup-days",
        type=int,
        default=3,
        help="Dedup window for upcoming tasks (default: 3 calendar days)",
    )
    parser.add_argument(
        "--dedup-days-overdue",
        type=int,
        default=2,
        help="Dedup window for overdue pending tasks (default: 2; re-remind sooner)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Ignore dedup window (still useful with --dry-run for debugging)",
    )
    args = parser.parse_args()

    if args.within_days < 0:
        raise SystemExit("--within-days must be >= 0")
    if args.overdue_max_days < 0:
        raise SystemExit("--overdue-max-days must be >= 0")
    if args.dedup_days < 0:
        raise SystemExit("--dedup-days must be >= 0")
    if args.dedup_days_overdue < 0:
        raise SystemExit("--dedup-days-overdue must be >= 0")

    overdue_max_days = 3650 if args.include_overdue else args.overdue_max_days

    notion_token = _require_env("NOTION_API_TOKEN")
    slack_token = _require_env("SLACK_BOT_TOKEN")
    slack_channel = _require_env("SLACK_DM_CHANNEL_ID")

    database_id = resolve_tasks_db_id()

    today = _local_today()
    window_end = today + timedelta(days=args.within_days)
    window_start = today - timedelta(days=overdue_max_days) if overdue_max_days > 0 else today

    state_path = STATE_PATH
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
    prop_map = {"notas": notas_prop, "slack_procesado": slack_procesado_prop}

    def _skip_by_status_and_tipo(pprops: Dict[str, Any]) -> bool:
        estado = _status_name(pprops, estado_prop)
        if estado and estado.lower() in exclude:
            return True
        if tipo_prop:
            tipo = _select_name(pprops, tipo_prop)
            if tipo and tipo not in {"Tarea", "Idea"}:
                return True
        return False

    cloudflare_candidates: List[Tuple[str, str, str]] = []
    # tuple: page_id, state_key, reminder_line
    cloudflare_pages = _query_pages_title_starts_with(
        client, database_id, ds_id, title_prop, CLOUDFLARE_TITLE_PREFIX
    )
    for page in cloudflare_pages:
        pid = page.get("id") or ""
        pprops = page.get("properties") or {}
        if _skip_by_status_and_tipo(pprops):
            continue
        title = _title_plain(pprops, title_prop)
        if not _is_cloudflare_task(title):
            continue
        state_key = f"{pid}|cloudflare"
        if not args.force and was_sent_within_dedup_window(
            sent_state, state_key, today, args.dedup_days
        ):
            continue
        cloudflare_candidates.append((pid, state_key, CLOUDFLARE_REMINDER_LINE))

    pages = _query_pages_due_window(client, database_id, ds_id, due_prop, window_start, window_end)

    candidates: List[Tuple[str, str, date, str, bool]] = []
    # tuple: page_id, state_key, due_date, reminder_line, is_overdue
    for page in pages:
        pid = page.get("id") or ""
        pprops = page.get("properties") or {}
        if _skip_by_status_and_tipo(pprops):
            continue
        title = _title_plain(pprops, title_prop)
        if _is_cloudflare_task(title):
            continue
        due_s = _date_start(pprops, due_prop)
        due_d = _parse_iso_date(due_s)
        if not due_d:
            continue
        is_overdue = due_d < today
        if is_overdue:
            if overdue_max_days <= 0 or due_d < today - timedelta(days=overdue_max_days):
                continue
        elif due_d > window_end:
            continue
        slack_ts_val = _rich_text_plain(pprops, slack_ts_prop) if slack_ts_prop else ""
        if is_overdue:
            reminder_line = _overdue_reminder_line(pprops, title, prop_map)
        else:
            from_obs = _read_recordatorio_from_vault(vault_path, slack_ts_val) if vault_path and slack_ts_val else ""
            reminder_line = (from_obs or "").strip()
            if not reminder_line:
                reminder_line = _best_description(pprops, title, due_d, prop_map)
            if not reminder_line:
                reminder_line = _fallback_reminder_line(title)
        state_key = f"{pid}|{due_d.isoformat()}"
        dedup_n = effective_dedup_days(is_overdue, args.dedup_days, args.dedup_days_overdue)
        if not args.force and was_sent_within_dedup_window(
            sent_state, state_key, today, dedup_n
        ):
            continue
        candidates.append((pid, state_key, due_d, reminder_line, is_overdue))

    candidates.sort(key=lambda x: (x[4], x[2], x[3].lower()))

    if not candidates and not cloudflare_candidates:
        print(
            "No tasks to remind (window empty, all excluded, or already notified within dedup window)."
        )
        return 0

    message_rows = [(d, line, is_overdue) for (_pid, _sk, d, line, is_overdue) in candidates]
    cloudflare_lines = [line for (_pid, _sk, line) in cloudflare_candidates]
    text = _build_message(cloudflare_lines, message_rows, overdue_max_days)

    if args.dry_run:
        print(f"[dry-run] Would post to Slack channel {slack_channel}:")
        print(text)
        total_keys = len(candidates) + len(cloudflare_candidates)
        print(f"[dry-run] Would mark {total_keys} keys in {state_path}")
        return 0

    slack_api_post(
        slack_token,
        "chat.postMessage",
        {"channel": slack_channel, "text": text, "mrkdwn": True, "link_names": True},
    )

    for _pid, sk, _d, _line, _overdue in candidates:
        sent_state[sk] = today_str
    for _pid, sk, _line in cloudflare_candidates:
        sent_state[sk] = today_str
    sent_state = _prune_sent_state(sent_state, today)
    _save_sent_state(state_path, sent_state)

    total = len(candidates) + len(cloudflare_candidates)
    print(
        f"Posted Slack reminder for {total} task(s) "
        f"({len(cloudflare_candidates)} Cloudflare, {len(candidates)} due-date). "
        f"State updated at {state_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
