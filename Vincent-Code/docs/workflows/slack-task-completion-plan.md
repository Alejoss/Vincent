# Plan: completado de tareas desde Slack

Plan de implementación para corregir el pipeline de **actualización de tareas** (Slack → Notion), separado del Pipeline 1 (ingesta) y Pipeline 2 (recordatorios).

**Estado:** Fases 0–5 implementadas. Fase 6 = limpieza manual en Notion/vault (opcional; no automatizada).

**Implementación Fase 1:**
- Módulo: `src/slack_task_completion_gate.py`
- Golden set: `tests/fixtures/slack_completion_gate_cases.json`
- Tests: `tests/test_slack_task_completion_gate.py` — ejecutar con `python -m unittest discover -s tests -v`

---

## Contexto confirmado

### Problemas observados

| # | Problema | Ejemplo |
|---|----------|---------|
| 1 | Mensajes de completado crean **tareas nuevas** en vez de cerrar la existente | Audio *"Marca como completada la newsletter…"* → fila *"Marcar como completada la tarea de redactar la newsletter"* |
| 2 | **Falsos positivos**: tareas marcadas `Hecho` sin frase explícita de completado | Club de lectura (*"Debo anunciar…"*) marcada `Hecho`; timeline Bitcoin (*"Debo terminar…"*) |
| 3 | **Sin trazabilidad**: no hay `task_update_processed` en Obsidian ni audit log versionado | Imposible saber qué audio cerró qué tarea |
| 4 | **Recordatorios silenciados** por dedup de 3 días aunque la tarea siga `Por hacer` | Club de lectura avisada el 25 jun, no el 26 jun |
| 5 | **Timing**: recordatorio corre antes de procesar audio de completado | Podcast: audio 14:29 UTC, recordatorio 15:18 UTC |
| 6 | **Vault local desincronizado** respecto a Notion/GHA | Transcripts recientes solo en Notion |

### Hecho manual confirmado por el usuario

La tarea **"Anuncio del club de lectura sobre el secuestro de Bitcoin"** fue marcada `Hecho` por el script por error. El usuario la revirtió manualmente a **`Por hacer`**.

---

## Decisión de producto: gate estricto de completado

**Regla:** la funcionalidad de marcar completada **solo se activa** si el mensaje (texto o transcripción de audio) contiene una frase explícita del tipo:

- `marcar como completada` / `marcar como completado`
- `marca como completada` / `marca como completado` (imperativo)

**No activar** con frases como:

- *"Ya terminé de publicar el podcast"*
- *"Debo anunciar el club de lectura…"*
- *"Debo terminar el esqueleto de Bitcoin"*
- *"Ya creé el script…"*

**Fuera de alcance (por ahora):** reschedule/delete automático por LLM sin frases propias definidas.

---

## Arquitectura objetivo (3 pipelines)

```text
Pipeline 1 — Ingesta     Slack → Obsidian → clasificar → Notion (tareas nuevas)
Pipeline 3 — Completadas Slack → [gate frase] → Notion (cerrar tarea existente)
Pipeline 2 — Recordatorios Notion (vencimientos) → Slack DM
```

Script Pipeline 3: `scripts/update_notion_tasks_from_slack_messages.py`  
Workflow GHA: `.github/workflows/slack-task-updates.yml`

**Orden de ejecución objetivo (por slot, UTC):**

```text
:00  Ingesta Slack → Obsidian
:15  Completadas (con gate estricto)
:30  Clasificar + sync Notion
:45  Recordatorios
```

Alternativa: un solo workflow secuencial por horario para evitar carreras.

---

## Fases de implementación

Principio: **primero dejar de hacer daño → ordenar flujos → auditoría → recordatorios → limpieza**.

```text
Fase 0 → Fase 1 → Fase 2 → Fase 3 → Fase 4 → Fase 5 → Fase 6
```

---

### Fase 0 — Golden set y criterios de prueba ✅

**Objetivo:** criterios claros antes de tocar cron o pipelines.

**Entregables:**

- Frases que **SÍ** activan completado (ver sección gate arriba).
- Frases que **NO** deben activar (regresión).
- Golden set de ~8–10 audios reales con `slack_ts` y resultado esperado → `tests/fixtures/slack_completion_gate_cases.json`

**Casos mínimos:**

