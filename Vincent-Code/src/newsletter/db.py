"""Shared SQLite connection for newsletter and editorial campaign data."""

from __future__ import annotations

import sqlite3
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = PROJECT_ROOT / "data" / "newsletter.db"

_NEWSLETTER_SCHEMA = """
CREATE TABLE IF NOT EXISTS campaigns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT NOT NULL,
    subject TEXT NOT NULL,
    tag TEXT NOT NULL,
    md_path TEXT,
    segment TEXT NOT NULL,
    sent_at TEXT NOT NULL,
    recipient_count INTEGER NOT NULL DEFAULT 0,
    ok INTEGER NOT NULL DEFAULT 0,
    method TEXT,
    bulk_id TEXT,
    error TEXT,
    editorial_slug TEXT
);

CREATE TABLE IF NOT EXISTS campaign_deliveries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER NOT NULL,
    email TEXT NOT NULL,
    name TEXT,
    sent_at TEXT NOT NULL,
    ok INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id)
);

CREATE INDEX IF NOT EXISTS idx_deliveries_campaign ON campaign_deliveries(campaign_id);
CREATE INDEX IF NOT EXISTS idx_deliveries_email ON campaign_deliveries(email);
CREATE UNIQUE INDEX IF NOT EXISTS idx_deliveries_campaign_email
    ON campaign_deliveries(campaign_id, email);
"""

_EDITORIAL_SCHEMA = """
CREATE TABLE IF NOT EXISTS editorial_campaigns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    folder_path TEXT NOT NULL,
    email_tag TEXT,
    newsletter_segment TEXT,
    landing_page TEXT,
    status TEXT,
    year TEXT,
    created_at TEXT,
    synced_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS channel_sends (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    editorial_campaign_id INTEGER NOT NULL,
    newsletter_send_id INTEGER,
    channel TEXT NOT NULL,
    sent_at TEXT NOT NULL,
    ok INTEGER NOT NULL DEFAULT 1,
    method TEXT,
    external_id TEXT,
    notes TEXT,
    FOREIGN KEY (editorial_campaign_id) REFERENCES editorial_campaigns(id),
    FOREIGN KEY (newsletter_send_id) REFERENCES campaigns(id)
);

CREATE INDEX IF NOT EXISTS idx_channel_sends_editorial ON channel_sends(editorial_campaign_id);
CREATE INDEX IF NOT EXISTS idx_channel_sends_channel ON channel_sends(channel);
"""


def _migrate(conn: sqlite3.Connection) -> None:
    conn.executescript(_NEWSLETTER_SCHEMA)
    conn.executescript(_EDITORIAL_SCHEMA)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(campaigns)")}
    if "editorial_slug" not in cols:
        conn.execute("ALTER TABLE campaigns ADD COLUMN editorial_slug TEXT")

    editorial_cols = {row[1] for row in conn.execute("PRAGMA table_info(editorial_campaigns)")}
    if "email_tag" not in editorial_cols:
        conn.execute("ALTER TABLE editorial_campaigns ADD COLUMN email_tag TEXT")
        if "postmark_tag" in editorial_cols:
            conn.execute(
                "UPDATE editorial_campaigns SET email_tag = postmark_tag "
                "WHERE email_tag IS NULL OR email_tag = ''"
            )


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    _migrate(conn)
    return conn
