#!/usr/bin/env python3
"""
Run the full topic knowledge pipeline in order:

  1) map volume (optional inventory)
  2) process_topic_transcripts
  3) embed_topic
  4) sync_topic_embeddings_to_qdrant (queue + sqlite extras)

Examples:
  python scripts/run_topic_knowledge_pipeline.py --topic-id 13
  python scripts/run_topic_knowledge_pipeline.py --topic-id 13 --dry-run
  python scripts/run_topic_knowledge_pipeline.py --topic-id 13 --skip-map
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv(PROJECT_ROOT / ".env", override=True)

from src.pipeline_logging import setup_pipeline_logging  # noqa: E402

SCRIPTS = PROJECT_ROOT / "scripts"


def _python() -> str:
    venv_py = PROJECT_ROOT / "venv" / "Scripts" / "python.exe"
    if venv_py.is_file():
        return str(venv_py)
    return sys.executable


def run_step(log, name: str, argv: list[str]) -> int:
    log.info("")
    log.info("======== STEP: %s ========", name)
    log.info("CMD: %s", " ".join(argv))
    result = subprocess.run(argv, cwd=str(PROJECT_ROOT))
    if result.returncode != 0:
        log.error("STEP FAILED: %s (exit=%s)", name, result.returncode)
    else:
        log.info("STEP OK: %s", name)
    return int(result.returncode)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run transcripts → embed → Qdrant/ack for one Sophia topic"
    )
    parser.add_argument("--topic-id", type=int, required=True)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Pass --dry-run to transcripts, embed, and sync (map still runs)",
    )
    parser.add_argument("--skip-map", action="store_true")
    parser.add_argument("--skip-transcripts", action="store_true")
    parser.add_argument("--skip-embed", action="store_true")
    parser.add_argument("--skip-sync", action="store_true")
    parser.add_argument(
        "--sync-mode",
        choices=("auto", "queue", "sqlite"),
        default="queue",
        help="Sync mode (default: queue)",
    )
    parser.add_argument(
        "--no-sqlite-extras",
        action="store_true",
        help="Do not pass --also-sqlite-extras to sync",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Pass --force to embed and sync",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    log, log_file = setup_pipeline_logging(
        "topic_knowledge_pipeline", verbose=args.verbose
    )
    topic_id = int(args.topic_id)
    py = _python()
    log.info("Topic knowledge pipeline | topic_id=%s | dry_run=%s", topic_id, args.dry_run)
    log.info("Python: %s", py)

    steps: list[tuple[str, list[str]]] = []

    if not args.skip_map:
        steps.append(
            (
                "map_volume",
                [py, str(SCRIPTS / "map_topic_embedding_volume.py"), "--topic-id", str(topic_id)],
            )
        )

    if not args.skip_transcripts:
        tx = [
            py,
            str(SCRIPTS / "process_topic_transcripts.py"),
            "--topic-id",
            str(topic_id),
        ]
        if args.dry_run:
            tx.append("--dry-run")
        if args.verbose:
            tx.append("--verbose")
        steps.append(("transcripts", tx))

    if not args.skip_embed:
        emb = [
            py,
            str(SCRIPTS / "embed_topic.py"),
            "--topic-id",
            str(topic_id),
        ]
        if args.dry_run:
            emb.append("--dry-run")
        if args.force:
            emb.append("--force")
        if args.verbose:
            emb.append("--verbose")
        steps.append(("embed", emb))

    if not args.skip_sync:
        sync = [
            py,
            str(SCRIPTS / "sync_topic_embeddings_to_qdrant.py"),
            "--topic-id",
            str(topic_id),
            "--mode",
            args.sync_mode,
        ]
        if args.dry_run:
            sync.append("--dry-run")
        if args.force:
            sync.append("--force")
        if not args.no_sqlite_extras:
            sync.append("--also-sqlite-extras")
        if args.verbose:
            sync.append("--verbose")
        steps.append(("qdrant_sync", sync))

    if not steps:
        log.error("Nothing to run (all steps skipped).")
        return 1

    failed_at: str | None = None
    for name, argv in steps:
        rc = run_step(log, name, argv)
        if rc != 0:
            failed_at = name
            log.error("Pipeline stopped at step '%s'. See child logs in logs/.", name)
            log.info("Orchestrator log: %s", log_file)
            return rc

    log.info("")
    log.info("Pipeline COMPLETE for topic_id=%s", topic_id)
    log.info("Orchestrator log: %s", log_file)
    log.info("Child latest logs: topic_volume_map_latest / topic_transcripts_latest / embed_topic_latest / qdrant_sync_latest")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
