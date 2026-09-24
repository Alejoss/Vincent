"""One-time, resumable copy of unfinished tasks; retains the original database."""
import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import sync_productivity_obsidian_to_notion as sync
from dotenv import set_key
from notion_client import Client

OLD = "20d793a2-5b64-4663-bca9-641d927171ca"
NEW = "0b762000-e576-4adc-b064-921992a2c9ad"
BACKUP = ROOT / "logs" / "tasks-migration-20260923.json"
MANIFEST = ROOT / "state" / "tasks_migration_20260923.json"

def query_all(client, ds):
    rows, cursor = [], None
    while True:
        kw = {"data_source_id": ds, "page_size": 100}
        if cursor:
            kw["start_cursor"] = cursor
        response = client.data_sources.query(**kw)
        rows.extend(response["results"])
        if not response.get("has_more"):
            return rows
        cursor = response["next_cursor"]

def clean_rich(items):
    return [{k: v for k, v in item.items() if k not in {"plain_text", "href"}} for item in items]

def payload(page):
    result = {}
    for name, prop in page["properties"].items():
        kind = prop["type"]
        value = prop[kind]
        if kind in {"title", "rich_text"}:
            value = clean_rich(value)
        elif kind == "select":
            value = {"name": value["name"]} if value else None
        elif kind == "status":
            value = {"name": "Sin empezar" if not value or value["name"] == "Por hacer" else value["name"]}
        elif kind != "date":
            raise RuntimeError(f"Unsupported property: {name} / {kind}")
        result[name] = {kind: value}
    return result

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    client = Client(auth=os.environ["NOTION_API_TOKEN"], notion_version="2025-09-03")
    old_ds, _ = sync.get_ds_and_props(client, OLD)
    new_ds, schema = sync.get_ds_and_props(client, NEW)
    all_pages = query_all(client, old_ds)
    unfinished = [p for p in all_pages if (p["properties"]["Estado"].get("status") or {}).get("name") != "Hecho"]
    backup = {"database": OLD, "pages": all_pages, "bodies": {}}
    for page in unfinished:
        blocks = client.blocks.children.list(block_id=page["id"], page_size=100)
        assert not blocks.get("has_more")
        assert all(b["type"] == "paragraph" and not b.get("has_children") for b in blocks["results"])
        backup["bodies"][page["id"]] = blocks["results"]
    print(f"Unfinished={len(unfinished)}; completed retained={len(all_pages)-len(unfinished)}")
    if not args.apply:
        return
    if not BACKUP.exists():
        BACKUP.write_text(json.dumps(backup, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else {"old_database": OLD, "new_database": NEW, "pages": {}}
    for page in unfinished:
        old_id = page["id"]
        if old_id in manifest["pages"]:
            continue
        children = []
        for block in backup["bodies"][old_id]:
            paragraph = {k: v for k, v in block["paragraph"].items() if v is not None}
            paragraph["rich_text"] = clean_rich(paragraph["rich_text"])
            children.append({"object": "block", "type": "paragraph", "paragraph": paragraph})
        kwargs = {"parent": {"type": "data_source_id", "data_source_id": new_ds}, "properties": payload(page)}
        if children:
            kwargs["children"] = children
        if page.get("icon"):
            kwargs["icon"] = page["icon"]
        new_page = client.pages.create(**kwargs)
        manifest["pages"][old_id] = new_page["id"]
        MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        print("Copied", old_id, "->", new_page["id"])
    new_pages = {p["id"]: p for p in query_all(client, new_ds)}
    assert len(new_pages) == len(unfinished) == len(manifest["pages"])
    for old_page in unfinished:
        new_page = new_pages[manifest["pages"][old_page["id"]]]
        assert payload(old_page) == payload(new_page), old_page["id"]
        blocks = client.blocks.children.list(block_id=new_page["id"], page_size=100)
        assert len(blocks["results"]) == len(backup["bodies"][old_page["id"]])
        for before, after in zip(backup["bodies"][old_page["id"]], blocks["results"]):
            assert before["paragraph"] == after["paragraph"]
    prop_map = sync.build_prop_map(schema)
    vault = Path(os.environ["OBSIDIAN_VAULT_PATH"])
    mirrored = 0
    for path in (vault / "0_Diario_Productividad" / "Tareas-Ideas").glob("slack-*.md"):
        fm, _ = sync.parse_frontmatter(path.read_text(encoding="utf-8"))
        old_id = fm.get("notion_page_id")
        if old_id in manifest["pages"]:
            sync.mirror_page(path, new_pages[manifest["pages"][old_id]], prop_map, NEW)
            mirrored += 1
    state_path = ROOT / "state" / "notion_slack_reminders_sent.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    for key, value in list(state.items()):
        page_id, sep, suffix = key.partition("|")
        if page_id in manifest["pages"]:
            state[manifest["pages"][page_id] + sep + suffix] = value
    state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    set_key(str(ROOT / ".env"), "NOTION_TASKS_DATABASE_ID", NEW)
    print(f"Verified {len(new_pages)} copies; relinked {mirrored} local notes; updated local routing.")

if __name__ == "__main__":
    main()
