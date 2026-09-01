"""Extract structured knowledge from Own_Transcripts via LLM."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.llm_client import LLMConfig, call_json


EXTRACTION_SUFFIX = "-knowledge"
TRANSCRIPT_WIKI_PREFIX = "10_Sources/Own_Transcripts"
SCHEMA_VERSION = "2.0"

ARRAY_FIELDS = (
    "theses",
    "arguments",
    "cited_claims",
    "counterarguments",
    "warnings",
    "questions",
    "quotes",
    "people",
    "organizations",
    "works",
    "events",
    "topics",
    "concepts",
    "technical_explanations",
    "legislation",
    "historical_references",
    "stories",
    "analogies",
    "mental_models",
    "controversial_claims",
)

ITEM_TYPE_BY_FIELD = {
    "theses": "thesis",
    "arguments": "argument",
    "cited_claims": "cited_claim",
    "counterarguments": "counterargument",
    "warnings": "warning",
    "questions": "question",
    "quotes": "quote",
    "people": "person",
    "organizations": "organization",
    "works": "work",
    "events": "event",
    "topics": "topic",
    "concepts": "concept",
    "technical_explanations": "technical_explanation",
    "legislation": "legislation",
    "historical_references": "historical_reference",
    "stories": "story",
    "analogies": "analogy",
    "mental_models": "mental_model",
    "controversial_claims": "controversial_claim",
}


def parse_frontmatter(content: str) -> Tuple[Dict[str, str], str]:
    text = content or ""
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end == -1:
        return {}, text
    block = text[4:end]
    body = text[end + 5 :]
    fm: Dict[str, str] = {}
    for line in block.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        fm[key.strip()] = value.strip().strip('"')
    return fm, body.strip()


def detect_format(*, transcript_id: str, title: str, word_count: int) -> str:
    haystack = f"{transcript_id} {title}".lower()
    if "short" in haystack or word_count < 500:
        return "short"
    if any(
        token in haystack
        for token in ("entrevista", "conversación", "conversacion", "podcast", "conversamos")
    ):
        return "interview"
    if any(token in haystack for token in ("en vivo", "directo", "live")):
        return "live"
    return "long"


def _format_instructions(format_hint: str) -> str:
    if format_hint == "short":
        return (
            "This is a SHORT video. Extract 1-2 theses, 2-5 arguments, 1-3 quotes. "
            "Keep other sections minimal."
        )
    if format_hint == "interview":
        return (
            "This is an INTERVIEW. Tag speaker on arguments and quotes (author vs guest). "
            "Extract guest factual claims as cited_claims; author analysis as theses/arguments."
        )
    if format_hint == "live":
        return (
            "This is a LIVE / multi-topic stream. The video jumps between thematic blocks. "
            "You MUST cover each major topic implied by the title and by clear topic shifts in the transcript. "
            "Do not collapse the whole video into 1-2 generic theses. "
            "Typical targets for this length: 3-6 theses, 8-20 arguments, 5-10 quotes, 3-6 mental_models, "
            "2-5 stories, 8-15 people, 5-10 cited_claims where third parties are discussed."
        )
    return (
        "This is a LONG monologue or analysis. Extract depth: multiple arguments with evidence, "
        "mental_models, quotes, and cited_claims when media or third parties appear."
    )


def output_paths(
    *,
    transcript_id: str,
    extraction_dir: Path,
    json_cache_dir: Path,
) -> Tuple[Path, Path]:
    markdown_path = extraction_dir / f"{transcript_id}{EXTRACTION_SUFFIX}.md"
    json_path = json_cache_dir / f"{transcript_id}.json"
    return markdown_path, json_path


def build_prompt(
    *,
    title: str,
    source_url: str,
    transcript_id: str,
    format_hint: str,
    body: str,
) -> str:
    format_rules = _format_instructions(format_hint)
    return f"""You are a Transcript Knowledge Extractor for Academia Blockchain.

Objective: Compile structured intellectual knowledge from a video transcript — not a shallow recap.

Core rules:
- Extract ONLY what appears in the transcript. Do not invent facts or outside context.
- theses / arguments = the channel author's positions.
- cited_claims = claims attributed to third parties (media, emails, guests, documents quoted in the video).
  Always set author_stance (agrees|rejects|nuances) when the author reacts to that claim.
- mental_models = reusable frameworks the author uses to explain the world (not single facts).
  Look for explicit reasoning patterns the author repeats or names.
- quotes: prefer verbatim phrases from the transcript; mark usable_as_hook when punchy.
- arguments: each needs at least one evidence string traceable to the transcript.
- stories: short narrative episodes the author tells (anecdotes, scenes, cases).
- All text fields in Spanish. Empty arrays when nothing applies — do not pad.