| slack_ts (aprox.) | Transcript / intención | Esperado |
|-------------------|------------------------|----------|
| 1782355437.156429 | *"Debo anunciar el club de lectura…"* | `ignore` |
| 1782484198.653939 | *"Ya terminé de publicar el primer podcast…"* | `ignore` (sin frase gate) |
| 1782355472.316599 | *"Debo terminar el esqueleto de Bitcoin…"* | `ignore` |
| 1780723952.365989 | *"Marca como completada la tarea de redactar la newsletter…"* | `complete` → tarea newsletter |
| (definir) | *"Marca como completada…"* + tarea concreta | `complete` → candidata correcta |

---

### Fase 1 — Gate estricto de completado ✅

**Objetivo:** cero completadas automáticas salvo frase explícita.

**Archivos:**

- `src/slack_task_completion_gate.py` — matcher determinista
- `scripts/update_notion_tasks_from_slack_messages.py` — integración; confianza mínima default 0.75
- `tests/test_slack_task_completion_gate.py` — regresión

**Cambios:**

1. **Pre-filtro determinista** (antes del LLM):
   - Normalizar texto (minúsculas, sin tildes).
   - Matcher: `marc(a|ar|ado).*completad[oa]`.
   - Sin match → `action=ignore`, no tocar Notion, no invocar LLM para `complete`.

2. **LLM acotado:**
   - Solo si pasó el gate: elegir **qué** tarea (`candidate_id`), no **si** completar.
   - Subir `--confidence` default para `complete` (p. ej. 0.55 → 0.75).

3. Reschedule/delete: sin cambios en esta fase.

**Validación:** dry-run con golden set; club de lectura y podcast *"ya terminé"* → `ignore`.

**Desplegar antes** de reordenar cron.

---

### Fase 2 — Reordenar pipelines (GitHub Actions) ✅

**Objetivo:** procesar completados antes de recordatorios el mismo día.

**Archivos:**

| Hora UTC | Workflow | Script |
|----------|----------|--------|
| `:00` | `.github/workflows/productivity-pipeline.yml` | `run_slack_inbox_sync.sh` |
| `:40` | `.github/workflows/slack-task-updates.yml` | `run_slack_task_updates.sh` |
| `:42` | `.github/workflows/productivity-classify-notion.yml` | `run_productivity_classify_notion.sh` |
| `:45` | `.github/workflows/notion-reminders.yml` | `run_notion_due_slack_reminders.sh` |

**Nota:** completadas a `:40` para procesar audios ~`:29` antes del recordatorio `:45`.

**Manual (GHA):** `productivity-pipeline.yml` → workflow_dispatch con *Run full pipeline* = true ejecuta el pipeline completo antiguo.

**Cron (UTC, 3×/día):**

| Hora | Paso |
|------|------|
| `:00` | Ingesta Slack → Obsidian |
| `:40` | Completadas (Fase 1) |
| `:42` | Clasificar + sync Notion |
| `:45` | Recordatorios |

**Validación:** audio 14:29 con *"Marca como completada…"* → `Hecho` antes del recordatorio ~14:45.

---

### Fase 3 — Separar ingesta vs actualización ✅

**Objetivo:** instrucciones de completado no crean filas nuevas en Notion.

**Archivos:**

- `src/slack_task_update_obsidian.py` — crear/marcar notas Input, skip compartido
- `scripts/update_notion_tasks_from_slack_messages.py` — crea Input si falta; marca en todos los outcomes
- `scripts/classify_slack_input_with_ollama.py` — skip por `task_update_*` o frase gate
- `scripts/sync_productivity_obsidian_to_notion.py` — no sincroniza notas de completado
- `tests/test_slack_task_update_obsidian.py`
- Cron: clasificar movido a `:42` (después de completadas `:40`)

**Cambios:**

1. **`update_notion_tasks_from_slack_messages.py`**
   - Tras `complete`, marcar nota Input: `task_update_processed`, `task_update_action`, `task_update_notion_page`, `task_update_razon`.
   - Si no existe nota Input, **crearla** con transcripción.

2. **`classify_slack_input_with_ollama.py`**
   - Ya salta `task_update_processed`; asegurar cobertura cuando la nota se crea desde Pipeline 3.

3. **`sync_productivity_obsidian_to_notion.py`** (opcional)
   - No crear fila nueva si el mensaje es solo instrucción de completado.

**Validación:** audio newsletter → cierra tarea existente; no crea *"Marcar como completada la tarea de…"*.

---

### Fase 4 — Auditoría y cursor fiable ✅

**Objetivo:** responder *"¿qué audio cerró qué tarea y cuándo?"*

**Cambios:**

