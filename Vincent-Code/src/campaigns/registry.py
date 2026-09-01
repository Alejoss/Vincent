"""Sync editorial campaigns from Obsidian to SQLite."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.campaigns.editorial import discover_campaigns
from src.newsletter.db import connect


def sync_editorial_campaigns() -> list[dict[str, Any]]:
    """Upsert all campaigns from Obsidian into SQLite."""
    now = datetime.now(timezone.utc).isoformat()
    campaigns = discover_campaigns()
    results: list[dict[str, Any]] = []

    with connect() as conn:
        for camp in campaigns:
            conn.execute(
                """
                INSERT INTO editorial_campaigns (
                    slug, title, folder_path, email_tag, newsletter_segment,
                    landing_page, status, year, created_at, synced_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(slug) DO UPDATE SET
                    title = excluded.title,
                    folder_path = excluded.folder_path,
                    email_tag = excluded.email_tag,
                    newsletter_segment = excluded.newsletter_segment,
                    landing_page = excluded.landing_page,
                    status = excluded.status,
                    year = excluded.year,
                    created_at = excluded.created_at,
                    synced_at = excluded.synced_at
                """,
                (
                    camp.slug,
                    camp.title,
                    str(camp.folder),
                    camp.email_tag,
                    camp.newsletter_segment,
                    camp.landing_page,
                    camp.status,
                    camp.year,
                    camp.created,
                    now,
                ),
            )
            results.append({"slug": camp.slug, "title": camp.title, "folder": str(camp.folder)})
        conn.commit()

    return results


def get_editorial_id(slug: str) -> int | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT id FROM editorial_campaigns WHERE slug = ?",
            (slug,),
        ).fetchone()
    return int(row["id"]) if row else None


def record_channel_send(
    *,
    editorial_slug: str,
    channel: str,
    newsletter_send_id: int | None = None,
    ok: bool = True,
    method: str | None = None,
    external_id: str | None = None,
    notes: str | None = None,
) -> int:
    now = datetime.now(timezone.utc).isoformat()
    editorial_id = get_editorial_id(editorial_slug)
    if editorial_id is None:
        sync_editorial_campaigns()
        editorial_id = get_editorial_id(editorial_slug)
    if editorial_id is None:
        raise ValueError(f"Campaña editorial no registrada: {editorial_slug}")

    with connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO channel_sends (
                editorial_campaign_id, newsletter_send_id, channel,
                sent_at, ok, method, external_id, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                editorial_id,
                newsletter_send_id,
                channel,
                now,
                1 if ok else 0,
                method,
                external_id,
                notes,
            ),
        )
        conn.commit()
        return int(cur.lastrowid)


def list_editorial_campaigns_db(limit: int = 50) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT id, slug, title, status, email_tag, newsletter_segment,
                   landing_page, year, synced_at
            FROM editorial_campaigns
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def channel_sends_for_editorial(slug: str) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT cs.id, cs.channel, cs.sent_at, cs.ok, cs.method, cs.external_id, cs.notes,
                   c.subject, c.recipient_count
            FROM channel_sends cs
            JOIN editorial_campaigns ec ON ec.id = cs.editorial_campaign_id
            LEFT JOIN campaigns c ON c.id = cs.newsletter_send_id
            WHERE ec.slug = ?
            ORDER BY cs.sent_at DESC
            """,
            (slug,),
        ).fetchall()
    return [dict(r) for r in rows]
