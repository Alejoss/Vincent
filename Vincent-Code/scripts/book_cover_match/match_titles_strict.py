"""
Match estricto: títulos/autores de portadas vs PDFs.

Uso:
  python match_titles_strict.py
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from rapidfuzz import fuzz

OUT_DIR = Path(__file__).resolve().parent / "output"

NOISE = {
    "the",
    "and",
    "del",
    "de",
    "la",
    "las",
    "los",
    "el",
    "un",
    "una",
    "y",
    "en",
    "a",
    "por",
    "para",
    "con",
    "sin",
    "vol",
    "volume",
    "tomo",
    "parte",
    "part",
    "edicion",
    "edition",
    "pdf",
}


def strip_accents(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def normalize(text: str) -> str:
    s = strip_accents(text or "").lower()
    s = s.replace("&", " and ")
    s = re.sub(r"[\[\]\(\)\{\}'’\"«»]", " ", s)
    s = re.sub(r"[_\-.:,;!?/\\]+", " ", s)
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def tokens(text: str) -> set[str]:
    return {t for t in normalize(text).split() if len(t) >= 3 and t not in NOISE}


def author_tokens(text: str) -> set[str]:
    # Keep surnames / significant name parts
    parts = re.split(r"[;,/]| and | y ", text or "", flags=re.I)
    out: set[str] = set()
    for part in parts:
        toks = [t for t in normalize(part).split() if len(t) >= 3 and t not in NOISE]
        if not toks:
            continue
        # last token often surname; also keep first if long
        out.add(toks[-1])
        if len(toks[0]) >= 4:
            out.add(toks[0])
        if len(toks) >= 2:
            out.add(toks[-2]) if len(toks[-2]) >= 4 else None
    return {t for t in out if t}


def title_score(a: str, b: str) -> float:
    na, nb = normalize(a), normalize(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 100.0
    # Strict blend: token_sort primary; token_set secondary but capped influence
    sort_s = fuzz.token_sort_ratio(na, nb)
    set_s = fuzz.token_set_ratio(na, nb)
    partial = fuzz.partial_ratio(na, nb)
    # Penalize huge length mismatch (avoids "Capitalismo" → long unrelated title)
    len_ratio = min(len(na), len(nb)) / max(len(na), len(nb))
    score = 0.55 * sort_s + 0.25 * set_s + 0.20 * partial
    if len_ratio < 0.45:
        score *= 0.75
    # Require meaningful token overlap
    ta, tb = tokens(a), tokens(b)
    if ta and tb:
        overlap = len(ta & tb) / len(ta)
        if overlap < 0.5:
            score *= 0.6
        elif overlap >= 0.8:
            score = min(100.0, score + 5)
    else:
        score *= 0.5
    return float(score)


def author_score(a: str, b: str) -> float:
    aa, bb = author_tokens(a), author_tokens(b)
    if not aa or not bb:
        return -1.0  # unknown
    if aa & bb:
        return 100.0 * len(aa & bb) / max(len(aa), len(bb))
    # fuzzy last-resort on full normalized author strings
    return float(fuzz.token_set_ratio(normalize(a), normalize(b)))


def load_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def is_generic_title(title: str) -> bool:
    """One/two-token or very short titles are dangerous without author."""
    t = tokens(title)
    n = normalize(title)
    return len(t) <= 2 or len(n) < 18


def decide(
    t_score: float,
    a_score: float,
    cover_title: str,
    *,
    auto_title: float,
    review_title: float,
    auto_author: float,
) -> str:
    generic = is_generic_title(cover_title)

    # Generic titles (Educación, Socialismo, Ética…) need strong author + near-exact title
    if generic:
        if a_score >= 80 and t_score >= 97:
            return "auto"
        if a_score >= 80 and t_score >= review_title:
            return "review"
        return "no_match"

    if t_score >= auto_title and (a_score < 0 or a_score >= auto_author):
        # Unknown author OK only for distinctive (non-generic) titles
        return "auto"
    if t_score >= auto_title and 0 <= a_score < auto_author:
        return "review"
    if t_score >= review_title and (a_score < 0 or a_score >= 30):
        return "review"
    return "no_match"


def run(args: argparse.Namespace) -> int:
    covers = load_csv(Path(args.covers))
    pdfs = load_csv(Path(args.pdfs))

    # Prefer richer tables if compact lacks fields
    print(f"Covers: {len(covers)}  PDFs: {len(pdfs)}")

    pdf_index: list[dict] = []
    for p in pdfs:
        title = (p.get("best_title") or p.get("title") or "").strip()
        author = (p.get("best_author") or p.get("author") or "").strip()
        if not title:
            continue
        pdf_index.append(
            {
                "title": title,
                "author": author,
                "filename": p.get("filename") or "",
                "rel_path": p.get("rel_path") or "",
                "abs_path": p.get("abs_path") or "",
                "norm_title": normalize(title),
            }
        )

    results: list[dict] = []
    counts = {"auto": 0, "review": 0, "no_match": 0, "skip_empty": 0}

    for c in covers:
        c_title = (c.get("title") or "").strip()
        c_author = (c.get("author") or "").strip()
        c_file = c.get("filename") or ""
        c_rel = c.get("rel_path") or ""
        c_abs = c.get("abs_path") or ""
        c_conf = c.get("confidence") or ""

        if not c_title:
            counts["skip_empty"] += 1
            results.append(
                {
                    "status": "skip_empty",
                    "title_score": 0,
                    "author_score": "",
                    "cover_file": c_file,
                    "cover_title": "",
                    "cover_author": c_author,
                    "pdf_file": "",
                    "pdf_title": "",
                    "pdf_author": "",
                    "pdf_rel_path": "",
                    "cover_rel_path": c_rel,
                    "cover_abs": c_abs,
                    "pdf_abs": "",
                    "cover_confidence": c_conf,
                    "alt2_pdf": "",
                    "alt2_title_score": "",
                    "alt3_pdf": "",
                    "alt3_title_score": "",
                }
            )
            continue

        scored: list[tuple[float, float, float, dict]] = []
        for p in pdf_index:
            ts = title_score(c_title, p["title"])
            if ts < args.review_title - 5:  # prune
                continue
            as_ = author_score(c_author, p["author"])
            # Combined rank: title dominates; author boosts when known
            rank = ts
            if as_ >= 0:
                if as_ >= 80:
                    rank += 8
                elif as_ < 40:
                    rank -= 12
            scored.append((rank, ts, as_, p))

        scored.sort(key=lambda x: (-x[0], -x[1]))
        top = scored[:3]

        if not top:
            status, ts, as_, best = "no_match", 0.0, -1.0, None
        else:
            _rank, ts, as_, best = top[0]
            status = decide(
                ts,
                as_,
                c_title,
                auto_title=args.auto_title,
                review_title=args.review_title,
                auto_author=args.auto_author,
            )

        counts[status] = counts.get(status, 0) + 1
        results.append(
            {
                "status": status,
                "title_score": round(ts, 1),
                "author_score": "" if as_ < 0 else round(as_, 1),
                "cover_file": c_file,
                "cover_title": c_title,
                "cover_author": c_author,
                "pdf_file": best["filename"] if best else "",
                "pdf_title": best["title"] if best else "",
                "pdf_author": best["author"] if best else "",
                "pdf_rel_path": best["rel_path"] if best else "",
                "cover_rel_path": c_rel,
                "cover_abs": c_abs,
                "pdf_abs": best["abs_path"] if best else "",
                "cover_confidence": c_conf,
                "alt2_pdf": top[1][3]["filename"] if len(top) > 1 else "",
                "alt2_title_score": round(top[1][1], 1) if len(top) > 1 else "",
                "alt3_pdf": top[2][3]["filename"] if len(top) > 2 else "",
                "alt3_title_score": round(top[2][1], 1) if len(top) > 2 else "",
            }
        )

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / f"title_match_strict_{stamp}.csv"
    latest = out_dir / "title_match_strict_latest.csv"
    summary_path = out_dir / "title_match_strict_summary_latest.txt"

    fields = list(results[0].keys()) if results else []
    with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(results)
    latest.write_bytes(csv_path.read_bytes())

    # Also write auto-only and review-only for easy browsing
    for status in ("auto", "review"):
        subset = [r for r in results if r["status"] == status]
        sp = out_dir / f"title_match_strict_{status}_latest.csv"
        with sp.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(subset)

    n = len(covers)
    summary = f"""Match estricto portada ↔ PDF
