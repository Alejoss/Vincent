"""
Slack DM messages -> Notion task updates.

This script complements the Slack -> Obsidian productivity pipeline. It reads the
same human DM stream, detects messages that update an existing task, finds the
best Notion task candidate, and applies one of these updates:

- complete: set the task status to a completed option (for example, "Hecho")
- reschedule: update the due date (`Fin` / `fecha objetivo`)
- delete: set an eliminated/cancelled status when present, otherwise archive

Messages that are classified as task updates are marked in the matching Obsidian
Input note so the normal classifier does not create a new task from text like
"ya envie el mail".

Completion (Hecho) runs when the message shows clear completion intent
(e.g. "completé la tarea", "marcar como completada"; see src/slack_task_intent.py).
Other messages are ignored by this script; reschedule/delete are not auto-detected yet.

Env:
  SLACK_BOT_TOKEN
  SLACK_DM_CHANNEL_ID
  NOTION_API_TOKEN
  NOTION_TASKS_DATABASE_ID (required; set in .env)
  OBSIDIAN_VAULT_PATH (optional; used to mark matching Input notes)
  LLM_PROVIDER / LLM_MODEL / OPENAI_API_KEY / GROQ_API_KEY / OLLAMA_URL
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sqlite3
import sys
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from dotenv import load_dotenv
from notion_client import Client

load_dotenv(override=True)

SCRIPTS_DIR = os.path.dirname(__file__)
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPTS_DIR, ".."))
sys.path.insert(0, SCRIPTS_DIR)
sys.path.insert(0, PROJECT_ROOT)

import sync_slack_inbox_to_obsidian as slack_sync  # noqa: E402
from src.llm_client import (  # noqa: E402
    LLMConfig,
    build_llm_config,
    call_json,
    ollama_is_reachable,
    validate_llm_config,
)
from src.productivity_dates import clamp_due_iso, infer_due_from_text, safe_date_from_slack_ts  # noqa: E402
from src.slack_task_completion_gate import GATE_SKIP_REASON, message_requests_complete  # noqa: E402
from src.slack_inbox_obsidian import default_input_rel_dir  # noqa: E402
from src.slack_task_update_obsidian import mark_task_update_note  # noqa: E402
from src.slack_task_updates_audit import (  # noqa: E402
    GATE_INTENT_MATCH,
    GATE_NO_INTENT,
    GATE_NO_PHRASE,
    GATE_PHRASE_MATCH,
    OUTCOME_APPLIED,
    OUTCOME_EMPTY,
    OUTCOME_FAILED,
    OUTCOME_GATE_SKIP,
    OUTCOME_IGNORED,
    OUTCOME_UNMATCHED,
    append_audit_entry,
    build_audit_entry,
    default_audit_path,
    should_advance_cursor,
)
from sync_productivity_obsidian_to_notion import (  # noqa: E402
    get_ds_and_props,
    normalize_id,
    pick_prop,
    resolve_tasks_db_id,
)

log = logging.getLogger("slack_task_updates")
logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)

ACTION_COMPLETE = "complete"
ACTION_RESCHEDULE = "reschedule"
ACTION_DELETE = "delete"
ACTION_IGNORE = "ignore"
VALID_ACTIONS = {ACTION_COMPLETE, ACTION_RESCHEDULE, ACTION_DELETE, ACTION_IGNORE}

STATUS_COMPLETE_CANDIDATES = (
    "Hecho",
    "Completado",
    "Completada",
    "Terminado",
    "Terminada",
    "Listo",
    "Lista",
    "Done",
    "Completed",
)
STATUS_DELETE_CANDIDATES = (
    "Eliminada",
    "Eliminado",
    "Cancelada",
    "Cancelado",
    "Descartada",
    "Descartado",
    "Archivada",
    "Archivado",
    "Deleted",
    "Cancelled",
    "Canceled",
)
DEFAULT_TERMINAL_STATUS_NAMES = STATUS_COMPLETE_CANDIDATES + STATUS_DELETE_CANDIDATES
NOTION_TEXT_PREVIEW_CHARS = 500


@dataclass(frozen=True)
class TaskPropMap:
    title: str
    status: Optional[str]
    status_options: Tuple[str, ...]
    due: Optional[str]
    due_type: str
    tipo: Optional[str]
    proyecto: Optional[str]
    notas: Optional[str]
    slack_procesado: Optional[str]


@dataclass(frozen=True)
class TaskCandidate:
    page_id: str
    candidate_id: str
    title: str
    status: str
    due_date: str
    tipo: str
    proyecto: str
    text: str
    score: int


@dataclass(frozen=True)
class UpdateDecision:
    action: str
    candidate_id: str
    due_date: str
    confidence: float
    reason: str


class SlackTaskUpdateStateStore:
    """Independent cursor for this task-update reader."""

    def __init__(self, project_root: str):
        self._db_path = os.path.join(project_root, "cache", "slack_task_updates", "state.sqlite3")
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS slack_task_update_cursor (
                channel_id TEXT PRIMARY KEY,
                last_ts TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.commit()
        return conn

    def load_last_ts(self, channel_id: str) -> Optional[str]:
        key = _safe_storage_key(channel_id)
        if not key:
            return None
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT last_ts FROM slack_task_update_cursor WHERE channel_id = ?",
                (key,),
            ).fetchone()
            return row[0] if row else None
        finally:
            conn.close()

    def save_last_ts(self, channel_id: str, slack_ts: str) -> None:
        key = _safe_storage_key(channel_id)
        value = (slack_ts or "").strip()
        if not key or not value:
            return
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO slack_task_update_cursor (channel_id, last_ts, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(channel_id) DO UPDATE SET
                    last_ts = excluded.last_ts,
                    updated_at = excluded.updated_at
                """,
                (key, value, datetime.now(tz=timezone.utc).isoformat()),
            )
            conn.commit()
        finally:
            conn.close()


