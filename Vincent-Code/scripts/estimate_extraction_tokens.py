#!/usr/bin/env python3
"""Estimate LLM tokens for knowledge extraction on one transcript."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.knowledge_extractor import build_prompt, parse_frontmatter

EXPANDED_SCHEMA_BLOCK = """
  "cited_claims": [{"claim": "", "attributed_to": "", "author_stance": "rejects|agrees|nuances"}],
  "counterarguments": [{"claim": "", "targets": "t1"}],
  "warnings": [{"claim": "", "timeframe": "near|long", "confidence": "high|medium|low"}],
  "people": [{"name": "", "role": "guest|criticized|mentioned|historical", "context": ""}],
  "organizations": [{"name": "", "type": "corp|gov|media|protocol|ngo", "author_view": ""}],
  "works": [{"title": "", "type": "book|film|law|document", "author_role": ""}],
  "events": [{"name": "", "date": "YYYY-MM-DD|null", "significance": ""}],
  "topics": ["string"],
  "technical_explanations": [{"concept": "", "mechanism": "", "author_critique": ""}],
  "legislation": [{"name": "", "article": "", "summary": "", "author_view": ""}],
  "historical_references": [{"reference": "", "used_to_argue": ""}],
  "stories": [{"narrative": "", "point": ""}],
  "analogies": [{"comparison": "", "explains": ""}],
"""


def est_tokens(text: str) -> int:
    try:
        import tiktoken

        enc = tiktoken.encoding_for_model("gpt-4o")
        return len(enc.encode(text))
    except Exception:
        return int(len(text) / 3.5)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("transcript", type=Path)
    args = parser.parse_args()

    raw = args.transcript.read_text(encoding="utf-8")
    fm, body = parse_frontmatter(raw)
    title = fm.get("title") or args.transcript.stem
    words = len(body.split())

    prompt_current = build_prompt(
        title=title,
        source_url=fm.get("source_url", ""),
        transcript_id=args.transcript.stem,
        format_hint="long",
        body=body,
    )
    prompt_expanded = prompt_current.replace(
        '  "content_angles":',
        EXPANDED_SCHEMA_BLOCK + '  "content_angles":',
    )

    in_cur = est_tokens(prompt_current)
    in_exp = est_tokens(prompt_expanded)
    out_lo = int(words * 1.15 * 0.12)
    out_hi_cur = int(words * 1.15 * 0.20)
    out_hi_exp = int(words * 1.15 * 0.28)

    print(f"file: {args.transcript.name}")
    print(f"title: {title}")
    print(f"words: {words}")
    print(f"chars_body: {len(body)}")
    print()
    print("CURRENT schema:")
    print(f"  input_tokens:  {in_cur:,}")
    print(f"  output_est:    {out_lo:,} - {out_hi_cur:,}")
    print(f"  total_est:     {in_cur + out_lo:,} - {in_cur + out_hi_cur:,}")
    print()
    print("EXPANDED schema:")
    print(f"  input_tokens:  {in_exp:,} (+{in_exp - in_cur:,})")
    print(f"  output_est:    {int(words*1.15*0.15):,} - {out_hi_exp:,}")
    print(f"  total_est:     {in_exp + int(words*1.15*0.15):,} - {in_exp + out_hi_exp:,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
