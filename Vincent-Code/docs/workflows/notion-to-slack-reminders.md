# Pipeline 2: Notion → Slack (recordatorios)

Lee la base de **tareas/ideas** en Notion, busca filas con **vencimiento cercano** (`Fin` o **fecha objetivo** como fecha) y envía **un mensaje agrupado** al mismo DM de Slack que usa la ingesta.

No confundir con el Pipeline 1: este flujo **no** importa mensajes; solo **avisa** de lo que ya está en Notion.

## Cuándo hay recordatorios

Una fila entra en la ventana si:

- **Próximas:** fecha objetivo entre **hoy** y **hoy + 5 días** (`--within-days`, default **5**).
- **Atrasadas:** fecha objetivo entre **hoy − 7** y **ayer** (`--overdue-max-days`, default **7**). Mensaje distinto: *"Ya deberías haber terminado con: …"*. Más antiguas no se avisan.
- `tipo` es **Tarea** o **Idea** (si existe la propiedad).
- `Estado` no está en la lista excluida (default: Hecho, Terminado, Listo, Done).

**Cloudflare (prioridad):** tareas cuyo título empieza por `Cloudflare` y no están terminadas generan el aviso *«Tienes un error importante en Cloudflare»* aunque no tengan fecha `Fin`. No se duplican en la sección de vencimientos.

Si el script dice *"No tasks to remind"*, suele significar que **ninguna fila tiene fecha objetivo** en esas ventanas (y tampoco hay tareas Cloudflare pendientes). Para depurar: `--dry-run --force`.

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
- `NOTION_TASKS_DATABASE_ID` — base **Tareas Ideas**
- `SLACK_BOT_TOKEN`
- `SLACK_DM_CHANNEL_ID` — mismo canal/DM que Pipeline 1

**Opcionales**
- `SLACK_REMINDER_EXCLUDE_STATUS` — estados a ignorar (coma-separados)
- `OBSIDIAN_VAULT_PATH` — para leer `recordatorio_slack` de `slack-<ts>.md` (mejor texto que el título de la fila)

## Texto del mensaje

- **Cloudflare:** bloque `:warning: *Cloudflare*` con *«Tienes un error importante en Cloudflare»* (sin depender de `Fin`).
- Formato habitual: lista con viñetas bajo `Recordatorios`, en dos bloques si aplica: **Próximas** y **Atrasadas**.
- Próximas: usa `recordatorio_slack` de la nota Obsidian (generado al clasificar), o fallback desde título / cuerpo en Notion.
- Atrasadas (≤7 días): *"Ya deberías haber terminado con: …"* a partir del resumen de la tarea.

## Flags útiles

| Flag | Efecto |
|------|--------|
| `--within-days N` | Ventana hoy … hoy+N (default 5) |
| `--overdue-max-days N` | Vencidas hasta N días atrás (default 7; 0 = ninguna) |
| `--include-overdue` | Legacy: todas las vencidas (ignora límite de 7 días) |
| `--dedup-days N` | Ventana dedup para **próximas** (default 3) |
| `--dedup-days-overdue N` | Ventana dedup para **atrasadas pendientes** (default 2) |
| `--dry-run` | Imprime el mensaje; no envía ni guarda dedup |
| `--force` | Ignora ventana de dedup (solo pruebas) |

## Deduplicación

- Archivo: `state/notion_slack_reminders_sent.json` (versionado en git; GHA hace commit tras cada envío).
- Reglas (zona horaria local):
  - **Próximas:** como máximo un aviso por página y día de vencimiento cada **3** días (`--dedup-days`, default 3).
  - **Atrasadas pendientes** (`Por hacer`, vencimiento ≤ ayer): cada **2** días (`--dedup-days-overdue`, default 2).
  - **Hecho / terminal:** no se avisa (excluidas por estado; no entra en dedup).
- En **GitHub Actions** el workflow corre **3 veces al día** (`:45` UTC ≈ 3:45, 9:45, 15:45 Ecuador); el estado en git evita repetir la misma tarea en runs consecutivos del mismo día.
- Tras un reset de Notion, conviene borrar este estado (`--clear-reminder-cache` en el script de purge).

## Relación con Pipeline 1

```text
Pipeline 1 (3×/día)         →  llena Notion + fecha objetivo si el audio lo dice
Pipeline 2 (3×/día)         →  avisa en Slack (próximas: cada 3 días; atrasadas: cada 2 días)
```

Si nunca llegan recordatorios, revisa en Notion que las tareas tengan **Fin** o **fecha objetivo** rellenados (el clasificador infiere fechas de frases como “el viernes”, “esta semana”).

## Programación

En **GitHub Actions** (3×/día, UTC): ingesta `:00` → completadas `:40` → clasificar+Notion `:42` → recordatorios `:45`. Ver [overview](overview.md).

Local / Windows: tarea separada del pipeline de ingesta, 1–2 veces al día.

## Troubleshooting

| Problema | Qué hacer |
|----------|-----------|
| Siempre “No tasks to remind” | Comprobar fechas en Notion; `--dry-run --force` para ver candidatos |
| Mensaje vacío / error Slack | `SLACK_BOT_TOKEN`, bot en el canal, `SLACK_DM_CHANNEL_ID` |
| Repite el mismo aviso | Verificar que `state/notion_slack_reminders_sent.json` se commitea en GHA; probar con `--dry-run` sin `--force` |
| Texto genérico | Asegurar `OBSIDIAN_VAULT_PATH` y nota `slack-<ts>.md` con `recordatorio_slack` |