def _safe_storage_key(raw: str) -> str:
    s = (raw or "").strip()
    s = re.sub(r"[^a-zA-Z0-9._-]+", "_", s)
    return s[:200] if len(s) > 200 else s


def _require_env(name: str) -> str:
    value = (os.getenv(name) or "").strip()
    if not value:
        raise SystemExit(f"Missing required env var: {name}")
    return value


def _strip_quotes(value: str) -> str:
    return (value or "").strip().strip('"').strip("'")


def _permalink_for_message(workspace_domain: str, channel_id: str, slack_ts: str) -> str:
    return slack_sync.build_message_permalink(workspace_domain, channel_id, slack_ts)


def _record_task_update_note(
    *,
    vault_path: str,
    input_rel: str,
    slack_ts: str,
    message_text: str,
    source_url: str,
    transcribed: bool,
    status: str,
    action: str,
    page_id: str,
    model_label: str,
    reason: str,
    dry_run: bool,
    enabled: bool,
) -> None:
    if not enabled:
        return
    ok = mark_task_update_note(
        vault_path=vault_path,
        input_rel=input_rel,
        slack_ts=slack_ts,
        message_text=message_text,
        source_url=source_url,
        transcribed=transcribed,
        status=status,
        action=action,
        page_id=page_id,
        model_label=model_label,
        reason=reason,
        dry_run=dry_run,
    )
    if dry_run and ok:
        log.info(f"[dry-run] would mark Input note for ts={slack_ts} status={status}")


def _normalize_text(value: str) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text.lower()


_STOPWORDS = {
    "a",
    "al",
    "con",
    "de",
    "del",
    "el",
    "en",
    "es",
    "esta",
    "este",
    "esto",
    "la",
    "las",
    "lo",
    "los",
    "me",
    "mi",
    "para",
    "por",
    "que",
    "se",
    "sin",
    "su",
    "un",
    "una",
    "ya",
}


def _tokens(value: str) -> List[str]:
    norm = _normalize_text(value)
    raw = re.findall(r"[a-z0-9]{3,}", norm)
    return [tok for tok in raw if tok not in _STOPWORDS]


def _compact(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip())


def _truncate(value: str, max_chars: int) -> str:
    text = _compact(value)
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars].rstrip()
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return f"{cut}..."


def _title_plain(props: Dict[str, Any], title_prop: str) -> str:
    block = (props.get(title_prop) or {}).get("title") or []
    return "".join((seg.get("plain_text") or ((seg.get("text") or {}).get("content") or "")) for seg in block).strip()


def _rich_text_plain(props: Dict[str, Any], prop_name: Optional[str]) -> str:
    if not prop_name:
        return ""
    block = (props.get(prop_name) or {}).get("rich_text") or []
    return "".join((seg.get("plain_text") or ((seg.get("text") or {}).get("content") or "")) for seg in block).strip()


def _select_name(props: Dict[str, Any], prop_name: Optional[str]) -> str:
    if not prop_name:
        return ""
    cell = (props.get(prop_name) or {}).get("select") or {}
    return str(cell.get("name") or "").strip()


def _status_name(props: Dict[str, Any], prop_name: Optional[str]) -> str:
    if not prop_name:
        return ""
    cell = (props.get(prop_name) or {}).get("status") or {}
    return str(cell.get("name") or "").strip()


def _date_start(props: Dict[str, Any], prop_name: Optional[str]) -> str:
    if not prop_name:
        return ""
    cell = (props.get(prop_name) or {}).get("date")
    if not cell:
        return ""
    return str(cell.get("start") or "").strip()[:10]


def _status_options(db_props: Dict[str, Any], status_prop: Optional[str]) -> Tuple[str, ...]:
    if not status_prop:
        return ()
    options = (((db_props.get(status_prop) or {}).get("status") or {}).get("options") or [])
    names = [str(opt.get("name") or "").strip() for opt in options]
    return tuple(n for n in names if n)


def _pick_due_prop(db_props: Dict[str, Any]) -> Tuple[Optional[str], str]:
    fin = pick_prop(db_props, ["fin", "end", "due", "deadline", "fecha fin"], ["date", "rich_text"])
    if fin and (db_props.get(fin) or {}).get("type") == "date":
        return fin, "date"
    fecha_obj = pick_prop(db_props, ["fecha_objetivo", "fecha objetivo", "due", "deadline"], ["date", "rich_text"])
    if fecha_obj:
        return fecha_obj, (db_props.get(fecha_obj) or {}).get("type") or "rich_text"
    if fin:
        return fin, (db_props.get(fin) or {}).get("type") or "rich_text"
    return None, ""


