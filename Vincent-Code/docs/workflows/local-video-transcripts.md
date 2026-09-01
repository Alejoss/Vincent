# Pipeline: vídeos locales → Obsidian (Whisper)

Transcribe archivos de vídeo que **no están en YouTube** (o no tienen subtítulos allí) y guarda el texto en el segundo cerebro.

Complementa el pipeline de YouTube (`process_youtube_channel.py`). Ambos escriben en la misma carpeta del vault y comparten la **misma base SQLite** de estado.

---

## Estado actual (snapshot)

Fuente de verdad: `cache/video_transcripts/state.sqlite3` · filas `source_kind=local`.

| Estado | Cantidad (2026-07-24) |
|--------|------------------------|
| `done` | 45 |
| `pending` | 1 (`donald trump teatro` — el `.mp4` en `E:\Buho Serpiente\...` no estaba en disco) |
| `failed` | 0 |
| `skipped` | 0 |
| **total local** | **46** |

Regenerar resumen en el vault:

```powershell
cd E:\Vincent\Vincent-Code
.\venv\Scripts\python.exe scripts\export_local_transcript_status.py
```

---

## Resumen rápido

| Qué | Dónde |
|-----|--------|
| Script principal | `scripts/process_local_videos.py` |
| Atajo Windows | `scripts/run_local_videos_transcripts.bat` |
| Salida Obsidian | `Cerebro-Vincent/10_Sources/Own_Transcripts/` |
| Fuente de verdad (estado) | `cache/video_transcripts/state.sqlite3` |
| Export legible (vault) | `_estado_videos_local.json`, `_estado_procesamiento_local.md` |
| Log última ejecución | `logs/local_videos_transcripts_latest.log` |
| Audio cache (ffmpeg) | `cache/local_videos/audio/` |

---

## Comando diario

Desde PowerShell o CMD, con el `.env` ya configurado:

```powershell
cd E:\Vincent\Vincent-Code
.\scripts\run_local_videos_transcripts.bat
```

Equivalente explícito:

```powershell
cd E:\Vincent\Vincent-Code
$env:PYTHONIOENCODING='utf-8'
.\venv\Scripts\python.exe scripts\process_local_videos.py
```

### Programarlo en Windows (Task Scheduler)

1. `Win+R` → `taskschd.msc`
2. Crear tarea → nombre: `Vincent - Transcripciones locales`
3. Desencadenador: **1× al día** (p. ej. 03:00, cuando no usas el PC)
4. Acción: **Iniciar un programa**
   - Programa: `E:\Vincent\Vincent-Code\scripts\run_local_videos_transcripts.bat`
   - **Iniciar en:** `E:\Vincent\Vincent-Code`
5. Repetir otro task para YouTube si quieres ambos automatizados:
   - `E:\Vincent\Vincent-Code\scripts\run_youtube_channel_transcripts.bat`

Ver también [Programador de tareas](../operations/windows-scheduler.md).

### Rutina diaria recomendada (YouTube + local)

| Orden | Pipeline | Comando | Notas |
|-------|----------|---------|-------|
| 1 | YouTube (subtítulos OAuth) | `scripts\run_youtube_channel_transcripts.bat` | Backlog OAuth vacío; sirve para **vídeos nuevos** |
| 2 | Local (Whisper) | `scripts\run_local_videos_transcripts.bat` | Búho Serpiente + one-offs |

YouTube tiene límite de cuota de API; el local no. Si el backlog local es grande y usas OpenAI Whisper (de pago), conviene limitar cuántos procesa cada día (ver `--limit` más abajo).

---

## YouTube sin subtítulos → Whisper

Los vídeos del canal marcados `failed` con `no_captions_available` **no** se arreglan con el pipeline OAuth. Flujo:

1. Consigue el `.mp4` (descarga, archivo de edición, etc.).
2. Ponlo solo en una carpeta temporal (evita mezclar con otros `*_final` pendientes), p. ej. `Vincent-Code/cache/_whisper_once_<slug>/`.
3. Renómbralo a `algo_final.mp4` (o usa `--all-files`).
4. Ejecuta:

```powershell
cd E:\Vincent\Vincent-Code
$env:PYTHONIOENCODING='utf-8'
.\venv\Scripts\python.exe scripts\process_local_videos.py `
  --input-dir "E:\Vincent\Vincent-Code\cache\_whisper_once_<slug>" `
  --limit 1 `
  --whisper-provider openai `
  --chunk-long-audio
```

5. El `.md` queda en `Own_Transcripts/`. Opcional: ajustar `title` / `source_url` del frontmatter al vídeo original.

Ejemplo ya hecho: directo `Videojuegos y educación…` → `2026-07-03-videojuegos-educacion-directo.md`.

**Nota:** `faster-whisper` no está instalado en el venv por defecto. Con `WHISPER_PROVIDER=openai` (o `auto` + `OPENAI_API_KEY`) se usa la API. Para local: `pip install faster-whisper` y `--whisper-provider local`.

