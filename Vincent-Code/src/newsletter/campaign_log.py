"""SQLite registry of newsletter sends and per-recipient deliveries."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .db import connect
from .send_result import SendResult
from .renderer import RenderedNewsletter
from .subscribers import Subscriber


def _campaign_slug(rendered: RenderedNewsletter) -> str:
    if rendered.md_path:
        return rendered.md_path.stem
    return rendered.tag


def record_campaign_send(
    rendered: RenderedNewsletter,
    result: SendResult,
    subscribers: list[Subscriber],
    *,
    segment: str,
    editorial_slug: str | None = None,
) -> int:
    """Persist newsletter send summary and one row per recipient."""
    sent_at = datetime.now(timezone.utc).isoformat()
    slug = _campaign_slug(rendered)

    with connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO campaigns (
                slug, subject, tag, md_path, segment, sent_at,
                recipient_count, ok, method, bulk_id, error, editorial_slug
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                slug,
                rendered.subject,
                rendered.tag,
                str(rendered.md_path) if rendered.md_path else None,
                segment,
                sent_at,
                result.recipient_count,
                1 if result.ok else 0,
                result.method,
                result.bulk_id,
                result.error,
                editorial_slug,
            ),
        )
        campaign_id = int(cur.lastrowid)

        if result.ok:
            conn.executemany(
                """
                INSERT OR IGNORE INTO campaign_deliveries (
                    campaign_id, email, name, sent_at, ok
                ) VALUES (?, ?, ?, ?, 1)
                """,
                [(campaign_id, sub.email, sub.name, sent_at) for sub in subscribers],
            )
        conn.commit()
        return campaign_id


def list_campaigns(limit: int = 20) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT id, slug, subject, tag, segment, sent_at, recipient_count,
                   ok, method, bulk_id, editorial_slug
            FROM campaigns
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_campaign_recipients(campaign_id: int) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT email, name, sent_at
            FROM campaign_deliveries
            WHERE campaign_id = ?
            ORDER BY email
            """,
            (campaign_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def recipients_for_slug(slug: str) -> list[str]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT d.email
            FROM campaign_deliveries d
            JOIN campaigns c ON c.id = d.campaign_id
            WHERE c.slug = ? OR c.editorial_slug = ?
            ORDER BY d.email
            """,
            (slug, slug),
        ).fetchall()
    return [row["email"] for row in rows]
