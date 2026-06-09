# Pipeline 2: Notion → Slack (recordatorios)

Lee la base de **tareas/ideas** en Notion, busca filas con **vencimiento cercano** (`Fin` o **fecha objetivo** como fecha) y envía **un mensaje agrupado** al mismo DM de Slack que usa la ingesta.

No confundir con el Pipeline 1: este flujo **no** importa mensajes; solo **avisa** de lo que ya está en Notion.

## Cuándo hay recordatorios

Una fila entra en la ventana si:

- **Próximas:** fecha objetivo entre **hoy** y **hoy + 5 días** (`--within-days`, default **5**).
- **Atrasadas:** fecha objetivo entre **hoy − 7** y **ayer** (`--overdue-max-days`, default **7**). Mensaje distinto: *"Ya deberías haber terminado con: …"*. Más antiguas no se avisan.
- `tipo` es **Tarea** o **Idea** (si existe la propiedad).
- `Estado` no está en la lista excluida (default: Hecho, Terminado, Listo, Done).

Si el script dice *"No tasks to remind"*, suele significar que **ninguna fila tiene fecha objetivo** en esas ventanas. Para depurar: `--dry-run --force`.

## Ejecución recomendada

```powershell
cd E:\Vincent\Vincent-Code
scripts\run_notion_due_slack_reminders.bat
```

Equivalente manual:

```powershell
python scripts/notion_tasks_due_slack_reminders.py
```

Log: `logs\notion_due_slack_reminders.log`

## Probar sin enviar a Slack

```powershell
python scripts/notion_tasks_due_slack_reminders.py --dry-run
```

Prueba amplia (todas las vencidas; solo depuración):

```powershell
python scripts/notion_tasks_due_slack_reminders.py --dry-run --include-overdue --force
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

- Formato: lista con viñetas bajo `Recordatorios`, en dos bloques si aplica: **Próximas** y **Atrasadas**.
- Próximas: usa `recordatorio_slack` de la nota Obsidian (generado al clasificar), o fallback desde título / cuerpo en Notion.
- Atrasadas (≤7 días): *"Ya deberías haber terminado con: …"* a partir del resumen de la tarea.

## Flags útiles

| Flag | Efecto |
|------|--------|
| `--within-days N` | Ventana hoy … hoy+N (default 5) |
| `--overdue-max-days N` | Vencidas hasta N días atrás (default 7; 0 = ninguna) |
| `--include-overdue` | Legacy: todas las vencidas (ignora límite de 7 días) |
| `--dry-run` | Imprime el mensaje; no envía ni guarda dedup |
| `--force` | Ignora dedup diario (solo pruebas) |

## Deduplicación

- Archivo: `cache/notion_slack_reminders/sent_state.json`
- Regla: como máximo **un aviso por página y día de vencimiento por día natural** (zona horaria local).
- En **GitHub Actions** el workflow corre **3 veces al día** (`:30` de 8, 14 y 20 UTC ≈ 3:30, 9:30 y 15:30 Ecuador), pero el caché evita repetir la misma tarea el mismo día aunque haya varios runs.
- Tras un reset de Notion, conviene borrar este caché (`--clear-reminder-cache` en el script de purge).

## Relación con Pipeline 1

```text
Pipeline 1 (3×/día)         →  llena Notion + fecha objetivo si el audio lo dice
Pipeline 2 (3×/día)         →  avisa en Slack (máx. 1 vez por tarea/día)
```

Si nunca llegan recordatorios, revisa en Notion que las tareas tengan **Fin** o **fecha objetivo** rellenados (el clasificador infiere fechas de frases como “el viernes”, “esta semana”).

## Programación

Ver [windows-scheduler.md](../operations/windows-scheduler.md): tarea separada del pipeline de ingesta, 1–2 veces al día.

## Troubleshooting

| Problema | Qué hacer |
|----------|-----------|
| Siempre “No tasks to remind” | Comprobar fechas en Notion; `--dry-run --force` para ver candidatos |
| Mensaje vacío / error Slack | `SLACK_BOT_TOKEN`, bot en el canal, `SLACK_DM_CHANNEL_ID` |
| Repite el mismo aviso | Dedup por día; en GHA verificar que `actions/cache` restaura `sent_state.json` |
| Texto genérico | Asegurar `OBSIDIAN_VAULT_PATH` y nota `slack-<ts>.md` con `recordatorio_slack` |
