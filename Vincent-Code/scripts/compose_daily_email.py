"""
Compose daily email from Vincent Notion database following plan_inicial_emails_diarios.
Output: subject + body to file. Use --send to also send via SMTP (once per day when run at startup).

Env vars for --send (optional): SMTP_HOST, SMTP_PORT (default 587), SMTP_USER,
SMTP_PASSWORD or EMAIL_APP_PASSWORD, EMAIL_FROM, EMAIL_TO.
Gmail: smtp.gmail.com, app password from myaccount.google.com/apppasswords.
Outlook: smtp.office365.com, app password from account.microsoft.com if 2FA.
"""

import argparse
import os
import re
import smtplib
import sys
from datetime import datetime
from email.mime.text import MIMEText

# Paths
SCRIPTS_DIR = os.path.dirname(__file__)
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPTS_DIR, ".."))
PARENT_ROOT = os.path.dirname(PROJECT_ROOT)
EMAILS_ROOT = os.path.join(PARENT_ROOT, "emails")

# Project root on path
sys.path.insert(0, PROJECT_ROOT)

from dotenv import load_dotenv

load_dotenv(override=True)

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from src.notion_vincent import VincentNotionClient, normalize_id, NOTION_VINCENT_DATABASE_ID
from src.email_daily_config import parse_plan_md, build_section_query, WEEKDAY_NAMES

# Day short names for subject: Lun, Mar, Mié, Jue, Vie
DAY_SHORT = ["Lun", "Mar", "Mié", "Jue", "Vie"]

MAX_BULLETS_TOTAL = 7
MAX_BULLETS_PER_SECTION = 3

# Path to plan MD (section 3 config)
DEFAULT_PLAN_MD = os.path.join(PROJECT_ROOT, "plan_inicial_emails_diarios.md")

# Marker file for "only one send per day" (project root)
LAST_SENT_DATE_FILE = os.path.join(PROJECT_ROOT, ".last_sent_date")


def get_weekday_config(plan_md_path: str, date: datetime) -> tuple:
    """Return (focus_title, sections list) for the date's weekday. Monday=0."""
    config = parse_plan_md(plan_md_path)
    weekday_index = date.weekday()  # 0=Monday
    if weekday_index > 4:
        weekday_index = 0
    day_config = config.get(weekday_index, {})
    focus_title = day_config.get("focus_title") or WEEKDAY_NAMES[weekday_index]
    sections = day_config.get("sections") or []
    return focus_title, sections


def _normalize_text(s: str) -> str:
    """Lowercase, collapse spaces, strip — for duplicate detection."""
    if not s:
        return ""
    return " ".join((s or "").lower().split())


def _normalize_word(w: str) -> str:
    """Strip punctuation for consistent first-words key."""
    return re.sub(r"[^\w\u00c0-\u024f]", "", (w or "").lower())


def _first_n_words(text: str, n: int) -> str:
    """First n words of normalized text (words stripped of punctuation for matching)."""
    words = _normalize_text(text).split()
    words = [_normalize_word(w) for w in words if _normalize_word(w)]
    return " ".join(words[:n]) if words else ""


def _is_duplicate_content(
    new_text: str,
    seen_normalized: set,
    seen_first_words: set,
    min_len: int = 15,
    first_words_n: int = 2,
    min_len_for_first_words: int = 35,
) -> bool:
    """True if new_text is duplicate of any seen (exact, substring, or same topic by first words)."""
    n = _normalize_text(new_text)
    if len(n) < min_len:
        return n in seen_normalized
    if n in seen_normalized:
        return True
    for seen in seen_normalized:
        if len(seen) < min_len:
            continue
        if n in seen or seen in n:
            return True
    # Same topic: first N words match and both texts long enough (evita fusionar títulos muy cortos)
    if len(n) >= min_len_for_first_words:
        key = _first_n_words(new_text, first_words_n)
        if key and len(key) >= 5 and key in seen_first_words:
            return True
    return False


def _get_smtp_config():
    """Return (host, port, user, password, from_addr, to_addr) or None if any required var missing."""
    host = os.getenv("SMTP_HOST")
    port_str = os.getenv("SMTP_PORT", "587")
    user = os.getenv("SMTP_USER") or os.getenv("EMAIL_USER")
    password = os.getenv("SMTP_PASSWORD") or os.getenv("EMAIL_APP_PASSWORD")
    from_addr = os.getenv("EMAIL_FROM")
    to_addr = os.getenv("EMAIL_TO")
    if not all([host, user, password, from_addr, to_addr]):
        return None
    try:
        port = int(port_str)
    except ValueError:
        port = 587
    return (host, port, user, password, from_addr, to_addr)


def _already_sent_today(date_str: str) -> bool:
    """True if .last_sent_date exists and contains date_str."""
    path = os.path.abspath(LAST_SENT_DATE_FILE)
    if not os.path.isfile(path):
        return False
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip() == date_str
    except Exception:
        return False


def _mark_sent_today(date_str: str) -> None:
    """Write date_str to .last_sent_date."""
    path = os.path.abspath(LAST_SENT_DATE_FILE)
    with open(path, "w", encoding="utf-8") as f:
        f.write(date_str)


def _send_email(subject: str, body: str) -> bool:
    """Send email via SMTP. Returns True on success."""
    cfg = _get_smtp_config()
    if not cfg:
        return False
    host, port, user, password, from_addr, to_addr = cfg
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_addr
    try:
        with smtplib.SMTP(host, port) as server:
            server.starttls()
            server.login(user, password)
            server.sendmail(from_addr, [to_addr], msg.as_string())
        return True
    except Exception as e:
        print(f"SMTP error: {e}", file=sys.stderr)
        return False


