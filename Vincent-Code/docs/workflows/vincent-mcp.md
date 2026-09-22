# Vincent MCP (Cursor local)

Local stdio server so Cursor can search Vincent and start the existing pipelines.
Cursor launches the process when a chat needs it and stops it afterwards. It is not a Windows service.

## Install

```powershell
cd E:\Vincent\Vincent-Code
.\venv\Scripts\python.exe -m pip install -r requirements.txt
```

`mcp>=2.0.0` is required. Topic TEXT documents also need `PyMuPDF`, `ebooklib`, and `beautifulsoup4` (listed in `requirements.txt`).

## Connect Cursor

1. Cursor Settings → **Tools & MCP** → add a server, or paste into your user MCP config.
2. Copy [mcp.json.example](../../mcp.json.example) into `.cursor/mcp.json` (this repo) and/or `~/.cursor/mcp.json`. Keep `type: stdio` plus the `venv` Python and `scripts/vincent_mcp.py` paths.
3. Restart Cursor (or reload MCP). Enable **vincent** under Settings → Tools & MCP if it is toggled off. Ask: “Call vincent_health”.

The server loads `Vincent-Code/.env` itself. Do not put secrets in `mcp.json`.

## Tools

**Read**

| Tool | What it does |
|------|----------------|
| `vincent_health` | Paths + which env keys are present (not values) |
| `search_topic` | Local SQLite topic RAG. `answer=true` also calls the LLM |
| `map_topic` | Inventory embeddable text for a topic (transcripts + TEXT PDF/EPUB status) |
| `topic_embedding_status` | Read-only live coverage audit by topic ID or approximate name: missing text/embeddings/uploads, Qdrant counts, and Sophia status gaps |
| `search_knowledge` | Keyword search over own-transcript `knowledge_items` |
| `knowledge_status` | Extraction counts + recent rows |
| `list_open_tasks` | Open Notion Tarea/Idea rows |

**Write** — `confirm=true` required, or `dry_run=true` to preview

| Tool | Script |
|------|--------|
| `extract_knowledge` | `extract_own_transcript_knowledge.py` (default `--limit 3`) |
| `complete_task` | Match + set Hecho (`page_id` if the match is weak) |
| `embed_topic` | `embed_topic.py` (VIDEO/AUDIO + TEXT PDF/EPUB) |
| `sync_topic` | `sync_topic_embeddings_to_qdrant.py` (TEXT via `--also-sqlite-extras`) |
| `run_topic_pipeline` | `run_topic_knowledge_pipeline.py` |
| `run_productivity_pipeline` | Slack → classify → Notion |
| `transcribe_local_video` | `transcribe_one_local_video.py` (ffmpeg + Whisper → Own_Transcripts) |
| `extract_local_audio` | `extract_one_video_audio.py` (ffmpeg MP3 → VideosParaPodcast/mp3; SQLite `podcast_episode`) |
| `generate_podcast_covers` | `generate_podcast_covers.py` (OpenAI Images → VideosParaPodcast/covers; SQLite cover_* ) |

Long jobs (`embed_topic`, `sync_topic`, pipelines, `transcribe_local_video`, `extract_local_audio`, `generate_podcast_covers`) default to `wait=false`: they start in the background and return `log_path`. Set `wait=true` to block.

A single lock (`cache/mcp/vincent_jobs.lock`) prevents two write jobs at once.

## Topic TEXT documents (PDF / EPUB)

### Frequent coverage questions

For “which files still lack embeddings?”, call
`topic_embedding_status(topic_name="El secuestro de Bitcoin y el tamaño de la cadena de bloques")`
or `topic_embedding_status(topic_id=2)`. Supply exactly one selector. Ambiguous names
return candidate IDs rather than choosing a topic. The default model is
`text-embedding-3-large`; pass `model` to audit another model.

This tool reads the current Sophia inventory, actual local chunk rows, Qdrant chunk
metadata (paginated, without vectors/text), and Sophia embedding-ingest with completed
items included. It does not extract files, generate embeddings, ACK Sophia, or write
to SQLite/Qdrant. An empty Sophia queue alone is **not** a coverage check.

