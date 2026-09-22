"""Vincent MCP server: Cursor-local stdio tools over existing pipelines."""

from __future__ import annotations

from typing import Annotated, Literal, Optional

from pydantic import Field

from mcp.server import MCPServer
from mcp.types import ToolAnnotations

from src.embeddings.query import default_embeddings_db
from src.knowledge_engine_state import state_db_path
from src.mcp import knowledge as knowledge_tools
from src.mcp import local_video as local_video_tools
from src.mcp import tasks as task_tools
from src.mcp import topic as topic_tools
from src.mcp.jobs import run_productivity_steps
from src.mcp.paths import PROJECT_ROOT, env_present
from src.topic_embedding_status import topic_embedding_status as audit_topic_embeddings

INSTRUCTIONS = """
Vincent local control plane. Search topics (SQLite embeddings), search own-transcript
knowledge, list/complete Notion tasks, and start existing Vincent pipelines.

For "which files lack embeddings" or coverage questions, use topic_embedding_status
with topic_id or an approximate topic_name. It compares current Sophia contents,
local chunks, live Qdrant and Sophia status. Report partial/unknown sources honestly;
an empty embedding-ingest queue does not establish coverage. No documentation reads
or map_topic extraction are needed for this audit.

Topic TEXT contents support PDF and EPUB (extracted in resolve_media_text /
sophia_document_extract). Use map_topic to inventory resolution status, then
embed_topic / sync_topic / run_topic_pipeline for embeddings and Qdrant.

Local video files (Patreon, disk) use transcribe_local_video (Whisper → Own_Transcripts)
and extract_local_audio (ffmpeg MP3 → VideosParaPodcast/mp3). Podcast episode covers
use generate_podcast_covers (OpenAI Images → VideosParaPodcast/covers).

Write tools require confirm=true. Use dry_run=true to preview. Long jobs default to
background (wait=false) and return a log_path.
""".strip()


def create_server() -> MCPServer:
    return MCPServer(
        "vincent",
        version="1.0.0",
        instructions=INSTRUCTIONS,
    )


mcp = create_server()


@mcp.tool(
    title="Topic embedding coverage status",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=True),
)
def topic_embedding_status(
    topic_id: Annotated[Optional[int], Field(description="Sophia topic id; supply this OR topic_name.", ge=1)] = None,
    topic_name: Annotated[Optional[str], Field(description="Approximate topic title; ambiguous matches return candidates.")] = None,
    model: str = "text-embedding-3-large",
) -> dict:
    """Find missing text, embeddings, uploads and Sophia status gaps. Read-only, no OpenAI calls.

    Returns per-content titles/IDs/reasons, counts and source availability. Unknown
    source failures are not missing records. Images are excluded; PDF vectors and
    Sophia transcript status are separate. Checks metadata, not source-text freshness.
    """
    return audit_topic_embeddings(PROJECT_ROOT, topic_id=topic_id, topic_name=topic_name, model=model)


@mcp.tool(
    title="Vincent health",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
)
def vincent_health() -> dict:
    """Check Vincent-Code paths and whether required env keys are present (not their values)."""
    embed_db = default_embeddings_db(PROJECT_ROOT)
    knowledge_db = state_db_path(PROJECT_ROOT)
    vault = (PROJECT_ROOT.parent / "Cerebro-Vincent")
    return {
        "ok": True,
        "project_root": str(PROJECT_ROOT),
        "paths": {
            "topic_embeddings_db": {"path": str(embed_db), "exists": embed_db.is_file()},
            "knowledge_engine_db": {"path": str(knowledge_db), "exists": knowledge_db.is_file()},
            "vault": {"path": str(vault), "exists": vault.is_dir()},
        },
        "env_present": {
            "OPENAI_API_KEY": env_present("OPENAI_API_KEY"),
            "NOTION_API_TOKEN": env_present("NOTION_API_TOKEN"),
            "NOTION_TASKS_DATABASE_ID": env_present("NOTION_TASKS_DATABASE_ID"),
            "SLACK_BOT_TOKEN": env_present("SLACK_BOT_TOKEN"),
            "OBSIDIAN_VAULT_PATH": env_present("OBSIDIAN_VAULT_PATH"),
            "QDRANT_URL": env_present("QDRANT_URL"),
            "QDRANT_API_KEY": env_present("QDRANT_API_KEY"),
            "SOPHIA_API_BASE": env_present("SOPHIA_API_BASE"),
        },
    }


@mcp.tool(
    title="Search topic embeddings",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
)
def search_topic(
    question: Annotated[str, Field(description="Question to retrieve against the topic.")],
    topic_id: Annotated[int, Field(description="Sophia topic id.", ge=1)],
    top_k: Annotated[int, Field(description="How many chunks to return.", ge=1, le=20)] = 8,
    answer: Annotated[
        bool,
        Field(description="If true, also generate a Sophia-style LLM answer (costs tokens)."),
    ] = False,
) -> dict:
    """RAG over local SQLite topic embeddings. Default returns chunks only."""
    return topic_tools.search_topic(
        question, topic_id, top_k=top_k, answer=answer
    )


