"""Map embeddable text volume for a Sophia topic (uses shared resolvers)."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv(PROJECT_ROOT / ".env", override=True)

from src.embeddings.chunking import count_tokens  # noqa: E402
from src.embeddings.openai_embed import DEFAULT_EMBEDDING_MODEL  # noqa: E402
from src.pipeline_logging import setup_pipeline_logging  # noqa: E402
from src.sophia_topic_text import (  # noqa: E402
    resolve_media_text,
    resolve_topic_description,
)
from src.sophia_topics import SophiaTopicsClient  # noqa: E402
from src.sophia_transcript_ingest import SophiaTranscriptIngestClient  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic-id", type=int, default=2)
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    topic_id = int(args.topic_id)

    log, log_file = setup_pipeline_logging("topic_volume_map", verbose=args.verbose)

    topics = SophiaTopicsClient()
    ingest = SophiaTranscriptIngestClient()
    topic = topics.get_topic(topic_id)
    log.info("Topic %s — %s", topic_id, topic.get("title"))
    units = [resolve_topic_description(topic)]
    for item in topics.list_topic_contents(topic_id, include_images=False):
        units.append(
            resolve_media_text(
                project_root=PROJECT_ROOT, item=item, ingest_client=ingest
            )
        )

    rows = []
    totals: dict[str, dict] = defaultdict(
        lambda: {"items": 0, "chars": 0, "words": 0, "tokens_est": 0}
    )
    for u in units:
        tokens = count_tokens(u.text, model=DEFAULT_EMBEDDING_MODEL) if u.text else 0
        words = len(u.text.split()) if u.text else 0
        totals[u.media_type]["items"] += 1
        totals[u.media_type]["chars"] += len(u.text)
        totals[u.media_type]["words"] += words
        totals[u.media_type]["tokens_est"] += tokens
        rows.append(
            {
                "content_id": u.content_id if u.content_id is not None else "",
                "media_type": u.media_type,
                "title": u.title[:160],
                "author": u.author[:80],
                "chars": len(u.text),
                "words": words,
                "tokens_est": tokens,
                "status": u.status,
                "text_source": u.source,
                "notes": u.notes,
            }
        )
        log.info(
            "  [%s] %s cid=%s tokens~%s src=%s | %s",
            u.status,
            u.media_type,
            u.content_id,
            tokens,
            (u.source or u.notes or "")[:50],
            (u.title or "")[:50],
        )

    out_dir = PROJECT_ROOT / "cache" / "topic_embeddings" / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / f"topic_{topic_id}_embedding_volume_map.csv"
    with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["content_id"])
        if rows:
            w.writeheader()
            w.writerows(rows)

    grand_tokens = sum(v["tokens_est"] for v in totals.values())
    summary = {
        "topic_id": topic_id,
        "title": topic.get("title"),
        "model_for_token_count": DEFAULT_EMBEDDING_MODEL,
        "by_type": {k: dict(v) for k, v in totals.items()},
        "grand_total_tokens_est": grand_tokens,
        "approx_chunks_800tok": round(grand_tokens / 800),
        "approx_embedding_cost_usd_3_large": round(grand_tokens / 1_000_000 * 0.13, 4),
    }
    json_path = out_dir / f"topic_{topic_id}_embedding_volume_map.json"
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("Summary: %s", json.dumps(summary, ensure_ascii=False))
    log.info("CSV: %s", csv_path)
    log.info("JSON: %s", json_path)
    log.info("Finished. Log: %s", log_file)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
