"""PDF cleaning: remove the Info dictionary, XMP streams, PieceInfo and embedded
content-credential (C2PA) attachments. Page text is left untouched (rewriting PDF content
streams safely is not possible in general) but hidden characters in it are reported."""
from __future__ import annotations

from pathlib import Path

from .report import Options, Report
from .text import classify

_AI_HINTS = ("chatgpt", "openai", "copilot", "gemini", "claude", "anthropic", "reportlab",
             "wkhtmltopdf", "weasyprint", "headless", "puppeteer", "playwright", "pandoc",
             "python", "pypdf", "fpdf", "generated")


def clean_pdf(src: Path, dst: Path, opts: Options, report: Report) -> Path:
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import NameObject

    reader = PdfReader(str(src))
    if reader.is_encrypted:
        if not reader.decrypt(""):
            raise ValueError("PDF is password-protected")
        report.note("PDF was encrypted with an empty password; saved unencrypted")

    meta = reader.metadata or {}
    if opts.metadata:
        for k, v in meta.items():
            report.add("PDF info field")
            if any(h in str(v).lower() for h in _AI_HINTS):
                report.note(f"generator hint removed: {k}={str(v)[:60]!r}")

    hidden = 0
    for page in reader.pages[:200]:
        try:
            hidden += sum(1 for ch in page.extract_text() or "" if classify(ch))
        except Exception:
            pass
    if hidden:
        report.note(f"{hidden} hidden characters are inside the PDF page text; regenerate the PDF "
                    "from a cleaned source to remove them")

    writer = PdfWriter(clone_from=reader)
    if opts.metadata:
        root = writer._root_object
        for key in ("/Metadata", "/PieceInfo", "/SpiderInfo"):
            if key in root:
                del root[NameObject(key)]
                report.add("XMP/metadata stream" if key == "/Metadata" else "PDF private data")
        names = root.get("/Names")
        if names is not None:
            names = names.get_object()
            ef = names.get("/EmbeddedFiles")
            if ef is not None:
                arr = ef.get_object().get("/Names", [])
                labels = [str(arr[i]) for i in range(0, len(arr), 2)]
                if any("c2pa" in lab.lower() or "manifest" in lab.lower() for lab in labels):
                    del names[NameObject("/EmbeddedFiles")]
                    report.add("C2PA content credential")
        if "/AF" in root:
            del root[NameObject("/AF")]
        for page in writer.pages:
            for key in ("/Metadata", "/PieceInfo"):
                if key in page:
                    del page[NameObject(key)]
                    report.add("page metadata")
        # blank Info dict: drop every key, including the Producer pypdf would add
        writer.metadata = None
        writer._info = None  # pypdf: no /Info in trailer at all
    with open(dst, "wb") as fh:
        writer.write(fh)
    return dst
