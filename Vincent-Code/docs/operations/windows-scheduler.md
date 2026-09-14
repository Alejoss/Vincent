# Operación: Windows Task Scheduler

Automatizar los **pipelines de productividad** y, opcionalmente, email diario y transcripciones.

## Tareas recomendadas

| Tarea | Script | Frecuencia sugerida |
|-------|--------|---------------------|
| Pipeline 1 — Slack → Notion | `E:\Vincent\Vincent-Code\scripts\run_productivity_pipeline.bat` | 2–3× al día |
| Pipeline 3 — Completadas (opcional; GHA ya lo cubre) | `E:\Vincent\Vincent-Code\scripts\run_slack_task_updates.sh` | Tras la ingesta, o confiar en classify+sync |
| Pipeline 2 — Recordatorios Slack | `E:\Vincent\Vincent-Code\scripts\run_notion_due_slack_reminders.bat` | 1–2× al día |
| Email diario (opcional) | `scripts\run_daily_email_send.bat` | 1× al día o al login |
| YouTube transcripts (opcional) | `scripts\run_youtube_channel_transcripts.bat` | 1× al día — vídeos **nuevos** del canal |
| Local Whisper (opcional) | `scripts\run_local_videos_transcripts.bat` | 1× al día o bajo demanda |

Guías: [YouTube](../workflows/youtube-channel-transcripts.md) · [Local Whisper](../workflows/local-video-transcripts.md)

**Iniciar en:** `E:\Vincent\Vincent-Code` (carpeta del proyecto, no la de `scripts`).

## Crear una tarea (pasos)

1. `Win+R` → `taskschd.msc`
2. Crear tarea básica → nombre ej. `Vincent - Slack a Notion`
3. Desencadenador: horas fijas o al iniciar sesión
4. Acción: **Iniciar un programa** → programa = ruta completa al `.bat`
5. Opcional: **Retrasar** 1–2 minutos tras login (red lista)
6. Repetir para Pipeline 2 con otro nombre (`Vincent - Recordatorios Notion`)

## Requisitos en el equipo

- **Pipeline 1:** Ollama instalado; el `.bat` puede arrancar `ollama serve` si no está activo.
- Variables en `.env` en la raíz del proyecto (el `venv` del `.bat` las carga vía scripts Python).

## Logs para revisar fallos

| Log | Pipeline |
|-----|----------|
| `logs\productivity_pipeline.log` | 1 |
| `logs\slack_task_updates.log` | 3 |
| `logs\notion_due_slack_reminders.log` | 2 |
| `logs\slack_inbox_sync.log` | Solo paso Slack (si usas `run_slack_inbox_sync.bat`) |
| `logs\youtube_channel_transcripts_latest.log` | YouTube OAuth |
| `logs\local_videos_transcripts_latest.log` | Local Whisper |