@mcp.tool(
    title="Search knowledge extractions",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
)
def search_knowledge(
    query: Annotated[str, Field(description="Keywords to find in extracted knowledge items.")],
    limit: Annotated[int, Field(ge=1, le=50)] = 12,
    item_type: Annotated[
        Optional[str],
        Field(description="Optional item_type filter (claim, quote, argument, …)."),
    ] = None,
) -> dict:
    """Keyword search over own-transcript knowledge_items in the local SQLite engine."""
    return knowledge_tools.search_knowledge(query, limit=limit, item_type=item_type)


@mcp.tool(
    title="Knowledge extraction status",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
)
def knowledge_status(
    limit: Annotated[int, Field(ge=1, le=50, description="Recent extractions to include.")] = 15,
) -> dict:
    """Queue counts and recent own-transcript extractions."""
    return knowledge_tools.knowledge_status(limit=limit)


@mcp.tool(
    title="List open Vincent tasks",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=True),
)
def list_open_tasks(
    query: Annotated[
        Optional[str],
        Field(description="Optional text to rank open Tarea/Idea rows."),
    ] = None,
    limit: Annotated[int, Field(ge=1, le=50)] = 20,
) -> dict:
    """List open Notion Tarea/Idea tasks (not Hecho / cancelled)."""
    return task_tools.list_tasks(query=query, limit=limit)


@mcp.tool(
    title="Extract transcript knowledge",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=False,
        open_world_hint=False,
    ),
)
def extract_knowledge(
    confirm: Annotated[bool, Field(description="Must be true to run (unless dry_run).")] = False,
    dry_run: Annotated[bool, Field(description="Preview the queue, no LLM writes.")] = False,
    limit: Annotated[
        int,
        Field(description="Max transcripts to process when transcript_id is omitted.", ge=0, le=20),
    ] = 3,
    transcript_id: Annotated[
        Optional[str],
        Field(description="Process one transcript by file stem."),
    ] = None,
    retry_failed: bool = False,
    wait: Annotated[bool, Field(description="Wait for the job to finish.")] = True,
) -> dict:
    """Run extract_own_transcript_knowledge.py. Requires confirm=true unless dry_run."""
    return knowledge_tools.extract_knowledge(
        confirm=confirm,
        dry_run=dry_run,
        limit=limit,
        transcript_id=transcript_id,
        retry_failed=retry_failed,
        wait=wait,
    )


@mcp.tool(
    title="Complete a Notion task",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=True,
        idempotent_hint=True,
        open_world_hint=True,
    ),
)
def complete_task(
    query: Annotated[
        Optional[str],
        Field(description="Text used to match an open task (ignored if page_id is set)."),
    ] = None,
    page_id: Annotated[
        Optional[str],
        Field(description="Exact Notion page id. Prefer this when the match is ambiguous."),
    ] = None,
    confirm: bool = False,
    dry_run: bool = False,
) -> dict:
    """Mark a matching open task as Hecho. Weak matches return candidates instead of writing."""
    return task_tools.complete_task(
        query=query, page_id=page_id, confirm=confirm, dry_run=dry_run
    )


@mcp.tool(
    title="Map topic embeddable text",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=True),
)
def map_topic(
    topic_id: Annotated[int, Field(description="Sophia topic id.", ge=1)],
    content_id: Annotated[
        Optional[int],
        Field(description="Optional: only resolve one Sophia content id."),
    ] = None,
    preview_chars: Annotated[
        int,
        Field(
            description="If >0, include a text preview per unit (useful to verify PDF/EPUB extract).",
            ge=0,
            le=2000,
        ),
    ] = 0,
) -> dict:
    """Inventory embeddable text for a topic: VIDEO/AUDIO transcripts + TEXT PDF/EPUB.

    Returns status/source per content (e.g. s3_epub:…, s3_pdf:…). Does not embed or sync.
    """
    return topic_tools.map_topic(
        topic_id, content_id=content_id, preview_chars=preview_chars
    )


@mcp.tool(
    title="Embed a Sophia topic",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=False,
        open_world_hint=True,
    ),
)
def embed_topic(
    topic_id: Annotated[int, Field(ge=1)],
    confirm: bool = False,
    dry_run: bool = False,
    force: bool = False,
    wait: Annotated[bool, Field(description="Default false: start and return log_path.")] = False,
) -> dict:
    """Chunk + embed one topic (VIDEO/AUDIO transcripts + TEXT PDF/EPUB) into local SQLite."""
    return topic_tools.embed_topic(
        topic_id, confirm=confirm, dry_run=dry_run, force=force, wait=wait
    )


