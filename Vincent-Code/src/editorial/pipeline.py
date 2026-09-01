"""Orchestrate outline → essay → platform posts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.campaigns.editorial import (
    OUTLINE_FILE,
    ESSAY_FILE,
    EditorialCampaign,
    get_campaign,
    post_output_path,
)
from src.llm_client import LLMConfig, build_editorial_llm_config

from src.editorial.loaders import _strip_frontmatter, read_campaign_doc
from src.editorial.paths import ALL_CHANNELS
from src.editorial.writers.channels import CHANNEL_WRITERS
from src.editorial.writers.essay import write_essay
from src.editorial.writers.outline import write_outline


@dataclass
class GenerationResult:
    path: Path
    step: str
    skipped: bool = False


def _essay_body(campaign: EditorialCampaign) -> str:
    text = read_campaign_doc(campaign, ESSAY_FILE)
    if not text:
        raise FileNotFoundError(f"Falta {ESSAY_FILE} en {campaign.folder}")
    return _strip_frontmatter(text)


def _outline_body(campaign: EditorialCampaign) -> str:
    text = read_campaign_doc(campaign, OUTLINE_FILE)
    if not text:
        raise FileNotFoundError(f"Falta {OUTLINE_FILE} en {campaign.folder}")
    return _strip_frontmatter(text)


def _write(path: Path, content: str, *, force: bool) -> GenerationResult:
    if path.is_file() and not force:
        return GenerationResult(path=path, step=path.stem, skipped=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return GenerationResult(path=path, step=path.stem)


def generate_outline(
    slug: str,
    *,
    config: LLMConfig | None = None,
    force: bool = False,
) -> GenerationResult:
    campaign = get_campaign(slug)
    path = campaign.outline_path
    if path.is_file() and not force:
        return GenerationResult(path=path, step="outline", skipped=True)
    cfg = config or build_editorial_llm_config()
    content = write_outline(campaign, cfg)
    return _write(path, content, force=True)


def generate_essay(
    slug: str,
    *,
    config: LLMConfig | None = None,
    force: bool = False,
) -> GenerationResult:
    campaign = get_campaign(slug)
    path = campaign.essay_path
    if path.is_file() and not force:
        return GenerationResult(path=path, step="essay", skipped=True)
    outline = _outline_body(campaign)
    cfg = config or build_editorial_llm_config()
    content = write_essay(campaign, outline, cfg)
    return _write(path, content, force=True)


def generate_channels(
    slug: str,
    *,
    channels: tuple[str, ...] | None = None,
    config: LLMConfig | None = None,
    force: bool = False,
) -> list[GenerationResult]:
    campaign = get_campaign(slug)
    essay = _essay_body(campaign)
    cfg = config or build_editorial_llm_config()
    selected = channels or ALL_CHANNELS
    results: list[GenerationResult] = []

    for channel in selected:
        channel = channel.strip().lower()
        writer = CHANNEL_WRITERS.get(channel)
        if not writer:
            raise ValueError(f"Canal desconocido: {channel}")

        if channel == "newsletter":
            out_path = campaign.newsletters_dir / "borrador-generado.md"
        else:
            out_path = post_output_path(campaign, channel)

        if out_path.is_file() and not force:
            results.append(GenerationResult(path=out_path, step=channel, skipped=True))
            continue
        out_path.parent.mkdir(parents=True, exist_ok=True)
        content = writer(campaign, essay, cfg)
        results.append(_write(out_path, content, force=True))
    return results


def generate_all(
    slug: str,
    *,
    channels: tuple[str, ...] | None = None,
    config: LLMConfig | None = None,
    force: bool = False,
) -> list[GenerationResult]:
    results: list[GenerationResult] = []
    results.append(generate_outline(slug, config=config, force=force))
    results.append(generate_essay(slug, config=config, force=force))
    results.extend(generate_channels(slug, channels=channels, config=config, force=force))
    return results
