"""Load campaign context, knowledge extractions, and editorial examples."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

import yaml

from src.campaigns.editorial import (
    FRONTMATTER_RE,
    VAULT_ROOT,
    EditorialCampaign,
    discover_campaigns,
    get_campaign,
    list_newsletter_files,
    list_post_files,
)
from src.editorial.paths import BRAND_BOOK_PATH

_EXAMPLE_MAX_CHARS = 1200


def _strip_frontmatter(text: str) -> str:
    match = FRONTMATTER_RE.match(text)
    if match:
        return text[match.end() :].strip()
    return text.strip()


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def load_brand_book() -> str:
    if BRAND_BOOK_PATH.is_file():
        return _read_text(BRAND_BOOK_PATH)
    return "Voz: reflexiva, rigurosa, sin hype. Academia Blockchain."


def resolve_vault_path(relative: str) -> Path:
    rel = relative.strip().lstrip("/").replace("\\", "/")
    if rel.startswith("Cerebro-Vincent/"):
        rel = rel[len("Cerebro-Vincent/") :]
    candidate = VAULT_ROOT / rel
    if candidate.is_file():
        return candidate.resolve()
    raise FileNotFoundError(f"Archivo no encontrado en vault: {relative}")


def load_knowledge_bundle(campaign: EditorialCampaign) -> str:
    """Read knowledge extraction markdown files linked in campaign.md."""
    if not campaign.knowledge_sources:
        return "(Sin knowledge_sources en campaign.md — el outline usará solo el manifiesto.)"

    parts: list[str] = []
    for source in campaign.knowledge_sources:
        try:
            path = resolve_vault_path(str(source))
            body = _strip_frontmatter(_read_text(path))
            parts.append(f"### Fuente: {path.name}\n\n{body[:8000]}")
        except FileNotFoundError:
            parts.append(f"### Fuente no encontrada: {source}")
    return "\n\n---\n\n".join(parts)


def load_campaign_brief(campaign: EditorialCampaign) -> str:
    manifest = _read_text(campaign.campaign_manifest_path)
    body = _strip_frontmatter(manifest)
    meta_match = FRONTMATTER_RE.match(manifest)
    meta = yaml.safe_load(meta_match.group(1)) if meta_match else {}
    lines = [
        f"Título: {campaign.title}",
        f"Slug: {campaign.slug}",
        f"Objetivo/estado: {campaign.status}",
        f"Landing: {campaign.landing_page}",
        f"CTA: inscribirse / visitar {campaign.landing_page}" if campaign.landing_page else "",
        "",
        body,
    ]
    if meta.get("knowledge_sources"):
        lines.append("\nKnowledge sources: " + ", ".join(meta["knowledge_sources"]))
    return "\n".join(line for line in lines if line is not None)


def read_campaign_doc(campaign: EditorialCampaign, filename: str) -> str | None:
    path = campaign.folder / filename
    if not path.is_file():
        return None
    return _read_text(path)


def _channel_meta(text: str) -> dict:
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}
    return yaml.safe_load(match.group(1)) or {}


def load_editorial_examples(
    channel: str,
    *,
    exclude_slug: str | None = None,
    limit: int = 3,
) -> list[str]:
    """Simple editorial memory: published posts from other campaigns."""
    channel = channel.strip().lower()
    examples: list[str] = []

    for camp in discover_campaigns():
        if exclude_slug and camp.slug == exclude_slug:
            continue

        if channel == "newsletter":
            candidates = list_newsletter_files(camp)
        else:
            candidates = list_post_files(camp, channel)

        for path in candidates:
            raw = _read_text(path)
            meta = _channel_meta(raw)
            if meta.get("status") not in (None, "published"):
                continue
            body = _strip_frontmatter(raw)
            if len(body) < 80 or body.startswith("> **Migrado**"):
                continue
            label = path.stem.replace("-", " ")
            examples.append(f"### Ejemplo ({camp.title} — {label})\n\n{body[:_EXAMPLE_MAX_CHARS]}")
            if len(examples) >= limit:
                return examples
    return examples


def compose_frontmatter(meta: dict) -> str:
    block = yaml.safe_dump(meta, allow_unicode=True, sort_keys=False).strip()
    return f"---\n{block}\n---\n\n"


def wrap_generated(meta: dict, body: str) -> str:
    clean = body.strip()
    clean = re.sub(r"^```(?:markdown|md)?\s*\n", "", clean)
    clean = re.sub(r"\n```\s*$", "", clean)
    return compose_frontmatter(meta) + clean + "\n"


def generation_meta(*, model: str, step: str) -> dict:
    return {
        "generated": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generator": "editorial-engine",
        "step": step,
        "model": model,
    }
