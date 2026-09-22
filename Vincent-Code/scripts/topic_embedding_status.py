"""Read-only topic coverage audit, also exposed as the topic_embedding_status MCP tool."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env", override=True)

from src.topic_embedding_status import topic_embedding_status  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    selector = parser.add_mutually_exclusive_group(required=True)
    selector.add_argument("--topic-id", type=int)
    selector.add_argument("--topic-name")
    parser.add_argument("--model", default="text-embedding-3-large")
    args = parser.parse_args()
    result = topic_embedding_status(ROOT, **vars(args))
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0 if result.get("ok") and result.get("complete") else 1


if __name__ == "__main__":
    raise SystemExit(main())
