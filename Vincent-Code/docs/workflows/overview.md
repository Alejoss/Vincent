# Pipelines de productividad (resumen)

Vincent-Code tiene **dos pipelines** que forman un ciclo Slack ↔ Notion:

```text
┌─────────────────────────────────────────────────────────────────┐
│  PIPELINE 1 — Entrada (Slack → Notion)                          │
│                                                                 │
│  Slack DM  →  Obsidian  →  LLM (tipo + intencion)  →  Notion │
│    intencion=nueva      → crea/actualiza fila                   │
│    intencion=completar  → cierra tarea existente (Hecho)        │
│                                                                 │
│  Script: run_productivity_pipeline.bat (local, todo junto)      │
│  GHA: sequential workflows, each after previous success       │
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
└─────────────────────────────────────────────────────────────────┘
```

### Ciclo en GitHub Actions (UTC, 3×/día)

| Hora UTC | Workflow | Paso |
|----------|----------|------|
| `:00` | `productivity-pipeline.yml` | Ingesta Slack → Obsidian |
| After inbox success | `slack-task-updates.yml` | Completadas (intent detector, Slack directo) |
| After task-update success | `productivity-classify-notion.yml` | Clasificar (`intencion`) + sync Notion |
| After Notion-sync success | `notion-reminders.yml` | Recordatorios |

Ecuador (UTC-5): scheduled starts at 03:00, 09:00 and 15:00. Each downstream workflow waits for upstream success and checks out the latest main. All four share a concurrency queue; manual inbox runs start the same chain.

Clasificar+sync también aplica `intencion=completar` (cierra la tarea abierta; no crea duplicado).


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
| `NOTION_TASKS_DATABASE_ID` | Sí | Sí |
| `OPENAI_API_KEY` + `WHISPER_PROVIDER` / `LLM_PROVIDER` | Cloud/GHA | Opcional |
| `OLLAMA_MODEL` / `OLLAMA_URL` | Local sin OpenAI | No |

## Documentación detallada

- [Slack → Notion](slack-to-notion.md) — ingesta, títulos, fechas, reset
- [Completadas Slack → Notion](slack-task-updates.md) — intención completar, audit, cursor
- [Notion → Slack](notion-to-slack-reminders.md) — recordatorios por vencimiento
- [Plan: completado de tareas Slack](slack-task-completion-plan.md) — fases de fix (Pipeline 3)
- [Programador de tareas](../operations/windows-scheduler.md)

## Otros flujos (no son estos dos pipelines)

- Email diario: [daily-email.md](daily-email.md)
- Newsletter SMTP2GO: [newsletter-smtp2go.md](newsletter-smtp2go.md)
- Transcripciones YouTube (OAuth): [youtube-channel-transcripts.md](youtube-channel-transcripts.md)
- Transcripciones locales (Whisper): [local-video-transcripts.md](local-video-transcripts.md)
- Podcast MP3 + catálogo Spotify: [podcast-mp3.md](podcast-mp3.md)
- Extracción de conocimiento: [own-transcript-knowledge.md](own-transcript-knowledge.md)
- Knowledge por tema (transcripts → embeddings → Qdrant → ack): [topic-embeddings.md](topic-embeddings.md)
- Transcripts por tema (Sophia): [topic-transcripts-sophia.md](topic-transcripts-sophia.md)
