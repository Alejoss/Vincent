# Vincent-Code

Automatización del segundo cerebro (Obsidian + Notion + Slack).

## Dos pipelines principales

| Pipeline | Qué hace | Comando |
|----------|----------|---------|
| **1. Entrada** | Slack → Obsidian → Ollama → Notion | `scripts\run_productivity_pipeline.bat` |
| **2. Recordatorios** | Notion (vencimientos) → Slack DM | `scripts\run_notion_due_slack_reminders.bat` |

Documentación detallada: **[docs/README.md](docs/README.md)** (diagramas, `.env`, troubleshooting).

## Quick start

```powershell
cd E:\Vincent\Vincent-Code
.\venv\Scripts\Activate.ps1
```

Configura `.env` (mínimo para ambos pipelines):

- `SLACK_BOT_TOKEN`, `SLACK_DM_CHANNEL_ID`
- `OBSIDIAN_VAULT_PATH`
- `NOTION_API_TOKEN`
- `OLLAMA_MODEL` (solo pipeline 1; p. ej. `dolphin-llama3:8b`)

```powershell
# Recoger mensajes y subir a Notion (requiere Ollama)
scripts\run_productivity_pipeline.bat

# Avisos de tareas que vencen pronto
scripts\run_notion_due_slack_reminders.bat
```

## Otros flujos

- **Email diario:** `scripts\run_daily_email_send.bat` — [docs/workflows/daily-email.md](docs/workflows/daily-email.md)
- **Transcripciones YouTube/RSS:** `python main.py` (pipeline legacy)

## Logs

- `logs/productivity_pipeline.log` — pipeline 1
- `logs/notion_due_slack_reminders.log` — pipeline 2
- `logs/slack_inbox_sync.log` — solo ingesta Slack