---

## Convención `_final` (Búho Serpiente)

Los vídeos viven en subcarpetas numeradas bajo una carpeta madre en el disco externo:

```text
E:\Buho Serpiente\
  0_ARCHIVOS_CANAL\
  1_Cap 5 Prohibido\
  2_Listo Cap 33\
  ...
```

**No hace falta copiarlos.** Renombra solo los que quieras transcribir para que el nombre termine en `_final` antes de la extensión:

| Archivo original | Archivo marcado |
|------------------|-----------------|
| `cap5_edit_v3.mp4` | `cap5_edit_v3_final.mp4` |
| `short hollywood.mp4` | `short hollywood_final.mp4` |

El script escanea **recursivamente** `LOCAL_VIDEOS_INPUT_DIR` y procesa únicamente `*_final.{mp4,mkv,...}`.

El título en Obsidian omite el sufijo `_final` (p. ej. `cap5 edit v3`).

Para procesar todos los vídeos sin filtro: `--all-files`.

---

## Configuración (`.env`)

Copia de `env.example`. Variables relevantes:

```env
OBSIDIAN_VAULT_PATH=../Cerebro-Vincent
YOUTUBE_OWN_TRANSCRIPTS_FOLDER=Own_Transcripts

# Obligatorio para este pipeline
LOCAL_VIDEOS_INPUT_DIR=E:/Buho Serpiente

# Solo procesa archivos marcados (renómbralos a algo_final.mp4)
LOCAL_VIDEOS_FILENAME_SUFFIX=_final

# Opcional
LOCAL_VIDEOS_EXTENSIONS=mp4,mkv,mov,avi,webm,m4v,wmv,flv
WHISPER_PROVIDER=auto
OPENAI_API_KEY=sk-...
WHISPER_MODEL=whisper-1
LOCAL_WHISPER_MODEL=small
WHISPER_CHUNK_SECONDS=600
```

| Variable | Valores | Notas |
|----------|---------|--------|
| `LOCAL_VIDEOS_INPUT_DIR` | Ruta absoluta | Carpeta raíz a escanear (recursivo por defecto) |
| `WHISPER_PROVIDER` | `auto`, `openai`, `local` | `auto` usa OpenAI si hay `OPENAI_API_KEY`, si no local |
| `WHISPER_CHUNK_SECONDS` | segundos (default 600) | Solo OpenAI: trocea audio largo en segmentos |
| `LOCAL_WHISPER_MODEL` | p. ej. `small`, `medium` | Solo modo local (`faster-whisper` o CLI) |

---

## Requisitos del sistema

| Componente | Para qué | Instalación |
|------------|----------|-------------|
| **ffmpeg** + **ffprobe** | Extraer audio del vídeo | `winget install Gyan.FFmpeg` y reiniciar terminal |
| **Python venv** | Scripts | Ya en `Vincent-Code/venv` |
| **OpenAI API** | Whisper en la nube | `OPENAI_API_KEY` en `.env` |
| **faster-whisper** | Whisper local sin API | `pip install faster-whisper` (opcional) |
| **openai-whisper CLI** | Alternativa local | `pip install openai-whisper` (opcional) |

Modo **local** recomendado para vídeos muy largos (2+ h) si no quieres muchas llamadas API ni trocear.

---

## Flujo interno

```text
E:\Buho Serpiente\          (LOCAL_VIDEOS_INPUT_DIR)
  1_Cap 5 Prohibido\
    mi_video_final.mp4        ← solo *_final.*
        │
        ▼
  ¿Ya transcrito? → skip
        │ no
        ▼
  ffmpeg → MP3 → Whisper → Own_Transcripts/
        │
        ▼
  state.sqlite3 (done) + export JSON en vault
```

Cada vídeo es **atómico**: o se guarda entero en Obsidian con `status=done`, o falla con `status=failed`. No hay notas a medias en el vault.

---

## ¿Se para a medias cuando hay un límite?

Depende de **qué límite** hablemos.

### Pipeline local (`process_local_videos.py`)

**No tiene cuota diaria integrada.** Una ejecución intenta procesar **todos** los vídeos pendientes de la carpeta (salvo skips).

| Situación | ¿Queda a medias? |
|-----------|------------------|
| Vídeo completado con `[OK]` | No — transcript entero en Obsidian |
| Error de ffmpeg / Whisper / transcript vacío | No en Obsidian — queda `failed` en SQLite; puedes `--retry-failed` |
| `--limit 5` | No a medias — procesa como máximo 5 archivos **enteros**; el resto sigue `pending` |
| Interrumpes con Ctrl+C | Posible corte en el vídeo **en curso** — no se escribe la nota Obsidian hasta el final; al relanzar, ese vídeo sigue pendiente o failed |
| OpenAI: vídeo largo en chunks | No a medias — se transcriben **todos** los chunks y se unen **antes** de guardar; si un chunk falla, el vídeo entero es `failed` |

