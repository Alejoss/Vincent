"""Markdown newsletter → HTML and plain text for email."""

from __future__ import annotations

import base64
import re
import mimetypes
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import markdown
import yaml
from jinja2 import Environment, FileSystemLoader, select_autoescape

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


@dataclass
class RenderedNewsletter:
    subject: str
    preview_text: str
    tag: str
    segment: str
    html_body: str
    preview_html_body: str
    email_html_body: str
    text_body: str
    md_path: Path | None = None
    attachments: list[dict[str, Any]] = field(default_factory=list)


def parse_frontmatter(text: str) -> tuple[dict, str]:
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    meta = yaml.safe_load(match.group(1)) or {}
    body = text[match.end() :]
    return meta, body


def _html_to_text(html: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", html, flags=re.I)
    text = re.sub(r"</p\s*>", "\n\n", text, flags=re.I)
    text = re.sub(r"</h[1-6]>", "\n\n", text, flags=re.I)
    text = re.sub(r"<li[^>]*>", "- ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


_IMG_SRC_RE = re.compile(r"(<img\b[^>]*\bsrc=)(['\"])(?P<src>[^'\"]+)\2", re.IGNORECASE)


def _resolve_local_image_src(src: str, *, md_path: Path | None) -> Path | None:
    src = (src or "").strip()
    if not src:
        return None
    if src.startswith(("cid:", "data:", "http://", "https://")):
        return None
    if src.startswith("file://"):
        candidate = src.replace("file://", "")
        candidate = candidate.lstrip("/")
        p = Path(candidate)
        return p if p.is_file() else None

    # Windows absolute path (C:\... or C:/...)
    if re.match(r"^[A-Za-z]:[\\/]", src):
        p = Path(src)
        return p if p.is_file() else None

    # Relative path (resolve against the markdown file directory)
    if md_path:
        p = (md_path.parent / src).resolve()
        return p if p.is_file() else None

    p2 = Path(src)
    return p2 if p2.is_file() else None


def _embed_local_images_for_email(
    html: str,
    *,
    md_path: Path | None,
) -> tuple[str, list[dict[str, Any]]]:
    path_to_cid: dict[str, str] = {}
    attachments: list[dict[str, Any]] = []
    counter = 0

    def repl(m: re.Match[str]) -> str:
        nonlocal counter
        prefix = m.group(1)
        quote = m.group(2)
        src = m.group("src")

        resolved = _resolve_local_image_src(src, md_path=md_path)
        if not resolved:
            return m.group(0)

        resolved_key = str(resolved.resolve())
        if resolved_key not in path_to_cid:
            counter += 1
            content_id = f"img-{counter}-{resolved.stem}"
            content_id = re.sub(r"[^A-Za-z0-9_-]", "", content_id)[:40] or f"img-{counter}"
            cid_value = f"cid:{content_id}"

            raw = resolved.read_bytes()
            content_b64 = base64.b64encode(raw).decode("ascii")
            mime_type = mimetypes.guess_type(str(resolved))[0] or "application/octet-stream"
            attachments.append(
                {
                    "Name": resolved.name,
                    "Content": content_b64,
                    "ContentType": mime_type,
                    "ContentID": cid_value,
                }
            )
            path_to_cid[resolved_key] = cid_value

        cid_value = path_to_cid[resolved_key]
        return f"{prefix}{quote}{cid_value}{quote}"

    new_html = _IMG_SRC_RE.sub(repl, html)
    return new_html, attachments


def _embed_local_images_for_preview(
    html: str,
    *,
    md_path: Path | None,
) -> str:
    """Replace local image paths with data: URIs so browser preview can render them."""

    def repl(m: re.Match[str]) -> str:
        prefix = m.group(1)
        quote = m.group(2)
        src = m.group("src")

        resolved = _resolve_local_image_src(src, md_path=md_path)
        if not resolved:
            return m.group(0)

        raw = resolved.read_bytes()
        mime_type = mimetypes.guess_type(str(resolved))[0] or "application/octet-stream"
        data_uri = f"data:{mime_type};base64,{base64.b64encode(raw).decode('ascii')}"
        return f"{prefix}{quote}{data_uri}{quote}"

    return _IMG_SRC_RE.sub(repl, html)


def _strip_leading_note_title(body: str, meta: dict) -> str:
    """Remove Obsidian note H1 from email body (subject lives in frontmatter)."""
    if meta.get("hide_note_title") is False:
        return body
    lines = body.lstrip().splitlines()
    if not lines:
        return body
    first = lines[0].strip()
    if first.startswith("# ") and not first.startswith("## "):
        return "\n".join(lines[1:]).lstrip()
    return body


def render_markdown(
    md_text: str,
    *,
    subject: str | None = None,
    preview_text: str | None = None,
    tag: str | None = None,
    segment: str | None = None,
    md_path: Path | None = None,
) -> RenderedNewsletter:
    meta, body = parse_frontmatter(md_text)
    body = _strip_leading_note_title(body, meta)

    final_subject = (subject or meta.get("subject") or "Newsletter").strip()
    final_preview = (preview_text or meta.get("preview_text") or "").strip()
    final_tag = (tag or meta.get("tag") or "newsletter").strip()
    final_segment = (segment or meta.get("segment") or "test").strip()

    content_html = markdown.markdown(
        body,
        extensions=["extra", "sane_lists", "nl2br"],
        output_format="html5",
    )

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html", "xml"]),
    )
    template = env.get_template("email_base.html")
    html_body = template.render(
        subject=final_subject,
        preview_text=final_preview,
        content_html=content_html,
    )
    email_html_body, attachments = _embed_local_images_for_email(
        html_body,
        md_path=md_path,
    )
    preview_html_body = _embed_local_images_for_preview(
        html_body,
        md_path=md_path,
    )

    text_body = _html_to_text(email_html_body)

    return RenderedNewsletter(
        subject=final_subject,
        preview_text=final_preview,
        tag=final_tag,
        segment=final_segment,
        html_body=html_body,
        preview_html_body=preview_html_body,
        email_html_body=email_html_body,
        text_body=text_body,
        md_path=md_path,
        attachments=attachments,
    )


def render_markdown_file(
    path: Path,
    **overrides: str | None,
) -> RenderedNewsletter:
    text = path.read_text(encoding="utf-8")
    return render_markdown(text, md_path=path, **overrides)


def compose_markdown_file(
    body: str,
    *,
    subject: str,
    preview_text: str = "",
    tag: str = "newsletter",
    segment: str = "general",
) -> str:
    """Build markdown with YAML frontmatter from editor fields."""
    _, body_only = parse_frontmatter(body)
    meta = {
        "subject": subject,
        "preview_text": preview_text,
        "tag": tag,
        "segment": segment,
    }
    frontmatter = yaml.safe_dump(meta, allow_unicode=True, sort_keys=False).strip()
    return f"---\n{frontmatter}\n---\n\n{body_only.lstrip()}"


def save_preview_html(rendered: RenderedNewsletter, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    slug = "preview"
    if rendered.md_path:
        slug = rendered.md_path.stem
    out_path = out_dir / f"{slug}.html"
    out_path.write_text(rendered.preview_html_body, encoding="utf-8")
    return out_path
