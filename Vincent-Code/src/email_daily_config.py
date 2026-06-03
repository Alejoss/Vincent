"""
Daily email config: parse instructions (section 3) from plan_inicial_emails_diarios.md
and map section names to Notion query (filter + sorts + limit).
"""

import re
import logging
from typing import Dict, List, Any, Optional, Tuple

logger = logging.getLogger(__name__)

# Weekday order in the plan: Lunes=0, Martes=1, ..., Viernes=4 (Python weekday: Monday=0)
WEEKDAY_NAMES = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes"]

# Base filter: exclude Archivado; optionally exclude Hecho (plan: "normalmente también Hecho")
ESTADOS_OPEN = ["Inbox/Todo", "Pendiente", "En progreso"]
ESTADO_BLOQUEADO = "Bloqueado"
ESTADO_ARCHIVADO = "Archivado"
ESTADO_HECHO = "Hecho"


def parse_plan_md(md_path: str) -> Dict[int, Dict[str, Any]]:
    """
    Parse plan_inicial_emails_diarios.md and return weekday_index (0=Mon .. 4=Fri) -> {
      "focus_title": str,
      "sections": [ {"label": str, "emoji": str, "limit": int}, ... ]
    }
    """
    try:
        with open(md_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        logger.warning("Could not read plan MD %s: %s", md_path, e)
        return {}

    # Find "### 3) Edición rápida" and take content until next ###
    start = content.find("### 3)")
    if start == -1:
        return {}
    end = content.find("\n### ", start + 1)
    block = content[start : end if end != -1 else len(content)]

    result: Dict[int, Dict[str, Any]] = {}
    current_day: Optional[int] = None
    current_focus = ""
    current_sections: List[Dict[str, Any]] = []

    for line in block.splitlines():
        line = line.strip()
        if not line:
            continue
        # Day header: "🟢 Lunes — Foco semanal" or "Lunes — Foco semanal"
        for i, day_name in enumerate(WEEKDAY_NAMES):
            if day_name in line and not line.startswith("-"):
                # Save previous day
                if current_day is not None:
                    result[current_day] = {"focus_title": current_focus, "sections": current_sections}
                # Parse this line: "X Lunes — Focus title"
                parts = line.split("—", 1)
                current_focus = (parts[1].strip() if len(parts) > 1 else "").strip()
                if not current_focus:
                    current_focus = day_name
                current_day = i
                current_sections = []
                break
        else:
            # Bullet: "- 🔥 Prioridades (3)" or "- Prioridades (3)"
            if line.startswith("-") and current_day is not None:
                rest = line[1:].strip()
                match = re.search(r"\((\d+)\)\s*$", rest)
                limit = int(match.group(1)) if match else 3
                label_part = rest[: match.start()].strip() if match else rest
                # Optional leading emoji (single codepoint or short sequence)
                emoji = ""
                label = label_part
                if label_part:
                    # Take leading emoji(s): non-ASCII run
                    for i, c in enumerate(label_part):
                        if ord(c) < 128 and c not in " \t":
                            emoji = label_part[:i].strip()
                            label = label_part[i:].strip()
                            break
                        if c.isalnum() or c in "()":
                            if i > 0:
                                emoji = label_part[:i].strip()
                                label = label_part[i:].strip()
                            break
                if not label:
                    label = label_part
                current_sections.append({"label": label, "emoji": emoji or "•", "limit": limit})

    if current_day is not None:
        result[current_day] = {"focus_title": current_focus, "sections": current_sections}

    return result


def _estado_filter(prop_name: str, prop_type: str, values: List[str]) -> Dict:
    """Build filter for Estado in values (or equals if single)."""
    if prop_type == "status":
        if len(values) == 1:
            return {"property": prop_name, "status": {"equals": values[0]}}
        return {"or": [{"property": prop_name, "status": {"equals": v}} for v in values]}
    # select
    if len(values) == 1:
        return {"property": prop_name, "select": {"equals": values[0]}}
    return {"or": [{"property": prop_name, "select": {"equals": v}} for v in values]}


def _tipo_filter(prop_name: str, value: str) -> Dict:
    return {"property": prop_name, "select": {"equals": value}}


def build_section_query(
    section_label: str,
    limit: int,
    prop_names: Dict[str, Dict[str, Any]],
    exclude_hecho: bool = True,
    date_window_days: Optional[int] = None,
) -> Tuple[Dict[str, Any], List[Dict], int]:
    """
    Return (filter, sorts, page_size) for the given section.
    prop_names is from VincentNotionClient.get_vincent_property_names().
    """
    estado_info = prop_names.get("estado", {})
    tipo_info = prop_names.get("tipo", {})
    fecha_info = prop_names.get("fecha", {})
    priority_info = prop_names.get("priority_score", {})
    estado_name = (estado_info or {}).get("name")
    estado_type = (estado_info or {}).get("type", "select")
    tipo_name = (tipo_info or {}).get("name")
    fecha_name = (fecha_info or {}).get("name")
    priority_name = (priority_info or {}).get("name")

    # Base: exclude Archivado (and optionally Hecho)
    and_parts: List[Dict] = []
    key = "status" if estado_type == "status" else "select"
    if estado_name:
        and_parts.append({"property": estado_name, key: {"does_not_equal": ESTADO_ARCHIVADO}})
        if exclude_hecho:
            and_parts.append({"property": estado_name, key: {"does_not_equal": ESTADO_HECHO}})

    label_lower = (section_label or "").lower().strip()
    sorts: List[Dict] = []
    if priority_name:
        sorts.append({"property": priority_name, "direction": "descending"})
    if fecha_name:
        sorts.append({"property": fecha_name, "direction": "descending"})

    # Section-specific filter and sort
    if "prioridades" in label_lower or "tareas críticas" in label_lower or "3 tareas" in label_lower:
        if estado_name:
            and_parts.append(_estado_filter(estado_name, estado_type, ESTADOS_OPEN))
        return ({"and": and_parts} if len(and_parts) > 1 else (and_parts[0] if len(and_parts) == 1 else {}), sorts, limit)

    if "bloqueos" in label_lower or "bloqueado" in label_lower:
        if estado_name:
            and_parts.append(_estado_filter(estado_name, estado_type, [ESTADO_BLOQUEADO]))
        return ({"and": and_parts} if len(and_parts) > 1 else (and_parts[0] if len(and_parts) == 1 else {}), sorts, limit)

    if "decisiones recientes" in label_lower and tipo_name:
        and_parts.append(_tipo_filter(tipo_name, "Decisiones"))
        if date_window_days and fecha_name:
            # Fecha in last N days
            from datetime import datetime, timedelta
            start = (datetime.now() - timedelta(days=date_window_days)).strftime("%Y-%m-%d")
            and_parts.append({"property": fecha_name, "date": {"on_or_after": start}})
        return ({"and": and_parts} if and_parts else {}, sorts, limit)

    if "aprendizajes recientes" in label_lower and tipo_name:
        and_parts.append(_tipo_filter(tipo_name, "Logs"))
        return ({"and": and_parts} if and_parts else {}, sorts, limit)

    if ("problemas abiertos" in label_lower or "problemas activos" in label_lower) and tipo_name:
        and_parts.append(_tipo_filter(tipo_name, "Problemas"))
        if estado_name:
            and_parts.append(_estado_filter(estado_name, estado_type, ESTADOS_OPEN + [ESTADO_BLOQUEADO]))
        return ({"and": and_parts} if and_parts else {}, sorts, limit)

    if "problema recurrente" in label_lower and tipo_name:
        and_parts.append(_tipo_filter(tipo_name, "Problemas"))
        return ({"and": and_parts} if and_parts else {}, sorts, min(limit, 1))

    if "vence pronto" in label_lower:
        # Vincent has no due_date; use open tasks by priority
        if estado_name:
            and_parts.append(_estado_filter(estado_name, estado_type, ESTADOS_OPEN))
        return ({"and": and_parts} if and_parts else {}, sorts, limit)

    if "inbox viejo" in label_lower and estado_name:
        and_parts.append(_estado_filter(estado_name, estado_type, ["Inbox/Todo"]))
        if fecha_name:
            sorts = [{"property": fecha_name, "direction": "ascending"}]
        return ({"and": and_parts} if and_parts else {}, sorts, limit)

    if "ideas" in label_lower and tipo_name:
        and_parts.append(_tipo_filter(tipo_name, "Ideas"))
        return ({"and": and_parts} if and_parts else {}, sorts, limit)

    if "métricas" in label_lower and tipo_name:
        and_parts.append(_tipo_filter(tipo_name, "Metrics"))
        return ({"and": and_parts} if and_parts else {}, sorts, limit)

    # Default: open items, by priority/date
    if estado_name:
        and_parts.append(_estado_filter(estado_name, estado_type, ESTADOS_OPEN))
    return ({"and": and_parts} if and_parts else (and_parts[0] if len(and_parts) == 1 else {}), sorts, limit)