Format guidance ({format_hint}):
{format_rules}

Summary: write a reusable synthesis (3-6 sentences). Name the major thematic blocks covered.
Do NOT write a generic "en este video se discute..." opener.

Return ONLY valid JSON with this shape:
{{
  "summary": "string",
  "theses": [{{"id": "t1", "statement": "string", "confidence": "high|medium|low", "speaker": "author"}}],
  "arguments": [{{"id": "a1", "claim": "string", "evidence": ["string"], "supports_thesis": "t1|null", "speaker": "author|guest|third_party"}}],
  "cited_claims": [{{"claim": "string", "attributed_to": "string", "author_stance": "rejects|agrees|nuances"}}],
  "counterarguments": [{{"claim": "string", "targets": "t1"}}],
  "warnings": [{{"claim": "string", "timeframe": "near|long", "confidence": "high|medium|low"}}],
  "questions": [{{"text": "string", "type": "rhetorical|open|provocative"}}],
  "quotes": [{{"text": "string", "speaker": "author|guest|third_party", "context": "string", "usable_as_hook": true}}],
  "people": [{{"name": "string", "role": "guest|criticized|mentioned|historical", "context": "string"}}],
  "organizations": [{{"name": "string", "type": "corp|gov|media|protocol|ngo", "author_view": "string"}}],
  "works": [{{"title": "string", "type": "book|film|law|document", "author_role": "criticizes|references"}}],
  "events": [{{"name": "string", "date": "YYYY-MM-DD or null", "significance": "string"}}],
  "topics": ["string"],
  "concepts": [{{"name": "string", "definition": "string", "related": ["string"]}}],
  "technical_explanations": [{{"concept": "string", "mechanism": "string", "author_critique": "string"}}],
  "legislation": [{{"name": "string", "article": "string", "summary": "string", "author_view": "string"}}],
  "historical_references": [{{"reference": "string", "used_to_argue": "string"}}],
  "stories": [{{"narrative": "string", "point": "string"}}],
  "analogies": [{{"comparison": "string", "explains": "string"}}],
  "mental_models": [{{"name": "string", "description": "string", "application": "string"}}],
  "controversial_claims": [{{"claim": "string", "why_controversial": "string", "evidence_in_transcript": "string"}}]
}}

Video metadata:
- title: {title}
- source_url: {source_url or "unknown"}
- transcript_id: {transcript_id}
- format_hint: {format_hint}

