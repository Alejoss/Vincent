"""Resolve editorial campaign paths for newsletter tooling."""

from __future__ import annotations

from pathlib import Path

from src.campaigns.editorial import (
    EditorialCampaign,
    get_campaign,
    resolve_newsletter_path,
)


def resolve_newsletter_for_editorial(
    slug: str,
    newsletter_file: str | None = None,
) -> tuple[Path, EditorialCampaign]:
    camp = get_campaign(slug)
    path = resolve_newsletter_path(camp, newsletter_file)
    if not path.is_file():
        raise FileNotFoundError(f"No existe el newsletter en {camp.folder}")
    return path, camp


def render_overrides_from_campaign(camp: EditorialCampaign) -> dict[str, str]:
    return {
        "tag": camp.email_tag,
        "segment": camp.newsletter_segment,
    }
