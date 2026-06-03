# Pipeline 2: Notion → Slack (recordatorios)

Lee la base de **tareas/ideas** en Notion, busca filas con **vencimiento cercano** (`Fin` o **fecha objetivo** como fecha) y envía **un mensaje agrupado** al mismo DM de Slack que usa la ingesta.

No confundir con el Pipeline 1: este flujo **no** importa mensajes; solo **avisa** de lo que ya está en Notion.

## Cuándo hay recordatorios

Una fila entra en la ventana si:

- Tiene fecha de vencimiento entre **hoy** y **hoy + N días** (`--within-days`, default **3**).
- `tipo` es **Tarea** o **Idea** (si existe la propiedad).
- `Estado` no está en la lista excluida (default: Hecho, Terminado, Listo, Done).

Opcional: `--include-overdue` para incluir vencidas.

Si el script dice *"No tasks to remind"*, suele significar que **ninguna fila tiene Fecha de vencimiento** en los próximos días (común tras mensajes sin plazos explícitos). Para probar: `--dry-run --within-days 30 --include-overdue`.

## Ejecución recomendada

```powershell
cd E:\Vincent\Vincent-Code
scripts\run_notion_due_slack_reminders.bat
```

Equivalente manual:

```powershell
python scripts/notion_tasks_due_slack_reminders.py --within-days 3
```

Log: `logs\notion_due_slack_reminders.log`

## Probar sin enviar a Slack

```powershell
python scripts/notion_tasks_due_slack_reminders.py --dry-run --within-days 3
```

Prueba amplia (muestra más filas; no usar en producción sin `--dry-run`):

```powershell
python scripts/notion_tasks_due_slack_reminders.py --dry-run --within-days 30 --include-overdue --force
```

## Variables de entorno

**Obligatorias**

- `NOTION_API_TOKEN`
- `SLACK_BOT_TOKEN`
- `SLACK_DM_CHANNEL_ID` — mismo canal/DM que Pipeline 1

**Opcionales**

- `NOTION_TASKS_DATABASE_ID` — default = misma base que el sync de tareas
- `SLACK_REMINDER_EXCLUDE_STATUS` — estados a ignorar (coma-separados)
- `OBSIDIAN_VAULT_PATH` — para leer `recordatorio_slack` de `slack-<ts>.md` (mejor texto que el título de la fila)

## Texto del mensaje

- Formato: lista con viñetas bajo `Recordatorios`.
- Cada línea usa `recordatorio_slack` de la nota Obsidian (generado al clasificar), o un fallback breve desde el título / cuerpo en Notion.
- **No** envía el título truncado de la tabla como mensaje principal (salvo fallback).

## Flags útiles

| Flag | Efecto |
|------|--------|
| `--within-days N` | Ventana hoy … hoy+N (default 3) |
| `--include-overdue` | Incluye vencidas |
| `--dry-run` | Imprime el mensaje; no envía ni guarda dedup |
| `--force` | Ignora dedup diario (solo pruebas) |

## Deduplicación

- Archivo: `cache/notion_slack_reminders/sent_state.json`
- Regla: como máximo **un aviso por página y día de vencimiento por día natural** (zona horaria local).
- Tras un reset de Notion, conviene borrar este caché (`--clear-reminder-cache` en el script de purge).

## Relación con Pipeline 1

```text
Pipeline 1 (mañana/tarde)     →  llena Notion + fecha objetivo si el audio lo dice
Pipeline 2 (1–2×/día)       →  avisa en Slack lo que vence pronto
```

Si nunca llegan recordatorios, revisa en Notion que las tareas tengan **Fin** o **fecha objetivo** rellenados (el clasificador infiere fechas de frases como “el viernes”, “esta semana”).

## Programación

Ver [windows-scheduler.md](../operations/windows-scheduler.md): tarea separada del pipeline de ingesta, 1–2 veces al día.

## Troubleshooting

| Problema | Qué hacer |
|----------|-----------|
| Siempre “No tasks to remind” | Ampliar `--within-days`; comprobar fechas en Notion; probar `--include-overdue` |
| Mensaje vacío / error Slack | `SLACK_BOT_TOKEN`, bot en el canal, `SLACK_DM_CHANNEL_ID` |
| Repite el mismo aviso | Normal sin `--force`; dedup por día |
| Texto genérico | Asegurar `OBSIDIAN_VAULT_PATH` y nota `slack-<ts>.md` con `recordatorio_slack` |
