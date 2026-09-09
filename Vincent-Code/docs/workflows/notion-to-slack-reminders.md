# Pipeline 2: Notion → Slack (recordatorios)

Lee la base de **tareas/ideas** en Notion, busca filas con **vencimiento cercano** (`Fin` o **fecha objetivo** como fecha) y envía **un mensaje agrupado** al mismo DM de Slack que usa la ingesta.

No confundir con el Pipeline 1: este flujo **no** importa mensajes; solo **avisa** de lo que ya está en Notion.

## Fuente de verdad

| Qué | Dónde |
|-----|--------|
| Script | `scripts/notion_tasks_due_slack_reminders.py` |
| Dedup | `src/notion_slack_reminders_dedup.py` |
| Wrapper local | `scripts/run_notion_due_slack_reminders.bat` |
| Wrapper GHA | `scripts/run_notion_due_slack_reminders.sh` |
| Workflow | `.github/workflows/notion-reminders.yml` |
| Estado dedup | `state/notion_slack_reminders_sent.json` (versionado; GHA hace commit) |
| Log | `logs/notion_due_slack_reminders.log` |
| Tests | `tests/test_notion_slack_reminders_dedup.py` |

## Cuándo hay recordatorios

Una fila entra en la ventana si:

- **Próximas:** fecha objetivo entre **hoy** y **hoy + 5 días** (`--within-days`, default **5**).
- **Atrasadas:** fecha objetivo entre **hoy − 7** y **ayer** (`--overdue-max-days`, default **7**). Mensaje distinto: *"Ya deberías haber terminado con: …"*. Más antiguas no se avisan.
- `tipo` es **Tarea** o **Idea**. Si la propiedad `tipo` existe pero está vacía, la fila **sí** entra. Cualquier otro valor (p. ej. Aprendizaje) se omite.
- `Estado` no está en la lista excluida (default: Hecho, Terminado, Listo, Done).

**Cloudflare (prioridad):** tareas cuyo título **empieza por** `Cloudflare` y no están en estado excluido generan un aviso aunque no tengan fecha `Fin`: *«Tienes un error importante en Cloudflare: {resto del título}»*. El título de Notion es el hallazgo (p. ej. LCP pobre); **no** es un 5xx del Overview. No se duplican en la sección de vencimientos.

Si el script dice *"No tasks to remind"*, puede ser que:

- ninguna fila tenga fecha objetivo en esas ventanas (ni Cloudflare pendiente), o
- las candidatas ya se avisaron dentro de la ventana de dedup.

Para ver el digest completo ignorando dedup: `--dry-run --force`.

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

En GitHub Actions el cron es `45 8,14,20 * * *` (08:45, 14:45 y 20:45 UTC ≈ 03:45, 09:45 y 15:45 Ecuador). Usa los mismos defaults que el script (sin `--force`).

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

- `SLACK_REMINDER_EXCLUDE_STATUS` — estados a ignorar (coma-separados; default `Hecho,Terminado,Listo,Done`)
- `OBSIDIAN_VAULT_PATH` — para leer `recordatorio_slack` de `slack-<ts>.md` (mejor texto que el título de la fila)

## Texto del mensaje

Un solo `chat.postMessage` con markdown Slack:

- **Cloudflare:** bloque `:warning: *Cloudflare*` con *«Tienes un error importante en Cloudflare: …»* más el resto del título de Notion (sin depender de `Fin`).
- **Recordatorios:** `:speech_balloon: *Recordatorios*` y, si aplica, dos bloques:
  - `*Próximas:*` — `recordatorio_slack` de la nota Obsidian (generado al clasificar). Si falta: `Para YYYY-MM-DD: {resumen}` desde Slack Procesado / notas / título. Último recurso: `¿Avanzaste con: {título}?`.
  - `*Atrasadas (últimos N días):*` — *"Ya deberías haber terminado con: …"* a partir del mismo resumen (N = `--overdue-max-days`).

## Flags útiles