1. Log en `logs/slack_task_updates.log` (via `run_slack_task_updates.sh`).
2. Append a `state/slack_task_updates_audit.jsonl` (versionado en git):

   ```json
   {"ts":"1782484198.653939","action":"complete","page_id":"...","title":"...","gate":"phrase_match","model":"openai:gpt-4o-mini"}
   ```

3. **Cursor** (`cache/slack_task_updates/state.sqlite3`):
   - Avanzar si: `applied`, `gate_skip`, mensaje vacío (`empty`).
   - **No avanzar** si: `unmatched`, `failed`, `ignored` (baja confianza post-gate).

4. GHA: commitear audit + notas Input marcadas.

5. Documentación: [slack-task-updates.md](slack-task-updates.md) + enlaces en `overview.md` y `docs/README.md`.

**Archivos:** `src/slack_task_updates_audit.py`, `tests/test_slack_task_updates_audit.py`, cambios en `update_notion_tasks_from_slack_messages.py`, `slack-task-updates.yml`.

---

### Fase 5 — Recordatorios (dedup inteligente) ✅

**Objetivo:** no repetir lo ya hecho; sí re-avisar pendientes vencidas.

**Archivo:** `scripts/notion_tasks_due_slack_reminders.py`, `src/notion_slack_reminders_dedup.py`

**Cambios:**

- Si tarea sigue `Por hacer` y vencimiento ≤ hoy → re-avisar cada **2** días (`--dedup-days-overdue`, default 2).
- Próximas: dedup **3** días (`--dedup-days`, sin cambio de default).
- Si `Hecho` / terminal → no avisar (comportamiento actual).

**Validación:** club de lectura `Por hacer`, due 26 jun → vuelve a aparecer tras 2 días si sigue pendiente.

---

### Fase 6 — Limpieza de datos y sync local (opcional, manual)

Tareas operativas puntuales; no forman parte del despliegue de código:

1. Listar tareas `Hecho` cuyo transcript **no** contiene frase gate → revertir a `Por hacer` las confirmadas.
2. Revisar batch `last_edited` 2026-06-26T20:43 UTC (sync masivo, no completadas manuales).
3. Rutina: `git pull` tras corridas GHA; verificar commits de `Input/` y `Tareas-Ideas/`.

---

## Orden de PRs sugerido

| PR | Fase | Descripción | Depende de |
|----|------|-------------|------------|
| PR-1 | 1 | Gate estricto + tests del matcher | Fase 0 |
| PR-2 | 4 (parcial) | Audit log + cursor conservador | PR-1 |
| PR-3 | 2 | Reorden cron GHA | PR-1 |
| PR-4 | 3 | Marcar/crear Input; clasificador skip | PR-2 |
| PR-5 | 5 | Dedup recordatorios | PR-1, PR-3 |
| PR-6 | 6 + docs | Limpieza Notion + doc Pipeline 3 | PR-1–5 |

PR-1 y PR-2 pueden ir en un solo despliegue inicial.

---

## Criterios de éxito global

1. Sin frase *marcar/marca como completad(a/o)* → **ningún** cambio de estado en Notion.
2. Con la frase → cierra **una** tarea correcta + línea en `audit.jsonl`.
3. Recordatorio no pregunta por tarea ya `Hecho` (con gate válido) en el mismo ciclo.
4. Tareas `Por hacer` vencidas siguen avisando aunque se hayan avisado antes.
5. Cada completado deja rastro en Obsidian (`task_update_*`) + audit log.

---

## Referencias

| Recurso | Ruta |
|---------|------|
| Script completadas | `Vincent-Code/scripts/update_notion_tasks_from_slack_messages.py` |
| Workflow GHA | `.github/workflows/slack-task-updates.yml` |
| Pipeline ingesta | `docs/workflows/slack-to-notion.md` |
| Recordatorios | `docs/workflows/notion-to-slack-reminders.md` |
| Overview pipelines | `docs/workflows/overview.md` |

---

## Historial

| Fecha | Nota |
|-------|------|
| 2026-07-29 | Intent integral: `intencion` en clasificador + sync cierra tareas; detector cubre “ya completé la tarea…” |
| 2026-06-27 | Fases 4–5: audit jsonl, cursor conservador, dedup atrasadas 2 días |
| 2026-06-27 | Fase 3: skip classify/sync, crear/marcar Input, cron classify :42 |
| 2026-06-27 | Fase 2: cron GHA :00/:40/:42/:45, scripts inbox y classify+notion |
| 2026-06-27 | Fase 0 + Fase 1: gate estricto, golden set JSON, tests unittest |
| 2026-06-27 | Plan inicial: gate estricto, fases 0–6, orden de PRs |
