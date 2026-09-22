"""Podcast episode covers via OpenAI Images (style-reference edits)."""

from __future__ import annotations

import base64
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import requests

from src.podcast_catalog import get_episode, list_episodes
from src.video_transcript_state import open_state, state_db_path

logger = logging.getLogger(__name__)

DEFAULT_OPENAI_BASE = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-image-2.5-flare"
MODEL_FALLBACKS = (
    "gpt-image-2.5-flare",
    "gpt-image-2",
    "gpt-image-1.5",
)
DEFAULT_SIZE = "1024x1024"
DEFAULT_QUALITY = "medium"
DEFAULT_INPUT_FIDELITY = None
IMAGE_TIMEOUT_S = 300

STYLE_REFERENCE_NAME = "academia_blockchain_visual_reference.jpg"

LOCKED_STYLE = """
Match the attached image as a STYLE and COLOR reference only.
Do not copy its composition, character, clothing, headphones, desk, or control-room layout.

Preserve: painterly editorial concept art, visible brushwork, inked technical linework,
mustard-amber against teal-blue, human-centered technology, serious documentary mood,
rich texture and detail on the main subject.

Simplify the composition around ONE dominant subject. Quiet background. Square 1:1 frame.
Leave a clear area for a short word.

No photoreal faces of real people. No logos, watermarks, arrows, UI screenshots,
or YouTube-thumbnail clichés. No extra slogans.
""".strip()


@dataclass(frozen=True)
class CoverSpec:
    episode_id: str
    word: str
    subject: str


COVER_SPECS: tuple[CoverSpec, ...] = (
    CoverSpec(
        "noticias_guerra_cripto_final.mp4",
        "PERSPECTIVA",
        "a lone observer seen from behind at a high window, looking down at a distant conflict; one brass spyglass as the dominant object",
    ),
    CoverSpec(
        "cripta_vs_ancap_final.mp4",
        "CRIPTOANARQUISMO",
        "two opposing stone masks or seals facing each other across a single cracked coin, one object dominating the frame",
    ),
    CoverSpec(
        "skynet_escenario_final3.mp4",
        "SKYNET",
        "a single silent machine-eye / radar dish above an empty city, no crowds, one dominant circular subject",
    ),
    CoverSpec(
        "criptoanarquismo_puro_TE_final.mp4",
        "CRIPTOANARQUISMO",
        "one hooded hands-and-cipher-machine still life: a mechanical encoder as the dominant subject, not a full control room",
    ),
    CoverSpec(
        "Bitcoin_no_NSA_final.mp4",
        "NSA",
        "a single black government seal dissolving into a bitcoin-like coin, one object, no portraits",
    ),
    CoverSpec(
        "guerra_tecnologica_version_publica.mp4",
        "TECNOLOGÍA",
        "one ancient-to-modern artifact hybrid (astrolabe fused with a circuit board) as the sole dominant subject",
    ),
    CoverSpec(
        "Farsa_Ripple_Satoshi_Emails2.mp4",
        "SATOSHI",
        "a single sealed envelope over a glowing mailbox, no faces, one dominant object",
    ),
    CoverSpec(
        "Jhon McAfee final.mp4",
        "MCAFEE",
        "an empty tropical balcony and one abandoned laptop, no likeness of a real person",
    ),
    CoverSpec(
        "epstein_files_btc.mp4",
        "EPSTEIN",
        "a single locked archive box of files with a bitcoin stamp, conceptual only, no people, no graphic content",
    ),
    CoverSpec(
        "ACBC Hechicero_Banco_Dinero_final.mp4",
        "HECHICERO",
        "one alchemical money-press / Faustian vault door as the dominant subject, Bank of England atmosphere without logos",
    ),
    CoverSpec(
        "Debate Derecho Natural.mp4",
        "DERECHO NATURAL",
        "a single carved stone tablet of law under a tree, one dominant object",
    ),
    CoverSpec(
        "Anom Privacidad.mp4",
        "ANOM",
        "one cracked encrypted phone as the dominant subject, conceptual surveillance, no victims",
    ),
    CoverSpec(
        "bch_ian_argentina_final.mp4",
        "CISMA",
        "one coin split cleanly in two, a single fracture as the dominant subject",
    ),
    CoverSpec(
        "Marx Armesilla.mp4",
        "MARXISMO",
        "a red bound book facing a gold coin, one pair as a single composition, no portraits",
    ),
    CoverSpec(
        "entrevista_danilo.mp4",
        "HACKING",
        "the dashboard of one car with a single diagnostic probe plugged in, one dominant vehicle interior",
    ),
    CoverSpec(
        "entrevista_sebastian_cardano.mp4",
        "CARDANO",
        "one architectural Ouroboros-like stone circle / research temple as the dominant subject, no corporate logos",
    ),
    CoverSpec(
        "entrevista_tertulia_x_parte_1.mp4",
        "CRIPTOGRAFÍA",
        "one brass cipher cylinder / Enigma-like machine as the dominant subject",
    ),
    CoverSpec(
        "entrevista_tertulia_x_2da_parte.mp4",
        "OPOSICIÓN",
        "a puppet theater with one figure on strings, the puppet as the dominant subject, no real faces",
    ),
    CoverSpec(
        "andres_f2pool_monero_final.mp4",
        "CENSURA",
        "a mining rig with one transaction-stamp being blocked by a gate, one dominant machine",
    ),
)

