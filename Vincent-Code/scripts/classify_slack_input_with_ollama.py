"""
Classify Slack productivity notes in Obsidian with a local or cloud LLM.

Purpose
- Convert raw Slack captures into structured productivity entries.
- Produce stable metadata used by the Notion sync script.

LLM backend (env LLM_PROVIDER=openai|groq|ollama|auto):
- auto: OPENAI_API_KEY -> OpenAI; GROQ_API_KEY -> Groq; else local Ollama
- See src/llm_client.py
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple
import shutil

from dotenv import load_dotenv

SCRIPTS_DIR = os.path.dirname(__file__)
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPTS_DIR, ".."))
sys.path.insert(0, PROJECT_ROOT)

from src.llm_client import LLMConfig, build_llm_config, call_json, ollama_is_reachable, validate_llm_config
from src.slack_inbox_obsidian import default_input_rel_dir, resolve_input_dir
from src.productivity_dates import anchor_date, clamp_due_iso, infer_due_from_text

load_dotenv(override=True)

log = logging.getLogger("classify_slack_input")
logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)

VALID_TYPES = {"Tarea", "Idea", "Aprendizaje"}
VALID_PROJECTS = {
    "Creacion de Contenido",
    "Desarrollo de Software para Academia Blockchain",
    "Desarrollo de Software para Vincent",
    "General - Otros",
}
INPUT_FOLDER = "Input"
TASKS_IDEAS_FOLDER = "Tareas-Ideas"
LEARNINGS_FOLDER = "Aprendizajes"
PROJECTS_FOLDER = "Projects"
SLACK_BODY_SECTION = "## Contenido completo (Slack)"

# Notion title: Ollama must produce a complete headline (never truncated in code).
MAX_TITLE_CHARS = 72

# Final words that suggest an incomplete phrase (reject → retry LLM).
_DANGLING_ENDINGS = (
    " el",
    " la",
    " los",
    " las",
    " de",
    " del",
    " en",
    " un",
    " una",
    " que",
    " con",
    " por",
    " al",
    " a",
    " y",
    " como",
    " mi",
    " tu",
    " su",
    " sus",
    " o",
)


def _require_env(name: str) -> str:
    value = (os.getenv(name) or "").strip()
    if not value:
        raise SystemExit(f"Missing required env var: {name}")
    return value


def _split_frontmatter(content: str) -> Tuple[Dict[str, str], str]:
    text = content or ""
    if not text.startswith("---\n"):
        return {}, text

    end = text.find("\n---\n", 4)
    if end == -1:
        return {}, text

    fm_block = text[4:end]
    body = text[end + 5 :]

    data: Dict[str, str] = {}
    for line in fm_block.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        data[key.strip()] = value.strip()
    return data, body


def _quote_yaml(value: str) -> str:
    escaped = (value or "").replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _compose_note(frontmatter: Dict[str, str], body: str) -> str:
    lines: List[str] = ["---"]
    for key, value in frontmatter.items():
        lines.append(f"{key}: {value}")
    lines.extend(["---", "", (body or "").strip(), ""])
    return "\n".join(lines)


def _extract_slack_plain(body: str) -> str:
    """Return only the raw Slack message text (strip classifier headers / prior sections)."""
    text = (body or "").strip()
    if SLACK_BODY_SECTION in text:
        after = text.split(SLACK_BODY_SECTION, 1)[1].lstrip("\n")
        return after.strip()

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


def _build_classified_body(
    tipo: str,
    proyecto: str,
    referencia_temporal: str,
    fecha_objetivo: str,
    titulo_corto: str,
    recordatorio_slack: str,
    slack_plain: str,
) -> str:
    rec_line = (recordatorio_slack or "").strip() or "N/A"
    parts = [
        f"Tipo de entrada: {tipo}",
        f"Proyecto: {proyecto}",
        f"Referencia temporal: {referencia_temporal or 'N/A'}",
        f"Fecha objetivo: {fecha_objetivo or 'N/A'}",
        f"Titulo: {titulo_corto}",
        f"Recordatorio Slack: {rec_line}",
        "",
        SLACK_BODY_SECTION,
        "",
        (slack_plain or "").strip(),
    ]
    return "\n".join(parts).strip()


def _build_prompt(note_text: str) -> str:
    return (
        "Clasifica la siguiente nota en EXACTAMENTE una categoria y un proyecto.\n"
        "Categorias validas: Tarea, Idea, Aprendizaje.\n"
        "Proyectos validos (elige SOLO uno):\n"
        "- Creacion de Contenido\n"
        "- Desarrollo de Software para Academia Blockchain\n"
        "- Desarrollo de Software para Vincent\n"
        "- General - Otros\n"
        "Reglas:\n"
        "- Tarea: accion concreta, pendiente, seguimiento o compromiso ejecutable.\n"
        "- Idea: propuesta, posibilidad, concepto a explorar, sin accion inmediata.\n"
        "- Aprendizaje: insight, leccion, conclusion o conocimiento adquirido.\n"
        "- Si hay mezcla, elige la intencion principal.\n"
        "- Si no hay suficiente contexto de proyecto, usa General - Otros.\n"
        "- Detecta referencias temporales relevantes para ejecucion o cierre, por ejemplo: "
        "hoy, manana, esta semana, la proxima semana, el proximo mes, el 21 de abril.\n"
        "- 'esta semana' / 'la proxima semana' / 'siguiente semana': fecha_objetivo = viernes de esa semana.\n"
        "- Diferencia: 'el viernes' = el viernes de la semana en curso si aun no paso; "
        "'el proximo viernes' / 'el viernes que viene' = viernes de la semana siguiente.\n"
        "- fecha_objetivo debe estar en formato YYYY-MM-DD si se puede inferir; si no, deja cadena vacia.\n"
        "- referencia_temporal debe conservar la frase original cuando exista; si no, cadena vacia.\n"
        "- titulo_corto:\n"
        f"  Titular en español, maximo {MAX_TITLE_CHARS} caracteres, frase COMPLETA.\n"
        "  Lee toda la transcripcion y sintetiza; no copies solo el inicio.\n"
        "  Sin comillas, sin '...', sin saltos de linea.\n"
        "- recordatorio_slack: si tipo es Aprendizaje, cadena vacia. Si es Tarea o Idea, "
        "UNA sola pregunta en español en segunda persona (tu), maximo 130 caracteres, "
        "como recordatorio conversacional del dia del vencimiento (ej. titulo sobre responder a alguien -> "
        "¿Ya le respondiste a...?). Debe terminar en un solo signo de interrogacion. Sin markdown ni comillas.\n"
        "Responde SOLO JSON valido con esta forma exacta:\n"
        '{"tipo":"Tarea|Idea|Aprendizaje","proyecto":"...","titulo_corto":"...",'
        '"referencia_temporal":"...","fecha_objetivo":"YYYY-MM-DD|","recordatorio_slack":"...",'
        '"confianza":0.0,"razon":"..."}\n'
        "Nota:\n"
        f"{note_text.strip()}\n"
    )


def _build_title_prompt(note_text: str, hint: str = "") -> str:
    extra = f"\nCorreccion: {hint.strip()}\n" if (hint or "").strip() else ""
    return (
        "Transcripcion COMPLETA de un mensaje de voz (puede tener varias frases).\n"
        "Lee TODO el texto antes de escribir el titulo.\n"
        "Escribe UN titular para Notion: una sola frase que condense la intencion de TODA la transcripcion.\n"
        "Reglas estrictas:\n"
        f"- Maximo {MAX_TITLE_CHARS} caracteres (cuenta bien; no exceder).\n"
        "- Frase gramaticalmente completa; prohibido cortar a mitad de idea.\n"
        "- PROHIBIDO: copiar las primeras palabras del dictado, usar '...', o recortar el texto.\n"
        "- Sin comillas, sin saltos de linea.\n"
        f"{extra}"
        "Responde SOLO JSON:\n"
        '{"titulo_corto":"..."}\n'
        "---\n"
        "Transcripcion:\n"
        f"{note_text.strip()}\n"
    )


def _build_reminder_from_title_prompt(titulo_corto: str, tipo: str) -> str:
    return (
        "Convierte el titulo en UNA pregunta corta en español, segunda persona (tu), "
        "como recordatorio amable para Slack el dia del vencimiento.\n"
        "Reglas:\n"
        "- Una sola oracion interrogativa; un solo signo de interrogacion al final.\n"
        "- Maximo 130 caracteres; sin markdown ni comillas.\n"
        "- Reformula en natural (no copies el titulo palabra por palabra si puedes mejorarlo).\n"
        "Responde SOLO JSON: {\"recordatorio_slack\":\"...\"}\n"
        f"Tipo: {tipo}\nTitulo: {titulo_corto.strip()}\n"
    )


def _call_llm(config: LLMConfig, prompt: str, timeout_s: int) -> Dict[str, object]:
    return call_json(prompt, config, timeout_s=timeout_s)


def _normalize_title_line(raw: str) -> str:
    s = (raw or "").replace('"', "").strip()
    s = s.replace("\n", " ")
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def _strip_ellipsis(title: str) -> str:
    t = _normalize_title_line(title)
    while t.endswith("..."):
        t = t[:-3].rstrip()
    if t.endswith("…"):
        t = t[:-1].rstrip()
    return t


def _title_ends_incomplete(title: str) -> bool:
    t = _normalize_title_line(title)
    if not t:
        return True
    if t.endswith("...") or t.endswith("…"):
        return True
    low = t.lower()
    return any(low.endswith(w.strip()) for w in _DANGLING_ENDINGS)


def _title_is_prefix_of_transcript(title: str, slack_plain: str) -> bool:
    """True when the title is basically a copy of the start of the message, not a summary."""
    t = _strip_ellipsis(title).lower()
    s = " ".join((slack_plain or "").strip().lower().split())
    if not t or not s:
        return False
    if s.startswith(t) and len(s) > len(t) + 8:
        return True
    if len(t) >= max(20, int(len(s) * 0.88)) and s.startswith(t[: max(15, len(t) - 5)]):
        return True
    return False


def _title_is_valid(title: str, slack_plain: str) -> bool:
    t = _strip_ellipsis(title)
    if not t or len(t.split()) < 3:
        return False
    if len(t) > MAX_TITLE_CHARS:
        return False
    if _title_ends_incomplete(t):
        return False
    if _title_is_prefix_of_transcript(t, slack_plain):
        return False
    return True


def _title_retry_hint(title: str, slack_plain: str) -> str:
    t = _strip_ellipsis(title)
    if len(t) > MAX_TITLE_CHARS:
        return (
            f"El titulo '{t}' tiene {len(t)} caracteres. "
            f"Reescribe uno nuevo de maximo {MAX_TITLE_CHARS} caracteres, frase completa."
        )
    if _title_ends_incomplete(t):
        return (
            f"El titulo '{t}' quedo incompleto. "
            f"Reescribe un titular completo (max {MAX_TITLE_CHARS} caracteres) sintetizando TODA la transcripcion."
        )
    if _title_is_prefix_of_transcript(t, slack_plain):
        return (
            "No copies el inicio del dictado. "
            f"Sintetiza toda la transcripcion en una frase completa (max "
            f"{MAX_TITLE_CHARS} caracteres)."
        )
    return f"Reescribe un titulo valido (max {MAX_TITLE_CHARS} caracteres, frase completa)."


def _generate_title_llm(
    config: LLMConfig,
    slack_plain: str,
    timeout_s: int,
    hint: str = "",
) -> str:
    try:
        obj = _call_llm(config, _build_title_prompt(slack_plain, hint), timeout_s)
        return _strip_ellipsis(str(obj.get("titulo_corto", "")))
    except Exception:
        return ""


def _resolve_titulo_corto(
    config: LLMConfig,
    slack_plain: str,
    _tipo: str,
    llm_primary: str,
    timeout_s: int,
) -> str:
    """
    titulo_corto for Notion: always from the LLM reading the full transcript.
    Never truncated in Python — if invalid or too long, retry with feedback.
    """
    primary = _strip_ellipsis(_normalize_title_line(llm_primary))
    if primary and _title_is_valid(primary, slack_plain):
        return primary

    hint = ""
    last = ""
    for _ in range(5):
        candidate = _generate_title_llm(config, slack_plain, timeout_s, hint)
        if not candidate:
            continue
        last = candidate
        if _title_is_valid(candidate, slack_plain):
            return candidate
        hint = _title_retry_hint(candidate, slack_plain)

    if primary and len(primary) <= MAX_TITLE_CHARS and not primary.endswith("..."):
        return primary
    return last if last and len(last) <= MAX_TITLE_CHARS else "Entrada Slack"


def _normalize_type(value: str) -> str:
    raw = (value or "").strip()
    if raw in VALID_TYPES:
        return raw
    low = raw.lower()
    if low == "tarea":
        return "Tarea"
    if low == "idea":
        return "Idea"
    if low == "aprendizaje":
        return "Aprendizaje"
    return ""


def _normalize_project(value: str) -> str:
    raw = (value or "").strip()
    if raw in VALID_PROJECTS:
        return raw
    low = raw.lower()
    if low in {"creacion de contenido", "creación de contenido", "contenido"}:
        return "Creacion de Contenido"
    if low in {
        "desarrollo de software para academia blockchain",
        "academia blockchain",
        "software academia blockchain",
    }:
        return "Desarrollo de Software para Academia Blockchain"
    if low in {"desarrollo de software para vincent", "software vincent", "vincent"}:
        return "Desarrollo de Software para Vincent"
    if low in {"general - otros", "general", "otros"}:
        return "General - Otros"
    return ""


def _sanitize_reminder_line(raw: str, tipo: str) -> str:
    s = (raw or "").strip().replace("\n", " ").replace('"', "").strip()
    if tipo == "Aprendizaje":
        return ""
    if len(s) > 200:
        s = s[:197].rstrip() + "..."
    if s and "?" not in s:
        s = s.rstrip(".! ") + "?"
    return s


def _reminder_from_title_llm(config: LLMConfig, titulo_corto: str, tipo: str, timeout_s: int) -> str:
    if tipo not in {"Tarea", "Idea"} or not (titulo_corto or "").strip():
        return ""
    try:
        obj = _call_llm(config, _build_reminder_from_title_prompt(titulo_corto, tipo), timeout_s)
        return _sanitize_reminder_line(str(obj.get("recordatorio_slack", "")), tipo)
    except Exception:
        return ""


def _classify_text(
    config: LLMConfig,
    note_text: str,
    timeout_s: int,
) -> Tuple[str, str, str, str, str, str, float, str]:
    prompt = _build_prompt(note_text)
    obj = _call_llm(config, prompt, timeout_s)

    tipo = _normalize_type(str(obj.get("tipo", "")))
    if not tipo:
        raise ValueError(f"Invalid tipo from model: {obj.get('tipo')!r}")
    proyecto = _normalize_project(str(obj.get("proyecto", "")))
    if not proyecto:
        raise ValueError(f"Invalid proyecto from model: {obj.get('proyecto')!r}")
    referencia_temporal = str(obj.get("referencia_temporal", "")).strip()
    fecha_objetivo = str(obj.get("fecha_objetivo", "")).strip()
    if fecha_objetivo:
        parts = fecha_objetivo.split("-")
        if len(parts) != 3 or any((not p.isdigit()) for p in parts):
            fecha_objetivo = ""

    try:
        confidence = float(obj.get("confianza", 0.0))
    except Exception:
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    titulo_corto = _normalize_title_line(str(obj.get("titulo_corto", "")))

    recordatorio_slack = _sanitize_reminder_line(str(obj.get("recordatorio_slack", "")), tipo)

    razon = str(obj.get("razon", "")).strip()
    return tipo, proyecto, titulo_corto, referencia_temporal, fecha_objetivo, recordatorio_slack, confidence, razon


def _iter_slack_notes(diario_root: str) -> List[Path]:
    roots = [
        Path(diario_root) / INPUT_FOLDER,
        Path(diario_root) / TASKS_IDEAS_FOLDER,
        Path(diario_root) / LEARNINGS_FOLDER,
    ]
    seen = set()
    notes: List[Path] = []
    for root in roots:
        if not root.exists():
            continue
        for path in sorted(root.glob("slack-*.md")):
            if not path.is_file():
                continue
            key = str(path.resolve()).lower()
            if key in seen:
                continue
            seen.add(key)
            notes.append(path)
    return notes


def _target_dir_for_type(diario_root: str, tipo: str) -> Path:
    if tipo == "Aprendizaje":
        return Path(diario_root) / LEARNINGS_FOLDER
    return Path(diario_root) / TASKS_IDEAS_FOLDER


def main() -> int:
    parser = argparse.ArgumentParser(description="Classify Slack Input notes with OpenAI, Groq, or Ollama")
    parser.add_argument(
        "--llm-provider",
        choices=("openai", "groq", "ollama", "auto"),
        default=None,
        help="LLM backend (default: LLM_PROVIDER env or auto)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Model name (default: LLM_MODEL / provider default)",
    )
    parser.add_argument(
        "--ollama-url",
        default=os.getenv("OLLAMA_URL", "http://127.0.0.1:11434"),
        help="Ollama base URL (only when provider=ollama)",
    )
    parser.add_argument("--timeout", type=int, default=90, help="Request timeout in seconds")
    parser.add_argument("--limit", type=int, default=0, help="Only process first N notes (0 = all)")
    parser.add_argument(
        "--reclassify",
        action="store_true",
        help="Reclassify even if tipo/proyecto already exist",
    )
    parser.add_argument("--dry-run", action="store_true", help="Do not modify files")
    args = parser.parse_args()

    llm = build_llm_config(args.llm_provider, args.model, args.ollama_url)
    try:
        validate_llm_config(llm)
    except ValueError as e:
        raise SystemExit(str(e)) from e

    if llm.provider == "ollama" and not ollama_is_reachable(llm.ollama_url):
        raise SystemExit(
            f"Ollama not reachable at {llm.ollama_url}. "
            "Start `ollama serve` or set OPENAI_API_KEY / LLM_PROVIDER=openai for cloud."
        )

    vault = _require_env("OBSIDIAN_VAULT_PATH")
    rel = (os.getenv("SLACK_INPUT_OBSIDIAN_REL") or "").strip() or default_input_rel_dir()
    input_dir = resolve_input_dir(vault, rel)
    diario_root = str(Path(input_dir).parent)

    os.makedirs(os.path.join(diario_root, TASKS_IDEAS_FOLDER), exist_ok=True)
    os.makedirs(os.path.join(diario_root, LEARNINGS_FOLDER), exist_ok=True)
    os.makedirs(os.path.join(diario_root, PROJECTS_FOLDER), exist_ok=True)

    notes = _iter_slack_notes(diario_root)
    if args.limit > 0:
        notes = notes[: args.limit]

    log.info(f"Input dir: {input_dir}")
    log.info(f"Diario root: {diario_root}")
    log.info(f"LLM: {llm.label}")
    log.info(f"Found {len(notes)} note(s)")

    processed = 0
    skipped = 0
    failed = 0

    for path in notes:
        raw = path.read_text(encoding="utf-8")
        fm, body = _split_frontmatter(raw)

        if (not args.reclassify) and fm.get("tipo") and fm.get("proyecto") and path.parent.name in {TASKS_IDEAS_FOLDER, LEARNINGS_FOLDER}:
            skipped += 1
            continue

        note_text = (body or "").strip()
        if not note_text:
            skipped += 1
            continue

        slack_plain = _extract_slack_plain(body) or note_text

        try:
            tipo, proyecto, titulo_corto, referencia_temporal, fecha_objetivo, recordatorio_slack, conf, razon = _classify_text(
                llm, slack_plain, args.timeout
            )
        except Exception as e:
            failed += 1
            log.info(f"[error] {path.name}: {e}")
            continue

        fm["tipo"] = _quote_yaml(tipo)
        fm["proyecto"] = _quote_yaml(proyecto)
        fm["referencia_temporal"] = _quote_yaml(referencia_temporal)
        anchor = anchor_date(fm.get("message_at", "").strip().strip('"'), fm.get("slack_ts", "").strip().strip('"'))
        fecha_objetivo = clamp_due_iso(fecha_objetivo, anchor)
        if not fecha_objetivo:
            fecha_objetivo = infer_due_from_text(slack_plain, anchor)
        fm["fecha_objetivo"] = _quote_yaml(fecha_objetivo)
        titulo_corto = _resolve_titulo_corto(
            llm,
            slack_plain,
            tipo,
            titulo_corto,
            args.timeout,
        )
        fm["titulo_corto"] = _quote_yaml(titulo_corto)
        if tipo in {"Tarea", "Idea"} and not (recordatorio_slack or "").strip():
            recordatorio_slack = _reminder_from_title_llm(llm, titulo_corto, tipo, args.timeout)
        if tipo == "Aprendizaje":
            recordatorio_slack = ""
        fm["recordatorio_slack"] = _quote_yaml(recordatorio_slack)
        fm["clasificacion_confianza"] = f"{conf:.2f}"
        fm["clasificacion_modelo"] = _quote_yaml(llm.label)
        fm["clasificacion_actualizada"] = _quote_yaml(datetime.now(tz=timezone.utc).isoformat())
        if razon:
            fm["clasificacion_razon"] = _quote_yaml(razon[:500])
        body_with_headers = _build_classified_body(
            tipo, proyecto, referencia_temporal, fecha_objetivo, titulo_corto, recordatorio_slack, slack_plain
        )
        target_dir = _target_dir_for_type(diario_root, tipo)
        target_path = target_dir / path.name

        if args.dry_run:
            log.info(f"[dry-run] {path.name}: {tipo} | {proyecto} | {titulo_corto!r} ({conf:.2f}) -> {target_dir.name}")
            processed += 1
            continue

        updated = _compose_note(fm, body_with_headers)
        path.write_text(updated, encoding="utf-8", newline="\n")
        if str(path.resolve()).lower() != str(target_path.resolve()).lower():
            if target_path.exists():
                target_path.unlink()
            shutil.move(str(path), str(target_path))
        log.info(f"[ok] {path.name}: {tipo} | {proyecto} | {titulo_corto!r} ({conf:.2f})")
        processed += 1

    log.info(f"Done. processed={processed} skipped={skipped} failed={failed}")
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