| Flag | Efecto |
|------|--------|
| `--within-days N` | Ventana hoy … hoy+N (default 5) |
| `--overdue-max-days N` | Vencidas hasta N días atrás (default 7; 0 = ninguna) |
| `--include-overdue` | Legacy: todas las vencidas (ignora límite de 7 días; usa 3650) |
| `--dedup-days N` | Ventana dedup para **próximas** y **Cloudflare** (default 3) |
| `--dedup-days-overdue N` | Ventana dedup para **atrasadas** (default 2) |
| `--dry-run` | Imprime el mensaje; no envía ni guarda dedup |
| `--force` | Ignora ventana de dedup (solo pruebas) |

## Deduplicación

- Archivo: `state/notion_slack_reminders_sent.json` (versionado en git; GHA hace commit tras cada envío).
- Claves:
  - vencimientos: `{page_id}|{YYYY-MM-DD}` (si cambia `Fin`, es una clave nueva);
  - Cloudflare: `{page_id}|cloudflare`.
- «Hoy» es la fecha local del proceso (`datetime.now().astimezone()`). En GHA el runner es **UTC**. Los tres slots (08:00, 14:00, 20:00 UTC) caen el **mismo día calendario** en Ecuador (UTC−5), así que no hay desfase de fecha entre producción y Ecuador.
- Reglas:
  - **Próximas** y **Cloudflare:** como máximo un aviso cada **3** días (`--dedup-days`, default 3).
  - **Atrasadas** (estado no excluido, vencimiento ≤ ayer): cada **2** días (`--dedup-days-overdue`, default 2). No exige el nombre `Por hacer`; basta con no estar en Hecho / Terminado / Listo / Done.
  - **Hecho / terminal:** no se avisa (excluidas por estado; no entra en dedup).
- Tras un envío real, se **podan** claves con fecha de envío más antigua que **30 días**.
- En **GitHub Actions** el workflow corre **3 veces al día**; el estado en git evita repetir la misma tarea en runs consecutivos del mismo día.
- Tras un reset de Notion, conviene borrar este estado (`--clear-reminder-cache` en el script de purge).

## Relación con Pipeline 1 y 3

```text
Pipeline 1 (3×/día, :00 UTC)  →  llena Notion + fecha objetivo si el audio lo dice
Pipeline 3 (3×/día, :40 UTC)  →  cierra tareas si el mensaje es de completar
Classify+sync (:42 UTC)       →  aplica intencion=completar antes del aviso
Pipeline 2 (3×/día, :45 UTC)  →  avisa en Slack (próximas/Cloudflare: cada 3 días; atrasadas: cada 2)
```

Si nunca llegan recordatorios, revisa en Notion que las tareas tengan **Fin** o **fecha objetivo** rellenados (el clasificador infiere fechas de frases como “el viernes”, “esta semana”).

## Programación

En **GitHub Actions** (3×/día): `cron: "45 8,14,20 * * *"` — 08:45 / 14:45 / 20:45 UTC. Orden del ciclo: ingesta `:00` → completadas `:40` → clasificar+Notion `:42` → recordatorios `:45`. Ver [overview](overview.md).

Local / Windows: tarea separada del pipeline de ingesta, 1–2 veces al día.

## Troubleshooting

| Problema | Qué hacer |
|----------|-----------|
| Siempre “No tasks to remind” | Comprobar fechas en Notion **y** `state/notion_slack_reminders_sent.json`; `--dry-run --force` para ver candidatos |
| Mensaje vacío / error Slack | `SLACK_BOT_TOKEN`, bot en el canal, `SLACK_DM_CHANNEL_ID` |
| Repite el mismo aviso | Verificar que `state/notion_slack_reminders_sent.json` se commitea en GHA; probar con `--dry-run` sin `--force` |
| Texto genérico (`Para …` / `¿Avanzaste con…`) | Asegurar `OBSIDIAN_VAULT_PATH` y nota `slack-<ts>.md` con `recordatorio_slack` |
| Cloudflare no avisa | El título debe **empezar** por `Cloudflare`; estado no terminal; dedup 3 días |
| Aviso Cloudflare sin detalle / Overview sin 5xx | El hallazgo está en el **título de Notion**, no en Overview. Abrir Web Analytics → Core Web Vitals. Tras este cambio el DM incluye el resto del título. |