### Pipeline YouTube (`process_youtube_channel.py`) — por comparación

| Situación | Comportamiento |
|-----------|----------------|
| Cuota diaria OAuth (~9000 unidades ≈ 36 vídeos) | Se **detiene antes** de empezar el siguiente vídeo si no hay cuota. El último vídeo **no** se empieza a medias. |
| Cuota se agota **durante** la descarga de un vídeo | Ese vídeo queda `failed` (error de cuota). **No** se guarda transcript parcial en Obsidian. Mañana sigue `pending` si no lo marcaste failed por cuota — conviene relanzar. |
| Vídeos ya `done` | No se vuelven a tocar |

En resumen: **nunca diseñamos guardar un transcript incompleto en Obsidian**. Lo peor caso es un vídeo marcado `failed` o quedar `pending` para la siguiente ejecución.

---

## Comandos útiles

```powershell
cd E:\Vincent\Vincent-Code
$env:PYTHONIOENCODING='utf-8'

# Ver plan sin transcribir
.\venv\Scripts\python.exe scripts\process_local_videos.py --dry-run

# Probar un solo vídeo
.\venv\Scripts\python.exe scripts\process_local_videos.py --limit 1

# Procesar como máximo N vídeos por ejecución (útil en Task Scheduler + OpenAI)
.\venv\Scripts\python.exe scripts\process_local_videos.py --limit 3

# Reintentar fallidos
.\venv\Scripts\python.exe scripts\process_local_videos.py --retry-failed

# Forzar reprocesado aunque exista en Obsidian
.\venv\Scripts\python.exe scripts\process_local_videos.py --no-skip-existing

# Whisper solo local (sin API)
.\venv\Scripts\python.exe scripts\process_local_videos.py --whisper-provider local

# Otra carpeta puntual
.\venv\Scripts\python.exe scripts\process_local_videos.py --input-dir "D:\Backup\videos"

# Regenerar JSON/MD de estado sin transcribir
.\venv\Scripts\python.exe scripts\export_local_transcript_status.py
```

---

## Estado y seguimiento

Misma SQLite que YouTube, filas con `source_kind=local`:

| Estado | Significado |
|--------|-------------|
| `pending` | Detectado, aún no transcrito |
| `done` | Transcript en `Own_Transcripts/` |
| `failed` | Error (ffmpeg, Whisper, vacío…) |
| `skipped` | Ya existía en Obsidian o en state |

Consulta rápida en Obsidian: abrir `_estado_procesamiento_local.md` o el JSON completo `_estado_videos_local.json`.

---

## Metadatos en Obsidian

Cada nota incluye frontmatter similar al pipeline YouTube:

- `source_type: "Own Video"`
- `source_url: "file:///E:/..."`  (ruta del archivo original)
- `tags: [transcript, source, own-video]` — **sin** tag `youtube`
- Fecha del archivo: `uploaded_date` desde la fecha de modificación del vídeo

---

## Coste y tiempo (orientativo)

| Modo | Vídeo 10 min | Vídeo 2 h |
|------|--------------|-----------|
| OpenAI Whisper API | ~1 llamada | ~12 chunks (600 s c/u) → ~12 llamadas |
| faster-whisper local | CPU/GPU, sin coste API | Puede tardar mucho; una sola pasada |

Para cientos de vídeos largos, valora **`WHISPER_PROVIDER=local`** en horario nocturno.

---

## Solución de problemas

| Síntoma | Qué revisar |
|---------|-------------|
| `ffmpeg no está en PATH` | Instalar ffmpeg y reiniciar terminal |
| `Falta carpeta de entrada` | `LOCAL_VIDEOS_INPUT_DIR` en `.env` |
| `WHISPER_PROVIDER=openai requiere OPENAI_API_KEY` | Añadir key o `--whisper-provider local` |
| Transcripción local falla | `pip install faster-whisper` |
| Archivo muy grande en OpenAI | Bajar `WHISPER_CHUNK_SECONDS` (p. ej. 300) |
| Log detallado | `logs/local_videos_transcripts_latest.log` |
| `NameError: Path is not defined` al exportar estado | Ya corregido en `export_local_transcript_status.py` (import `Path`) |
| Pendiente con path que no existe | Disco externo desconectado o archivo renombrado; reconectar/renombrar y re-lanzar |

---

## Archivos relacionados

- Código: `src/audio_extract.py`, `src/whisper_client.py`, `src/video_transcript_state.py`
- Pipeline YouTube: [youtube-channel-transcripts.md](youtube-channel-transcripts.md)
- Podcast (solo audio, no transcript): `scripts/extract_podcast_mp3.py` → `VideosParaPodcast/mp3/`
- Slack audio (Whisper reutilizado): [slack-to-notion.md](slack-to-notion.md)