def _build_task_prop_map(db_props: Dict[str, Any]) -> TaskPropMap:
    title = pick_prop(db_props, ["name", "titulo", "title", "tarea", "aprendizaje"], ["title"])
    if not title:
        raise SystemExit("Missing title property in Notion tasks DB.")
    status = pick_prop(db_props, ["estado", "status"], ["status"])
    due, due_type = _pick_due_prop(db_props)
    return TaskPropMap(
        title=title,
        status=status,
        status_options=_status_options(db_props, status),
        due=due,
        due_type=due_type,
        tipo=pick_prop(db_props, ["tipo", "type"], ["select"]),
        proyecto=pick_prop(db_props, ["proyecto", "project"], ["select"]),
        notas=pick_prop(db_props, ["notas (extra)", "notas", "descripcion", "body"], ["rich_text"]),
        slack_procesado=pick_prop(
            db_props,
            ["slack procesado (origen)", "slack procesado", "slack procesado origen"],
            ["rich_text"],
        ),
    )


def _query_all_pages(client: Client, database_id: str, ds_id: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    cursor: Optional[str] = None
    while True:
        kwargs: Dict[str, Any] = {"page_size": 100}
        if cursor:
            kwargs["start_cursor"] = cursor
        if ds_id == database_id:
            resp = client.databases.query(database_id=database_id, **kwargs)
        else:
            resp = client.data_sources.query(data_source_id=ds_id, **kwargs)
        out.extend(resp.get("results") or [])
        if not resp.get("has_more"):
            break
        cursor = resp.get("next_cursor")
    return out


def _terminal_statuses_from_env() -> set[str]:
    raw = os.getenv("SLACK_TASK_UPDATE_TERMINAL_STATUS", "")
    names = list(DEFAULT_TERMINAL_STATUS_NAMES)
    if raw:
        names.extend(part.strip() for part in raw.split(",") if part.strip())
    return {_normalize_text(n) for n in names if n}


def _page_to_candidate(page: Dict[str, Any], prop_map: TaskPropMap, candidate_id: str) -> TaskCandidate:
    props = page.get("properties") or {}
    title = _title_plain(props, prop_map.title) or "(sin titulo)"
    status = _status_name(props, prop_map.status)
    due_date = _date_start(props, prop_map.due)
    tipo = _select_name(props, prop_map.tipo)
    proyecto = _select_name(props, prop_map.proyecto)
    notes = _rich_text_plain(props, prop_map.slack_procesado) or _rich_text_plain(props, prop_map.notas)
    text = _truncate(" ".join([title, proyecto, notes]), NOTION_TEXT_PREVIEW_CHARS)
    return TaskCandidate(
        page_id=page.get("id") or "",
        candidate_id=candidate_id,
        title=title,
        status=status,
        due_date=due_date,
        tipo=tipo,
        proyecto=proyecto,
        text=text,
        score=0,
    )


def _score_candidate(query_text: str, candidate: TaskCandidate) -> int:
    q_tokens = set(_tokens(query_text))
    if not q_tokens:
        return 0
    title_tokens = set(_tokens(candidate.title))
    text_tokens = set(_tokens(candidate.text))
    score = len(q_tokens & text_tokens)
    score += 2 * len(q_tokens & title_tokens)
    q_norm = _normalize_text(query_text)
    title_norm = _normalize_text(candidate.title)
    if title_norm and title_norm in q_norm:
        score += 8
    return score


def _rank_candidates(
    *,
    pages: Sequence[Dict[str, Any]],
    prop_map: TaskPropMap,
    query_text: str,
    include_terminal: bool,
    limit: int,
) -> List[TaskCandidate]:
    terminal = _terminal_statuses_from_env()
    out: List[TaskCandidate] = []
    seq = 0
    for page in pages:
        if page.get("archived"):
            continue
        props = page.get("properties") or {}
        tipo = _select_name(props, prop_map.tipo)
        if tipo and tipo not in {"Tarea", "Idea"}:
            continue
        status = _status_name(props, prop_map.status)
        if (not include_terminal) and status and _normalize_text(status) in terminal:
            continue
        seq += 1
        candidate = _page_to_candidate(page, prop_map, f"c{seq}")
        score = _score_candidate(query_text, candidate)
        out.append(
            TaskCandidate(
                page_id=candidate.page_id,
                candidate_id=candidate.candidate_id,
                title=candidate.title,
                status=candidate.status,
                due_date=candidate.due_date,
                tipo=candidate.tipo,
                proyecto=candidate.proyecto,
                text=candidate.text,
                score=score,
            )
        )
    out.sort(key=lambda c: (-c.score, c.due_date or "9999-99-99", c.title.lower()))
    if out and out[0].score > 0:
        positive = [c for c in out if c.score > 0]
        return positive[:limit]
    return out[: min(limit, 10)]


def _candidate_prompt_block(candidates: Sequence[TaskCandidate]) -> str:
    if not candidates:
        return "(sin candidatos)"
    lines: List[str] = []
    for c in candidates:
        bits = [
            f"id={c.candidate_id}",
            f"titulo={c.title}",
            f"estado={c.status or 'N/A'}",
            f"fecha={c.due_date or 'N/A'}",
            f"proyecto={c.proyecto or 'N/A'}",
        ]
        if c.text and c.text != c.title:
            bits.append(f"detalle={c.text}")
        lines.append("- " + " | ".join(bits))
    return "\n".join(lines)


def _build_complete_candidate_prompt(
    *,
    message_text: str,
    slack_context: str,
    candidates: Sequence[TaskCandidate],
    anchor_iso: str,
) -> str:
    return (
        "Eres un asistente que elige UNA tarea existente de Notion para marcar como completada.\n"
        "El usuario ya indicó que una tarea quedó hecha o pidió marcarla como completada.\n"
        "No decidas si completar: eso ya está confirmado. Solo elige la tarea candidata correcta.\n"
        "Reglas:\n"
        "- Responde candidate_id de la lista (p. ej. c1) o vacío si ninguna encaja.\n"
        "- Usa el contexto del bot si el mensaje dice 'esto', 'esa tarea', etc.\n"
        "- No crees tareas nuevas.\n"
        "Responde SOLO JSON valido con esta forma exacta:\n"
        '{"candidate_id":"c1|","confidence":0.0,"reason":"..."}\n'
        f"Fecha ancla: {anchor_iso}\n"
        "Mensaje humano:\n"
        f"{message_text.strip()}\n"
        "Contexto reciente del bot (puede estar vacio):\n"
        f"{slack_context.strip() or 'N/A'}\n"
        "Tareas candidatas:\n"
        f"{_candidate_prompt_block(candidates)}\n"
    )


def _build_decision_prompt(
    *,
    message_text: str,
    slack_context: str,
    candidates: Sequence[TaskCandidate],
    anchor_iso: str,
) -> str:
    return (
        "Eres un actualizador de tareas de Notion a partir de mensajes de Slack en español.\n"
        "Decide si el mensaje humano modifica una tarea EXISTENTE. No crees tareas nuevas.\n"
        "Acciones validas:\n"
        "- complete: el mensaje dice que algo ya se hizo, quedo enviado, terminado o resuelto.\n"
        "- reschedule: el mensaje posterga o cambia la fecha de una tarea existente.\n"
        "- delete: el mensaje dice que la tarea ya no importa, se cancela, se descarta o se elimina.\n"
        "- ignore: el mensaje crea una tarea nueva, es una idea/aprendizaje, o no hay suficiente claridad.\n"
        "Reglas:\n"
        "- Elige candidate_id solo si hay una tarea candidata claramente relacionada.\n"
        "- Si el mensaje dice 'esto', 'eso' o 'esta tarea', usa el contexto reciente del bot si ayuda.\n"
        "- Para reschedule, due_date debe ser YYYY-MM-DD. Interpreta fechas relativas con fecha ancla.\n"
        "- Si falta fecha para reschedule, deja due_date vacio y baja la confianza.\n"
        "- Si no hay candidato claro, action puede ser complete/reschedule/delete pero candidate_id debe quedar vacio.\n"
        "Responde SOLO JSON valido con esta forma exacta:\n"
        '{"action":"complete|reschedule|delete|ignore","candidate_id":"c1|","due_date":"YYYY-MM-DD|",'
        '"confidence":0.0,"reason":"..."}\n'
        f"Fecha ancla: {anchor_iso}\n"
        "Mensaje humano:\n"
        f"{message_text.strip()}\n"
        "Contexto reciente del bot (puede estar vacio):\n"
        f"{slack_context.strip() or 'N/A'}\n"
        "Tareas candidatas:\n"
        f"{_candidate_prompt_block(candidates)}\n"
    )


def _normalize_action(raw: str) -> str:
    value = (raw or "").strip().lower()
    if value in VALID_ACTIONS:
        return value
    aliases = {
        "completed": ACTION_COMPLETE,
        "done": ACTION_COMPLETE,
        "hecho": ACTION_COMPLETE,
        "rescheduled": ACTION_RESCHEDULE,
        "postpone": ACTION_RESCHEDULE,
        "postponed": ACTION_RESCHEDULE,
        "delete": ACTION_DELETE,
        "deleted": ACTION_DELETE,
        "remove": ACTION_DELETE,
        "cancel": ACTION_DELETE,
        "cancelled": ACTION_DELETE,
    }
    return aliases.get(value, ACTION_IGNORE)


def _decision_complete_from_llm(
    llm: LLMConfig,
    message_text: str,
    slack_context: str,
    candidates: Sequence[TaskCandidate],
    anchor_iso: str,
    timeout_s: int,
) -> UpdateDecision:
    prompt = _build_complete_candidate_prompt(
        message_text=message_text,
        slack_context=slack_context,
        candidates=candidates,
        anchor_iso=anchor_iso,
    )
    obj = call_json(prompt, llm, timeout_s=timeout_s)
    candidate_id = str(obj.get("candidate_id", "") or "").strip()
    try:
        confidence = float(obj.get("confidence", 0.0))
    except Exception:
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))
    return UpdateDecision(
        action=ACTION_COMPLETE,
        candidate_id=candidate_id,
        due_date="",
        confidence=confidence,
        reason=str(obj.get("reason", "") or "").strip(),
    )


