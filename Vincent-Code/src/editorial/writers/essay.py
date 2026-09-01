"""Canonical essay writer."""

from __future__ import annotations

from src.campaigns.editorial import EditorialCampaign
from src.llm_client import LLMConfig

from src.editorial.loaders import (
    generation_meta,
    load_brand_book,
    load_campaign_brief,
    wrap_generated,
)
from src.editorial.writers.base import load_prompt, run_writer


def write_essay(
    campaign: EditorialCampaign,
    outline_body: str,
    config: LLMConfig,
) -> str:
    system = load_prompt("essay_system.md")
    brand = load_brand_book()
    user = f"""# Brand Book
{brand}

# Brief de campaña
{load_campaign_brief(campaign)}

# Outline aprobado
{outline_body}

Escribe el ensayo canónico en Markdown."""

    body = run_writer(system_prompt=system, user_prompt=user, config=config, temperature=0.65)
    meta = generation_meta(model=config.label, step="essay")
    meta["campaign"] = campaign.slug
    return wrap_generated(meta, body)
