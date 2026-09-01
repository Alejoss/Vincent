"""Paths and discovery for editorial campaigns in Obsidian."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv

from src.newsletter.config import PROJECT_ROOT

load_dotenv(PROJECT_ROOT / ".env", override=True)

VAULT_ROOT = PROJECT_ROOT.parent / "Cerebro-Vincent"
DEFAULT_CAMPAIGNS_DIR = VAULT_ROOT / "Campaigns"
NEWSLETTER_AUDIENCE_DIR = VAULT_ROOT / "newsletters"

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)

EDITORIAL_SUBDIR = "editorial"
NEWSLETTERS_SUBDIR = "newsletters"
POSTS_SUBDIR = "posts"

OUTLINE_FILE = "outline.md"
ESSAY_FILE = "essay.md"

# Legacy flat layout (pre-2026-07 reorg)
LEGACY_CHANNEL_FILES = {
    "newsletter": "newsletter.md",
    "telegram": "telegram.md",
    "x": "x.md",
    "instagram": "instagram.md",
    "youtube": "youtube.md",
}

SOCIAL_CHANNELS = ("youtube", "telegram", "x", "instagram")


@dataclass
class EditorialCampaign:
    slug: str
    title: str
    folder: Path
    status: str = "draft"
    landing_page: str = ""
    email_tag: str = "newsletter"
    newsletter_segment: str = "test"
    created: str = ""
    knowledge_sources: list[str] = field(default_factory=list)
    year: str = ""
    primary_newsletter: str = ""

    @property
    def editorial_dir(self) -> Path:
        return self.folder / EDITORIAL_SUBDIR

    @property
    def newsletters_dir(self) -> Path:
        return self.folder / NEWSLETTERS_SUBDIR

    @property
    def posts_dir(self) -> Path:
        return self.folder / POSTS_SUBDIR

    @property
    def outline_path(self) -> Path:
        nested = self.editorial_dir / OUTLINE_FILE
        if nested.is_file():
            return nested
        return self.folder / OUTLINE_FILE

    @property
    def essay_path(self) -> Path:
        nested = self.editorial_dir / ESSAY_FILE
        if nested.is_file():
            return nested
        return self.folder / ESSAY_FILE

    @property
    def newsletter_path(self) -> Path:
        return resolve_newsletter_path(self)

    @property
    def campaign_manifest_path(self) -> Path:
        return self.folder / "campaign.md"

    def channel_path(self, channel: str) -> Path:
        return resolve_post_path(self, channel)


def campaigns_root() -> Path:
    raw = os.getenv("CAMPAIGNS_DIR", "").strip()
    if raw:
        p = Path(raw)
        return p.resolve() if p.is_absolute() else (PROJECT_ROOT / p).resolve()
    return DEFAULT_CAMPAIGNS_DIR.resolve()


def _parse_frontmatter(text: str) -> dict:
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}
    return yaml.safe_load(match.group(1)) or {}


def _load_campaign_folder(folder: Path) -> EditorialCampaign | None:
    manifest = folder / "campaign.md"
    if not manifest.is_file():
        return None

    meta = _parse_frontmatter(manifest.read_text(encoding="utf-8"))
    slug = str(meta.get("id") or folder.name).strip()
    if not slug:
        slug = folder.name

    year = folder.parent.name if folder.parent.name.isdigit() else ""

    return EditorialCampaign(
        slug=slug,
        title=str(meta.get("title") or folder.name),
        folder=folder.resolve(),
        status=str(meta.get("status") or "draft"),
        landing_page=str(meta.get("landing_page") or ""),
        email_tag=str(meta.get("email_tag") or meta.get("postmark_tag") or "newsletter"),
        newsletter_segment=str(meta.get("newsletter_segment") or "test"),
        created=str(meta.get("created") or ""),
        knowledge_sources=list(meta.get("knowledge_sources") or []),
        year=year,
        primary_newsletter=str(meta.get("primary_newsletter") or "").strip(),
    )


def list_newsletter_files(campaign: EditorialCampaign) -> list[Path]:
    """All newsletter sends under newsletters/."""
    root = campaign.newsletters_dir
    if root.is_dir():
        return sorted(root.glob("*.md"))
    legacy = campaign.folder / LEGACY_CHANNEL_FILES["newsletter"]
    return [legacy] if legacy.is_file() else []


def list_post_files(campaign: EditorialCampaign, channel: str | None = None) -> list[Path]:
    """Social posts under posts/ (optionally filtered by channel prefix)."""
    root = campaign.posts_dir
    files: list[Path] = []
    if root.is_dir():
        if channel:
            files = sorted(root.glob(f"{channel}-*.md"))
        else:
            files = sorted(root.glob("*.md"))
    if files:
        return files
    if channel and channel in LEGACY_CHANNEL_FILES:
        legacy = campaign.folder / LEGACY_CHANNEL_FILES[channel]
        if legacy.is_file():
            return [legacy]
    return []


def resolve_newsletter_path(campaign: EditorialCampaign, filename: str | None = None) -> Path:
    if filename:
        path = campaign.folder / filename
        if path.is_file():
            return path.resolve()
        nested = campaign.newsletters_dir / filename
        if nested.is_file():
            return nested.resolve()
        raise FileNotFoundError(f"Newsletter no encontrado: {filename}")

    if campaign.primary_newsletter:
        path = campaign.folder / campaign.primary_newsletter
        if path.is_file():
            return path.resolve()

    newsletters = list_newsletter_files(campaign)
    if newsletters:
        return newsletters[0].resolve()

    legacy = campaign.folder / LEGACY_CHANNEL_FILES["newsletter"]
    if legacy.is_file():
        return legacy.resolve()
    raise FileNotFoundError(f"No hay newsletters en {campaign.folder}")


def resolve_post_path(
    campaign: EditorialCampaign,
    channel: str,
    filename: str | None = None,
) -> Path:
    channel = channel.strip().lower()
    if channel not in SOCIAL_CHANNELS and channel != "newsletter":
        raise KeyError(f"Canal desconocido: {channel}")

    if filename:
        path = campaign.posts_dir / filename
        if path.is_file():
            return path.resolve()
        raise FileNotFoundError(f"Post no encontrado: {filename}")

    posts = list_post_files(campaign, channel)
    if posts:
        return posts[-1].resolve()

    legacy_name = LEGACY_CHANNEL_FILES.get(channel)
    if legacy_name:
        legacy = campaign.folder / legacy_name
        if legacy.is_file():
            return legacy.resolve()
    raise FileNotFoundError(f"No hay posts de {channel} en {campaign.folder}")


def post_output_path(campaign: EditorialCampaign, channel: str) -> Path:
    """Default path for IA-generated social post."""
    return campaign.posts_dir / f"{channel}-borrador.md"


def list_newsletter_choices(campaign: EditorialCampaign) -> list[tuple[str, str]]:
    """(relative_path, label) for UI."""
    choices: list[tuple[str, str]] = []
    for path in list_newsletter_files(campaign):
        rel = path.relative_to(campaign.folder).as_posix()
        choices.append((rel, path.stem.replace("-", " ").title()))
    return choices


def discover_campaigns(root: Path | None = None) -> list[EditorialCampaign]:
    """Find all folders under Campaigns/YYYY/ that contain campaign.md."""
    base = root or campaigns_root()
    if not base.is_dir():
        return []

    found: list[EditorialCampaign] = []
    for year_dir in sorted(base.iterdir()):
        if not year_dir.is_dir() or year_dir.name.startswith("_"):
            continue
        if year_dir.name.isdigit():
            for folder in sorted(year_dir.iterdir()):
                if folder.is_dir() and not folder.name.startswith("."):
                    camp = _load_campaign_folder(folder)
                    if camp:
                        found.append(camp)
        else:
            camp = _load_campaign_folder(year_dir)
            if camp:
                found.append(camp)

    return found


def get_campaign(slug_or_folder: str, root: Path | None = None) -> EditorialCampaign:
    """Resolve by id (slug) or folder name."""
    campaigns = discover_campaigns(root)
    key = slug_or_folder.strip().lower()
    for camp in campaigns:
        if camp.slug.lower() == key or camp.folder.name.lower() == key:
            return camp
    raise FileNotFoundError(f"Campaña editorial no encontrada: {slug_or_folder}")


def list_campaign_choices() -> list[tuple[str, str]]:
    """Return (slug, display label) for UI/CLI."""
    return [(c.slug, f"{c.title} ({c.year or 'sin año'}) — {c.status}") for c in discover_campaigns()]


# Backward compatibility for imports
CHANNEL_FILES = LEGACY_CHANNEL_FILES