Each item includes title, content ID, counts, text status, reason and issues. PDF
vectors without Sophia bookkeeping are `embedded` with `sophia_status_untracked`.
Missing uploads, mismatched chunk indexes/hashes and Sophia `stale` status are
distinguished from missing embeddings. Images are `excluded`.

Check `complete` and `sources`: inaccessible sources are **unknown**, never zero.
`ok=true, complete=false` is a partial audit. Counts exclude the topic description.
Text availability is metadata-based: this quick check does not scan other transcript
caches, extract PDF/EPUB/webpages, or establish freshness against current source text.

CLI fallback (same implementation):

```powershell
.\venv\Scripts\python.exe scripts\topic_embedding_status.py --topic-name "secuestro de Bitcoin"
.\venv\Scripts\python.exe scripts\topic_embedding_status.py --topic-id 2
```

CLI prints JSON; exit 1 means unresolved topic or incomplete audit, not missing files.
Restart/reload the Vincent MCP connection after updating the server to discover this
tool. The connection must expose Vincent's tools to the current client; otherwise use
the CLI fallback. No script/documentation investigation is needed for routine audits.

Sophia **TEXT** contents are not Whisper transcripts. They are resolved when mapping/embedding:

```text
file URL or S3 file_key
        → sophia_document_extract (sniff PDF vs EPUB)
        → resolve_media_text
        → embed_topic → SQLite
        → sync_topic (--also-sqlite-extras) → Qdrant
```

| Format | Extractor | Typical `text_source` |
|--------|-----------|------------------------|
| PDF | PyMuPDF | `s3_pdf:filename.pdf` |
| EPUB | ebooklib (+ zip/HTML fallback) | `s3_epub:filename.epub` |

Recommended MCP flow for a topic that includes books/articles:

1. `map_topic(topic_id=N)` — confirm TEXT rows are `ok` with `s3_epub:…` / `s3_pdf:…`
2. Optional: `map_topic(topic_id=N, content_id=…, preview_chars=400)` to spot-check extract quality
3. `embed_topic(topic_id=N, dry_run=true)` then `confirm=true`
4. `sync_topic(topic_id=N, confirm=true)` — or `run_topic_pipeline` for the full chain

VIDEO/AUDIO still use the transcript worker inside `run_topic_pipeline`. TEXT does not go through Whisper. Sophia embedding ACK remains VIDEO/AUDIO only; TEXT/description still land in Qdrant via sqlite extras.

Code: `src/sophia_document_extract.py`, `src/sophia_topic_text.py`, `src/sophia_topic_volume.py`.  
Pipeline detail: [topic-embeddings.md](topic-embeddings.md).

## Local video (Whisper + MP3)

One local `.mp4` / `.mkv` / … file (Patreon, disk):

1. `extract_local_audio(video="E:\\Patreon\\….mp4", dry_run=true)` then `confirm=true` → `VideosParaPodcast/mp3/` (row in SQLite `podcast_episode`)
2. `transcribe_local_video(video="…", dry_run=true)` then `confirm=true` → `Own_Transcripts/`
3. `generate_podcast_covers(limit=1, dry_run=true)` then `confirm=true` → `VideosParaPodcast/covers/` (OpenAI Images, square 1:1)

Spotify titles/dates: `python scripts/sync_podcast_rss.py`. Full pipeline: [podcast-mp3.md](podcast-mp3.md).

Folder-wide ingest (`process_local_videos.py` / `extract_podcast_mp3.py` over a directory) stays a script. Whisper detail: [local-video-transcripts.md](local-video-transcripts.md).

## Out of scope (v1)

Newsletter send, daily email, creating Notion tasks, HTTP/remote MCP, Qdrant as the search backend (Qdrant is write/sync only).

## Local check without Cursor

```powershell
cd E:\Vincent\Vincent-Code
.\venv\Scripts\python.exe -m unittest tests.test_mcp tests.test_sophia_document_extract
npx --yes @modelcontextprotocol/inspector@latest .\venv\Scripts\python.exe .\scripts\vincent_mcp.py
```
