"""Outline writer."""

from __future__ import annotations

from src.campaigns.editorial import EditorialCampaign
from src.llm_client import LLMConfig

from src.editorial.loaders import (
    generation_meta,
    load_brand_book,
    load_campaign_brief,
    load_knowledge_bundle,
    wrap_generated,
)
from src.editorial.writers.base import load_prompt, run_writer


def write_outline(campaign: EditorialCampaign, config: LLMConfig) -> str:
    system = load_prompt("outline_system.md")
    brand = load_brand_book()
    user = f"""# Brand Book
{brand}

# Brief de campaña
{load_campaign_brief(campaign)}

# Knowledge (extracciones existentes — no re-extraer)
{load_knowledge_bundle(campaign)}

Genera el outline en Markdown."""

    body = run_writer(system_prompt=system, user_prompt=user, config=config, temperature=0.5)
    meta = generation_meta(model=config.label, step="outline")
    meta["campaign"] = campaign.slug
    return wrap_generated(meta, body)
