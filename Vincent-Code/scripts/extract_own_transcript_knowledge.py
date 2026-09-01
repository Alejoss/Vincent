#!/usr/bin/env python3
"""
Extract structured knowledge from Own_Transcripts and save to Obsidian.

Reads:
  Cerebro-Vincent/10_Sources/Own_Transcripts/*.md

Writes:
  Cerebro-Vincent/20_Extractions/Own_Transcripts/{stem}-knowledge.md
  Vincent-Code/cache/knowledge_extractions/json/{stem}.json

State (source of truth):
  Vincent-Code/cache/knowledge_engine/state.sqlite3

Examples (from Vincent-Code root):
  python scripts/extract_own_transcript_knowledge.py --dry-run
  python scripts/extract_own_transcript_knowledge.py --limit 3
  python scripts/extract_own_transcript_knowledge.py --id 2026-02-25-qué-es-paragon-solutions-y-qué-tiene-que-ver-con-epstein
  python scripts/extract_own_transcript_knowledge.py --export-status

Requires in .env:
  OBSIDIAN_VAULT_PATH=../Cerebro-Vincent
  OPENAI_API_KEY (or GROQ_API_KEY / local Ollama via LLM_PROVIDER)
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv(PROJECT_ROOT / ".env", override=True)

from src.knowledge_engine_state import (
    delete_knowledge_items,
    get_extraction_status,
    infer_source_kind,
    insert_knowledge_items,
    mark_content_changed,
    mark_extraction_done,
    mark_extraction_failed,
    open_engine,
    reconcile_done_with_vault,
    state_db_path,
    sync_status_exports,
    transcript_id_from_path,
    upsert_video,
    count_items_by_type,
)
from src.knowledge_extraction_state import content_hash
from src.knowledge_extractor import (
    extract_knowledge,
    flatten_to_knowledge_items,
    is_status_artifact,
    parse_frontmatter,
    write_outputs,
)
from src.llm_client import build_knowledge_llm_config, validate_llm_config

DEFAULT_TRANSCRIPT_FOLDER = "Own_Transcripts"
DEFAULT_EXTRACTION_FOLDER = "Own_Transcripts"
LOG_DIR = PROJECT_ROOT / "logs"
LATEST_LOG_NAME = "knowledge_extraction_latest.log"
JSON_CACHE_DIR = PROJECT_ROOT / "cache" / "knowledge_engine" / "json"


def setup_logging(verbose: bool) -> Path:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = LOG_DIR / f"knowledge_extraction_{timestamp}.log"
    latest_log = LOG_DIR / LATEST_LOG_NAME

    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    root.handlers.clear()

    detailed = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(message)s",
        datefmt="%H:%M:%S",
    )
    console = logging.Formatter("%(message)s")

    for path, mode in ((log_file, "w"), (latest_log, "w")):
        fh = logging.FileHandler(path, encoding="utf-8", mode=mode)
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(detailed)
        root.addHandler(fh)

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(console)
    root.addHandler(ch)

    log = logging.getLogger(__name__)
    log.info("=" * 60)
    log.info("Pipeline — extracción de conocimiento (Own_Transcripts)")
    log.info("Log detallado: %s", log_file)
    log.info("Log en vivo (última ejecución): %s", latest_log)
    log.info("=" * 60)
    return log_file


def resolve_vault_path(explicit: Optional[str] = None) -> Path:
    raw = (explicit or os.getenv("OBSIDIAN_VAULT_PATH") or "../Cerebro-Vincent").strip()
    return (PROJECT_ROOT / raw).resolve()


def list_transcript_files(transcript_dir: Path) -> List[Path]:
    if not transcript_dir.is_dir():
        return []
    files = [
        path
        for path in sorted(transcript_dir.glob("*.md"))
        if path.is_file() and not is_status_artifact(path)
    ]
    return files


def discover_transcripts(
    conn,
    *,
    transcript_dir: Path,
    log: logging.Logger,
) -> int:
    discovered = 0
    for path in list_transcript_files(transcript_dir):
        video_id = transcript_id_from_path(path)
        raw = path.read_text(encoding="utf-8")
        fm, body = parse_frontmatter(raw)
        title = (fm.get("title") or video_id).strip()
        source_url = (fm.get("source_url") or "").strip()
        source_type = (fm.get("source_type") or "").strip()
        language = (fm.get("language_code") or "es").strip() or "es"
        published_at = (fm.get("uploaded_date") or "").strip() or None
        body_hash = content_hash(body)
        word_count = len(body.split())
        source_path = source_url if source_url.lower().startswith("file:") else None

        upsert_video(
            conn,
            video_id=video_id,
            source_kind=infer_source_kind(source_url, source_type),
            title=title,
            source_url=source_url,
            source_path=source_path,
            transcript_path=str(path.resolve()),
            transcript_hash=body_hash,
            word_count=word_count,
            language_code=language,
            published_at=published_at,
            ingest_status="done",
        )

        status = get_extraction_status(conn, video_id)
        if status is None:
            discovered += 1
            log.debug("  registrado: %s", video_id)
            continue

        mark_content_changed(conn, video_id=video_id, transcript_hash=body_hash)
    return discovered


def build_work_queue(
    conn,
    *,
    transcript_dir: Path,
    transcript_id: Optional[str],
    retry_failed: bool,
    reprocess: bool,
) -> List[Path]:
    if transcript_id:
        path = transcript_dir / f"{transcript_id}.md"
        return [path] if path.is_file() else []

    queue: List[Path] = []
    for path in list_transcript_files(transcript_dir):
        tid = transcript_id_from_path(path)
        status = get_extraction_status(conn, tid)
        if status is None:
            queue.append(path)
            continue
        if status == "pending":
            queue.append(path)
            continue
        if status == "failed" and retry_failed:
            queue.append(path)
            continue
        if status == "done" and reprocess:
            queue.append(path)
    return queue


def timeout_for_body(body: str) -> int:
    words = len(body.split())
    if words > 6000:
        return 300
    if words > 2500:
        return 240
    return 180


def process_transcript(
    *,
    path: Path,
    conn,
    extraction_dir: Path,
    config,
    dry_run: bool,
    log: logging.Logger,
) -> str:
    transcript_id = transcript_id_from_path(path)
    raw = path.read_text(encoding="utf-8")
    fm, body = parse_frontmatter(raw)
    title = (fm.get("title") or transcript_id).strip()
    source_url = (fm.get("source_url") or "").strip()
    language = (fm.get("language_code") or "es").strip() or "es"
    uploaded_date = (fm.get("uploaded_date") or "").strip() or None
    body_hash = content_hash(body)

    if not body.strip():
        if not dry_run:
            mark_extraction_failed(
                conn,
                video_id=transcript_id,
                extraction_id=transcript_id,
                transcript_hash=body_hash,
                error="empty_transcript_body",
            )
        log.warning("  [FAIL] transcript vacío: %s", title)
        return "failed"

    if dry_run:
        log.info("  [DRY] %s (~%s palabras)", title, len(body.split()))
        return "dry_run"

    try:
        log.info("  extrayendo (%s)...", config.label)
        t0 = time.perf_counter()
        extraction = extract_knowledge(
            title=title,
            source_url=source_url,
            transcript_id=transcript_id,
            body=body,
            config=config,
            language=language,
            uploaded_date=uploaded_date,
            timeout_s=timeout_for_body(body),
        )
        elapsed = time.perf_counter() - t0
        markdown_path, json_path = write_outputs(
            extraction,
            transcript_id=transcript_id,
            extraction_dir=extraction_dir,
            json_cache_dir=JSON_CACHE_DIR,
        )
        extraction_id = transcript_id
        delete_knowledge_items(conn, extraction_id)
        items = flatten_to_knowledge_items(extraction)
        n_items = insert_knowledge_items(
            conn,
            extraction_id=extraction_id,
            video_id=transcript_id,
            items=items,
        )
        mark_extraction_done(
            conn,
            video_id=transcript_id,
            extraction_id=extraction_id,
            model=config.label,
            transcript_hash=body_hash,
            summary=(extraction.get("summary") or "").strip(),
            output_md_path=str(markdown_path.resolve()),
            output_json_path=str(json_path.resolve()),
        )
        by_type = count_items_by_type(conn, transcript_id)
        log.info(
            "  [OK] %.1fs -> %s (%s items: %s)",
            elapsed,
            markdown_path.name,
            n_items,
            ", ".join(f"{k}={v}" for k, v in sorted(by_type.items())[:8]),
        )
        return "done"
    except Exception as exc:
        mark_extraction_failed(
            conn,
            video_id=transcript_id,
            extraction_id=transcript_id,
            transcript_hash=body_hash,
            error=str(exc),
        )
        log.warning("  [FAIL] %s — %s", title, exc)
        log.debug("  error completo", exc_info=True)
        return "failed"


def export_status(
    conn,
    *,
    transcript_dir: Path,
    extraction_dir: Path,
    log: logging.Logger,
) -> None:
    paths = sync_status_exports(
        conn,
        project_root=PROJECT_ROOT,
        vault_extraction_dir=extraction_dir,
        transcript_input_dir=str(transcript_dir.resolve()),
    )
    log.info("Estado exportado:")
    log.info("  JSON: %s", paths["json"])
    log.info("  Markdown: %s", paths["markdown"])


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extraer conocimiento estructurado desde Own_Transcripts."
    )
    parser.add_argument(
        "--vault",
        default=None,
        help="Ruta al vault Obsidian (default: OBSIDIAN_VAULT_PATH)",
    )
    parser.add_argument(
        "--transcript-folder",
        default=os.getenv("KNOWLEDGE_TRANSCRIPT_FOLDER", DEFAULT_TRANSCRIPT_FOLDER),
        help="Subcarpeta bajo 10_Sources (default: Own_Transcripts)",
    )
    parser.add_argument(
        "--extraction-folder",
        default=os.getenv("KNOWLEDGE_EXTRACTION_FOLDER", DEFAULT_EXTRACTION_FOLDER),
        help="Subcarpeta bajo 20_Extractions (default: Own_Transcripts)",
    )
    parser.add_argument("--limit", type=int, default=0, help="Máximo de transcripts a procesar")
    parser.add_argument("--id", dest="transcript_id", default=None, help="Procesar un transcript por stem")
    parser.add_argument("--retry-failed", action="store_true", help="Reintentar filas failed")
    parser.add_argument("--reprocess", action="store_true", help="Re-extraer aunque esté done")
    parser.add_argument("--dry-run", action="store_true", help="Listar trabajo sin llamar al LLM")
    parser.add_argument("--export-status", action="store_true", help="Solo regenerar export de estado")
    parser.add_argument("--verbose", action="store_true", help="Log detallado en consola")
    args = parser.parse_args()

    setup_logging(args.verbose)
    log = logging.getLogger(__name__)

    vault_path = resolve_vault_path(args.vault)
    if not vault_path.is_dir():
        log.error("Vault no encontrado: %s", vault_path)
        return 1

    transcript_dir = vault_path / "10_Sources" / args.transcript_folder.strip()
    extraction_dir = vault_path / "20_Extractions" / args.extraction_folder.strip()
    extraction_dir.mkdir(parents=True, exist_ok=True)

    conn = open_engine(PROJECT_ROOT)
    log.info("Fuente de verdad: %s", state_db_path(PROJECT_ROOT).resolve())
    log.info("Transcripts: %s", transcript_dir)
    log.info("Extracciones: %s", extraction_dir)

    discovered = discover_transcripts(conn, transcript_dir=transcript_dir, log=log)
    if discovered:
        log.info("Descubiertos: %s transcripts nuevos", discovered)

    repair_stats = reconcile_done_with_vault(conn)
    if any(repair_stats.values()):
        log.info(
            "Reconciliación: kept_done=%s missing_output_pending=%s missing_source_skipped=%s",
            repair_stats["kept_done"],
            repair_stats["missing_output_pending"],
            repair_stats["missing_source_skipped"],
        )

    if args.export_status:
        export_status(conn, transcript_dir=transcript_dir, extraction_dir=extraction_dir, log=log)
        return 0

    queue = build_work_queue(
        conn,
        transcript_dir=transcript_dir,
        transcript_id=args.transcript_id,
        retry_failed=args.retry_failed,
        reprocess=args.reprocess,
    )

    if args.limit and args.limit > 0:
        queue = queue[: args.limit]

    if not queue:
        log.info("Nada que procesar.")
        export_status(conn, transcript_dir=transcript_dir, extraction_dir=extraction_dir, log=log)
        return 0

    if args.dry_run:
        log.info("Cola (%s):", len(queue))
        for path in queue:
            process_transcript(
                path=path,
                conn=conn,
                extraction_dir=extraction_dir,
                config=build_knowledge_llm_config(),
                dry_run=True,
                log=log,
            )
        export_status(conn, transcript_dir=transcript_dir, extraction_dir=extraction_dir, log=log)
        return 0

    config = build_knowledge_llm_config()
    try:
        validate_llm_config(config)
    except ValueError as exc:
        log.error("%s", exc)
        return 1

    log.info("LLM: %s", config.label)
    log.info("Procesando %s transcript(s)...", len(queue))

    stats = {"done": 0, "failed": 0}
    for idx, path in enumerate(queue, start=1):
        log.info("[%s/%s] %s", idx, len(queue), path.name)
        result = process_transcript(
            path=path,
            conn=conn,
            extraction_dir=extraction_dir,
            config=config,
            dry_run=False,
            log=log,
        )
        stats[result] = stats.get(result, 0) + 1

    export_status(conn, transcript_dir=transcript_dir, extraction_dir=extraction_dir, log=log)
    log.info(
        "Completado: done=%s failed=%s",
        stats.get("done", 0),
        stats.get("failed", 0),
    )
    return 1 if stats.get("failed", 0) else 0


if __name__ == "__main__":
    raise SystemExit(main())