Transcript:
\"\"\"
{body}
\"\"\"
"""


def _as_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def normalize_extraction(raw: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("LLM response is not a JSON object")

    summary = raw.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise ValueError("Missing or empty summary")

    normalized: Dict[str, Any] = {"summary": summary.strip()}
    for field in ARRAY_FIELDS:
        normalized[field] = _as_list(raw.get(field))
    return normalized


def attach_meta(
    extraction: Dict[str, Any],
    *,
    transcript_id: str,
    title: str,
    source_url: str,
    language: str,
    format_hint: str,
    model_label: str,
    uploaded_date: Optional[str] = None,
) -> Dict[str, Any]:
    payload = dict(extraction)
    meta: Dict[str, Any] = {
        "transcript_id": transcript_id,
        "title": title,
        "source_url": source_url,
        "language": language,
        "format": format_hint,
        "schema_version": SCHEMA_VERSION,
        "extracted_at": datetime.now(tz=timezone.utc).isoformat(),
        "model": model_label,
    }
    if uploaded_date:
        meta["uploaded_date"] = uploaded_date
    payload["meta"] = meta
    return payload


def extract_knowledge(
    *,
    title: str,
    source_url: str,
    transcript_id: str,
    body: str,
    config: LLMConfig,
    language: str = "es",
    uploaded_date: Optional[str] = None,
    timeout_s: int = 180,
) -> Dict[str, Any]:
    word_count = len(body.split())
    format_hint = detect_format(
        transcript_id=transcript_id,
        title=title,
        word_count=word_count,
    )
    prompt = build_prompt(
        title=title,
        source_url=source_url,
        transcript_id=transcript_id,
        format_hint=format_hint,
        body=body,
    )
    raw = call_json(prompt, config, timeout_s=timeout_s)
    normalized = normalize_extraction(raw)
    return attach_meta(
        normalized,
        transcript_id=transcript_id,
        title=title,
        source_url=source_url,
        language=language,
        format_hint=format_hint,
        model_label=config.label,
        uploaded_date=uploaded_date,
    )


def _anchor_from_payload(item_type: str, payload: Any) -> str:
    if isinstance(payload, str):
        return payload.strip()
    if not isinstance(payload, dict):
        return str(payload).strip()

    for key in (
        "statement",
        "claim",
        "text",
        "name",
        "title",
        "concept",
        "reference",
        "narrative",
        "comparison",
        "summary",
    ):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return json.dumps(payload, ensure_ascii=False)[:500]


def flatten_to_knowledge_items(extraction: Dict[str, Any]) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    summary = (extraction.get("summary") or "").strip()
    if summary:
        items.append(
            {
                "item_type": "summary",
                "item_key": None,
                "payload": {"text": summary},
                "anchor_text": summary,
            }
        )

    for field, item_type in ITEM_TYPE_BY_FIELD.items():
        for idx, raw_item in enumerate(_as_list(extraction.get(field)), start=1):
            if item_type == "topic":
                if not isinstance(raw_item, str) or not raw_item.strip():
                    continue
                payload = {"name": raw_item.strip()}
                items.append(
                    {
                        "item_type": item_type,
                        "item_key": f"topic{idx}",
                        "payload": payload,
                        "anchor_text": raw_item.strip(),
                    }
                )
                continue

            if not isinstance(raw_item, dict):
                continue
            item_key = raw_item.get("id") or raw_item.get("name") or f"{item_type}{idx}"
            if isinstance(item_key, str):
                item_key = item_key.strip() or f"{item_type}{idx}"
            items.append(
                {
                    "item_type": item_type,
                    "item_key": str(item_key),
                    "payload": raw_item,
                    "anchor_text": _anchor_from_payload(item_type, raw_item),
                }
            )
    return items


def _escape_yaml(value: str) -> str:
    return (value or "").replace('"', '\\"')


def _wiki_link(transcript_id: str) -> str:
    return f"[[{TRANSCRIPT_WIKI_PREFIX}/{transcript_id}]]"


def _render_bullets(items: List[Any], *, primary_key: str, empty: str) -> List[str]:
    lines: List[str] = []
    for item in items:
        if isinstance(item, str):
            text = item.strip()
            if text:
                lines.append(f"- {text}")
            continue
        if not isinstance(item, dict):
            continue
        text = (item.get(primary_key) or item.get("name") or item.get("claim") or "").strip()
        if not text:
            continue
        lines.append(f"- {text}")
    return lines or [f"- _{empty}_"]


def _render_theses(items: List[Any]) -> List[str]:
    lines: List[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        statement = (item.get("statement") or "").strip()
        if not statement:
            continue
        confidence = (item.get("confidence") or "").strip()
        suffix = f" ({confidence})" if confidence else ""
        lines.append(f"- {statement}{suffix}")
    return lines or ["- _Sin tesis identificadas._"]


def _render_arguments(items: List[Any]) -> List[str]:
    lines: List[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        claim = (item.get("claim") or "").strip()
        if not claim:
            continue
        evidence = [str(x).strip() for x in _as_list(item.get("evidence")) if str(x).strip()]
        supports = (item.get("supports_thesis") or "").strip()
        speaker = (item.get("speaker") or "").strip()
        block = [f"- **{claim}**"]
        if speaker:
            block.append(f"  - Voz: {speaker}")
        if evidence:
            block.extend(f"  - Evidencia: {point}" for point in evidence)
        if supports and supports.lower() != "null":
            block.append(f"  - Sostiene: {supports}")
        lines.extend(block)
    return lines or ["- _Sin argumentos identificados._"]


def _render_cited_claims(items: List[Any]) -> List[str]:
    lines: List[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        claim = (item.get("claim") or "").strip()
        if not claim:
            continue
        attributed = (item.get("attributed_to") or "").strip()
        stance = (item.get("author_stance") or "").strip()
        line = f"- **{claim}**"
        if attributed:
            line += f" — atribuido a _{attributed}_"
        if stance:
            line += f" → autor: {stance}"
        lines.append(line)
    return lines or ["- _Sin claims citados._"]


def _render_quotes(items: List[Any]) -> List[str]:
    lines: List[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        text = (item.get("text") or "").strip()
        if not text:
            continue
        context = (item.get("context") or "").strip()
        speaker = (item.get("speaker") or "").strip()
        hook = item.get("usable_as_hook")
        hook_label = " [hook]" if hook is True else ""
        line = f'- "{text}"{hook_label}'
        if speaker:
            line += f" ({speaker})"
        if context:
            line += f" — _{context}_"
        lines.append(line)
    return lines or ["- _Sin citas memorables identificadas._"]


def _render_mental_models(items: List[Any]) -> List[str]:
    lines: List[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = (item.get("name") or "").strip()
        if not name:
            continue
        description = (item.get("description") or "").strip()
        application = (item.get("application") or "").strip()
        block = [f"- **{name}**"]
        if description:
            block.append(f"  - {description}")
        if application:
            block.append(f"  - Aplicación: {application}")
        lines.extend(block)
    return lines or ["- _Sin modelos mentales identificados._"]


def render_markdown(extraction: Dict[str, Any], *, transcript_id: str) -> str:
    meta = extraction.get("meta") if isinstance(extraction.get("meta"), dict) else {}
    title = (meta.get("title") or transcript_id).strip()
    source_url = (meta.get("source_url") or "").strip()
    extracted_at = (meta.get("extracted_at") or "").strip()
    model = (meta.get("model") or "").strip()
    schema_version = (meta.get("schema_version") or SCHEMA_VERSION).strip()
    format_hint = (meta.get("format") or "").strip()
    uploaded_date = (meta.get("uploaded_date") or "").strip()
    summary = (extraction.get("summary") or "").strip()
    item_count = len(flatten_to_knowledge_items(extraction))

    frontmatter = [
        "---",
        f'title: "{_escape_yaml(title)} — Knowledge Extraction"',
        f"source_transcript: \"{_wiki_link(transcript_id)}\"",
    ]
    if source_url:
        frontmatter.append(f'source_url: "{_escape_yaml(source_url)}"')
    if uploaded_date:
        frontmatter.append(f'uploaded_date: "{_escape_yaml(uploaded_date)}"')
    if format_hint:
        frontmatter.append(f'format: "{_escape_yaml(format_hint)}"')
    if extracted_at:
        frontmatter.append(f'extraction_date: "{extracted_at}"')
    if model:
        frontmatter.append(f'model: "{_escape_yaml(model)}"')
    frontmatter.extend(
        [
            f'schema_version: "{schema_version}"',
            f"knowledge_items: {item_count}",
            "tags: [extraction, knowledge, knowledge-engine]",
            "---",
            "",
            "## Summary",
            "",
            summary,
            "",
            "## Theses",
            "",
            *_render_theses(_as_list(extraction.get("theses"))),
            "",
            "## Arguments",
            "",
            *_render_arguments(_as_list(extraction.get("arguments"))),
            "",
            "## Cited Claims",
            "",
            *_render_cited_claims(_as_list(extraction.get("cited_claims"))),
            "",
            "## Warnings",
            "",
            *_render_bullets(_as_list(extraction.get("warnings")), primary_key="claim", empty="Sin advertencias"),
            "",
            "## Quotes",
            "",
            *_render_quotes(_as_list(extraction.get("quotes"))),
            "",
            "## People",
            "",
            *_render_bullets(_as_list(extraction.get("people")), primary_key="name", empty="Sin personas"),
            "",
            "## Organizations",
            "",
            *_render_bullets(_as_list(extraction.get("organizations")), primary_key="name", empty="Sin organizaciones"),
            "",
            "## Topics",
            "",
            *_render_bullets(_as_list(extraction.get("topics")), primary_key="name", empty="Sin temas"),
            "",
            "## Mental Models",
            "",
            *_render_mental_models(_as_list(extraction.get("mental_models"))),
            "",
            "## Stories",
            "",
            *_render_bullets(_as_list(extraction.get("stories")), primary_key="narrative", empty="Sin historias"),
            "",
            "## Questions",
            "",
            *_render_bullets(_as_list(extraction.get("questions")), primary_key="text", empty="Sin preguntas"),
            "",
        ]
    )
    return "\n".join(frontmatter)


def write_outputs(
    extraction: Dict[str, Any],
    *,
    transcript_id: str,
    extraction_dir: Path,
    json_cache_dir: Path,
) -> Tuple[Path, Path]:
    markdown_path, json_path = output_paths(
        transcript_id=transcript_id,
        extraction_dir=extraction_dir,
        json_cache_dir=json_cache_dir,
    )
    extraction_dir.mkdir(parents=True, exist_ok=True)
    json_cache_dir.mkdir(parents=True, exist_ok=True)

    markdown_path.write_text(
        render_markdown(extraction, transcript_id=transcript_id),
        encoding="utf-8",
    )
    with json_path.open("w", encoding="utf-8") as handle:
        json.dump(extraction, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return markdown_path, json_path


def is_status_artifact(path: Path) -> bool:
    name = path.name.lower()
    return name.startswith("_estado_") or name.endswith("-knowledge.md")
