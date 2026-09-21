"""Mirror authoritative Notion properties without rewriting the Slack source."""

import json
import re
from pathlib import Path


def property_value(prop: dict) -> str:
    kind = prop.get("type", "")
    value = prop.get(kind)
    if kind in {"title", "rich_text"}:
        return "".join(p.get("plain_text", p.get("text", {}).get("content", "")) for p in value or [])
    if kind in {"select", "status"}:
        return (value or {}).get("name", "")
    if kind == "date":
        return (value or {}).get("start", "")
    return value if isinstance(value, str) else ""


def mirror_page(path: Path, page: dict, prop_map: dict, database_id: str, dry_run: bool = False) -> bool:
    """Update shared fields, including explicit clears; preserve unrelated note content."""
    raw = path.read_text(encoding="utf-8")
    if not raw.startswith("---\n") or "\n---\n" not in raw[4:]:
        raise ValueError(f"Missing note frontmatter: {path}")
    header, body = raw[4:].split("\n---\n", 1)
    fields = {"notion_page_id": page["id"], "notion_database_id": database_id,
              "notion_archived": bool(page.get("archived") or page.get("in_trash"))}
    properties = page.get("properties", {})
    mapping = {"title": "titulo_corto", "tipo": "tipo", "proyecto": "proyecto",
               "estado": "estado", "inicio": "inicio", "fin": "fecha_objetivo",
               "referencia_temporal": "referencia_temporal", "notas": "notion_notas",
               "slack_procesado": "notion_slack_procesado", "source": "notion_source"}
    # Fin is the visible task deadline. A cleared Fin must not fall back to stale dates.
    if not prop_map.get("fin"):
        mapping["fecha_objetivo"] = "fecha_objetivo"
    for key, field in mapping.items():
        name = prop_map.get(key)
        if name in properties:
            prop = properties[name]
            fields[field] = property_value(prop)
            if prop.get("type") == "date":
                fields[field + "_end"] = (prop.get("date") or {}).get("end", "") or ""
                fields[field + "_time_zone"] = (prop.get("date") or {}).get("time_zone", "") or ""
    lines = header.splitlines()
    for key, value in fields.items():
        replacement = f"{key}: {json.dumps(value, ensure_ascii=False)}"
        for i, line in enumerate(lines):
            if line.startswith(key + ":"):
                lines[i] = replacement
                break
        else:
            lines.append(replacement)
    labels = {"titulo_corto": "Titulo", "tipo": "Tipo de entrada", "proyecto": "Proyecto",
              "fecha_objetivo": "Fecha objetivo", "inicio": "Inicio", "estado": "Estado",
              "referencia_temporal": "Referencia temporal"}
    summary, marker, original = body.partition("## Contenido completo (Slack)")
    for key, label in labels.items():
        if key not in fields:
            continue
        line = f"{label}: {str(fields[key]).replace(chr(10), ' ')}"
        pattern = rf"^{re.escape(label)}:.*$"
        if re.search(pattern, summary, flags=re.MULTILINE):
            summary = re.sub(pattern, lambda _: line, summary, flags=re.MULTILINE)
        else:
            summary = line + "\n" + summary
    updated = "---\n" + "\n".join(lines) + "\n---\n" + summary + marker + original
    if updated == raw:
        return False
    if not dry_run:
        path.write_text(updated, encoding="utf-8", newline="\n")
    return True
