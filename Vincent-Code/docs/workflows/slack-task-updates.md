# Pipeline 3: Completadas Slack → Notion

Cierra tareas **existentes** en Notion cuando un mensaje muestra intención de completar
(no crea filas nuevas).

La **fuente de verdad** de la intención es la clasificación (`intencion: nueva|completar`).
Pipeline 3 sigue leyendo Slack directamente como red de seguridad con el mismo detector
en `src/slack_task_intent.py`.

## Flujo preferido (clasificar → sync)

```text
Slack DM
    │
    ▼
Ingesta → Obsidian Input
    │
    ▼
Clasificar (LLM + señales deterministas)
    │  intencion=nueva      → crear/actualizar fila Notion
    │  intencion=completar  → emparejar tarea abierta → Estado Hecho
    ▼
Sync Obsidian → Notion
```

## Flujo Pipeline 3 (Slack directo, :40 UTC)

```text
Slack DM
    │
    ▼
Intent detector (completé la tarea / marcar como completada / …)
    │ no → skip
    ▼
LLM elige candidata entre tareas abiertas
    │
    ▼
Notion: Estado → Hecho + nota Input marcada
```

## Cuándo corre

| Entorno | Comando / trigger |
|---------|-------------------|
| Local | `bash scripts/run_slack_task_updates.sh` |
| GHA | `.github/workflows/slack-task-updates.yml` — `:40` UTC |
| Preferido | Clasificar + sync (`productivity-classify-notion.yml` — `:42`) aplica `intencion=completar` |

## Intención de completar

`src/slack_task_intent.py` reconoce, entre otras:

- ✅ *"Marca como completada la newsletter"*
- ✅ *"Ya completé la tarea de anunciar el canal de Telegram…"*
- ✅ *"Ya terminé la tarea de enviar el mail"*
- ❌ *"Debo anunciar el club de lectura"* (pendiente nuevo)
- ❌ *"Debo completar la newsletter"* (compromiso futuro)
- ❌ *"Ya terminé de publicar el podcast"* (reporte de actividad sin “la tarea”)

## Trazabilidad

| Artefacto | Ubicación | Propósito |
|-----------|-----------|-----------|
| Frontmatter | `intencion`, `task_update_*` en la nota Obsidian | Clasificación + resultado del cierre |
| Audit append-only | `state/slack_task_updates_audit.jsonl` | Pipeline 3 (Slack directo) |
| Cursor Slack | `cache/slack_task_updates/state.sqlite3` | Último `ts` procesado de forma segura |

## Referencias

- Intent: `src/slack_task_intent.py`
- Match + Hecho desde sync: `src/notion_task_complete.py`
- Clasificador: `scripts/classify_slack_input_with_ollama.py`
- Sync: `scripts/sync_productivity_obsidian_to_notion.py`
- Script Slack directo: `scripts/update_notion_tasks_from_slack_messages.py`
- Plan histórico: [slack-task-completion-plan.md](slack-task-completion-plan.md)
