# Operación: Windows Task Scheduler

Automatizar los **dos pipelines de productividad** (y opcionalmente el email diario).

## Tareas recomendadas

| Tarea | Script | Frecuencia sugerida |
|-------|--------|---------------------|
| Pipeline 1 — Slack → Notion | `E:\Vincent\Vincent-Code\scripts\run_productivity_pipeline.bat` | 2–3× al día |
| Pipeline 2 — Recordatorios | `E:\Vincent\Vincent-Code\scripts\run_notion_due_slack_reminders.bat` | 1–2× al día |
| Email diario (opcional) | `scripts\run_daily_email_send.bat` | 1× al día o al login |

**Iniciar en:** `E:\Vincent\Vincent-Code` (carpeta del proyecto, no la de `scripts`).

## Crear una tarea (pasos)

1. `Win+R` → `taskschd.msc`
2. Crear tarea básica → nombre ej. `Vincent - Slack a Notion`
3. Desencadenador: horas fijas o al iniciar sesión
4. Acción: **Iniciar un programa** → programa = ruta completa al `.bat`
5. Opcional: **Retrasar** 1–2 minutos tras login (red lista)
6. Repetir para el segundo pipeline con otro nombre (`Vincent - Recordatorios Notion`)

## Requisitos en el equipo

- **Pipeline 1:** Ollama instalado; el `.bat` puede arrancar `ollama serve` si no está activo.
- Variables en `.env` en la raíz del proyecto (el `venv` del `.bat` las carga vía scripts Python).

## Logs para revisar fallos

| Log | Pipeline |
|-----|----------|
| `logs\productivity_pipeline.log` | 1 |
| `logs\notion_due_slack_reminders.log` | 2 |
| `logs\slack_inbox_sync.log` | Solo paso Slack (si usas `run_slack_inbox_sync.bat`) |
