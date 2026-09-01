# Pipeline: Knowledge por Tema (Sophia → embeddings → Qdrant)

Pipeline end-to-end para un tema de Academia Blockchain:

1. Asegurar transcripts VIDEO/AUDIO en Sophia  
2. Generar embeddings locales (`text-embedding-3-large`)  
3. Subir vectores a Qdrant Cloud  
4. ACK bookkeeping en Sophia (`embedding-ingest`)  
5. (Opcional) consultar / chatear en local sobre los chunks  

Las **IMAGE** se excluyen. TEXT/descripción van a Qdrant vía SQLite local; el ACK de Sophia solo aplica a VIDEO/AUDIO con transcript.

Contrato en Sophia.AI (fuente de verdad del API): [qdrant-embeddings.md](https://github.com/Alejoss/Sophia.AI/blob/main/docs/operations/qdrant-embeddings.md) · RAG chat: [topic-rag-chat.md](https://github.com/Alejoss/Sophia.AI/blob/main/docs/operations/topic-rag-chat.md).

---

## División de trabajo (Vincent vs Sophia)

Coherente con el código actualizado y con la doc de Sophia: **Vincent crea y escribe los vectores de contenido; Sophia no indexa transcripts.**

| Rol | Vincent (este repo) | Sophia.AI |
|-----|---------------------|-----------|
| Transcripts VIDEO/AUDIO | Worker `transcript-ingest` (Whisper / captions) | Cola + `ContentTranscript` en Postgres |
| Embeddings de **contenido** (chunks) | OpenAI `text-embedding-3-large` (3072 dims) | **No.** No guarda vectores en Django |
| Escritura Qdrant | Upsert a `sophia_acbc_topic_chunks` | No escribe puntos. `check_qdrant --ensure-collection` solo crea la colección vacía |
| Bookkeeping | Tabla local `qdrant_sync` | `PUT /api/content/embedding-ingest/{id}/` → `indexed` / `failed` / `skipped` |
| Lectura Qdrant | Query local opcional (`query_topic_embeddings.py`) | RAG: busca filtrando `topic_id` |
| Embeddings de **pregunta** (query) | Solo en el chat local | Sí, al `POST .../topics/{id}/chat/` (mismo modelo, para buscar; no re-embebe transcripts) |

Auth del worker: la misma key que transcripts (`TRANSCRIPT_INGEST_API_KEY`, header `X-Transcript-Ingest-Key` o `Authorization: Bearer`).

---

## Resumen de scripts

| Paso | Script | Rol |
|------|--------|-----|
| **All-in-one** | `scripts/run_topic_knowledge_pipeline.py` | Orquesta 0→3 en orden |
| 0 | `scripts/map_topic_embedding_volume.py` | Inventario de volumen (tokens / missing) |
| 1 | `scripts/process_topic_transcripts.py` | Transcripts → Sophia + vault |
| 2 | `scripts/embed_topic.py` | Chunk + embed → SQLite local |
| 3 | `scripts/sync_topic_embeddings_to_qdrant.py` | SQLite/cola → Qdrant → ACK Sophia |
| 4 | `scripts/query_topic_embeddings.py` | RAG local (SQLite + OpenAI/Ollama) |

| Qué | Dónde |
|-----|--------|
| Cliente temas | `src/sophia_topics.py` |
| Resolución de texto | `src/sophia_topic_text.py` |
| Transcript ingest client | `src/sophia_transcript_ingest.py` |
| Embedding ingest client | `src/sophia_embedding_ingest.py` |
| Chunk + OpenAI embed | `src/embeddings/` |
| Qdrant client | `src/embeddings/qdrant_store.py` |
| Logging compartido | `src/pipeline_logging.py` |
| SQLite embeddings | `cache/topic_embeddings/state.sqlite3` |
| Reportes JSON/CSV | `cache/topic_embeddings/reports/` |
| Logs de corrida | `logs/` |

Doc de transcripts (detalle): [topic-transcripts-sophia.md](topic-transcripts-sophia.md).

---

## Orden recomendado (tema N)

Comando único (recomendado):

```powershell
cd E:\Vincent\Vincent-Code
.\venv\Scripts\python.exe scripts\run_topic_knowledge_pipeline.py --topic-id N
# o:
.\scripts\run_topic_knowledge_pipeline.bat --topic-id N

# Plan sin efectos:
.\scripts\run_topic_knowledge_pipeline.bat --topic-id N --dry-run
```

Ese wrapper corre en orden: map → transcripts → embed → Qdrant/ack (`--mode queue --also-sqlite-extras`).  
Log orquestador: `logs/topic_knowledge_pipeline_latest.log`. Si un paso falla, se detiene y deja los logs del hijo en `logs/`.

Pasos sueltos (si prefieres controlar uno a uno):

```powershell
# 0) Inventario
.\venv\Scripts\python.exe scripts\map_topic_embedding_volume.py --topic-id N
.\venv\Scripts\python.exe scripts\process_topic_transcripts.py --topic-id N --export-only

# 1) Transcripts faltantes
.\venv\Scripts\python.exe scripts\process_topic_transcripts.py --topic-id N --dry-run
.\venv\Scripts\python.exe scripts\process_topic_transcripts.py --topic-id N

# 2) Embeddings locales
.\venv\Scripts\python.exe scripts\embed_topic.py --topic-id N --dry-run
.\venv\Scripts\python.exe scripts\embed_topic.py --topic-id N

# 3) Qdrant + ACK Sophia
.\venv\Scripts\python.exe scripts\sync_topic_embeddings_to_qdrant.py --ping
.\venv\Scripts\python.exe scripts\sync_topic_embeddings_to_qdrant.py --topic-id N --dry-run
.\venv\Scripts\python.exe scripts\sync_topic_embeddings_to_qdrant.py --topic-id N --mode queue --also-sqlite-extras

# 4) Probar chat local (opcional; no está en el wrapper)
.\venv\Scripts\python.exe scripts\query_topic_embeddings.py --topic-id N --llm-provider openai
```

`--mode auto` (default del sync suelto) usa cola Sophia si el API está vivo; si no, cae a push desde SQLite. El wrapper usa `--mode queue` por defecto.

---

## Sync Qdrant / ACK (detalle)

Worker según handoff Sophia:

1. `GET /api/content/embedding-ingest/?topic_id=N` (cola `pending|stale|failed`)
2. Reusa chunks locales si el texto ya está embebido; si no, chunk + embed
3. Upsert a colección `sophia_acbc_topic_chunks`
4. `PUT .../embedding-ingest/{content_id}/` → `indexed` | `failed` | `skipped`
5. Registro local en tabla `qdrant_sync`

```powershell
.\venv\Scripts\python.exe scripts\sync_topic_embeddings_to_qdrant.py --topic-id N --mode queue
.\venv\Scripts\python.exe scripts\sync_topic_embeddings_to_qdrant.py --topic-id N --mode sqlite
.\venv\Scripts\python.exe scripts\sync_topic_embeddings_to_qdrant.py --topic-id N --mode queue --also-sqlite-extras
```

Atajo: `.\scripts\run_sync_topic_embeddings_to_qdrant.bat --topic-id N`

---

## Query local (RAG)

Retrieval: mismo modelo de embeddings (`text-embedding-3-large` vía OpenAI).  
Respuesta: OpenAI / Groq / Ollama (`--llm-provider`).

```powershell
.\venv\Scripts\python.exe scripts\query_topic_embeddings.py --topic-id N --llm-provider openai
.\venv\Scripts\python.exe scripts\query_topic_embeddings.py --topic-id N --retrieve-only "pregunta"
```

Atajo: `.\scripts\run_query_topic_embeddings.bat --topic-id N --llm-provider openai`

---

## Logs y reportes (cómo revisar qué pasó)

Cada corrida escribe:

1. **Consola** (stdout) con timestamp  
2. **Archivo timestamped** `logs/{run}_{YYYYMMDD_HHMMSS}.log`  
3. **Copia latest** `logs/{run}_latest.log` (se sobrescribe cada run)

| Script | Prefijo de log | Reportes / estado extra |
|--------|----------------|-------------------------|
| `run_topic_knowledge_pipeline.py` | `topic_knowledge_pipeline_*` | Orquesta pasos; mira también los `*_latest` de cada hijo |
| `process_topic_transcripts.py` | `topic_transcripts_*` | Vault `_estado_tema_{id}.json/.md` + SQLite `sophia_content_transcript` |
| `map_topic_embedding_volume.py` | `topic_volume_map_*` | `reports/topic_{id}_embedding_volume_map.{csv,json}` |
| `embed_topic.py` | `embed_topic_*` | `reports/topic_{id}_embed_plan_latest.json` + SQLite `documents`/`chunks` |
| `sync_topic_embeddings_to_qdrant.py` | `qdrant_sync_*` | `reports/topic_{id}_qdrant_sync_latest.json` + SQLite `qdrant_sync` |
| `query_topic_embeddings.py` | `query_topic_*` | (solo log) |

Al inicio de cada run el log imprime las rutas (`Log file:` / `Latest log:`).

### Señales de fallo (sin alertas)

| Señal | Significado |
|--------|-------------|
| Exit code ≠ 0 | Fallo duro (p. ej. Qdrant upsert falló en el sync) |
| `Summary` en consol/JSON con `*_failed` > 0 | Hubo ítems fallidos |
| `qdrant_sync.sophia_ack_status = unavailable/failed` | ACK no aplicado |
| Cola Sophia `GET embedding-ingest/?topic_id=N` con `count > 0` | Quedan pending/stale/failed |
| Docs locales `status=missing` | Sin texto (Spotify sin archivo, Medium, etc.) |
| Cobertura transcripts `remote.pending` | Falta transcribir |

Comprobación rápida post-sync:

```powershell
.\venv\Scripts\python.exe scripts\sync_topic_embeddings_to_qdrant.py --ping
Get-Content .\logs\qdrant_sync_latest.log -Tail 40
Get-Content .\cache\topic_embeddings\reports\topic_N_qdrant_sync_latest.json
```

---

## Resolución de texto (prioridad)

Para VIDEO/AUDIO:

1. `sophia_content_transcript.output_path` (worker de tema)  
2. `video_transcript` por YouTube id / URL (pipelines locales / Knowledge Engine)  
3. Nota en vault `sophia-{id}-*.md` o frontmatter `sophia_content_id`  
4. API `transcript-ingest`  

Para TEXT: PDF público en S3 → PyMuPDF. URLs externas (Medium) quedan `missing` hasta scrapear.

---

## Env

```env
OPENAI_API_KEY=...
SOPHIA_API_BASE=https://www.academiablockchain.com/api
TRANSCRIPT_INGEST_API_KEY=...
OBSIDIAN_VAULT_PATH=../Cerebro-Vincent
EMBEDDING_MODEL=text-embedding-3-large   # opcional
OLLAMA_URL=http://127.0.0.1:11434        # si usas LLM local en query
OLLAMA_MODEL=dolphin-llama3:8b
QDRANT_URL=https://….aws.cloud.qdrant.io
QDRANT_API_KEY=...
QDRANT_COLLECTION=sophia_acbc_topic_chunks
QDRANT_VECTOR_SIZE=3072                  # esperado (3-large); Vincent infiere dims del vector al upsert
```

---

## Relación con Knowledge Engine

No re-extrae `knowledge_items`. Solo reutiliza transcripts locales ya indexados. La extracción estructurada es un pipeline aparte: [own-transcript-knowledge.md](own-transcript-knowledge.md).

## Relación con Sophia.AI

| Doc Sophia | Qué cubre |
|------------|-----------|
| [qdrant-embeddings.md](https://github.com/Alejoss/Sophia.AI/blob/main/docs/operations/qdrant-embeddings.md) | API `embedding-ingest` (cola + ack) y payload Qdrant |
| [topic-rag-chat.md](https://github.com/Alejoss/Sophia.AI/blob/main/docs/operations/topic-rag-chat.md) | Chat autenticado: embebe la **pregunta**, busca en Qdrant, no indexa transcripts |
| [transcript-ingest.md](https://github.com/Alejoss/Sophia.AI/blob/main/docs/api/transcript-ingest.md) | Cola + PUT de transcripts (paso previo) |
| [environment-variables.md](https://github.com/Alejoss/Sophia.AI/blob/main/docs/deployment/environment-variables.md) | `QDRANT_*`, `OPENAI_EMBEDDING_MODEL`, `TRANSCRIPT_INGEST_API_KEY` |
