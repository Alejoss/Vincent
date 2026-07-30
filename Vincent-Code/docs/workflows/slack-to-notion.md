# Pipeline 1: Slack → Notion

Convierte mensajes de tu DM con el bot de Vincent en filas de la base **Tareas Ideas** (y aprendizajes en su base), con título sintetizado, fechas y texto completo.

## Flujo (3 pasos internos)

| Paso | Script | Qué hace |
|------|--------|----------|
| 1 | `sync_slack_inbox_to_obsidian.py` | Lee Slack (ventana incremental, p. ej. últimos 3 días) y crea `slack-<ts>.md` en Obsidian |
| 2 | `classify_slack_input_with_ollama.py` | Clasifica con Ollama: `tipo`, `proyecto`, `titulo_corto`, `fecha_objetivo`, `recordatorio_slack` |
| 3 | `sync_productivity_obsidian_to_notion.py` | Upsert en Notion por `slack_ts` (crea o actualiza la fila) |

## Ejecución recomendada (un solo comando)

Desde `E:\Vincent\Vincent-Code`:

```powershell
scripts\run_productivity_pipeline.bat
```

El `.bat`:

1. Comprueba Ollama en `http://127.0.0.1:11434` (si no responde, intenta `ollama serve` y lo apaga al terminar).
2. Ejecuta los 3 scripts en cadena.
3. Escribe log en `logs\productivity_pipeline.log`.

**Ollama:** debe estar instalado y el modelo de `.env` (`OLLAMA_MODEL`, p. ej. `dolphin-llama3:8b`) descargado (`ollama pull ...`).

## Ejecución manual (paso a paso)

```powershell
cd E:\Vincent\Vincent-Code
.\venv\Scripts\Activate.ps1

# 1 — Slack → Obsidian
python scripts/sync_slack_inbox_to_obsidian.py --days 3

# 2 — Clasificar (usar --reclassify para regenerar títulos en notas ya clasificadas)
python scripts/classify_slack_input_with_ollama.py --model dolphin-llama3:8b --reclassify

# 3 — Obsidian → Notion
python scripts/sync_productivity_obsidian_to_notion.py
```

Solo ingesta Slack (sin Ollama ni Notion):

```powershell
scripts\run_slack_inbox_sync.bat
```

## Variables de entorno

**Obligatorias**

- `SLACK_BOT_TOKEN` — token de bot (`xoxb-...`)
- `SLACK_DM_CHANNEL_ID` — ID del DM/canal donde envías mensajes al bot
- `OBSIDIAN_VAULT_PATH` — p. ej. `E:\Vincent\Cerebro-Vincent`
- `NOTION_API_TOKEN`
- `NOTION_TASKS_DATABASE_ID` — base **Tareas Ideas** (obligatoria)

En **GitHub Actions** (environment `Ramdau`), configura el secret de entorno `NOTION_TASKS_DATABASE_ID` con el mismo valor que en `.env`.

**Opcionales**

- `SLACK_WORKSPACE_DOMAIN` — permalink en frontmatter
- `SLACK_INPUT_OBSIDIAN_REL` — subcarpeta de Input (default `0_Diario_Productividad/Input`)
- `SLACK_HUMAN_USER_ID` — filtrar solo tus mensajes en el DM
- **Audio Slack → texto:** `WHISPER_PROVIDER` (`openai` | `local` | `auto`), **`OPENAI_API_KEY`** (misma key que el clasificador; idioma `es` fijo en código)
- **Clasificador LLM:** `LLM_PROVIDER` (`openai` | `groq` | `ollama` | `auto`), `LLM_MODEL`, `OPENAI_API_KEY`, `GROQ_API_KEY`, `OLLAMA_MODEL`, `OLLAMA_URL`

## Qué se guarda en Notion

