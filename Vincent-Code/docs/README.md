# Documentación Vincent-Code

## Los tres pipelines de productividad

| # | Nombre | Dirección | Comando rápido | Guía |
|---|--------|-----------|----------------|------|
| **1** | Entrada | Slack → Obsidian → Notion | `scripts\run_productivity_pipeline.bat` | [slack-to-notion.md](workflows/slack-to-notion.md) |
| **3** | Completadas | Slack → Notion (frase explícita) | `scripts\run_slack_task_updates.sh` | [slack-task-updates.md](workflows/slack-task-updates.md) |
| **2** | Recordatorios (notificaciones Slack) | Notion → Slack | `scripts\run_notion_due_slack_reminders.bat` | [notion-to-slack-reminders.md](workflows/notion-to-slack-reminders.md) |

Diagrama y rutina diaria: [workflows/overview.md](workflows/overview.md). En GHA el ciclo corre 3×/día a las **8, 14 y 20 UTC** (`:00` ingesta → `:40` completadas → `:42` classify+Notion → `:45` recordatorios).

## Índice completo

- [README raíz](../README.md) — quick start y `.env`
- [Overview pipelines](workflows/overview.md)
- [Pipeline 1: Slack → Notion](workflows/slack-to-notion.md)
- [Pipeline 2: Notion → Slack](workflows/notion-to-slack-reminders.md)
- [Pipeline 3: Completadas Slack → Notion](workflows/slack-task-updates.md)
- [Plan: completado de tareas Slack](workflows/slack-task-completion-plan.md)
- [Email diario](workflows/daily-email.md)
- [Newsletter SMTP2GO](workflows/newsletter-smtp2go.md)
- [Campañas editoriales](workflows/editorial-campaigns.md)
- [Motor editorial IA](workflows/editorial-engine.md)
- [Transcripciones YouTube (canal)](workflows/youtube-channel-transcripts.md) — subtítulos OAuth → Obsidian (backlog OAuth vacío; 57 sin captions → Whisper)
- [Transcripciones locales (Whisper)](workflows/local-video-transcripts.md) — vídeos en disco → Obsidian
- [Extracción de conocimiento (Own_Transcripts)](workflows/own-transcript-knowledge.md) — transcripts propios → activos estructurados
- [Vincent MCP (Cursor)](workflows/vincent-mcp.md) — herramientas locales para buscar y lanzar pipelines
- [Programador de tareas Windows](operations/windows-scheduler.md)

## Orden típico en un día

En GitHub Actions esto ya está encadenado (08/14/20 UTC). En local:

1. `run_productivity_pipeline.bat` — recoger y procesar mensajes nuevos (ingesta + clasificar + Notion).
2. Revisar Notion (ordenar por **Fecha Slack**). Completados con frase explícita los aplica classify+sync o, como red de seguridad, Pipeline 3.
3. `run_notion_due_slack_reminders.bat` — avisos de vencimientos y Cloudflare al DM de Slack.
