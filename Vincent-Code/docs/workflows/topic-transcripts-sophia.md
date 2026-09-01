# Pipeline: transcripts por Tema (Sophia / Digital Ocean)

Asegura que cada contenido **VIDEO** o **AUDIO** de un tema en AcademIA Blockchain tenga un `ContentTranscript` en el servidor.

El worker corre en el laptop (Vincent-Code): usa la API machine-to-machine `transcript-ingest`, captions de YouTube y/o Whisper (archivo en S3 o yt-dlp), y guarda estado local con `topic_id(s)` + `transcribed_at`.

Complementa los pipelines de YouTube/local → Obsidian; este escribe también a Sophia.

---

## Resumen rápido

| Qué | Dónde |
|-----|--------|
| Script principal | `scripts/process_topic_transcripts.py` |
| Atajo Windows | `scripts/run_topic_transcripts.bat` |
| Cliente HTTP | `src/sophia_transcript_ingest.py` |
| Estado SQLite | `cache/video_transcripts/state.sqlite3` → tabla `sophia_content_transcript` |
| Cache media S3 | `cache/sophia_media/{content_id}/` |
| Cobertura | `10_Sources/Own_Transcripts/_estado_tema_{id}.json` (+ `.md`) |
| Contrato API | Sophia `docs/api/transcript-ingest.md` |

---

## Variables de entorno

En `Vincent-Code/.env` (también se lee como fallback `Sophia…/acbc_app/.env` para AWS):

```env
SOPHIA_API_BASE=https://www.academiablockchain.com/api
TRANSCRIPT_INGEST_API_KEY=...   # debe coincidir con el valor en el droplet DO

AWS_STORAGE_BUCKET_NAME=academiablockchain
AWS_S3_REGION_NAME=us-west-2
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...

OPENAI_API_KEY=...              # si WHISPER_PROVIDER=openai
WHISPER_PROVIDER=auto
OBSIDIAN_VAULT_PATH=../Cerebro-Vincent
```

Si `TRANSCRIPT_INGEST_API_KEY` está vacío en el servidor, la API responde **403**.

### Activar la key en Digital Ocean (una vez)

1. Copia el valor de `TRANSCRIPT_INGEST_API_KEY` desde `Vincent-Code/.env` (ya generado localmente).
2. En el droplet, edita `acbc_app/.env` y añade la **misma** línea.
3. Recrea el backend para cargar env, p. ej.:

```bash
cd /ruta/al/repo   # donde está docker-compose.prod.yml
docker compose --env-file .env.compose -f docker-compose.prod.yml up -d --force-recreate backend
```

4. Verifica desde el laptop:

```powershell
cd E:\Vincent\Vincent-Code
.\venv\Scripts\python.exe scripts\process_topic_transcripts.py --topic-id 1 --export-only
```

Sin SSH desde esta máquina al droplet (`Permission denied (publickey)`), este paso es manual (consola DO o la clave SSH autorizada).

Comprobar bucket:

```powershell
aws s3 ls s3://academiablockchain/ --region us-west-2
```

---

## Comandos

Desde `E:\Vincent\Vincent-Code`:

```powershell
# Inventario + export cobertura (sin gastar Whisper)
.\venv\Scripts\python.exe scripts\process_topic_transcripts.py --topic-id 12 --export-only

# Dry-run: qué se procesaría
.\venv\Scripts\python.exe scripts\process_topic_transcripts.py --topic-id 12 --dry-run

# Smoke: un solo contenido
.\venv\Scripts\python.exe scripts\process_topic_transcripts.py --topic-id 12 --limit 1

# Tema completo
.\venv\Scripts\python.exe scripts\process_topic_transcripts.py --topic-id 12

# Forzar re-PUT aunque remoto ya tenga transcript
.\venv\Scripts\python.exe scripts\process_topic_transcripts.py --topic-id 12 --content-id 101 --force
```

Atajo:

```powershell
.\scripts\run_topic_transcripts.bat 12
.\scripts\run_topic_transcripts.bat 12 --dry-run
```

---

## Orden por ítem

1. Si remoto `has_transcript` (salvo `--force`) → skip; merge `topic_id` en SQLite
2. **Buscar transcript local** en SQLite `video_transcript` por **YouTube video id** (o `source_url` exacta) → leer el `.md` de `output_path` → reutilizar (`method=local_vault`). No se escanea la carpeta ni se comparan títulos (son frágiles).
3. Else YouTube captions (`youtube-transcript-api`) si aplica
4. Else `file_key` → `aws s3 cp` → ffmpeg audio → Whisper
5. Else URL → yt-dlp audio → Whisper
6. `PUT /api/content/transcript-ingest/{content_id}/`
7. Marcar `done` + `transcribed_at` (UTC) + `text_hash` / `server_created_at`
8. Nota nueva en Obsidian solo si no hubo reuse local
9. Export cobertura del tema

En `--dry-run`, el log distingue `would REUSE LOCAL` vs `would GENERATE`.

---

## Estado local (SQLite)

Tabla `sophia_content_transcript`:

- PK `content_id` (Sophia)
- `topic_ids` (JSON), `primary_topic_id`
- `status`: pending / done / failed / skipped
- `method`: youtube_captions / whisper_s3 / whisper_ytdlp
- `transcribed_at`, `uploaded_at`, `server_created_at`, `server_updated_at`
- `text_hash`, `output_path`, `error`

Un contenido en varios temas: el transcript es 1:1 en servidor; local solo añade el `topic_id` al array.

---

## Checklist de cobertura

1. Key local = key en droplet; `export-only` no debe dar 403
2. `--export-only` → revisar `_estado_tema_{id}.md` (remote pending/completed)
3. `--dry-run` / `--limit 1` (preferir un YouTube con captions)
4. Procesar pendientes del tema
5. Re-export: `remote.pending` = 0 o lista explícita de `failed`
6. Opcional: detail GET → `has_transcript: true` + `transcribed_at` en SQLite

## Verificación hecha en el laptop (implementación)

| Check | Resultado |
|-------|-----------|
| Unit tests `tests.test_sophia_topic_transcripts` | OK |
| `aws s3 ls s3://academiablockchain/` | OK |
| `SOPHIA_API_BASE` + key en `.env` local | OK |
| Endpoint prod `/transcript-ingest/` | Ruta viva (403 sin key remota alineada) |
| Smoke PUT contra un tema real | **Bloqueado** hasta alinear key en el droplet |

---

## Relación con otros pipelines

| Pipeline | Destino | Clave estado |
|----------|---------|--------------|
| `process_youtube_channel.py` | Obsidian | `video_id` YouTube |
| `process_local_videos.py` | Obsidian | `local:…` |
| **`process_topic_transcripts.py`** | Sophia + Obsidian | `content_id` Sophia |

Siguiente paso del mismo tema (embeddings → Qdrant → ack): [topic-embeddings.md](topic-embeddings.md).

### Logs

Cada corrida escribe `logs/topic_transcripts_{timestamp}.log` y el mismo contenido en `logs/topic_transcripts_latest.log`.

