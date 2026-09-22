# Pipeline: vídeo local → MP3 de podcast + catálogo Spotify

Extrae audio de un `.mp4` (Patreon, disco, `VideosParaPodcast/`) a MP3 de calidad podcast y registra el episodio en SQLite. Si el episodio ya está en Spotify, el RSS aporta el **título publicado** y la **fecha de publicación**.

Esto **no** es el pipeline de transcripción. Whisper escribe transcripts en Obsidian (`video_transcript`). Aquí solo hay audio para publicar y metadatos de Spotify.

---

## Fuente de verdad

Misma base que las transcripciones, **otra tabla**:

`Vincent-Code/cache/video_transcripts/state.sqlite3`

| Tabla | Pipeline | No mezclar con |
|-------|----------|----------------|
| `video_transcript` | YouTube OAuth + Whisper local | títulos RSS, fechas Spotify, rutas MP3 |
| `podcast_episode` | Extract ffmpeg + match RSS | `output_path` de transcript, `published_at` de YouTube |
| `podcast_meta` | `rss_url`, `last_sync_at` | — |

`video_transcript.title` / `published_at` son del vídeo o de YouTube. `podcast_episode.rss_title` / `rss_pub_date` son del feed de Spotify. Un mismo archivo puede tener fila en ambas tablas (`video_id` opcional en `podcast_episode` si ya existe transcript del mismo `source_path`).

**No** hay un JSON de estado editable. `_estado_podcast.json` era un almacén paralelo; se migró a SQLite y se eliminó. El markdown es un **export derivado**, igual que `_estado_procesamiento_local.md`.

