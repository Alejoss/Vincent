# Pipeline 3: Completadas Slack → Notion

Cierra tareas **existentes** en Notion cuando un mensaje (texto o audio) en el DM de Slack contiene una frase explícita de completado.

## Flujo

```text
Slack DM (humano → bot)
    │
    ▼
Gate determinista (frase "marcar/marca como completad(a/o)")
    │ no frase → skip, cursor avanza
    ▼
Transcripción audio (Whisper) si aplica
    │
    ▼
LLM elige candidata entre tareas Notion abiertas
    │
    ▼
Notion: estado → Hecho (+ nota Input en Obsidian marcada)
    │
    ▼
Audit JSONL + cursor SQLite
```

## Cuándo corre

| Entorno | Comando / trigger |
|---------|-------------------|
| Local | `bash scripts/run_slack_task_updates.sh` |
| GHA | `.github/workflows/slack-task-updates.yml` — `:40` UTC (3×/día) |

En el ciclo GHA va **después** de ingesta (`:00`) y **antes** de clasificar (`:42`) y recordatorios (`:45`).

## Gate estricto

Solo procesa mensajes que pasan `src/slack_task_completion_gate.py`:

- ✅ *"Marca como completada la newsletter"*
- ✅ *"Marcar como completado el timeline de Bitcoin"*
- ❌ *"Debo anunciar el club de lectura"* (intención futura, no completado)
- ❌ *"Ya envié el mail"* (sin frase gate)

Implementación: [slack-task-completion-plan.md](slack-task-completion-plan.md) (Fase 1).

## Trazabilidad

| Artefacto | Ubicación | Propósito |
|-----------|-----------|-----------|
| Log de corrida | `logs/slack_task_updates.log` | stdout capturado por el shell script |
| Audit append-only | `state/slack_task_updates_audit.jsonl` | Una línea JSON por mensaje inspeccionado |
| Cursor Slack | `cache/slack_task_updates/state.sqlite3` | Último `ts` procesado de forma segura |
| Nota Obsidian | `0_Diario_Productividad/Input/slack-<ts>.md` | `task_update_processed`, `page_id`, razón |

Ejemplo de línea audit:

```json
{"ts":"1782484198.653939","outcome":"applied","gate":"phrase_match","action":"complete","page_id":"...","title":"Newsletter","confidence":0.92,"model":"openai:gpt-4o-mini","logged_at":"2026-06-26T20:40:12+00:00"}
```

### Outcomes y cursor

El cursor **solo avanza** cuando el outcome permite descartar el mensaje sin reintento:

| Outcome | Avanza cursor | Significado |
|---------|:-------------:|-------------|
| `gate_skip` | Sí | Sin frase de completado |
| `empty` | Sí | Mensaje vacío / sin texto |
| `applied` | Sí | Tarea cerrada en Notion |
| `ignored` | No | Confianza LLM bajo umbral |
| `unmatched` | No | Frase gate OK pero sin candidata clara |
| `failed` | No | Error audio, LLM o Notion |

Si un mensaje con outcome `failed` queda **antes** en el tiempo que otros ya avanzados, no se reintenta automáticamente. Recuperación: `--full-refresh` o borrar cursor en SQLite.

## Variables de entorno

Las mismas que Pipeline 1, más:

| Variable | Requerida | Notas |
|----------|:---------:|-------|
| `SLACK_BOT_TOKEN` | Sí | Bot OAuth (`xoxb-…`) |
| `SLACK_DM_CHANNEL_ID` | Sí | Canal DM |
| `NOTION_API_TOKEN` | Sí | |
| `NOTION_TASKS_DATABASE_ID` | Sí | Base Tareas Ideas |
| `OPENAI_API_KEY` | Sí* | Transcripción + LLM en GHA |
| `OBSIDIAN_VAULT_PATH` | Recomendado | Marca notas Input |
| `SLACK_TASK_UPDATE_DAYS` | No | Ventana de lectura (default 3) |

\* Local puede usar Ollama con `LLM_PROVIDER=ollama`.

## Opciones CLI

```bash
python scripts/update_notion_tasks_from_slack_messages.py --help
```

Útiles:

- `--dry-run` — simula sin Notion, audit ni cursor
- `--full-refresh` — ignora cursor guardado
- `--confidence 0.75` — umbral mínimo (default)
- `--limit N` — procesar como máximo N mensajes humanos

## Relación con otros pipelines

- **Pipeline 1** crea tareas nuevas desde Slack; este script **no** debe crear filas nuevas por instrucciones de completado.
- **Clasificador** (`classify_slack_input_with_ollama.py`) salta notas con `task_update_processed: true`.
- **Recordatorios** (Pipeline 2) no intervienen aquí; corren después en `:45`.

## Referencias

- Script: `scripts/update_notion_tasks_from_slack_messages.py`
- Gate: `src/slack_task_completion_gate.py`
- Audit: `src/slack_task_updates_audit.py`
- Plan de implementación: [slack-task-completion-plan.md](slack-task-completion-plan.md)