@mcp.tool(
    title="Sync topic embeddings to Qdrant",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=False,
        open_world_hint=True,
    ),
)
def sync_topic(
    topic_id: Annotated[int, Field(ge=1)],
    confirm: bool = False,
    dry_run: bool = False,
    force: bool = False,
    mode: Literal["auto", "queue", "sqlite"] = "queue",
    wait: bool = False,
) -> dict:
    """Push topic embeddings to Qdrant (incl. TEXT PDF/EPUB via sqlite extras) and ACK Sophia VIDEO/AUDIO."""
    return topic_tools.sync_topic(
        topic_id,
        confirm=confirm,
        dry_run=dry_run,
        force=force,
        mode=mode,
        wait=wait,
    )


@mcp.tool(
    title="Run full topic knowledge pipeline",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=False,
        open_world_hint=True,
    ),
)
def run_topic_pipeline(
    topic_id: Annotated[int, Field(ge=1)],
    confirm: bool = False,
    dry_run: bool = False,
    force: bool = False,
    wait: bool = False,
    skip_map: bool = False,
) -> dict:
    """Map → VIDEO/AUDIO transcripts → embed (incl. PDF/EPUB TEXT) → Qdrant/ack. Defaults to background."""
    return topic_tools.run_topic_pipeline(
        topic_id,
        confirm=confirm,
        dry_run=dry_run,
        force=force,
        wait=wait,
        skip_map=skip_map,
    )


@mcp.tool(
    title="Transcribe a local video",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=False,
        open_world_hint=False,
    ),
)
def transcribe_local_video(
    video: Annotated[str, Field(description="Absolute path to a local .mp4/.mkv/… file.")],
    confirm: bool = False,
    dry_run: bool = False,
    wait: Annotated[
        bool,
        Field(description="Default false: start Whisper and return log_path."),
    ] = False,
    retry_failed: bool = False,
    force: Annotated[
        bool,
        Field(description="Re-transcribe even if a transcript already exists."),
    ] = False,
    chunk_long_audio: Annotated[
        bool,
        Field(description="Split long audio before OpenAI Whisper (default true)."),
    ] = True,
) -> dict:
    """Run transcribe_one_local_video.py (ffmpeg + Whisper → Own_Transcripts). Defaults to background."""
    return local_video_tools.transcribe_local_video(
        video,
        confirm=confirm,
        dry_run=dry_run,
        wait=wait,
        retry_failed=retry_failed,
        force=force,
        chunk_long_audio=chunk_long_audio,
    )


@mcp.tool(
    title="Extract MP3 from a local video",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=False,
        open_world_hint=False,
    ),
)
def extract_local_audio(
    video: Annotated[str, Field(description="Absolute path to a local .mp4/.mkv/… file.")],
    confirm: bool = False,
    dry_run: bool = False,
    wait: Annotated[
        bool,
        Field(description="Default false: start ffmpeg and return log_path."),
    ] = False,
    force: Annotated[
        bool,
        Field(description="Overwrite an existing MP3."),
    ] = False,
    output_dir: Annotated[
        Optional[str],
        Field(description="MP3 folder. Default: VideosParaPodcast/mp3."),
    ] = None,
) -> dict:
    """Run extract_one_video_audio.py (ffmpeg podcast MP3). Defaults to background."""
    return local_video_tools.extract_local_audio(
        video,
        confirm=confirm,
        dry_run=dry_run,
        wait=wait,
        force=force,
        output_dir=output_dir,
    )


@mcp.tool(
    title="Generate podcast episode covers",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=False,
        open_world_hint=True,
    ),
)
def generate_podcast_covers(
    confirm: bool = False,
    dry_run: bool = False,
    wait: Annotated[
        bool,
        Field(description="Default false: start OpenAI Images and return log_path."),
    ] = False,
    episode_id: Annotated[
        Optional[str],
        Field(description="podcast_episode.episode_id (video filename). Omit to walk catalog order."),
    ] = None,
    limit: Annotated[
        Optional[int],
        Field(description="Only the first N published episodes. Omit for the full published queue.", ge=1),
    ] = None,
    word: Annotated[
        Optional[str],
        Field(description="Override the 1–2 cover words for this run."),
    ] = None,
    force: Annotated[
        bool,
        Field(description="Regenerate even if a cover file already exists."),
    ] = False,
    include_unpublished: Annotated[
        bool,
        Field(description="Also generate for episodes that have no rss_title."),
    ] = False,
) -> dict:
    """Run generate_podcast_covers.py (OpenAI Images → VideosParaPodcast/covers). Defaults to background."""
    return local_video_tools.generate_podcast_covers(
        episode_id=episode_id,
        limit=limit,
        word=word,
        confirm=confirm,
        dry_run=dry_run,
        wait=wait,
        force=force,
        include_unpublished=include_unpublished,
    )


@mcp.tool(
    title="Run Slack → Notion productivity pipeline",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=False,
        open_world_hint=True,
    ),
)
def run_productivity_pipeline(
    confirm: bool = False,
    dry_run: bool = False,
    wait: bool = False,
) -> dict:
    """Slack inbox → classify → Notion sync. Same three Python steps as the Windows .bat."""
    from src.mcp.confirm import write_gate

    refused = write_gate(confirm, dry_run)
    if refused:
        return refused
    return run_productivity_steps(wait=wait, dry_run=dry_run)