def _decision_from_llm(
    llm: LLMConfig,
    message_text: str,
    slack_context: str,
    candidates: Sequence[TaskCandidate],
    anchor_iso: str,
    timeout_s: int,
) -> UpdateDecision:
    prompt = _build_decision_prompt(
        message_text=message_text,
        slack_context=slack_context,
        candidates=candidates,
        anchor_iso=anchor_iso,
    )
    obj = call_json(prompt, llm, timeout_s=timeout_s)
    action = _normalize_action(str(obj.get("action", "")))
    candidate_id = str(obj.get("candidate_id", "") or "").strip()
    due_date = str(obj.get("due_date", "") or "").strip()[:10]
    try:
        confidence = float(obj.get("confidence", 0.0))
    except Exception:
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))
    return UpdateDecision(
        action=action,
        candidate_id=candidate_id,
        due_date=due_date,
        confidence=confidence,
        reason=str(obj.get("reason", "") or "").strip(),
    )


def _choose_status_option(options: Iterable[str], candidates: Iterable[str]) -> str:
    option_list = [o for o in options if (o or "").strip()]
    exact = {o: o for o in option_list}
    for wanted in candidates:
        if wanted in exact:
            return exact[wanted]
    normalized = {_normalize_text(o): o for o in option_list}
    for wanted in candidates:
        found = normalized.get(_normalize_text(wanted))
        if found:
            return found
    for option in option_list:
        opt_norm = _normalize_text(option)
        for wanted in candidates:
            if _normalize_text(wanted) in opt_norm or opt_norm in _normalize_text(wanted):
                return option
    return ""


