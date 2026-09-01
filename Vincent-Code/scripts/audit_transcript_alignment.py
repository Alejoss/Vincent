#!/usr/bin/env python3
"""Audit transcript vault vs SQLite — no API calls."""
from __future__ import annotations

import re
import sqlite3
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB = PROJECT_ROOT / "cache" / "video_transcripts" / "state.sqlite3"
VAULT = (PROJECT_ROOT / "../Cerebro-Vincent").resolve() / "10_Sources" / "Own_Transcripts"

YOUTUBE_ID_RE = re.compile(r"(?:v=|youtu\.be/)([A-Za-z0-9_-]{11})")


def parse_frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8", errors="replace")
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    block = text[3:end]
    out: dict[str, str] = {}
    for line in block.splitlines():
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        out[key] = val
    return out


def yt_id(url: str | None) -> str | None:
    if not url:
        return None
    m = YOUTUBE_ID_RE.search(url)
    return m.group(1) if m else None


def main() -> int:
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM video_transcript").fetchall()
    conn.close()

    by_video_id: dict[str, sqlite3.Row] = {}
    for r in rows:
        by_video_id[r["video_id"]] = r

    md_files = [p for p in VAULT.glob("*.md") if not p.name.startswith("_estado")]
    md_by_yt: dict[str, list[Path]] = defaultdict(list)
    md_by_local_path: dict[str, list[Path]] = defaultdict(list)
    md_meta: dict[Path, dict] = {}

    for p in md_files:
        fm = parse_frontmatter(p)
        md_meta[p] = fm
        url = fm.get("source_url", "")
        vid = yt_id(url)
        if vid:
            md_by_yt[vid].append(p)
        if url.startswith("file:///"):
            # normalize path fragment
            local = url.replace("file:///", "").replace("%20", " ")
            md_by_local_path[local.lower()].append(p)

    print("=" * 60)
    print("ACLARACIÓN: skipped = YA TIENEN transcript (no faltan)")
    print("             failed  = SIN transcript en vault")
    print("             done    = transcript + registrado en SQLite")
    print("=" * 60)
    print()

    skipped = [r for r in rows if r["status"] == "skipped" and r["source_kind"] == "youtube"]
    failed = [r for r in rows if r["status"] == "failed" and r["source_kind"] == "youtube"]
    done = [r for r in rows if r["status"] == "done" and r["source_kind"] == "youtube"]

    print(f"YouTube skipped: {len(skipped)} (tienen .md)")
    print(f"YouTube failed:  {len(failed)} (faltan)")
    print(f"YouTube done:    {len(done)}")
    print()

    # --- Skipped: verify vault match ---
    print("--- SKIPPED: comprobación source_url / archivo ---")
    skip_ok = 0
    skip_issues = []
    for r in skipped:
        vid = r["video_id"]
        mds = md_by_yt.get(vid, [])
        if not mds:
            skip_issues.append((vid, r["title"], "skipped pero NO hay .md con ese video_id"))
        elif len(mds) > 1:
            skip_issues.append((vid, r["title"], f"skipped pero {len(mds)} .md duplicados: {[m.name for m in mds]}"))
        else:
            skip_ok += 1
            # title mismatch?
            fm = md_meta[mds[0]]
            db_title = (r["title"] or "").strip()
            md_title = (fm.get("title") or "").strip()
            if db_title and md_title and db_title.lower() != md_title.lower():
                skip_issues.append((vid, r["title"], f"título distinto en .md: '{md_title[:60]}' -> {mds[0].name}"))

    print(f"  OK (encontrado .md): {skip_ok}/{len(skipped)}")
    if skip_issues:
        print(f"  PROBLEMAS: {len(skip_issues)}")
        for vid, title, msg in skip_issues[:25]:
            print(f"    {vid} | {title[:50]} | {msg}")
        if len(skip_issues) > 25:
            print(f"    ... y {len(skip_issues) - 25} más")
    print()

    # --- Done: output_path + source_url ---
    print("--- DONE: comprobación output_path y source_url ---")
    done_ok = 0
    done_issues = []
    for r in done:
        vid = r["video_id"]
        out = r["output_path"]
        mds = md_by_yt.get(vid, [])
        if out and not Path(out).exists():
            done_issues.append((vid, r["title"], f"output_path no existe: {out}"))
        elif not mds:
            done_issues.append((vid, r["title"], "done pero ningún .md con ese video_id en frontmatter"))
        elif len(mds) > 1:
            done_issues.append((vid, r["title"], f"done pero {len(mds)} .md con mismo video_id"))
        else:
            done_ok += 1
            if out and Path(out).resolve() != mds[0].resolve():
                done_issues.append((vid, r["title"], f"output_path DB != .md: {Path(out).name} vs {mds[0].name}"))

    print(f"  OK: {done_ok}/{len(done)}")
    if done_issues:
        print(f"  PROBLEMAS: {len(done_issues)}")
        for vid, title, msg in done_issues[:25]:
            print(f"    {vid} | {title[:50]} | {msg}")
        if len(done_issues) > 25:
            print(f"    ... y {len(done_issues) - 25} más")
    print()

    # --- Orphan .md (YouTube id not in DB or DB says failed) ---
    print("--- .md HUÉRFANOS o DESCUADRE con SQLite ---")
    orphans = []
    for vid, paths in md_by_yt.items():
        row = by_video_id.get(vid)
        if row is None:
            orphans.append((vid, paths, "video_id en .md pero NO está en SQLite"))
        elif row["status"] == "failed":
            orphans.append((vid, paths, f".md existe pero SQLite dice failed: {row['title'][:50]}"))

    # md with youtube url but video not in channel DB at all - already covered
    # duplicate video ids across md
    dup_yt = {k: v for k, v in md_by_yt.items() if len(v) > 1}
    if dup_yt:
        print(f"  video_id duplicado en varios .md: {len(dup_yt)}")
        for vid, paths in list(dup_yt.items())[:10]:
            print(f"    {vid}: {[p.name for p in paths]}")

    if orphans:
        print(f"  huérfanos / failed con .md: {len(orphans)}")
        for vid, paths, msg in orphans[:20]:
            print(f"    {vid} | {msg} | {[p.name for p in paths]}")
        if len(orphans) > 20:
            print(f"    ... y {len(orphans) - 20} más")
    else:
        print("  Ningún .md de YouTube huérfano o en conflicto con failed")
    print()

    # --- YouTube ids in vault but not in any DB row ---
    db_yt_ids = {r["video_id"] for r in rows if r["source_kind"] == "youtube"}
    vault_yt_ids = set(md_by_yt.keys())
    extra_in_vault = vault_yt_ids - db_yt_ids
    if extra_in_vault:
        print(f"--- .md con video_id NO registrado en canal (227): {len(extra_in_vault)} ---")
        for vid in sorted(extra_in_vault)[:15]:
            print(f"    {vid}: {md_by_yt[vid][0].name}")
    print()

    # --- Filename date vs upload_date ---
    print("--- FECHA en nombre de archivo vs frontmatter uploaded_date ---")
    date_mismatch = []
    for p, fm in md_meta.items():
        ud = fm.get("uploaded_date") or fm.get("upload_date") or ""
        if not ud or len(ud) < 10:
            continue
        file_date = p.name[:10]  # YYYY-MM-DD
        upload_date = ud[:10]
        if file_date != upload_date:
            vid = yt_id(fm.get("source_url"))
            date_mismatch.append((p.name, file_date, upload_date, fm.get("title", "")[:50], vid))

    print(f"  Archivos con fecha distinta: {len(date_mismatch)} (puede ser normal si se republicó)")
    for item in date_mismatch[:15]:
        print(f"    {item[0]} | archivo={item[1]} upload={item[2]} | {item[3]}")
    if len(date_mismatch) > 15:
        print(f"    ... y {len(date_mismatch) - 15} más")
    print()

    # --- Local pipeline ---
    print("--- LOCAL (Búho Serpiente): SQLite vs archivo ---")
    local_rows = [r for r in rows if r["source_kind"] == "local"]
    local_ok = local_issues = 0
    for r in local_rows:
        op = r["output_path"]
        if r["status"] == "done":
            if op and Path(op).exists():
                local_ok += 1
            else:
                local_issues += 1
                print(f"    done sin archivo: {r['title']} -> {op}")
        elif r["status"] != "done":
            local_issues += 1
            print(f"    {r['status']}: {r['title']} | {r['source_path']}")
    print(f"  local done OK: {local_ok}/{sum(1 for r in local_rows if r['status']=='done')}")
    print()

    all_yt_with_md = len(vault_yt_ids)
    print("=" * 60)
    print("RESUMEN")
    print(f"  .md en vault (sin _estado): {len(md_files)}")
    print(f"  .md con source_url YouTube: {all_yt_with_md}")
    print(f"  YouTube con transcript real (vault): ~{all_yt_with_md} ids únicos")
    print(f"  SQLite skipped+done con .md verificado: {skip_ok}+{done_ok}")
    print(f"  Faltan (failed en SQLite): {len(failed)}")
    print("=" * 60)
    print()
    check_failed_in_vault_body()
    return 0


def check_failed_in_vault_body() -> None:
    """Check if failed youtube ids appear in any md (alternate source)."""
    conn = sqlite3.connect(DB)
    failed = conn.execute(
        "SELECT video_id, title FROM video_transcript WHERE status='failed' AND source_kind='youtube'"
    ).fetchall()
    conn.close()
    found = []
    for vid, title in failed:
        for p in VAULT.glob("*.md"):
            if p.name.startswith("_estado"):
                continue
            if vid in p.read_text(encoding="utf-8", errors="replace"):
                found.append((vid, title, p.name))
                break
    print("--- FAILED con posible .md bajo otro enlace ---")
    print(f"  {len(found)} de {len(failed)}")
    for vid, title, name in found[:10]:
        print(f"    {vid} -> {name}")


if __name__ == "__main__":
    raise SystemExit(main())
