"""Local podcast MP3 catalog + RSS (Spotify/Anchor) enrichment."""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Optional

import feedparser

from src.video_transcript_state import local_video_id, open_state, state_db_path

logger = logging.getLogger(__name__)

LEGACY_JSON_NAME = "_estado_podcast.json"
DEFAULT_RSS_URL = "https://anchor.fm/s/114269ac0/podcast/rss"
NEAR_SIZE_BYTES = 2048

# filename stem -> distinctive phrases in RSS title/summary
FILENAME_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("andres_f2pool_monero_final", ("f2pool", "anhdres", "censura en bitcoin")),
    ("entrevista_tertulia_x_2da_parte", ("oposicion controlada", "conspiracion")),
    ("entrevista_tertulia_x_parte_1", ("1 parte", "nuestra defensa")),
    ("entrevista_sebastian_cardano", ("cardano", "sebastian")),
    ("entrevista_danilo", ("car hacking", "reverseeverything", "reverse everything")),
    ("marx armesilla", ("armesilla", "marxismo vs bitcoin")),
    ("bch_ian_argentina_final", ("laeconomiap2p", "economia p2p", "cisma")),
    ("anom privacidad", ("anom",)),
    ("debate derecho natural", ("derecho natural",)),
    ("acbc hechicero_banco_dinero_final", ("hechicero", "banco de inglaterra")),
    ("epstein_files_btc", ("epstein",)),
    ("jhon mcafee final", ("mcafee",)),
    ("farsa_ripple_satoshi_emails2", ("satoshi", "malmi", "schwartz")),
    ("guerra_tecnologica_version_publica", ("historia oculta",)),
    ("bitcoin_no_nsa_final", ("nsa",)),
    ("criptoanarquismo_puro_te_final", ("criptoanarquismo puro",)),
    ("skynet_escenario_final3", ("skynet",)),
    ("noticias_guerra_cripto_final", ("perspectiva", "seleccion de noticias")),
    ("cripta_vs_ancap_final", ("anarcocapitalismo",)),
)

_STOP = frozenset(
    {
        "final",
        "version",
        "publica",
        "entrevista",
        "podcast",
        "parte",
        "conversacion",
        "historia",
        "bitcoin",
        "sobre",
        "como",
        "para",
        "este",
        "esta",
        "episodio",
    }
)


def default_catalog_dir(repo_root: Path) -> Path:
    return repo_root / "VideosParaPodcast"


def legacy_json_path(catalog_dir: Path) -> Path:
    return catalog_dir / LEGACY_JSON_NAME


def _mtime_iso(path: Path) -> str:
    ts = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return ts.isoformat()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_item(row: Any) -> dict[str, Any]:
    data = dict(row)
    data["title"] = data.get("rss_title") or data.get("file_title")
    data["video"] = data.get("video_filename")
    data["mp3"] = data.get("mp3_filename")
    data["processed_at"] = data.get("extracted_at")
    data["skipped"] = bool(data.get("skipped"))
    return data


def get_episode(conn: Any, episode_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM podcast_episode WHERE episode_id = ?",
        (episode_id,),
    ).fetchone()
    return _row_to_item(row) if row else None


def list_episodes(conn: Any) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM podcast_episode ORDER BY COALESCE(rss_pub_date, extracted_at, updated_at)"
    ).fetchall()
    return [_row_to_item(row) for row in rows]