def _status_update_payload(prop_map: TaskPropMap, action: str) -> Tuple[Dict[str, Any], bool, str]:
    if action == ACTION_COMPLETE:
        chosen = _choose_status_option(prop_map.status_options, STATUS_COMPLETE_CANDIDATES)
        if not prop_map.status or not chosen:
            return {}, False, "No completed status option found."
        return {prop_map.status: {"status": {"name": chosen}}}, False, f"Estado -> {chosen}"
    if action == ACTION_DELETE:
        chosen = _choose_status_option(prop_map.status_options, STATUS_DELETE_CANDIDATES)
        if prop_map.status and chosen:
            return {prop_map.status: {"status": {"name": chosen}}}, False, f"Estado -> {chosen}"
        return {}, True, "Archived page (no delete status option found)."
    return {}, False, ""


def _reschedule_payload(prop_map: TaskPropMap, due_date: str) -> Tuple[Dict[str, Any], str]:
    if not prop_map.due:
        return {}, "No due date property found."
    if prop_map.due_type == "date":
        return {prop_map.due: {"date": {"start": due_date}}}, f"{prop_map.due} -> {due_date}"
    return {
        prop_map.due: {"rich_text": [{"type": "text", "text": {"content": due_date}}]}
    }, f"{prop_map.due} -> {due_date}"


def _apply_update(
    *,
    client: Client,
    prop_map: TaskPropMap,
    task: TaskCandidate,
    decision: UpdateDecision,
    dry_run: bool,
) -> Tuple[bool, str]:
    properties: Dict[str, Any] = {}
    archived = False
    detail = ""

    if decision.action in {ACTION_COMPLETE, ACTION_DELETE}:
        properties, archived, detail = _status_update_payload(prop_map, decision.action)
    elif decision.action == ACTION_RESCHEDULE:
        properties, detail = _reschedule_payload(prop_map, decision.due_date)
    else:
        return False, "Ignored."

    if not properties and not archived:
        return False, detail or "No update payload built."

    if dry_run:
        return True, f"[dry-run] would update {task.page_id}: {detail}"

    kwargs: Dict[str, Any] = {}
    if properties:
        kwargs["properties"] = properties
    if archived:
        kwargs["archived"] = True
    client.pages.update(page_id=task.page_id, **kwargs)
    return True, detail


def _extract_message_text(
    *,
    message: Dict[str, Any],
    slack_token: str,
    audio: bool,
    whisper_provider: str,
    dry_run: bool,
) -> Tuple[str, bool]:
    text = (message.get("text") or "").strip()
    if text or not audio:
        return text, False

    files = message.get("files") or []
    for f in files if isinstance(files, list) else []:
        if not slack_sync._is_audio_file(f):
            continue
        file_id = (f.get("id") or "").strip()
        url = (f.get("url_private_download") or f.get("url_private") or "").strip()
        if not file_id or not url:
            continue
        ext = (f.get("filetype") or "").strip().lower() or "bin"
        cache_dir = os.path.join(PROJECT_ROOT, "cache", "slack_task_update_audio")
        os.makedirs(cache_dir, exist_ok=True)
        audio_path = os.path.join(cache_dir, f"{slack_sync._safe_filename(file_id)}.{ext}")
        txt_path = os.path.join(cache_dir, f"{slack_sync._safe_filename(file_id)}.txt")
        if dry_run:
            return "[transcript dry-run]", True
        if os.path.isfile(txt_path):
            cached = Path(txt_path).read_text(encoding="utf-8").strip()
            if cached:
                return cached, True
        if not os.path.isfile(audio_path):
            slack_sync._download_slack_file(slack_token, url, audio_path)
        transcript = slack_sync._transcribe_audio(audio_path, whisper_provider).strip()
        if transcript:
            Path(txt_path).write_text(transcript, encoding="utf-8")
            return transcript, True
    return text, False


