# Documentación Vincent-Code

## Los dos pipelines de productividad

| # | Nombre | Dirección | Comando rápido | Guía |
|---|--------|-----------|----------------|------|
| **1** | Entrada | Slack → Obsidian → Notion | `scripts\run_productivity_pipeline.bat` | [slack-to-notion.md](workflows/slack-to-notion.md) |
| **2** | Recordatorios | Notion → Slack | `scripts\run_notion_due_slack_reminders.bat` | [notion-to-slack-reminders.md](workflows/notion-to-slack-reminders.md) |

Diagrama y rutina diaria: [workflows/overview.md](workflows/overview.md)

## Índice completo

- [README raíz](../README.md) — quick start y `.env`
- [Overview pipelines](workflows/overview.md)
- [Pipeline 1: Slack → Notion](workflows/slack-to-notion.md)
- [Pipeline 2: Notion → Slack](workflows/notion-to-slack-reminders.md)
- [Email diario](workflows/daily-email.md)
- [Programador de tareas Windows](operations/windows-scheduler.md)

## Orden típico en un día

1. `run_productivity_pipeline.bat` — recoger y procesar mensajes nuevos.
2. Revisar Notion (ordenar por **Fecha Slack**).
3. `run_notion_due_slack_reminders.bat` — avisos de vencimientos.