SPECS_BY_ID = {spec.episode_id: spec for spec in COVER_SPECS}


def default_covers_dir(repo_root: Path) -> Path:
    return repo_root / "VideosParaPodcast" / "covers"


def default_style_reference(project_root: Path) -> Path:
    return project_root / "assets" / "podcast_covers" / STYLE_REFERENCE_NAME


def build_prompt(spec: CoverSpec, *, title: str) -> str:
    word = " ".join((spec.word or "").split())
    return (
        f"{LOCKED_STYLE}\n\n"
        f"Create a NEW square 1:1 illustration (not a copy of the reference).\n"
        f"Episode idea (do not letter the full title): {title}\n"
        f"One dominant subject: {spec.subject}\n\n"
        f"The only text in the image is this word or short phrase, large, "
        f"exact spelling, editorial lettering integrated into the scene:\n"
        f"{word}\n"
    )


def spec_for_episode(episode: dict[str, Any], *, word_override: str | None = None) -> CoverSpec | None:
    episode_id = episode.get("episode_id") or ""
    spec = SPECS_BY_ID.get(episode_id)
    if spec and not word_override:
        return spec
    word = (word_override or (spec.word if spec else "") or "").strip()
    if not word:
        return None
    subject = spec.subject if spec else f"one symbolic object that captures: {episode.get('title') or episode.get('file_title')}"
    return CoverSpec(episode_id=episode_id, word=word, subject=subject)


def cover_output_path(covers_dir: Path, episode: dict[str, Any]) -> Path:
    stem = Path(episode.get("mp3_filename") or episode.get("episode_id") or "episode").stem
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_", " "} else "_" for ch in stem).strip()
    return covers_dir / f"{safe}.png"