def _recent_bot_context(
    messages: Sequence[Dict[str, Any]],
    index: int,
    bot_user_id: str,
    *,
    max_messages: int,
    window_hours: int,
) -> str:
    current_ts = slack_sync.ts_to_epoch_seconds(messages[index].get("ts", ""))
    if current_ts <= 0:
        return ""
    cutoff = current_ts - (window_hours * 3600)
    parts: List[str] = []
    for prior in reversed(messages[:index]):
        ts = slack_sync.ts_to_epoch_seconds(prior.get("ts", ""))
        if ts < cutoff:
            break
        if (prior.get("user") or "").strip() != bot_user_id:
            continue
        text = _compact(prior.get("text") or "")
        if not text:
            continue
        parts.append(_truncate(text, 700))
        if len(parts) >= max_messages:
            break
    parts.reverse()
    return "\n---\n".join(parts)


def _message_anchor_iso(slack_ts: str) -> str:
    return safe_date_from_slack_ts(slack_ts).isoformat()


def _resolve_due_date(decision: UpdateDecision, message_text: str, slack_context: str, slack_ts: str) -> str:
    anchor = safe_date_from_slack_ts(slack_ts)
    due = clamp_due_iso(decision.due_date, anchor)
    if due:
        return due
    return infer_due_from_text(" ".join([message_text, slack_context]), anchor)


