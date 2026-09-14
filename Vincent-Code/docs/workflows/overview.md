# Pipelines de productividad (resumen)

Vincent-Code tiene **tres pipelines** que forman un ciclo Slack ↔ Notion:

```text
┌─────────────────────────────────────────────────────────────────┐
│  PIPELINE 1 — Entrada (Slack → Notion)                          │
│                                                                 │
│  Slack DM  →  Obsidian  →  LLM (tipo + intencion)  →  Notion │
│    intencion=nueva      → crea/actualiza fila                   │
│    intencion=completar  → cierra tarea existente (Hecho)        │
│                                                                 │
│  Script: run_productivity_pipeline.bat (local, todo junto)      │
│  GHA: 08/14/20 UTC — :00 → :40 → :42 → :45                      │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
                    Base "Tareas Ideas" en Notion
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  PIPELINE 3 — Completadas (Slack directo, misma intención)      │
│  Red de seguridad; classify+sync es el camino preferido         │
│  Script: run_slack_task_updates.sh · GHA: slack-task-updates    │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  PIPELINE 2 — Recordatorios (Notion → Slack)                    │
│  Script: run_notion_due_slack_reminders.bat                     │
│  GHA: notion-reminders.yml · cron 45 8,14,20                    │
└─────────────────────────────────────────────────────────────────┘
```

### Ciclo en GitHub Actions (3×/día)

Crons reales: minutos `:00` / `:40` / `:42` / `:45` en las horas **8, 14 y 20 UTC**.

| UTC | Ecuador (UTC−5) | Workflow | Paso |
|-----|-----------------|----------|------|
| 08:00 / 14:00 / 20:00 | 03:00 / 09:00 / 15:00 | `productivity-pipeline.yml` | Ingesta Slack → Obsidian |
| 08:40 / 14:40 / 20:40 | 03:40 / 09:40 / 15:40 | `slack-task-updates.yml` | Completadas (intent detector, Slack directo) |
| 08:42 / 14:42 / 20:42 | 03:42 / 09:42 / 15:42 | `productivity-classify-notion.yml` | Clasificar (`intencion`) + sync Notion |
| 08:45 / 14:45 / 20:45 | 03:45 / 09:45 / 15:45 | `notion-reminders.yml` | Recordatorios (Pipeline 2) |

Clasificar+sync también aplica `intencion=completar` (cierra la tarea abierta; no crea duplicado).


## Cuándo correr cada uno

| Momento | Pipeline | Comando |
|--------|----------|---------|
| Varias veces al día (mañana / tarde) | 1 — Entrada | `scripts\run_productivity_pipeline.bat` |
| Tras la ingesta, si hay audios de “ya completé…” | 3 — Completadas | `scripts\run_slack_task_updates.sh` (en GHA va solo; local suele ir implícito en classify+sync) |
| 1–2 veces al día (cuando revises pendientes) | 2 — Recordatorios | `scripts\run_notion_due_slack_reminders.bat` |

En GHA no hace falta lanzarlos a mano: el ciclo de arriba corre 3×/día.

## Requisitos comunes (`.env`)

| Variable | Pipeline 1 | Pipeline 3 | Pipeline 2 |
|----------|:------------:|:------------:|:------------:|
| `SLACK_BOT_TOKEN` | Sí | Sí | Sí |
| `SLACK_DM_CHANNEL_ID` | Sí | Sí | Sí |
| `OBSIDIAN_VAULT_PATH` | Sí | Recomendado | Recomendado |
| `NOTION_API_TOKEN` | Sí | Sí | Sí |
| `NOTION_TASKS_DATABASE_ID` | Sí | Sí | Sí |
| `OPENAI_API_KEY` + `WHISPER_PROVIDER` / `LLM_PROVIDER` | Cloud/GHA | Cloud/GHA | Opcional |
| `OLLAMA_MODEL` / `OLLAMA_URL` | Local sin OpenAI | Local sin OpenAI | No |
| `SLACK_REMINDER_EXCLUDE_STATUS` | No | No | Opcional |

## Documentación detallada

- [Slack → Notion](slack-to-notion.md) — ingesta, títulos, fechas, reset
- [Completadas Slack → Notion](slack-task-updates.md) — intención completar, audit, cursor
- [Notion → Slack](notion-to-slack-reminders.md) — recordatorios (vencimientos + Cloudflare)
- [Plan: completado de tareas Slack](slack-task-completion-plan.md) — fases de fix (Pipeline 3)
- [Programador de tareas](../operations/windows-scheduler.md)

## Otros flujos (no son estos tres pipelines)

- Email diario: [daily-email.md](daily-email.md)
- Newsletter SMTP2GO: [newsletter-smtp2go.md](newsletter-smtp2go.md)
- Transcripciones YouTube (OAuth): [youtube-channel-transcripts.md](youtube-channel-transcripts.md)
- Transcripciones locales (Whisper): [local-video-transcripts.md](local-video-transcripts.md)
- Extracción de conocimiento: [own-transcript-knowledge.md](own-transcript-knowledge.md)
- Knowledge por tema (transcripts → embeddings → Qdrant → ack): [topic-embeddings.md](topic-embeddings.md)
- Transcripts por tema (Sophia): [topic-transcripts-sophia.md](topic-transcripts-sophia.md)