def published_first(episodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def key(item: dict[str, Any]) -> tuple[int, str]:
        pub = item.get("rss_pub_date") or ""
        extracted = item.get("extracted_at") or ""
        return (0 if pub else 1, pub or extracted)

    return sorted(episodes, key=key)


def select_episodes(
    episodes: list[dict[str, Any]],
    *,
    episode_id: str | None = None,
    limit: int | None = None,
    include_unpublished: bool = False,
) -> list[dict[str, Any]]:
    ordered = published_first(episodes)
    if episode_id:
        match = [item for item in ordered if item.get("episode_id") == episode_id]
        if not match:
            raise ValueError(f"Episode not in catalog: {episode_id}")
        return match
    if not include_unpublished:
        ordered = [item for item in ordered if item.get("rss_title")]
    if limit is not None:
        ordered = ordered[: max(0, int(limit))]
    return ordered


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def record_cover(
    conn: Any,
    episode_id: str,
    *,
    cover_path: str | None,
    cover_word: str | None,
    cover_model: str | None,
    cover_status: str,
    cover_error: str | None = None,
    cover_prompt: str | None = None,
) -> None:
    generated_at = _now() if cover_status == "done" else None
    conn.execute(
        """
        UPDATE podcast_episode SET
            cover_path = ?,
            cover_word = ?,
            cover_model = ?,
            cover_status = ?,
            cover_generated_at = COALESCE(?, cover_generated_at),
            cover_error = ?,
            cover_prompt = ?,
            updated_at = ?
        WHERE episode_id = ?
        """,
        (
            cover_path,
            cover_word,
            cover_model,
            cover_status,
            generated_at,
            cover_error,
            cover_prompt,
            _now(),
            episode_id,
        ),
    )
    conn.commit()


def _api_key() -> str:
    key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not key:
        raise ValueError("OPENAI_API_KEY is required for podcast cover generation")
    return key


def _base_url() -> str:
    return (os.getenv("OPENAI_API_BASE") or DEFAULT_OPENAI_BASE).rstrip("/")


def _decode_image_payload(payload: dict[str, Any]) -> bytes:
    rows = payload.get("data") or []
    if not rows:
        raise RuntimeError(f"Images API returned no data: {payload!r}"[:500])
    first = rows[0]
    b64 = first.get("b64_json")
    if b64:
        return base64.b64decode(b64)
    url = first.get("url")
    if url:
        response = requests.get(url, timeout=60)
        response.raise_for_status()
        return response.content
    raise RuntimeError("Images API row had neither b64_json nor url")


def _post_image_edit(
    *,
    prompt: str,
    reference_path: Path,
    model: str,
    size: str,
    quality: str,
    input_fidelity: str | None,
    timeout_s: float,
) -> tuple[bytes, str]:
    key = _api_key()
    url = f"{_base_url()}/images/edits"
    mime = "image/jpeg" if reference_path.suffix.lower() in {".jpg", ".jpeg"} else "image/png"
    data: dict[str, str] = {
        "model": model,
        "prompt": prompt,
        "size": size,
        "quality": quality,
        "n": "1",
        "output_format": "png",
    }
    if input_fidelity:
        data["input_fidelity"] = input_fidelity

    with reference_path.open("rb") as handle:
        files = {"image": (reference_path.name, handle, mime)}
        response = requests.post(
            url,
            headers={"Authorization": f"Bearer {key}"},
            files=files,
            data=data,
            timeout=timeout_s,
        )

    if response.status_code >= 400:
        detail = (response.text or "").strip()[:800]
        raise RuntimeError(f"Images API error {response.status_code} ({model}): {detail}")
    payload = response.json()
    return _decode_image_payload(payload), model


def generate_cover_bytes(
    *,
    prompt: str,
    reference_path: Path,
    model: str = DEFAULT_MODEL,
    size: str = DEFAULT_SIZE,
    quality: str = DEFAULT_QUALITY,
    input_fidelity: str | None = DEFAULT_INPUT_FIDELITY,
    timeout_s: float = IMAGE_TIMEOUT_S,
) -> tuple[bytes, str]:
    if not reference_path.is_file():
        raise FileNotFoundError(f"Style reference not found: {reference_path}")

    models = [model] + [m for m in MODEL_FALLBACKS if m != model]
    sizes = [size]
    if size != "1024x1024":
        sizes.append("1024x1024")
    fidelities: list[str | None] = [input_fidelity, None] if input_fidelity else [None]

    last_err: Optional[Exception] = None
    for candidate_model in models:
        for candidate_size in sizes:
            for fidelity in fidelities:
                try:
                    return _post_image_edit(
                        prompt=prompt,
                        reference_path=reference_path,
                        model=candidate_model,
                        size=candidate_size,
                        quality=quality,
                        input_fidelity=fidelity,
                        timeout_s=timeout_s,
                    )
                except RuntimeError as exc:
                    last_err = exc
                    logger.warning("%s", exc)
                    continue
    raise RuntimeError(str(last_err) if last_err else "Images API failed")


def generate_one(
    conn: Any,
    episode: dict[str, Any],
    *,
    covers_dir: Path,
    reference_path: Path,
    dry_run: bool = False,
    force: bool = False,
    word_override: str | None = None,
    model: str = DEFAULT_MODEL,
    size: str = DEFAULT_SIZE,
    quality: str = DEFAULT_QUALITY,
) -> dict[str, Any]:
    spec = spec_for_episode(episode, word_override=word_override)
    title = episode.get("rss_title") or episode.get("file_title") or episode.get("episode_id")
    output = cover_output_path(covers_dir, episode)
    result: dict[str, Any] = {
        "episode_id": episode.get("episode_id"),
        "title": title,
        "cover_word": spec.word if spec else None,
        "output": str(output),
        "dry_run": dry_run,
    }
    if spec is None:
        result["ok"] = False
        result["skipped"] = True
        result["error"] = "No cover word/spec for this episode"
        return result

    prompt = build_prompt(spec, title=str(title))
    result["prompt"] = prompt
    existing = (episode.get("cover_status") == "done") and output.is_file()
    if existing and not force:
        result["ok"] = True
        result["skipped"] = True
        result["error"] = None
        result["message"] = "Cover already exists (pass --force to regenerate)"
        return result

    if dry_run:
        result["ok"] = True
        result["skipped"] = False
        return result

    covers_dir.mkdir(parents=True, exist_ok=True)
    try:
        image_bytes, used_model = generate_cover_bytes(
            prompt=prompt,
            reference_path=reference_path,
            model=model,
            size=size,
            quality=quality,
        )
        output.write_bytes(image_bytes)
        record_cover(
            conn,
            spec.episode_id,
            cover_path=str(output),
            cover_word=spec.word,
            cover_model=used_model,
            cover_status="done",
            cover_prompt=prompt,
        )
        result["ok"] = True
        result["skipped"] = False
        result["model"] = used_model
        result["bytes"] = len(image_bytes)
        return result
    except Exception as exc:
        record_cover(
            conn,
            spec.episode_id,
            cover_path=None,
            cover_word=spec.word,
            cover_model=model,
            cover_status="failed",
            cover_error=str(exc)[:800],
            cover_prompt=prompt,
        )
        result["ok"] = False
        result["skipped"] = False
        result["error"] = str(exc)
        return result


def generate_covers(
    *,
    project_root: Path,
    repo_root: Path,
    episode_id: str | None = None,
    limit: int | None = None,
    include_unpublished: bool = False,
    dry_run: bool = False,
    force: bool = False,
    word_override: str | None = None,
    model: str = DEFAULT_MODEL,
    size: str = DEFAULT_SIZE,
    quality: str = DEFAULT_QUALITY,
    covers_dir: Path | None = None,
    reference_path: Path | None = None,
) -> dict[str, Any]:
    covers_dir = covers_dir or default_covers_dir(repo_root)
    reference_path = reference_path or default_style_reference(project_root)
    conn = open_state(str(project_root))
    try:
        episodes = select_episodes(
            list_episodes(conn),
            episode_id=episode_id,
            limit=limit,
            include_unpublished=include_unpublished,
        )
        items = []
        for episode in episodes:
            # Re-read so cover_status is current after prior writes.
            fresh = get_episode(conn, episode["episode_id"]) or episode
            item = generate_one(
                conn,
                fresh,
                covers_dir=covers_dir,
                reference_path=reference_path,
                dry_run=dry_run,
                force=force,
                word_override=word_override,
                model=model,
                size=size,
                quality=quality,
            )
            items.append(item)
            if item.get("skipped"):
                logger.info(
                    "Skipped %s: %s",
                    item.get("episode_id"),
                    item.get("message") or item.get("error"),
                )
            elif dry_run:
                logger.info("Dry-run %s (%s)", item.get("episode_id"), item.get("cover_word"))
            elif item.get("ok"):
                logger.info("Cover written %s (%s)", item.get("output"), item.get("cover_word"))
            else:
                logger.error("Failed %s: %s", item.get("episode_id"), item.get("error"))
        return {
            "ok": all(item.get("ok") for item in items) if items else False,
            "dry_run": dry_run,
            "count": len(items),
            "state_db": str(state_db_path(project_root).resolve()),
            "covers_dir": str(covers_dir),
            "reference": str(reference_path),
            "items": items,
        }
    finally:
        conn.close()
