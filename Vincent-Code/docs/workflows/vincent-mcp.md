# Vincent MCP (Cursor local)

Local stdio server so Cursor can search Vincent and start the existing pipelines.
Cursor launches the process when a chat needs it and stops it afterwards. It is not a Windows service.

## Install

```powershell
cd E:\Vincent\Vincent-Code
.\venv\Scripts\python.exe -m pip install -r requirements.txt
```

`mcp>=2.0.0` is the only new dependency.

## Connect Cursor

1. Cursor Settings → **Tools & MCP** → add a server, or paste into your user MCP config.
2. Copy [mcp.json.example](../../mcp.json.example) and keep the `venv` Python + `scripts/vincent_mcp.py` paths.
3. Restart Cursor (or reload MCP). Ask: “Call vincent_health”.

The server loads `Vincent-Code/.env` itself. Do not put secrets in `mcp.json`.

## Tools

**Read**

| Tool | What it does |
|------|----------------|
| `vincent_health` | Paths + which env keys are present (not values) |
| `search_topic` | Local SQLite topic RAG. `answer=true` also calls the LLM |
| `search_knowledge` | Keyword search over own-transcript `knowledge_items` |
| `knowledge_status` | Extraction counts + recent rows |
| `list_open_tasks` | Open Notion Tarea/Idea rows |

**Write** — `confirm=true` required, or `dry_run=true` to preview

| Tool | Script |
|------|--------|
| `extract_knowledge` | `extract_own_transcript_knowledge.py` (default `--limit 3`) |
| `complete_task` | Match + set Hecho (`page_id` if the match is weak) |
| `embed_topic` | `embed_topic.py` |
| `sync_topic` | `sync_topic_embeddings_to_qdrant.py` |
| `run_topic_pipeline` | `run_topic_knowledge_pipeline.py` |
| `run_productivity_pipeline` | Slack → classify → Notion |

Long jobs (`embed_topic`, `sync_topic`, pipelines) default to `wait=false`: they start in the background and return `log_path`. Set `wait=true` to block.

A single lock (`cache/mcp/vincent_jobs.lock`) prevents two write jobs at once.

## Out of scope (v1)

Newsletter send, daily email, local Whisper folder ingest, creating Notion tasks, HTTP/remote MCP, Qdrant as the search backend (Qdrant is write/sync only).

## Local check without Cursor

```powershell
cd E:\Vincent\Vincent-Code
.\venv\Scripts\python.exe -m unittest tests.test_mcp
npx --yes @modelcontextprotocol/inspector@latest .\venv\Scripts\python.exe .\scripts\vincent_mcp.py
```
