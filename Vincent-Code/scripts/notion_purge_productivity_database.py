"""
Archive (send to Notion trash) all pages in the productivity Notion databases.

Use before a full re-import from Slack to reset titles, dates, and dedup state.

Requires NOTION_API_TOKEN and --yes (or --dry-run to preview).

Examples:
  python scripts/notion_purge_productivity_database.py --dry-run
  python scripts/notion_purge_productivity_database.py --database tasks --yes
  python scripts/notion_purge_productivity_database.py --database both --yes
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from notion_client import Client

load_dotenv(override=True)

SCRIPTS_DIR = os.path.dirname(__file__)
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPTS_DIR, ".."))
sys.path.insert(0, SCRIPTS_DIR)

from sync_productivity_obsidian_to_notion import (  # noqa: E402
    LEARNINGS_DB_ID,
    get_ds_and_props,
    normalize_id,
    resolve_tasks_db_id,
)


def _require_env(name: str) -> str:
    v = (os.getenv(name) or "").strip()
    if not v:
        raise SystemExit(f"Missing required env var: {name}")
    return v


def _query_all_pages(client: Client, database_id: str, ds_id: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    cursor: Optional[str] = None
    while True:
        kw: Dict[str, Any] = {"page_size": 100}
        if cursor:
            kw["start_cursor"] = cursor
        if ds_id == database_id:
            resp = client.databases.query(database_id=database_id, **kw)
        else:
            resp = client.data_sources.query(data_source_id=ds_id, **kw)
        out.extend(resp.get("results") or [])
        if not resp.get("has_more"):
            break
        cursor = resp.get("next_cursor")
    return out


def _archive_page(client: Client, page_id: str, dry_run: bool) -> None:
    if dry_run:
        return
    client.pages.update(page_id=page_id, archived=True)


def _purge_db(client: Client, database_id: str, label: str, dry_run: bool, sleep_s: float) -> int:
    db_id = normalize_id(database_id)
    ds_id, _props = get_ds_and_props(client, db_id)
    pages = _query_all_pages(client, db_id, ds_id)
    print(f"[{label}] {len(pages)} page(s) in {db_id}")
    for i, page in enumerate(pages):
        pid = page.get("id") or ""
        if not pid:
            continue
        if dry_run:
            print(f"  [dry-run] would archive {pid}")
        else:
            _archive_page(client, pid, dry_run=False)
            if (i + 1) % 10 == 0:
                print(f"  archived {i + 1}/{len(pages)}")
        time.sleep(max(0.0, sleep_s))
    if not dry_run and pages:
        print(f"[{label}] archived {len(pages)} page(s)")
    return len(pages)


def _clear_reminder_cache(dry_run: bool) -> None:
    cache = Path(PROJECT_ROOT) / "cache" / "notion_slack_reminders" / "sent_state.json"
    if not cache.is_file():
        return
    if dry_run:
        print(f"[dry-run] would delete {cache}")
        return
    cache.unlink()
    print(f"Deleted reminder dedup cache: {cache}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Archive all pages in productivity Notion DB(s)")
    parser.add_argument(
        "--database",
        choices=("tasks", "learnings", "both"),
        default="tasks",
        help="Which database to purge (default: tasks / Tareas Ideas)",
    )
    parser.add_argument("--dry-run", action="store_true", help="List pages only; no archive")
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Required to archive pages (except with --dry-run)",
    )
    parser.add_argument("--sleep-s", type=float, default=0.2, help="Pause between API calls")
    parser.add_argument(
        "--clear-reminder-cache",
        action="store_true",
        help="Also delete cache/notion_slack_reminders/sent_state.json",
    )
    args = parser.parse_args()

    if not args.dry_run and not args.yes:
        raise SystemExit("Refusing to archive without --yes (use --dry-run to preview).")

    _require_env("NOTION_API_TOKEN")
    client = Client(auth=os.getenv("NOTION_API_TOKEN"), notion_version="2025-09-03")

    total = 0
    if args.database in ("tasks", "both"):
        db = resolve_tasks_db_id()
        total += _purge_db(client, db, "tasks", args.dry_run, args.sleep_s)
    if args.database in ("learnings", "both"):
        total += _purge_db(client, LEARNINGS_DB_ID, "learnings", args.dry_run, args.sleep_s)

    if args.clear_reminder_cache:
        _clear_reminder_cache(args.dry_run)

    print(f"Done. total_pages={'would archive ' if args.dry_run else ''}{total}")
    if not args.dry_run:
        print("Next: run_productivity_pipeline.bat (or sync + classify) to re-import from Slack.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
