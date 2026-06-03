# Pipelines de productividad (resumen)

Vincent-Code tiene **dos pipelines** que forman un ciclo Slack ↔ Notion:

```text
┌─────────────────────────────────────────────────────────────────┐
│  PIPELINE 1 — Entrada (Slack → Notion)                          │
│                                                                 │
│  Slack DM  →  Obsidian  →  Ollama (clasificar)  →  Notion       │
│                                                                 │
│  Script: run_productivity_pipeline.bat                          │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
                    Base "Tareas Ideas" en Notion
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  PIPELINE 2 — Recordatorios (Notion → Slack)                    │
│                                                                 │
│  Notion (vencimiento cercano)  →  mensaje agrupado en Slack DM  │
│                                                                 │
│  Script: run_notion_due_slack_reminders.bat                     │
└─────────────────────────────────────────────────────────────────┘
```

## Cuándo correr cada uno

| Momento | Pipeline | Comando |
|--------|----------|---------|
| Varias veces al día (mañana / tarde) | 1 — Entrada | `scripts\run_productivity_pipeline.bat` |
| 1–2 veces al día (cuando revises pendientes) | 2 — Recordatorios | `scripts\run_notion_due_slack_reminders.bat` |

## Requisitos comunes (`.env`)

| Variable | Pipeline 1 | Pipeline 2 |
|----------|:------------:|:------------:|
| `SLACK_BOT_TOKEN` | Sí | Sí |
| `SLACK_DM_CHANNEL_ID` | Sí | Sí |
| `OBSIDIAN_VAULT_PATH` | Sí | Recomendado |
| `NOTION_API_TOKEN` | Sí | Sí |
| `NOTION_TASKS_DATABASE_ID` | Opcional | Opcional |
| `OLLAMA_MODEL` / `OLLAMA_URL` | Sí (pipeline 1) | No |

## Documentación detallada

- [Slack → Notion](slack-to-notion.md) — ingesta, títulos, fechas, reset
- [Notion → Slack](notion-to-slack-reminders.md) — recordatorios por vencimiento
- [Programador de tareas](../operations/windows-scheduler.md)

## Otros flujos (no son estos dos pipelines)

- Email diario: [daily-email.md](daily-email.md)
- Transcripciones YouTube/RSS: `main.py` (ver README raíz)