def get_meta(conn: Any, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM podcast_meta WHERE key = ?", (key,)).fetchone()
    if not row:
        return default
    return row["value"]


def set_meta(conn: Any, key: str, value: str) -> None:
    conn.execute(
        """
        INSERT INTO podcast_meta (key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (key, value),
    )


def _link_video_id(conn: Any, source_path: str | None) -> str | None:
    if not source_path:
        return None
    path = Path(source_path)
    if not path.is_file():
        return None
    video_id = local_video_id(path)
    row = conn.execute(
        "SELECT video_id FROM video_transcript WHERE video_id = ?",
        (video_id,),
    ).fetchone()
    return video_id if row else None


def _upsert_episode(conn: Any, episode_id: str, fields: dict[str, Any]) -> None:
    existing = get_episode(conn, episode_id) or {}
    merged = {**existing, **{k: v for k, v in fields.items() if v is not None}}
    conn.execute(
        """
        INSERT INTO podcast_episode (
            episode_id, file_title, video_filename, source_path, mp3_filename, mp3_path,
            status, skipped, extracted_at, error, folder,
            rss_guid, rss_title, rss_pub_date, rss_link, rss_duration,
            rss_enclosure_bytes, rss_match, video_id, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(episode_id) DO UPDATE SET
            file_title = excluded.file_title,
            video_filename = excluded.video_filename,
            source_path = COALESCE(excluded.source_path, podcast_episode.source_path),
            mp3_filename = COALESCE(excluded.mp3_filename, podcast_episode.mp3_filename),
            mp3_path = COALESCE(excluded.mp3_path, podcast_episode.mp3_path),
            status = excluded.status,
            skipped = excluded.skipped,
            extracted_at = COALESCE(excluded.extracted_at, podcast_episode.extracted_at),
            error = excluded.error,
            folder = COALESCE(excluded.folder, podcast_episode.folder),
            rss_guid = COALESCE(excluded.rss_guid, podcast_episode.rss_guid),
            rss_title = COALESCE(excluded.rss_title, podcast_episode.rss_title),
            rss_pub_date = COALESCE(excluded.rss_pub_date, podcast_episode.rss_pub_date),
            rss_link = COALESCE(excluded.rss_link, podcast_episode.rss_link),
            rss_duration = COALESCE(excluded.rss_duration, podcast_episode.rss_duration),
            rss_enclosure_bytes = COALESCE(excluded.rss_enclosure_bytes, podcast_episode.rss_enclosure_bytes),
            rss_match = COALESCE(excluded.rss_match, podcast_episode.rss_match),
            video_id = COALESCE(excluded.video_id, podcast_episode.video_id),
            updated_at = excluded.updated_at
        """,
        (
            episode_id,
            merged.get("file_title") or Path(episode_id).stem,
            merged.get("video_filename") or merged.get("video") or episode_id,
            merged.get("source_path"),
            merged.get("mp3_filename") or merged.get("mp3"),
            merged.get("mp3_path"),
            merged.get("status") or "done",
            1 if merged.get("skipped") else 0,
            merged.get("extracted_at") or merged.get("processed_at"),
            merged.get("error"),
            merged.get("folder"),
            merged.get("rss_guid"),
            merged.get("rss_title"),
            merged.get("rss_pub_date"),
            merged.get("rss_link"),
            merged.get("rss_duration"),
            merged.get("rss_enclosure_bytes"),
            merged.get("rss_match"),
            merged.get("video_id"),
            _now(),
        ),
    )


def record_item(
    conn: Any,
    video: Path,
    *,
    status: str,
    mp3: Path | None = None,
    error: str | None = None,
    skipped: bool = False,
    source_path: Path | str | None = None,
) -> None:
    episode_id = video.name
    existing = get_episode(conn, episode_id) or {}
    extracted_at = _now()
    if skipped and existing.get("extracted_at"):
        extracted_at = existing["extracted_at"]
    elif skipped and mp3 and mp3.is_file():
        extracted_at = _mtime_iso(mp3)
    src = str(source_path) if source_path is not None else existing.get("source_path")
    _upsert_episode(
        conn,
        episode_id,
        {
            "file_title": video.stem,
            "video_filename": video.name,
            "source_path": src,
            "mp3_filename": mp3.name if mp3 else existing.get("mp3_filename"),
            "mp3_path": str(mp3) if mp3 else existing.get("mp3_path"),
            "status": status,
            "skipped": skipped,
            "extracted_at": extracted_at,
            "error": error,
            "rss_guid": existing.get("rss_guid"),
            "rss_title": existing.get("rss_title"),
            "rss_pub_date": existing.get("rss_pub_date"),
            "rss_link": existing.get("rss_link"),
            "rss_duration": existing.get("rss_duration"),
            "rss_enclosure_bytes": existing.get("rss_enclosure_bytes"),
            "rss_match": existing.get("rss_match"),
            "folder": existing.get("folder"),
            "video_id": existing.get("video_id") or _link_video_id(conn, src),
        },
    )
    conn.commit()


def normalize_text(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", value or "")
    stripped = "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")
    stripped = stripped.replace("\u200b", "")
    return re.sub(r"[^a-z0-9]+", " ", stripped.lower()).strip()


def _tokens(value: str) -> set[str]:
    return {tok for tok in normalize_text(value).split() if len(tok) >= 4 and tok not in _STOP}


def parse_rss_episodes(source: str) -> list[dict[str, Any]]:
    feed = feedparser.parse(source)
    episodes: list[dict[str, Any]] = []
    for entry in feed.entries:
        enclosure = {}
        if entry.get("enclosures"):
            enclosure = entry.enclosures[0]
        pub_raw = entry.get("published") or entry.get("updated") or ""
        pub_iso = None
        if pub_raw:
            try:
                pub_iso = parsedate_to_datetime(pub_raw).astimezone(timezone.utc).isoformat()
            except (TypeError, ValueError, OverflowError):
                pub_iso = pub_raw
        length_raw = enclosure.get("length")
        try:
            enclosure_bytes = int(length_raw) if length_raw not in (None, "") else None
        except (TypeError, ValueError):
            enclosure_bytes = None
        title = (entry.get("title") or "").replace("\u200b", "").strip()
        summary = (entry.get("summary") or entry.get("description") or "").strip()
        episodes.append(
            {
                "rss_title": title,
                "rss_pub_date": pub_iso,
                "rss_link": entry.get("link") or "",
                "rss_guid": (entry.get("id") or entry.get("guid") or "").strip(),
                "rss_duration": (entry.get("itunes_duration") or "").strip() or None,
                "rss_enclosure_bytes": enclosure_bytes,
                "rss_summary": summary,
                "_blob": f"{title} {summary}",
            }
        )
    return episodes


def _hint_hit(stem: str, episode: dict[str, Any]) -> bool:
    stem_n = normalize_text(stem)
    blob = normalize_text(episode.get("_blob") or "")
    for key, phrases in FILENAME_HINTS:
        key_n = normalize_text(key)
        if key_n != stem_n and key_n not in stem_n:
            continue
        if any(normalize_text(phrase) in blob for phrase in phrases):
            return True
    return False


def match_episodes(
    episodes: list[dict[str, Any]],
    locals_: list[dict[str, Any]],
) -> list[tuple[dict[str, Any], dict[str, Any], str]]:
    """Return (episode, local, reason) pairs. Each episode/local used at most once."""
    remaining_eps = list(episodes)
    remaining_locs = {item["stem"]: item for item in locals_}
    pairs: list[tuple[dict[str, Any], dict[str, Any], str]] = []

    def take(ep: dict[str, Any], loc: dict[str, Any], reason: str) -> None:
        pairs.append((ep, loc, reason))
        remaining_eps.remove(ep)
        remaining_locs.pop(loc["stem"], None)

    for ep in list(remaining_eps):
        size = ep.get("rss_enclosure_bytes")
        if not size:
            continue
        exact = [loc for loc in remaining_locs.values() if loc.get("size") == size]
        if len(exact) == 1:
            take(ep, exact[0], "size_exact")

    for ep in list(remaining_eps):
        size = ep.get("rss_enclosure_bytes")
        if not size:
            continue
        near = [
            loc
            for loc in remaining_locs.values()
            if loc.get("size") is not None and abs(int(loc["size"]) - int(size)) <= NEAR_SIZE_BYTES
        ]
        if len(near) == 1:
            take(ep, near[0], "size_near")

    for ep in list(remaining_eps):
        hits = [loc for loc in remaining_locs.values() if _hint_hit(loc["stem"], ep)]
        if len(hits) == 1:
            take(ep, hits[0], "filename_hint")

    for ep in list(remaining_eps):
        rss_tokens = _tokens(ep.get("_blob") or "")
        scored: list[tuple[int, dict[str, Any]]] = []
        for loc in remaining_locs.values():
            overlap = rss_tokens & _tokens(loc["stem"])
            if overlap:
                scored.append((len(overlap), loc))
        scored.sort(key=lambda row: row[0], reverse=True)
        if len(scored) == 1 or (len(scored) >= 2 and scored[0][0] > scored[1][0] and scored[0][0] >= 1):
            if scored[0][0] >= 1:
                take(ep, scored[0][1], "token_overlap")

    return pairs


def list_local_mp3s(mp3_dir: Path) -> list[dict[str, Any]]:
    if not mp3_dir.is_dir():
        return []
    items = []
    for path in sorted(mp3_dir.glob("*.mp3")):
        items.append(
            {
                "stem": path.stem,
                "mp3": path.name,
                "path": path,
                "size": path.stat().st_size,
                "processed_at": _mtime_iso(path),
            }
        )
    return items


def _guess_source_path(catalog_dir: Path, stem: str, existing: dict[str, Any]) -> Optional[str]:
    if existing.get("source_path"):
        return str(existing["source_path"])
    local_video = catalog_dir / f"{stem}.mp4"
    if local_video.is_file():
        return None
    patreon = Path("E:/Patreon") / f"{stem}.mp4"
    if patreon.is_file():
        return str(patreon)
    return None


def ingest_local_mp3s(conn: Any, catalog_dir: Path, mp3_dir: Path) -> int:
    added = 0
    for local in list_local_mp3s(mp3_dir):
        episode_id = f"{local['stem']}.mp4"
        existing = get_episode(conn, episode_id)
        src = _guess_source_path(catalog_dir, local["stem"], existing or {})
        if existing:
            _upsert_episode(
                conn,
                episode_id,
                {
                    "file_title": existing.get("file_title") or local["stem"],
                    "video_filename": episode_id,
                    "mp3_filename": existing.get("mp3_filename") or local["mp3"],
                    "mp3_path": existing.get("mp3_path") or str(local["path"]),
                    "status": existing.get("status") or "done",
                    "skipped": existing.get("skipped"),
                    "extracted_at": existing.get("extracted_at") or local["processed_at"],
                    "source_path": src,
                    "video_id": existing.get("video_id") or _link_video_id(conn, src),
                    "rss_guid": existing.get("rss_guid"),
                    "rss_title": existing.get("rss_title"),
                    "rss_pub_date": existing.get("rss_pub_date"),
                    "rss_link": existing.get("rss_link"),
                    "rss_duration": existing.get("rss_duration"),
                    "rss_enclosure_bytes": existing.get("rss_enclosure_bytes"),
                    "rss_match": existing.get("rss_match"),
                    "folder": existing.get("folder"),
                },
            )
            continue
        _upsert_episode(
            conn,
            episode_id,
            {
                "file_title": local["stem"],
                "video_filename": episode_id,
                "mp3_filename": local["mp3"],
                "mp3_path": str(local["path"]),
                "status": "done",
                "skipped": False,
                "extracted_at": local["processed_at"],
                "source_path": src,
                "video_id": _link_video_id(conn, src),
            },
        )
        added += 1
    conn.commit()
    return added


def apply_rss_matches(
    conn: Any,
    pairs: list[tuple[dict[str, Any], dict[str, Any], str]],
) -> int:
    updated = 0
    for episode, local, reason in pairs:
        episode_id = f"{local['stem']}.mp4"
        existing = get_episode(conn, episode_id) or {}
        _upsert_episode(
            conn,
            episode_id,
            {
                "file_title": existing.get("file_title") or local["stem"],
                "video_filename": episode_id,
                "mp3_filename": local["mp3"],
                "mp3_path": str(local.get("path") or existing.get("mp3_path") or ""),
                "status": existing.get("status") or "done",
                "skipped": existing.get("skipped"),
                "extracted_at": existing.get("extracted_at") or local.get("processed_at"),
                "source_path": existing.get("source_path"),
                "folder": existing.get("folder"),
                "video_id": existing.get("video_id"),
                "rss_guid": episode["rss_guid"],
                "rss_title": episode["rss_title"],
                "rss_pub_date": episode["rss_pub_date"],
                "rss_link": episode["rss_link"],
                "rss_duration": episode["rss_duration"],
                "rss_enclosure_bytes": episode["rss_enclosure_bytes"],
                "rss_match": reason,
            },
        )
        updated += 1
    conn.commit()
    return updated


def migrate_legacy_json(conn: Any, catalog_dir: Path) -> int:
    """One-shot import of VideosParaPodcast/_estado_podcast.json into SQLite."""
    count = conn.execute("SELECT COUNT(*) AS n FROM podcast_episode").fetchone()["n"]
    path = legacy_json_path(catalog_dir)
    if count or not path.is_file():
        return 0
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("No se pudo leer JSON legado %s: %s", path, exc)
        return 0
    items = data.get("items") or {}
    imported = 0
    for episode_id, raw in items.items():
        _upsert_episode(
            conn,
            episode_id,
            {
                "file_title": Path(str(raw.get("video") or episode_id)).stem,
                "video_filename": raw.get("video") or episode_id,
                "source_path": raw.get("source_path"),
                "mp3_filename": raw.get("mp3"),
                "status": raw.get("status") or "done",
                "skipped": raw.get("skipped"),
                "extracted_at": raw.get("processed_at"),
                "error": raw.get("error"),
                "folder": raw.get("folder"),
                "rss_guid": raw.get("rss_guid"),
                "rss_title": raw.get("rss_title"),
                "rss_pub_date": raw.get("rss_pub_date"),
                "rss_link": raw.get("rss_link"),
                "rss_duration": raw.get("rss_duration"),
                "rss_enclosure_bytes": raw.get("rss_enclosure_bytes"),
                "rss_match": raw.get("rss_match"),
            },
        )
        imported += 1
    if data.get("rss_url"):
        set_meta(conn, "rss_url", str(data["rss_url"]))
    conn.commit()
    logger.info("Migrated %s podcast rows from %s into SQLite", imported, path)
    return imported


def write_catalog_markdown(
    conn: Any,
    output_path: Path,
    *,
    project_root: Path,
    rss_url: str,
) -> Path:
    """Derived human export. SQLite remains the source of truth."""
    db = state_db_path(project_root)
    items = list_episodes(conn)
    published = [item for item in items if item.get("rss_pub_date")]
    unpublished = [item for item in items if not item.get("rss_pub_date")]
    published.sort(key=lambda item: item.get("rss_pub_date") or "")
    unpublished.sort(key=lambda item: item.get("extracted_at") or "")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines = [
        "---",
        'title: "Catálogo de podcasts (export)"',
        f'updated_at: "{now}"',
        f'rss: "{rss_url}"',
        "tags: [podcast, publicacion, mp3, rss]",
        "---",
        "",
        "# Catálogo de podcasts",
        "",
        "Fuente de verdad (no editar a mano):",
        f"`{db.resolve()}` · tabla `podcast_episode`",
        "",
        "Este markdown es un **export derivado**. Regenerar:",
        "",
        "```powershell",
        "cd E:\\Vincent\\Vincent-Code",
        ".\\venv\\Scripts\\python.exe scripts\\sync_podcast_rss.py",
        "```",
        "",
        f"RSS: {rss_url}",
        "",
        f"## Publicados en Spotify ({len(published)})",
        "",
        "| # | Publicado | Título Spotify | MP3 local | Extraído | Duración |",
        "|---|-----------|----------------|-----------|----------|----------|",
    ]
    for idx, item in enumerate(published, start=1):
        pub = (item.get("rss_pub_date") or "")[:10]
        extracted = (item.get("extracted_at") or "")[:10]
        title = (item.get("rss_title") or item.get("file_title") or "").replace("|", "\\|")
        mp3 = item.get("mp3_filename") or ""
        duration = item.get("rss_duration") or ""
        lines.append(f"| {idx} | {pub} | {title} | `{mp3}` | {extracted} | {duration} |")
    lines.extend(
        [
            "",
            f"## Extraídos, aún no en el RSS ({len(unpublished)})",
            "",
            "| MP3 local | Extraído | Fuente |",
            "|-----------|----------|--------|",
        ]
    )
    for item in unpublished:
        extracted = (item.get("extracted_at") or "")[:10]
        mp3 = item.get("mp3_filename") or ""
        src = item.get("source_path") or "VideosParaPodcast/"
        lines.append(f"| `{mp3}` | {extracted} | `{src}` |")
    lines.append("")
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def sync_from_rss(
    catalog_dir: Path,
    *,
    project_root: Path,
    rss_url: str = DEFAULT_RSS_URL,
    mp3_dir: Path | None = None,
    rss_source: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    mp3_dir = mp3_dir or (catalog_dir / "mp3")
    episodes = parse_rss_episodes(rss_source or rss_url)
    locals_ = list_local_mp3s(mp3_dir)
    pairs = match_episodes(episodes, locals_)
    matched_stems = {loc["stem"] for _, loc, _ in pairs}
    matched_ids = {(p[0].get("rss_guid") or p[0]["rss_title"]) for p in pairs}
    unmatched_rss = [
        ep["rss_title"]
        for ep in episodes
        if (ep.get("rss_guid") or ep["rss_title"]) not in matched_ids
    ]
    unmatched_local = [item["mp3"] for item in locals_ if item["stem"] not in matched_stems]
    summary = {
        "ok": True,
        "dry_run": dry_run,
        "rss_url": rss_url,
        "rss_episodes": len(episodes),
        "local_mp3s": len(locals_),
        "matched": len(pairs),
        "added_local": 0,
        "migrated_json": 0,
        "unmatched_rss": unmatched_rss,
        "unmatched_local": unmatched_local,
        "state_db": str(state_db_path(project_root).resolve()),
        "markdown_export": None,
        "matches": [
            {
                "mp3": loc["mp3"],
                "rss_title": ep["rss_title"],
                "rss_pub_date": ep["rss_pub_date"],
                "reason": reason,
            }
            for ep, loc, reason in pairs
        ],
    }
    if dry_run:
        return summary

    conn = open_state(str(project_root))
    try:
        summary["migrated_json"] = migrate_legacy_json(conn, catalog_dir)
        summary["added_local"] = ingest_local_mp3s(conn, catalog_dir, mp3_dir)
        apply_rss_matches(conn, pairs)
        set_meta(conn, "rss_url", rss_url)
        set_meta(conn, "last_sync_at", _now())
        conn.commit()
        markdown_path = write_catalog_markdown(
            conn,
            catalog_dir / "orden-publicacion.md",
            project_root=project_root,
            rss_url=rss_url,
        )
        summary["markdown_export"] = str(markdown_path)
        legacy = legacy_json_path(catalog_dir)
        if legacy.is_file():
            legacy.unlink()
            logger.info("Removed legacy JSON source %s", legacy)
        return summary
    finally:
        conn.close()