def format_bullet(item_dict: dict, emoji: str = "•") -> str:
    """One line: • emoji {Resumen or Item} — ({Estado}) link"""
    text = (item_dict.get("resumen") or "").strip() or (item_dict.get("item") or "").strip()
    estado = (item_dict.get("estado") or "").strip()
    url = (item_dict.get("url") or "").strip()
    part = f"{emoji} {text} — ({estado})" if estado else f"{emoji} {text}"
    if url:
        part += f" {url}"
    return part


def main():
    parser = argparse.ArgumentParser(description="Compose daily email from Vincent Notion DB")
    parser.add_argument("--date", default=None, help="Date YYYY-MM-DD (default: today)")
    parser.add_argument("--output", default=None, help="Output file path (default: parent 'emails' folder, email_diario_YYYY-MM-DD.txt)")
    parser.add_argument("--plan-md", default=DEFAULT_PLAN_MD, help="Path to plan_inicial_emails_diarios.md")
    parser.add_argument("--no-hecho", action="store_true", default=True, help="Exclude Hecho (default: true)")
    parser.add_argument("--schema", action="store_true", help="Only print Vincent DB schema (property names) and exit")
    parser.add_argument("--send", action="store_true", help="Send email via SMTP (requires SMTP_* and EMAIL_* in .env). At most once per day.")
    args = parser.parse_args()

    api_token = os.getenv("NOTION_API_TOKEN")
    db_id = os.getenv("NOTION_VINCENT_DATABASE_ID") or NOTION_VINCENT_DATABASE_ID
    if not api_token:
        print("NOTION_API_TOKEN not set (e.g. in .env)", file=sys.stderr)
        sys.exit(1)

    if args.schema:
        client = VincentNotionClient(api_token=api_token, database_id=db_id)
        names = client.get_vincent_property_names()
        for k, v in names.items():
            print(f"  {k}: {v.get('name')!r} (type={v.get('type')})")
        return

    if args.date:
        try:
            date = datetime.strptime(args.date, "%Y-%m-%d")
        except ValueError:
            print("Invalid --date; use YYYY-MM-DD", file=sys.stderr)
            sys.exit(1)
    else:
        date = datetime.now()

    # Load config for this weekday
    focus_title, sections = get_weekday_config(args.plan_md, date)
    if not sections:
        print("No sections for this weekday; check plan MD section 3.", file=sys.stderr)

    client = VincentNotionClient(api_token=api_token, database_id=db_id)
    prop_names = client.get_vincent_property_names()

    date_str = date.strftime("%Y-%m-%d")
    weekday_index = min(date.weekday(), 4)
    day_short = DAY_SHORT[weekday_index]

    subject = f"[{day_short}] {focus_title} — {date_str}"

    body_lines = [focus_title, ""]
    bullets_used = 0
    seen_urls = set()
    seen_content_normalized = set()
    seen_first_words = set()  # first N words of each seen text (for same-topic dedup)

    for sec in sections:
        if bullets_used >= MAX_BULLETS_TOTAL:
            break
        label = sec.get("label", "")
        emoji = sec.get("emoji", "•")
        limit = min(sec.get("limit", 3), MAX_BULLETS_PER_SECTION, MAX_BULLETS_TOTAL - bullets_used)
        filter_obj, sorts, page_size = build_section_query(
            label, limit, prop_names, exclude_hecho=args.no_hecho, date_window_days=7
        )
        page_size = min(page_size, MAX_BULLETS_PER_SECTION, MAX_BULLETS_TOTAL - bullets_used)
        results = client.query(filter_obj=filter_obj if filter_obj else None, sorts=sorts, page_size=page_size)
        items = [client.page_to_item(p) for p in results[:page_size]]
        if not items:
            continue
        section_bullets = []
        for it in items:
            if bullets_used >= MAX_BULLETS_TOTAL:
                break
            url = (it.get("url") or "").strip()
            content_text = (it.get("resumen") or "").strip() or (it.get("item") or "").strip()
            if url and url in seen_urls:
                continue
            if _is_duplicate_content(content_text, seen_content_normalized, seen_first_words):
                continue
            section_bullets.append(format_bullet(it, emoji))
            if url:
                seen_urls.add(url)
            if content_text:
                norm = _normalize_text(content_text)
                seen_content_normalized.add(norm)
                fw = _first_n_words(content_text, 2)
                if len(fw) >= 5:
                    seen_first_words.add(fw)
            bullets_used += 1
        if section_bullets:
            body_lines.append(f"**{label}**")
            body_lines.extend(section_bullets)
            body_lines.append("")

    body = "\n".join(body_lines).strip()

    if args.output:
        out_path = args.output
    else:
        out_path = os.path.join(EMAILS_ROOT, f"email_diario_{date_str}.txt")

    out_content = f"Subject: {subject}\n\n{body}\n"
    out_dir = os.path.dirname(out_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(out_content)
    print(f"Wrote: {out_path}")
    print(f"Subject: {subject}")

    if args.send:
        if _already_sent_today(date_str):
            print("Ya enviado hoy; no se vuelve a enviar.")
            return
        if not _get_smtp_config():
            print("--send requiere SMTP_HOST, SMTP_USER, SMTP_PASSWORD (o EMAIL_APP_PASSWORD), EMAIL_FROM, EMAIL_TO en .env", file=sys.stderr)
            sys.exit(1)
        if _send_email(subject, body):
            _mark_sent_today(date_str)
            print("Email enviado.")
        else:
            sys.exit(1)


if __name__ == "__main__":
    main()
