"""Newsletter email provider: SMTP2GO."""

from __future__ import annotations

from .config import NewsletterConfig
from .renderer import RenderedNewsletter
from .send_result import SendResult
from . import smtp2go_client
from .subscribers import Subscriber

# Re-export for callers
__all__ = ["SendResult", "send_test", "send_campaign"]


def send_test(
    config: NewsletterConfig,
    rendered: RenderedNewsletter,
    to_email: str,
) -> SendResult:
    return smtp2go_client.send_test(config, rendered, to_email)


def send_campaign(
    config: NewsletterConfig,
    rendered: RenderedNewsletter,
    subscribers: list[Subscriber],
    *,
    prefer_bulk: bool = True,
) -> SendResult:
    return smtp2go_client.send_campaign(
        config, rendered, subscribers, prefer_bulk=prefer_bulk
    )