| Rol | Ruta |
|-----|------|
| Fuente de verdad | `cache/video_transcripts/state.sqlite3` · `podcast_episode` |
| MP3 | `VideosParaPodcast/mp3/` |
| Export legible | `VideosParaPodcast/orden-publicacion.md` (regenerar, no editar a mano) |
| RSS | `https://anchor.fm/s/114269ac0/podcast/rss` |
| Show Spotify | [Alejandro Veintimilla](https://open.spotify.com/show/033DER84Vz4fQNno4Znh9u) |

---

## Resumen rápido

| Qué | Dónde |
|-----|--------|
| Un archivo (MCP) | `extract_local_audio` — [vincent-mcp.md](vincent-mcp.md) |
| Portadas 1:1 (MCP) | `generate_podcast_covers` — [vincent-mcp.md](vincent-mcp.md) |
| Un archivo (script) | `scripts/extract_one_video_audio.py` |
| Carpeta de vídeos | `scripts/extract_podcast_mp3.py` |
| Sync títulos/fechas Spotify | `scripts/sync_podcast_rss.py` |
| Código | `src/podcast_catalog.py`, `src/audio_extract.py`, `src/podcast_covers.py`, tabla en `src/video_transcript_state.py` |
| Tests | `tests/test_podcast_catalog.py`, `tests/test_podcast_covers.py` |
| Portadas 1:1 | `scripts/generate_podcast_covers.py` (OpenAI Images + estilo en `assets/podcast_covers/`) |

ffmpeg debe estar en `PATH`. Bitrate podcast: 192k / 44.1 kHz (`extract_audio_podcast`).

---

## Extraer audio

### Un vídeo (preferido: MCP)

```text
extract_local_audio(video="E:\\Patreon\\Filosofia Politica Profunda Vol 1.mp4", dry_run=true)
extract_local_audio(video="E:\\Patreon\\Filosofia Politica Profunda Vol 1.mp4", confirm=true)
```

Si el MCP no está cargado:

```powershell
cd E:\Vincent\Vincent-Code
.\venv\Scripts\python.exe scripts\extract_one_video_audio.py "E:\Patreon\video.mp4"
```

Salida por defecto: `E:\Vincent\VideosParaPodcast\mp3\<stem>.mp3`.  
Eso hace `INSERT`/`UPDATE` en `podcast_episode` (`extracted_at`, `source_path` si el `.mp4` no está en `VideosParaPodcast/`).

### Lote (vídeos ya en `VideosParaPodcast/`)

```powershell
cd E:\Vincent\Vincent-Code
.\venv\Scripts\python.exe scripts\extract_podcast_mp3.py
.\venv\Scripts\python.exe scripts\extract_podcast_mp3.py --dry-run
```

---

## Sync RSS (títulos y fechas de Spotify)

Tras extraer, o cuando hay episodios nuevos en Spotify:

```powershell
cd E:\Vincent\Vincent-Code
.\venv\Scripts\python.exe scripts\sync_podcast_rss.py
.\venv\Scripts\python.exe scripts\sync_podcast_rss.py --dry-run
```

`--dry-run` solo calcula el emparejamiento; no escribe SQLite ni el markdown.

El match, en orden: tamaño de enclosure exacto → tamaño ±2 KB → pistas de nombre de archivo → solape de tokens. Un episodio RSS y un MP3 se usan como máximo una vez.

Luego regenera `VideosParaPodcast/orden-publicacion.md` desde SQLite.

---

## Portadas (OpenAI Images)

Una imagen cuadrada **1:1** por episodio publicado. El estilo vive en
`Vincent-Code/assets/podcast_covers/academia_blockchain_visual_reference.jpg`
(solo color/línea/atmósfera; no se copia el personaje). En la imagen va **una o dos palabras** del título (p. ej. `PERSPECTIVA`), no el título completo.

Prefer MCP:

```text
generate_podcast_covers(limit=1, dry_run=true)
generate_podcast_covers(limit=1, confirm=true)
generate_podcast_covers(episode_id="noticias_guerra_cripto_final.mp4", force=true, confirm=true)
```

If the MCP is down:

```powershell
cd E:\Vincent\Vincent-Code
.\venv\Scripts\python.exe scripts\generate_podcast_covers.py --limit 1 --dry-run
.\venv\Scripts\python.exe scripts\generate_podcast_covers.py --limit 1
.\venv\Scripts\python.exe scripts\generate_podcast_covers.py --episode-id "noticias_guerra_cripto_final.mp4" --force
```

`--limit 1` es el primer episodio con `rss_pub_date` (hoy: PERSPECTIVA).
Salida: `VideosParaPodcast/covers/<stem>.png`. SQLite guarda `cover_path`, `cover_word`, `cover_model`, `cover_status`.

Usa `OPENAI_API_KEY` (no el generador de imágenes de Cursor). Tamaño por defecto `1024x1024` (el tamaño cuadrado que admite la API). Calidad `medium`.

---

## Columnas de `podcast_episode`

| Columna | Qué es |
|---------|--------|
| `episode_id` | Clave = nombre del vídeo (`Marx Armesilla.mp4`) |
| `file_title` | Stem del archivo local (no el título de Spotify) |
| `video_filename` / `source_path` | Nombre y ruta del `.mp4` (Patreon, `E:\Academia Blockchain\…`, etc.) |
| `mp3_filename` / `mp3_path` | MP3 en `VideosParaPodcast/mp3/` |
| `status` / `skipped` / `extracted_at` / `error` | Resultado del extract |
| `rss_guid` / `rss_title` / `rss_pub_date` / `rss_link` / `rss_duration` | Feed Anchor/Spotify (NULL si aún no está publicado) |
| `rss_match` | `size_exact`, `size_near`, `filename_hint`, `token_overlap` |
| `video_id` | FK opcional a `video_transcript` si hay transcript del mismo path |
| `cover_path` / `cover_word` / `cover_model` / `cover_status` | Portada 1:1 (OpenAI Images) |
| `cover_generated_at` / `cover_error` / `cover_prompt` | Auditoría de la generación |
| `updated_at` | Última escritura de esta fila |

Consultar:

```powershell
cd E:\Vincent\Vincent-Code
.\venv\Scripts\python.exe -c "from src.video_transcript_state import open_state; c=open_state('.'); print(list(c.execute('SELECT mp3_filename, rss_title, rss_pub_date, extracted_at FROM podcast_episode ORDER BY COALESCE(rss_pub_date, extracted_at)'))); c.close()"
```

---

## Qué no hacer

- No volver a crear `_estado_podcast.json` como almacén. SQLite es la fuente de verdad.
- No editar `orden-publicacion.md` a mano; se pisa en el siguiente `sync_podcast_rss.py`.
- No añadir `rss_title` / `rss_pub_date` a `video_transcript` (denormaliza Whisper).
- No usar la fecha de modificación del MP3 como fecha del episodio: el lote ffmpeg no es la cronología de Spotify. Usa `rss_pub_date` para lo publicado y `extracted_at` para “cuándo salió el MP3”.

---

## Relacionado

- Transcripciones locales (Whisper): [local-video-transcripts.md](local-video-transcripts.md)
- MCP: [vincent-mcp.md](vincent-mcp.md)
- Show: [open.spotify.com/show/033DER84Vz4fQNno4Znh9u](https://open.spotify.com/show/033DER84Vz4fQNno4Znh9u)
