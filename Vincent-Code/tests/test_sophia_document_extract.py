"""Unit tests for PDF/EPUB document extraction (no network)."""

from __future__ import annotations

import io
import unittest
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import fitz

from src.sophia_document_extract import (
    UnsupportedDocumentFormat,
    extract_document,
    extract_epub,
    extract_pdf,
    sniff_document_format,
)
from src.sophia_topic_text import resolve_media_text


def _minimal_pdf_bytes(text: str = "Hello from PDF") -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    data = doc.tobytes()
    doc.close()
    return data


def _minimal_epub_bytes(
    body_html: str = "<p>Hello from EPUB chapter.</p>",
) -> bytes:
    """Build a tiny EPUB with ebooklib (valid package + NCX/nav)."""
    from ebooklib import epub

    book = epub.EpubBook()
    book.set_identifier("vincent-test-epub")
    book.set_title("Test Book")
    book.set_language("en")
    chapter = epub.EpubHtml(title="Chapter 1", file_name="chapter1.xhtml", lang="en")
    chapter.content = f"<html><body>{body_html}</body></html>"
    book.add_item(chapter)
    book.toc = (chapter,)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", chapter]
    buf = io.BytesIO()
    epub.write_epub(buf, book)
    return buf.getvalue()


def _bare_epub_zip_bytes(
    body_html: str = "<html><body><p>Bare zip EPUB text.</p></body></html>",
) -> bytes:
    """Intentionally incomplete EPUB to exercise the zip/html fallback."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "mimetype",
            "application/epub+zip",
            compress_type=zipfile.ZIP_STORED,
        )
        zf.writestr(
            "META-INF/container.xml",
            """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf"
      media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
""",
        )
        zf.writestr(
            "OEBPS/content.opf",
            """<?xml version="1.0"?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="uid" version="2.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="uid">bare</dc:identifier>
    <dc:title>Bare</dc:title>
    <dc:language>en</dc:language>
  </metadata>
  <manifest>
    <item id="ch1" href="chapter1.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="ch1"/>
  </spine>
</package>
""",
        )
        zf.writestr("OEBPS/chapter1.xhtml", body_html)
    return buf.getvalue()


class SniffFormatTests(unittest.TestCase):
    def test_url_extension(self):
        self.assertEqual(
            sniff_document_format(url="https://cdn.example/a/book.epub"),
            "epub",
        )
        self.assertEqual(
            sniff_document_format(url="https://cdn.example/a/paper.PDF"),
            "pdf",
        )

    def test_content_type(self):
        self.assertEqual(
            sniff_document_format(content_type="application/epub+zip"),
            "epub",
        )
        self.assertEqual(
            sniff_document_format(content_type="application/pdf; charset=binary"),
            "pdf",
        )

    def test_magic_bytes(self):
        self.assertEqual(sniff_document_format(data=_minimal_pdf_bytes()), "pdf")
        self.assertEqual(sniff_document_format(data=_minimal_epub_bytes()), "epub")


class ExtractTests(unittest.TestCase):
    def test_extract_pdf(self):
        out = extract_pdf(_minimal_pdf_bytes("Alpha PDF body"), basename="a.pdf")
        self.assertEqual(out.format, "pdf")
        self.assertIn("Alpha PDF body", out.text)
        self.assertEqual(out.source_label, "s3_pdf:a.pdf")
        self.assertTrue(out.notes.startswith("pages="))

    def test_extract_epub(self):
        out = extract_epub(_minimal_epub_bytes(), basename="book.epub")
        self.assertEqual(out.format, "epub")
        self.assertIn("Hello from EPUB chapter", out.text)
        self.assertEqual(out.source_label, "s3_epub:book.epub")
        self.assertIn("spine_docs=", out.notes)

    def test_extract_epub_zip_fallback(self):
        # Force the zip/html path (ebooklib may also succeed on some bare packages).
        from src import sophia_document_extract as mod

        with patch.object(
            mod,
            "_extract_epub_ebooklib",
            side_effect=RuntimeError("forced"),
        ):
            out = extract_epub(_bare_epub_zip_bytes(), basename="bare.epub")
        self.assertEqual(out.format, "epub")
        self.assertIn("Bare zip EPUB text", out.text)
        self.assertIn("zip_html_docs=", out.notes)
        self.assertIn("ebooklib_fallback", out.notes)

    def test_extract_document_dispatch(self):
        pdf = extract_document(
            _minimal_pdf_bytes("Zed"),
            url="https://x/y/z.pdf",
        )
        self.assertEqual(pdf.format, "pdf")
        self.assertIn("Zed", pdf.text)

        epub = extract_document(
            _minimal_epub_bytes("<p>Chapter text here</p>"),
            url="https://x/y/z.epub",
        )
        self.assertEqual(epub.format, "epub")
        self.assertIn("Chapter text here", epub.text)

    def test_unsupported(self):
        with self.assertRaises(UnsupportedDocumentFormat):
            extract_document(b"not-a-document", url="https://x/y/z.txt")


class ResolveTextDocumentTests(unittest.TestCase):
    def test_epub_via_file_details_url(self):
        payload = _minimal_epub_bytes()
        response = MagicMock()
        response.content = payload
        response.headers = {"Content-Type": "application/epub+zip"}
        response.raise_for_status = MagicMock()

        item = {
            "id": 42,
            "media_type": "TEXT",
            "original_title": "Test Book",
            "original_author": "Author",
            "file_details": {
                "file": "https://cdn.example.com/media/test-book.epub",
            },
        }
        with patch("src.sophia_topic_text.requests.get", return_value=response):
            resolved = resolve_media_text(
                project_root=Path("."),
                item=item,
            )

        self.assertEqual(resolved.status, "ok")
        self.assertEqual(resolved.source, "s3_epub:test-book.epub")
        self.assertIn("Hello from EPUB chapter", resolved.text)

    def test_pdf_still_works(self):
        payload = _minimal_pdf_bytes("Legacy PDF path")
        response = MagicMock()
        response.content = payload
        response.headers = {"Content-Type": "application/pdf"}
        response.raise_for_status = MagicMock()

        item = {
            "id": 7,
            "media_type": "TEXT",
            "original_title": "Paper",
            "file_details": {"file": "https://cdn.example.com/x/paper.pdf"},
        }
        with patch("src.sophia_topic_text.requests.get", return_value=response):
            resolved = resolve_media_text(project_root=Path("."), item=item)

        self.assertEqual(resolved.status, "ok")
        self.assertTrue(resolved.source.startswith("s3_pdf:"))
        self.assertIn("Legacy PDF path", resolved.text)


if __name__ == "__main__":
    unittest.main()