Covers: {n} | PDFs indexados con título: {len(pdf_index)}
Umbrales: auto_title>={args.auto_title}, review_title>={args.review_title}, auto_author>={args.auto_author}

  AUTO:       {counts.get('auto', 0)}
  REVIEW:     {counts.get('review', 0)}
  NO_MATCH:   {counts.get('no_match', 0)}
  SKIP_EMPTY: {counts.get('skip_empty', 0)}

CSV: {latest}
"""
    summary_path.write_text(summary, encoding="utf-8")
    (out_dir / f"title_match_strict_{stamp}.json").write_text(
        json.dumps({"counts": counts, "thresholds": vars(args)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(summary)
    print("--- AUTO samples ---")
    for r in [x for x in results if x["status"] == "auto"][:12]:
        print(f"  [{r['title_score']}|a={r['author_score']}] {r['cover_title'][:50]}")
        print(f"       -> {r['pdf_title'][:60]}  ({r['pdf_file'][:50]})")
    print("--- REVIEW samples ---")
    for r in [x for x in results if x["status"] == "review"][:8]:
        print(f"  [{r['title_score']}|a={r['author_score']}] {r['cover_title'][:50]}")
        print(f"       -> {r['pdf_title'][:60]}  ({r['pdf_file'][:50]})")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--covers",
        default=str(OUT_DIR / "cover_title_table_latest.csv"),
    )
    p.add_argument(
        "--pdfs",
        default=str(OUT_DIR / "pdf_title_table_latest.csv"),
    )
    p.add_argument("--out", default=str(OUT_DIR))
    p.add_argument("--auto-title", type=float, default=92.0)
    p.add_argument("--review-title", type=float, default=85.0)
    p.add_argument("--auto-author", type=float, default=50.0)
    return p


if __name__ == "__main__":
    sys.exit(run(build_parser().parse_args()))
