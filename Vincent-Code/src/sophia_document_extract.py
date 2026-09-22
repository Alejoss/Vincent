"""Extract plain text from Sophia TEXT document files (PDF, EPUB).

Used by `sophia_topic_text.resolve_media_text`. Embed / Qdrant pipelines stay
format-agnostic once text is resolved.
"""

from __future__ import annotations

import io
import logging
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse, unquote

logger = logging.getLogger(__name__)

SUPPORTED_FORMATS = frozenset({"pdf", "epub"})


class UnsupportedDocumentFormat(ValueError):
    """Raised when bytes/URL cannot be mapped to a supported extractor."""


@dataclass(frozen=True)
class DocumentExtract:
    text: str
    format: str  # pdf | epub
    notes: str = ""
    basename: str = ""

    @property
    def source_label(self) -> str:
        name = self.basename or f"document.{self.format}"
        return f"s3_{self.format}:{name}"


def basename_from_url(url: str) -> str:
    path = unquote(urlparse(url or "").path or "")
    name = Path(path).name.strip()
    return name or ""


def sniff_document_format(
    *,
    url: str = "",
    content_type: str = "",
    data: bytes = b"",
    hint: str = "",
) -> Optional[str]:
    """Return 'pdf' | 'epub' | None from URL, Content-Type, magic bytes, or hint."""
    candidates: list[str] = []

    for raw in (hint, basename_from_url(url)):
        ext = Path(raw or "").suffix.lower().lstrip(".")
        if ext in SUPPORTED_FORMATS:
            candidates.append(ext)

    ctype = (content_type or "").split(";", 1)[0].strip().lower()
    if ctype in {"application/pdf", "application/x-pdf"}:
        candidates.append("pdf")
    elif ctype in {
        "application/epub+zip",
        "application/epub",
        "application/x-epub+zip",
    }:
        candidates.append("epub")

    if data.startswith(b"%PDF"):
        candidates.append("pdf")
    elif _looks_like_epub(data):
        candidates.append("epub")

    for fmt in candidates:
        if fmt in SUPPORTED_FORMATS:
            return fmt
    return None


def _looks_like_epub(data: bytes) -> bool:
    if len(data) < 4 or data[:2] != b"PK":
        return False
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            # EPUB OCF: optional mimetype entry must be first and uncompressed,
            # but many files still carry application/epub+zip somewhere.
            names = zf.namelist()
            if "mimetype" in names:
                raw = zf.read("mimetype").decode("utf-8", errors="replace").strip()
                if "epub" in raw.lower():
                    return True
            return any(
                n.lower().endswith(".opf") or n.lower().startswith("meta-inf/")
                for n in names
            )
    except zipfile.BadZipFile:
        return False


def extract_pdf(data: bytes, *, basename: str = "") -> DocumentExtract:
    import fitz  # PyMuPDF

    doc = fitz.open(stream=data, filetype="pdf")
    try:
        parts = [doc[i].get_text("text") or "" for i in range(doc.page_count)]
        pages = doc.page_count
    finally:
        doc.close()
    text = _normalize_whitespace("\n".join(parts))
    return DocumentExtract(
        text=text,
        format="pdf",
        notes=f"pages={pages}",
        basename=basename or "document.pdf",
    )


def extract_epub(data: bytes, *, basename: str = "") -> DocumentExtract:
    text = ""
    notes = ""
    try:
        text, notes = _extract_epub_ebooklib(data)
    except Exception as exc:  # noqa: BLE001
        logger.info("ebooklib extract failed (%s); falling back to zip/html", exc)
        text, notes = _extract_epub_zip_fallback(data)
        notes = f"{notes};ebooklib_fallback:{type(exc).__name__}"

    return DocumentExtract(
        text=text,
        format="epub",
        notes=notes,
        basename=basename or "document.epub",
    )


def _extract_epub_ebooklib(data: bytes) -> tuple[str, str]:
    import ebooklib
    from bs4 import BeautifulSoup
    from ebooklib import epub

    book = epub.read_epub(io.BytesIO(data))
    parts: list[str] = []
    doc_count = 0
    for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        doc_count += 1
        soup = BeautifulSoup(item.get_content(), "html.parser")
        for tag in soup(["script", "style", "nav"]):
            tag.decompose()
        chunk = soup.get_text("\n", strip=True)
        if chunk:
            parts.append(chunk)
    return _normalize_whitespace("\n\n".join(parts)), f"spine_docs={doc_count}"


def _extract_epub_zip_fallback(data: bytes) -> tuple[str, str]:
    """Parse XHTML/HTML members directly when ebooklib rejects the package."""
    from bs4 import BeautifulSoup

    parts: list[str] = []
    doc_count = 0
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = sorted(
            n
            for n in zf.namelist()
            if n.lower().endswith((".xhtml", ".html", ".htm"))
            and not n.lower().endswith("nav.xhtml")
        )
        for name in names:
            doc_count += 1
            raw = zf.read(name)
            soup = BeautifulSoup(raw, "html.parser")
            for tag in soup(["script", "style", "nav"]):
                tag.decompose()
            chunk = soup.get_text("\n", strip=True)
            if chunk:
                parts.append(chunk)
    return (
        _normalize_whitespace("\n\n".join(parts)),
        f"zip_html_docs={doc_count}",
    )


def extract_document(
    data: bytes,
    *,
    url: str = "",
    content_type: str = "",
    hint: str = "",
) -> DocumentExtract:
    """Sniff format and extract plain text. Raises UnsupportedDocumentFormat."""
    fmt = sniff_document_format(
        url=url, content_type=content_type, data=data, hint=hint
    )
    if not fmt:
        raise UnsupportedDocumentFormat(
            "unsupported_or_unknown_document_format"
            f" url={basename_from_url(url)!r} content_type={content_type!r}"
        )

    name = basename_from_url(url) or f"document.{fmt}"
    if fmt == "pdf":
        return extract_pdf(data, basename=name)
    if fmt == "epub":
        return extract_epub(data, basename=name)
    raise UnsupportedDocumentFormat(f"unsupported_format:{fmt}")


_MULTI_NL = re.compile(r"\n{3,}")
_MULTI_SPACE = re.compile(r"[ \t]+\n")


def _normalize_whitespace(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _MULTI_SPACE.sub("\n", text)
    text = _MULTI_NL.sub("\n\n", text)
    return text.strip()
