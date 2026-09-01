# Pipeline: canal YouTube → Obsidian (subtítulos OAuth)

Transcribe los vídeos publicados en `@AcademiaBlockchain` usando la API oficial de subtítulos (OAuth), sin scraper.

Guía del pipeline **local** (Whisper): [local-video-transcripts.md](local-video-transcripts.md)

---

## Estado actual (snapshot)

Fuente de verdad: `cache/video_transcripts/state.sqlite3` · filas `source_kind=youtube`.

| Estado | Significado | Cantidad (2026-07-24) |
|--------|-------------|------------------------|
| `done` | Transcript en Obsidian vía este pipeline | 118 |
| `skipped` | Ya existía en Obsidian (no re-descargar) | 53 |
| `failed` | Sin subtítulos en YouTube (`no_captions_available`) | 57 |
| `pending` | Detectado, aún no procesado | 0 |
| **total canal** | | **228** |

**Conclusión:** el backlog de subtítulos OAuth está **vacío** (`pending=0`). Los **57 `failed`** no se arreglan reintentando OAuth: YouTube no tiene captions. Hay que bajar el vídeo (o usar archivo local) y pasar por **Whisper** — ver [local-video-transcripts.md](local-video-transcripts.md#youtube-sin-subtitulos--whisper).

Los `skipped` casi todos son “ya existe en Obsidian”: **sí cuentan como transcript disponible**.

Regenerar el resumen en el vault:

```powershell
cd E:\Vincent\Vincent-Code
.\venv\Scripts\python.exe scripts\export_youtube_transcript_status.py
```

---

## Comando diario

```powershell
cd E:\Vincent\Vincent-Code
.\scripts\run_youtube_channel_transcripts.bat
```

Útil sobre todo para **vídeos nuevos** del canal. Task Scheduler: programa `run_youtube_channel_transcripts.bat` con **Iniciar en** `E:\Vincent\Vincent-Code`.

---

## Cuota diaria

Variable `YOUTUBE_OAUTH_DAILY_QUOTA_BUDGET=9000` (~36 vídeos/día, 250 unidades/vídeo).

- El script **no empieza** un vídeo nuevo si la cuota restante no alcanza.
- Los vídeos ya `done` no se repiten.
- Los `pending` se procesan en la siguiente ejecución (al día siguiente).

Si la cuota se agota **en mitad** de una llamada API, ese vídeo queda `failed` con error de cuota; **no** se guarda transcript parcial en Obsidian. Relanzar al día siguiente (o `--retry-failed`).

`--retry-failed` **no** sirve para `no_captions_available` (el error se repetirá).

---

## Estado (archivos)

| Archivo | Rol |
|---------|-----|
| `cache/video_transcripts/state.sqlite3` | Fuente de verdad |
| `10_Sources/Own_Transcripts/_estado_videos.json` | Export completo |
| `10_Sources/Own_Transcripts/_estado_procesamiento.md` | Resumen en Obsidian |

Log: `logs/youtube_channel_transcripts_latest.log`

**Formato:** los `.md` son notas Obsidian con frontmatter YAML + texto plano. El pipeline descarga **SRT** (no VTT) para evitar markup `<c>` que cuelga Obsidian. Si quedaron archivos rotos de antes, el task scheduler ejecuta `repair_youtube_transcript_markdown.py` antes del pipeline.

Reparación manual: `python scripts/repair_youtube_transcript_markdown.py`

Primera vez OAuth: `python scripts/youtube_oauth_login.py`

---

## Automatización diaria (Windows)

Para procesar **vídeos nuevos** del canal sin intervención manual:

```powershell
cd E:\Vincent\Vincent-Code\scripts
.\register_youtube_transcripts_task.ps1
```

Eso crea la tarea `Vincent - YouTube transcripts` **al iniciar sesión** (3 min de retraso para que la red esté lista). Si prefieres hora fija o ambos:

```powershell
.\register_youtube_transcripts_task.ps1 -TriggerType Daily -DailyTime 08:00
.\register_youtube_transcripts_task.ps1 -TriggerType Both
```

Probar:

```powershell
Start-ScheduledTask -TaskName "Vincent - YouTube transcripts"
Get-Content E:\Vincent\Vincent-Code\logs\youtube_scheduler_task.log -Tail 30
```

Wrapper con log dedicado: `scripts/run_youtube_channel_transcripts_scheduled.bat`

Si el Task Scheduler falla (común: usuario sin sesión, rutas, venv), ver plan GHA más abajo.

---

## Automatización en GitHub Actions (plan B)

Sin **cache** de Actions: commitear el SQLite de estado en el repo (ver sección siguiente).

Flujo propuesto (cuando lo implementemos):

1. Cron 1×/día en GHA
2. Checkout → restaurar `pipeline_state/video_transcripts.sqlite3` desde git
3. Escribir token OAuth desde secret → correr `process_youtube_channel.py`
4. Commit vault (`Own_Transcripts/`) + SQLite actualizado

Los vídeos **nuevos** en el canal se detectan en cada run (`upsert_discovered`); el siguiente día pasan a `pending` y se procesan hasta la cuota.

---

## ¿Commitear el SQLite es mala práctica?

**No para tu caso** — es razonable y mejor que cachear en GHA.

| Commitear SQLite | Cache en GHA |
|------------------|--------------|
| Estado visible en git, auditable | Opaco; expira si no hay runs |
| Mismo estado local y en CI | Desincronización local vs CI |
| ~228 filas YouTube (+ locales) = archivo pequeño | Hay que configurar keys de cache |

**Cuándo sí es mala práctica:** datos sensibles en la DB, muchos escritores en paralelo, binarios enormes.

**Cuándo está bien:** pipeline personal, un solo writer (tu PC o un job GHA diario), estado de procesamiento.

Ubicación futura sugerida (fuera de `cache/`, trackeado en git):

`Vincent-Code/pipeline_state/video_transcripts.sqlite3`

Hoy sigue en `cache/video_transcripts/state.sqlite3` (gitignored). Lo movemos cuando montemos GHA.