def _find_candidate(candidates: Sequence[TaskCandidate], candidate_id: str) -> Optional[TaskCandidate]:
    target = (candidate_id or "").strip()
    if not target:
        return None
    for candidate in candidates:
        if candidate.candidate_id == target:
            return candidate
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Update Notion tasks from Slack DM messages")
    parser.add_argument("--days", type=int, default=3, help="Read Slack messages from the last N days")
    parser.add_argument("--full-refresh", action="store_true", help="Ignore saved cursor and reread the window")
    parser.add_argument("--dry-run", action="store_true", help="Print intended updates without modifying Notion or notes")
    parser.add_argument("--limit", type=int, default=0, help="Process at most N human messages (0 = all)")
    parser.add_argument("--candidate-limit", type=int, default=25, help="Max Notion candidates sent to the LLM")
    parser.add_argument("--confidence", type=float, default=0.75, help="Minimum confidence to apply complete (default: 0.75)")
    parser.add_argument("--timeout", type=int, default=90, help="LLM timeout in seconds")
    parser.add_argument("--llm-provider", choices=("openai", "groq", "ollama", "auto"), default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--ollama-url", default=os.getenv("OLLAMA_URL", "http://127.0.0.1:11434"))
    parser.add_argument("--context-messages", type=int, default=3, help="Recent bot messages to include as context")
    parser.add_argument("--context-hours", type=int, default=24, help="How far back to look for bot context")
    parser.add_argument("--mark-obsidian-notes", dest="mark_obsidian_notes", action="store_true", default=True)
    parser.add_argument("--no-mark-obsidian-notes", dest="mark_obsidian_notes", action="store_false")
    parser.add_argument("--audio", dest="audio", action="store_true", default=True)
    parser.add_argument("--no-audio", dest="audio", action="store_false")
    parser.add_argument(
        "--whisper-provider",
        choices=("openai", "local", "auto"),
        default=None,
        help="Transcription backend for audio-only Slack messages",
    )
    args = parser.parse_args()

    if args.days <= 0:
        raise SystemExit("--days must be > 0")
    if args.candidate_limit <= 0:
        raise SystemExit("--candidate-limit must be > 0")

    slack_token = _require_env("SLACK_BOT_TOKEN").strip().strip('"').strip("'")
    if not slack_token.startswith("xoxb-"):
        raise SystemExit("SLACK_BOT_TOKEN must be a Bot User OAuth token (starts with xoxb-).")
    slack_channel = _require_env("SLACK_DM_CHANNEL_ID").strip()
    human_user_id = (os.getenv("SLACK_HUMAN_USER_ID") or "").strip() or None
    notion_token = _require_env("NOTION_API_TOKEN")
    database_id = resolve_tasks_db_id()

    llm = build_llm_config(args.llm_provider, args.model, args.ollama_url)
    try:
        validate_llm_config(llm)
    except ValueError as e:
        raise SystemExit(str(e)) from e
    if llm.provider == "ollama" and not ollama_is_reachable(llm.ollama_url):
        raise SystemExit(
            f"Ollama not reachable at {llm.ollama_url}. "
            "Start `ollama serve` or set OPENAI_API_KEY / LLM_PROVIDER=openai."
        )

    whisper_provider = slack_sync.resolve_whisper_provider(args.whisper_provider)
    if args.audio and whisper_provider == "openai" and not (os.getenv("OPENAI_API_KEY") or "").strip():
        raise SystemExit("Audio transcription with openai requires OPENAI_API_KEY.")

    log.info(f"Slack channel: {slack_channel}")
    log.info(f"Notion tasks DB: {database_id}")
    log.info(f"LLM: {llm.label}")

    bot_user_id = slack_sync._slack_bot_user_id(slack_token)
    state = SlackTaskUpdateStateStore(PROJECT_ROOT)
    last_ts = None if args.full_refresh else state.load_last_ts(slack_channel)
    if last_ts:
        log.info(f"Loaded task-update Slack cursor last_ts={last_ts}")

    raw_messages = slack_sync.fetch_messages_incremental(
        slack_token=slack_token,
        channel_id=slack_channel,
        days=args.days,
        last_ts=last_ts,
        full_refresh=args.full_refresh,
    )
    raw_messages.sort(key=lambda m: slack_sync.ts_to_epoch_seconds(m.get("ts", "")))
    human_indexes = [
        i
        for i, msg in enumerate(raw_messages)
        if slack_sync.is_human_message_to_bot(msg, bot_user_id, human_user_id)
    ]
    if args.limit > 0:
        human_indexes = human_indexes[: args.limit]
    log.info(f"Fetched {len(raw_messages)} message(s); {len(human_indexes)} human message(s) to inspect.")

    if not human_indexes:
        return 0

    notion = Client(auth=notion_token, notion_version="2025-09-03")
    ds_id, db_props = get_ds_and_props(notion, database_id)
    prop_map = _build_task_prop_map(db_props)
    all_pages = _query_all_pages(notion, database_id, ds_id)
    log.info(f"Loaded {len(all_pages)} Notion page(s) from tasks DB.")

    vault_path = _strip_quotes(os.getenv("OBSIDIAN_VAULT_PATH") or "")
    input_rel = (os.getenv("SLACK_INPUT_OBSIDIAN_REL") or "").strip() or default_input_rel_dir()
    workspace_domain = (os.getenv("SLACK_WORKSPACE_DOMAIN") or "").strip().strip('"').strip("'")

    applied = 0
    ignored = 0
    unmatched = 0
    failed = 0
    audit_path = default_audit_path(PROJECT_ROOT)
    cursor_advance_ts = ""
    cursor_advance_epoch = 0.0

    def _audit(slack_ts: str, outcome: str, **fields: Any) -> None:
        append_audit_entry(
            audit_path,
            build_audit_entry(slack_ts=slack_ts, outcome=outcome, dry_run=args.dry_run, **fields),
            dry_run=args.dry_run,
        )

    def _note_cursor(slack_ts: str, ts_epoch: float, outcome: str) -> None:
        nonlocal cursor_advance_ts, cursor_advance_epoch
        if should_advance_cursor(outcome) and ts_epoch >= cursor_advance_epoch:
            cursor_advance_epoch = ts_epoch
            cursor_advance_ts = slack_ts

    for idx in human_indexes:
        message = raw_messages[idx]
        slack_ts = (message.get("ts") or "").strip()
        ts_epoch = slack_sync.ts_to_epoch_seconds(slack_ts)

        try:
            message_text, transcribed = _extract_message_text(
                message=message,
                slack_token=slack_token,
                audio=args.audio,
                whisper_provider=whisper_provider,
                dry_run=args.dry_run,
            )
        except Exception as e:
            failed += 1
            log.info(f"[error] ts={slack_ts}: could not read message/audio: {e}")
            _audit(slack_ts, OUTCOME_FAILED, reason=str(e))
            continue

        if not message_text.strip():
            _audit(slack_ts, OUTCOME_EMPTY, gate=GATE_NO_PHRASE)
            _note_cursor(slack_ts, ts_epoch, OUTCOME_EMPTY)
            continue

        if not message_requests_complete(message_text):
            log.info(f"ts={slack_ts}: skip — {GATE_SKIP_REASON}")
            _audit(slack_ts, OUTCOME_GATE_SKIP, gate=GATE_NO_PHRASE, reason=GATE_SKIP_REASON)
            _note_cursor(slack_ts, ts_epoch, OUTCOME_GATE_SKIP)
            continue

        context = _recent_bot_context(
            raw_messages,
            idx,
            bot_user_id,
            max_messages=max(0, args.context_messages),
            window_hours=max(0, args.context_hours),
        )
        query_text = " ".join([message_text, context])
        candidates = _rank_candidates(
            pages=all_pages,
            prop_map=prop_map,
            query_text=query_text,
            include_terminal=False,
            limit=args.candidate_limit,
        )
        anchor_iso = _message_anchor_iso(slack_ts)
        permalink = _permalink_for_message(workspace_domain, slack_channel, slack_ts)

        try:
            decision = _decision_complete_from_llm(
                llm, message_text, context, candidates, anchor_iso, args.timeout
            )
        except Exception as e:
            failed += 1
            log.info(f"[error] ts={slack_ts}: LLM failed: {e}")
            _audit(
                slack_ts,
                OUTCOME_FAILED,
                gate=GATE_PHRASE_MATCH,
                action=ACTION_COMPLETE,
                model=llm.label,
                reason=str(e),
                transcribed=transcribed,
            )
            _record_task_update_note(
                vault_path=vault_path,
                input_rel=input_rel,
                slack_ts=slack_ts,
                message_text=message_text,
                source_url=permalink,
                transcribed=transcribed,
                status="failed",
                action=ACTION_COMPLETE,
                page_id="",
                model_label=llm.label,
                reason=str(e),
                dry_run=args.dry_run,
                enabled=args.mark_obsidian_notes,
            )
            continue

        prefix = "[audio] " if transcribed else ""
        log.info(
            f"{prefix}ts={slack_ts}: action={decision.action} candidate={decision.candidate_id or '-'} "
            f"confidence={decision.confidence:.2f}"
        )

        if decision.confidence < args.confidence:
            ignored += 1
            _audit(
                slack_ts,
                OUTCOME_IGNORED,
                gate=GATE_PHRASE_MATCH,
                action=decision.action,
                confidence=decision.confidence,
                model=llm.label,
                reason=decision.reason or "Below confidence threshold.",
                transcribed=transcribed,
            )
            _record_task_update_note(
                vault_path=vault_path,
                input_rel=input_rel,
                slack_ts=slack_ts,
                message_text=message_text,
                source_url=permalink,
                transcribed=transcribed,
                status="ignored",
                action=decision.action,
                page_id="",
                model_label=llm.label,
                reason=decision.reason or "Below confidence threshold.",
                dry_run=args.dry_run,
                enabled=args.mark_obsidian_notes,
            )
            continue

        task = _find_candidate(candidates, decision.candidate_id)
        if not task:
            unmatched += 1
            reason = decision.reason or "No clear Notion task candidate."
            log.info(f"[unmatched] ts={slack_ts}: {reason}")
            _audit(
                slack_ts,
                OUTCOME_UNMATCHED,
                gate=GATE_PHRASE_MATCH,
                action=decision.action,
                confidence=decision.confidence,
                model=llm.label,
                reason=reason,
                transcribed=transcribed,
            )
            _record_task_update_note(
                vault_path=vault_path,
                input_rel=input_rel,
                slack_ts=slack_ts,
                message_text=message_text,
                source_url=permalink,
                transcribed=transcribed,
                status="unmatched",
                action=decision.action,
                page_id="",
                model_label=llm.label,
                reason=reason,
                dry_run=args.dry_run,
                enabled=args.mark_obsidian_notes,
            )
            continue

        try:
            ok, detail = _apply_update(
                client=notion,
                prop_map=prop_map,
                task=task,
                decision=decision,
                dry_run=args.dry_run,
            )
        except Exception as e:
            failed += 1
            log.info(f"[error] ts={slack_ts}: Notion update failed for {task.title!r}: {e}")
            _audit(
                slack_ts,
                OUTCOME_FAILED,
                gate=GATE_PHRASE_MATCH,
                action=decision.action,
                page_id=task.page_id,
                title=task.title,
                confidence=decision.confidence,
                model=llm.label,
                reason=str(e),
                transcribed=transcribed,
            )
            _record_task_update_note(
                vault_path=vault_path,
                input_rel=input_rel,
                slack_ts=slack_ts,
                message_text=message_text,
                source_url=permalink,
                transcribed=transcribed,
                status="failed",
                action=decision.action,
                page_id=task.page_id,
                model_label=llm.label,
                reason=str(e),
                dry_run=args.dry_run,
                enabled=args.mark_obsidian_notes,
            )
            continue

        if not ok:
            failed += 1
            log.info(f"[error] ts={slack_ts}: {detail}")
            _audit(
                slack_ts,
                OUTCOME_FAILED,
                gate=GATE_PHRASE_MATCH,
                action=decision.action,
                page_id=task.page_id,
                title=task.title,
                confidence=decision.confidence,
                model=llm.label,
                reason=detail,
                transcribed=transcribed,
            )
            _record_task_update_note(
                vault_path=vault_path,
                input_rel=input_rel,
                slack_ts=slack_ts,
                message_text=message_text,
                source_url=permalink,
                transcribed=transcribed,
                status="failed",
                action=decision.action,
                page_id=task.page_id,
                model_label=llm.label,
                reason=detail,
                dry_run=args.dry_run,
                enabled=args.mark_obsidian_notes,
            )
            continue

        applied += 1
        log.info(f"[ok] {decision.action}: {task.title!r} ({task.page_id}) — {detail}")
        _audit(
            slack_ts,
            OUTCOME_APPLIED,
            gate=GATE_PHRASE_MATCH,
            action=decision.action,
            page_id=task.page_id,
            title=task.title,
            confidence=decision.confidence,
            model=llm.label,
            reason=decision.reason,
            transcribed=transcribed,
        )
        _note_cursor(slack_ts, ts_epoch, OUTCOME_APPLIED)
        _record_task_update_note(
            vault_path=vault_path,
            input_rel=input_rel,
            slack_ts=slack_ts,
            message_text=message_text,
            source_url=permalink,
            transcribed=transcribed,
            status="true",
            action=decision.action,
            page_id=task.page_id,
            model_label=llm.label,
            reason=decision.reason,
            dry_run=args.dry_run,
            enabled=args.mark_obsidian_notes,
        )

    if cursor_advance_ts and not args.dry_run:
        state.save_last_ts(slack_channel, cursor_advance_ts)
        log.info(f"Saved task-update Slack cursor last_ts={cursor_advance_ts}")

    log.info(f"Done. applied={applied} unmatched={unmatched} ignored={ignored} failed={failed}")
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
