# Vincent-Code

Automatización del segundo cerebro (Obsidian + Notion + Slack).

## Tres pipelines de productividad

| Pipeline | Qué hace | Comando |
|----------|----------|---------|
| **1. Entrada** | Slack → Obsidian → LLM → Notion | `scripts\run_productivity_pipeline.bat` |
| **3. Completadas** | Slack (frase explícita) → Notion `Hecho` | `scripts\run_slack_task_updates.sh` |
| **2. Recordatorios** | Notion (vencimientos + Cloudflare) → Slack DM | `scripts\run_notion_due_slack_reminders.bat` |

En GitHub Actions el ciclo corre 3×/día a las **8, 14 y 20 UTC** (`:00` → `:40` → `:42` → `:45`). Guía de notificaciones Slack: **[docs/workflows/notion-to-slack-reminders.md](docs/workflows/notion-to-slack-reminders.md)**.

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
- **Local (sin OpenAI):** `OLLAMA_MODEL` (p. ej. `dolphin-llama3:8b`)
- **Cloud / GHA:** `OPENAI_API_KEY`, `WHISPER_PROVIDER=openai`, `LLM_PROVIDER=openai`, `LLM_MODEL=gpt-4o-mini` — ver `env.example`

```powershell
# Recoger mensajes y subir a Notion (Whisper + LLM según .env)
scripts\run_productivity_pipeline.bat

# Avisos de tareas que vencen pronto
scripts\run_notion_due_slack_reminders.bat
```

## Otros flujos

- **Newsletter / campañas:** `scripts\run_newsletter_app.bat` — pestaña **Generar** + envío SMTP2GO — [docs/workflows/editorial-engine.md](docs/workflows/editorial-engine.md)
- **Email diario:** `scripts\run_daily_email_send.bat` — [docs/workflows/daily-email.md](docs/workflows/daily-email.md)
- **Transcripciones YouTube (OAuth):** `scripts\run_youtube_channel_transcripts.bat` — [docs/workflows/youtube-channel-transcripts.md](docs/workflows/youtube-channel-transcripts.md)
- **Transcripciones locales (Whisper):** `scripts\run_local_videos_transcripts.bat` — [docs/workflows/local-video-transcripts.md](docs/workflows/local-video-transcripts.md)
- **Podcast MP3:** `python scripts/extract_podcast_mp3.py` — carpeta `VideosParaPodcast/`
- **Cursor MCP:** `scripts/vincent_mcp.py` — search + pipeline tools — [docs/workflows/vincent-mcp.md](docs/workflows/vincent-mcp.md)

## Logs

- `logs/productivity_pipeline.log` — pipeline 1
- `logs/notion_due_slack_reminders.log` — pipeline 2 (notificaciones Slack)
- `logs/slack_task_updates.log` — pipeline 3
- `logs/slack_inbox_sync.log` — solo ingesta Slack
- `logs/youtube_channel_transcripts_latest.log` — YouTube
- `logs/local_videos_transcripts_latest.log` — Whisper local
