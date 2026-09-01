"""Platform channel writers."""

from __future__ import annotations

import re
from collections.abc import Callable

from src.campaigns.editorial import EditorialCampaign
from src.llm_client import LLMConfig

from src.editorial.loaders import (
    generation_meta,
    load_brand_book,
    load_campaign_brief,
    load_editorial_examples,
    wrap_generated,
)
from src.editorial.writers.base import load_prompt, run_writer

ChannelWriter = Callable[[EditorialCampaign, str, LLMConfig], str]


def _examples_block(channel: str, campaign: EditorialCampaign) -> str:
    examples = load_editorial_examples(channel, exclude_slug=campaign.slug)
    if not examples:
        return "(Sin ejemplos previos indexados — escribe con el Brand Book.)"
    return "\n\n".join(examples)


def _write_channel(
    campaign: EditorialCampaign,
    essay_body: str,
    config: LLMConfig,
    *,
    channel: str,
    prompt_file: str,
    temperature: float = 0.7,
) -> str:
    system = load_prompt(prompt_file)
    brand = load_brand_book()
    user = f"""# Brand Book
{brand}

# Brief de campaña
{load_campaign_brief(campaign)}

# Ensayo canónico
{essay_body}

# Ejemplos editoriales ({channel})
{_examples_block(channel, campaign)}

Genera el contenido para {channel}."""

    body = run_writer(
        system_prompt=system,
        user_prompt=user,
        config=config,
        temperature=temperature,
    )
    meta = generation_meta(model=config.label, step=channel)
    meta["campaign"] = campaign.slug
    meta["channel"] = channel
    meta["derived_from"] = "essay.md"
    return wrap_generated(meta, body)


def write_newsletter(campaign: EditorialCampaign, essay_body: str, config: LLMConfig) -> str:
    system = load_prompt("newsletter_system.md")
    brand = load_brand_book()
    user = f"""# Brand Book
{brand}

# Brief de campaña
{load_campaign_brief(campaign)}

# Ensayo canónico
{essay_body}

# Ejemplos editoriales (newsletter)
{_examples_block("newsletter", campaign)}

Genera el newsletter."""

    raw = run_writer(
        system_prompt=system,
        user_prompt=user,
        config=config,
        temperature=0.65,
    )
    return _parse_newsletter_output(raw, campaign, config)


def _parse_newsletter_output(raw: str, campaign: EditorialCampaign, config: LLMConfig) -> str:
    """Extract META_SUBJECT / META_PREVIEW and build newsletter frontmatter."""
    lines = raw.splitlines()
    subject = campaign.title
    preview = ""
    body_start = 0
    meta_found = False

    for i, line in enumerate(lines):
        if line.startswith("META_SUBJECT:"):
            subject = line.split(":", 1)[1].strip()
            meta_found = True
        elif line.startswith("META_PREVIEW:"):
            preview = line.split(":", 1)[1].strip()
            meta_found = True
        elif meta_found and line.strip() == "":
            body_start = i + 1
            break

    body = "\n".join(lines[body_start:]).strip()
    body = re.sub(r"^---\s*\n.*?\n---\s*\n", "", body, flags=re.DOTALL)

    meta = generation_meta(model=config.label, step="newsletter")
    meta.update(
        {
            "campaign": campaign.slug,
            "channel": "newsletter",
            "derived_from": "essay.md",
            "subject": subject,
            "preview_text": preview,
            "tag": campaign.email_tag,
            "segment": campaign.newsletter_segment,
        }
    )
    return wrap_generated(meta, body)


def write_youtube(campaign: EditorialCampaign, essay_body: str, config: LLMConfig) -> str:
    return _write_channel(
        campaign,
        essay_body,
        config,
        channel="youtube",
        prompt_file="youtube_system.md",
    )


def write_telegram(campaign: EditorialCampaign, essay_body: str, config: LLMConfig) -> str:
    return _write_channel(
        campaign,
        essay_body,
        config,
        channel="telegram",
        prompt_file="telegram_system.md",
    )


def write_x(campaign: EditorialCampaign, essay_body: str, config: LLMConfig) -> str:
    return _write_channel(
        campaign,
        essay_body,
        config,
        channel="x",
        prompt_file="x_system.md",
        temperature=0.75,
    )


def write_instagram(campaign: EditorialCampaign, essay_body: str, config: LLMConfig) -> str:
    return _write_channel(
        campaign,
        essay_body,
        config,
        channel="instagram",
        prompt_file="instagram_system.md",
    )


CHANNEL_WRITERS: dict[str, ChannelWriter] = {
    "newsletter": write_newsletter,
    "youtube": write_youtube,
    "telegram": write_telegram,
    "x": write_x,
    "instagram": write_instagram,
}
