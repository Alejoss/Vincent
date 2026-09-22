"""Map embeddable text volume for a Sophia topic (uses shared resolvers)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv(PROJECT_ROOT / ".env", override=True)

from src.pipeline_logging import setup_pipeline_logging  # noqa: E402
from src.sophia_topic_volume import map_topic_volume  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Inventory topic text for embeddings (VIDEO/AUDIO + TEXT PDF/EPUB)."
    )
    parser.add_argument("--topic-id", type=int, default=2)
    parser.add_argument(
        "--content-id",
        type=int,
        default=None,
        help="Optional: only resolve one Sophia content id.",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    topic_id = int(args.topic_id)

    log, log_file = setup_pipeline_logging("topic_volume_map", verbose=args.verbose)
    summary = map_topic_volume(
        PROJECT_ROOT,
        topic_id,
        content_id=args.content_id,
        write_reports=True,
    )
    if not summary.get("ok"):
        log.error("%s", summary.get("error") or summary)
        return 1

    log.info("Topic %s — %s", topic_id, summary.get("title"))
    for row in summary.get("units") or []:
        log.info(
            "  [%s] %s cid=%s tokens~%s src=%s | %s",
            row.get("status"),
            row.get("media_type"),
            row.get("content_id"),
            row.get("tokens_est"),
            (row.get("text_source") or row.get("notes") or "")[:50],
            (row.get("title") or "")[:50],
        )

    slim = {k: v for k, v in summary.items() if k != "units"}
    log.info("Summary: %s", json.dumps(slim, ensure_ascii=False))
    log.info("CSV: %s", summary.get("csv_path"))
    log.info("JSON: %s", summary.get("json_path"))
    log.info("Finished. Log: %s", log_file)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