| Campo Notion | Origen | Siempre |
|--------------|--------|---------|
| Título (prop. `Tarea` / `Name`) | `titulo_corto` (Ollama) | Sí |
| `tipo`, `proyecto` | Clasificación | Sí |
| `slack_ts` | Mensaje Slack | Sí |
| **Fecha Slack** | Fecha del mensaje (`message_at` / `slack_ts`) | Sí (se crea la propiedad si falta) |
| `Fin` / **fecha objetivo** | Inferida del texto (“el viernes”, “esta semana”…) | Solo si hay plazo en el mensaje |
| Slack Procesado / Notas | Transcripción completa | Sí |
| `Estado` | Por defecto “Por hacer” en tareas nuevas (`intencion=nueva`) | Al crear |
| `intencion` (Obsidian) | `nueva` = crear fila; `completar` = cerrar tarea abierta existente | Sí (clasificador) |

**Ordenar en Notion:** vista por **Fecha Slack** descendente (fecha en que enviaste el mensaje, no vencimiento).

**Títulos:** Ollama genera el titular (máx. **72 caracteres**, frase completa) leyendo **toda** la transcripción. El código **no trunca**; si el título no cumple, se reintenta con feedback al modelo. Regenerar con `--reclassify`.

## Estado local y deduplicación

- Cursor Slack: `cache/slack_inbox/sync_state.sqlite3`
- Audio temporal: `cache/slack_audio/`
- Dedup Notion: propiedad `slack_ts` (misma clave que el nombre del archivo Obsidian)

## Reset completo (vaciar Notion y reimportar)

```powershell
# Vista previa
python scripts/notion_purge_productivity_database.py --dry-run

# Archivar todas las filas de la base de tareas (papelera Notion)
python scripts/notion_purge_productivity_database.py --database tasks --yes --clear-reminder-cache

# Reimportar desde Obsidian/Slack
scripts\run_productivity_pipeline.bat
```

Atajo: `scripts\run_notion_purge_tasks.bat` (purge + borra caché de recordatorios).

Renombrar solo títulos en Notion (sin borrar filas):

```powershell
python scripts/notion_rename_task_titles_ollama.py --dry-run
python scripts/notion_rename_task_titles_ollama.py
```

## Troubleshooting

| Problema | Qué revisar |
|----------|-------------|
| Mensajes de voz sin texto en Obsidian | `OPENAI_API_KEY` + `WHISPER_PROVIDER=openai` (cloud) o whisper local; log `Transcription failed` |
| Clasificador falla en GHA | `OPENAI_API_KEY` + `LLM_PROVIDER=openai`; local sin key usa Ollama |
| Ollama `404` / conexión rechazada | Solo si `LLM_PROVIDER=ollama`: `ollama serve` o el `.bat` lo levanta |
| No aparecen mensajes nuevos | Ventana `--days 3`; cursor en `cache/slack_inbox/`; mensajes deben ser **tuyos hacia el bot** |
| Notion sin filas nuevas | Token + integración conectada a la base; log paso 4 del pipeline |
| Fechas vacías en columna “Fin” | Normal si el mensaje no menciona plazo; usar columna **Fecha Slack** |
| Títulos truncados con `...` | `classify_slack_input_with_ollama.py --reclassify` y volver a sync |
| Clasificación no actualiza notas en `Tareas-Ideas` | Hace falta `--reclassify` (sin eso se saltan notas ya clasificadas) |
| Mensaje de “ya completé la tarea…” crea fila nueva | Debe clasificarse con `intencion=completar`; sync cierra la abierta. Ver [slack-task-updates.md](slack-task-updates.md) |

## Scripts relacionados

| Archivo | Uso |
|---------|-----|
| `run_productivity_pipeline.bat` | Pipeline 1 completo |
| `run_slack_inbox_sync.bat` | Solo paso 1 |
| `notion_purge_productivity_database.py` | Vaciar base Notion |
| `notion_rename_task_titles_ollama.py` | Regenerar títulos en Notion |
| `normalize_notion_productivity_schema.py` | Alinear selects tipo/proyecto en Notion |
