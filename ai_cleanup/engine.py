"""Dispatch files to the right cleaner and decide where output goes."""
from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .images import IMAGE_EXTS, clean_image
from .media import MEDIA_EXTS, clean_media
from .office import ZIP_DOC_EXTS, clean_zip_document
from .pdf import clean_pdf
from .report import Options, Report
from .text import clean_markup, clean_rtf, clean_text

PROSE_EXTS = {".txt", ".md", ".markdown", ".rst", ".text", ".tex", ".log", ".org", ".adoc",
              ".srt", ".vtt", ".eml", ".nfo"}
MARKUP_EXTS = {".html", ".htm", ".xhtml", ".xml", ".svg", ".fodt", ".opml", ".rss", ".atom"}
HTML_EXTS = {".html", ".htm", ".xhtml"}
CODE_EXTS = {".json", ".jsonl", ".csv", ".tsv", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".py",
             ".js", ".mjs", ".ts", ".tsx", ".jsx", ".java", ".c", ".h", ".cpp", ".hpp", ".cs",
             ".go", ".rs", ".rb", ".php", ".sh", ".bash", ".ps1", ".bat", ".sql", ".css", ".scss",
             ".kt", ".swift", ".lua", ".r", ".m", ".pl", ".ipynb", ".env", ".properties"}
RTF_EXTS = {".rtf"}
PDF_EXTS = {".pdf"}

SUPPORTED_EXTS = (PROSE_EXTS | MARKUP_EXTS | CODE_EXTS | RTF_EXTS | PDF_EXTS | IMAGE_EXTS
                  | ZIP_DOC_EXTS | MEDIA_EXTS)


@dataclass
class Result:
    src: Path
    dst: Path | None
    kind: str
    report: Report = field(default_factory=Report)
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


def detect_kind(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in IMAGE_EXTS:
        return "image"
    if ext in ZIP_DOC_EXTS:
        return "document"
    if ext in PDF_EXTS:
        return "pdf"
    if ext in MEDIA_EXTS:
        return "media"
    if ext in RTF_EXTS:
        return "rtf"
    if ext in MARKUP_EXTS:
        return "markup"
    if ext in CODE_EXTS:
        return "code"
    if ext in PROSE_EXTS:
        return "text"
    # unknown extension: treat as text if it decodes and has no NUL bytes
    try:
        head = path.read_bytes()[:8192]
    except OSError:
        return "unsupported"
    if b"\x00" not in head:
        try:
            head.decode("utf-8")
            return "text"
        except UnicodeDecodeError:
            pass
    return "unsupported"


def read_text_file(path: Path, report: Report) -> tuple[str, str]:
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        report.add("byte order mark")
        return raw[3:].decode("utf-8", errors="replace"), "utf-8"
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16"), "utf-16"
    try:
        return raw.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace"), "cp1252"


def output_path(src: Path, out_dir: Path | None, suffix: str, in_place: bool) -> Path:
    if in_place:
        return src
    folder = out_dir or src.parent
    return folder / f"{src.stem}{suffix}{src.suffix}"


def clean_file(src: Path | str, out_dir: Path | str | None = None, opts: Options | None = None,
               suffix: str = ".cleaned", in_place: bool = False, dry_run: bool = False) -> Result:
    src = Path(src)
    opts = opts or Options()
    kind = detect_kind(src)
    out_dir = Path(out_dir) if out_dir else None
    dst = output_path(src, out_dir, suffix, in_place)
    result = Result(src, None if dry_run else dst, kind)
    if kind == "unsupported":
        result.error = f"unsupported file type ({src.suffix or 'no extension'})"
        return result

    # always write to a temp file in the destination folder, then atomically move into place
    target_dir = dst.parent
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=".aiclean-", suffix=src.suffix, dir=target_dir)
        os.close(fd)
        tmp = Path(tmp_name)
    except OSError as e:
        result.error = f"cannot write to {target_dir}: {e}"
        return result

    try:
        rep = result.report
        if kind in ("text", "code", "markup", "rtf"):
            text, enc = read_text_file(src, rep)
            if kind == "markup":
                text, _ = clean_markup(text, opts, rep, html=src.suffix.lower() in HTML_EXTS)
            elif kind == "rtf":
                text, _ = clean_rtf(text, opts, rep)
            else:
                text, _ = clean_text(text, opts, rep, "code" if kind == "code" else "prose")
            with open(tmp, "w", encoding=enc, newline="") as fh:
                fh.write(text)
        elif kind == "image":
            clean_image(src, tmp, opts, rep)
        elif kind == "document":
            clean_zip_document(src, tmp, opts, rep)
        elif kind == "pdf":
            clean_pdf(src, tmp, opts, rep)
        elif kind == "media":
            clean_media(src, tmp, opts, rep)

        if dry_run:
            tmp.unlink(missing_ok=True)
        else:
            try:
                shutil.copymode(src, tmp)
            except OSError:
                pass
            os.replace(tmp, dst)
    except Exception as e:  # noqa: BLE001 - surface any failure per file
        tmp.unlink(missing_ok=True)
        result.dst = None
        result.error = f"{type(e).__name__}: {e}"
    return result


def iter_files(paths, recursive: bool = True, suffix: str = ".cleaned"):
    """Expand files/folders into a flat list of files, skipping our own outputs."""
    for p in paths:
        p = Path(p)
        if p.is_dir():
            it = p.rglob("*") if recursive else p.glob("*")
            for f in sorted(it):
                if f.is_file() and not f.name.startswith(".aiclean-") \
                        and not f.stem.endswith(suffix) and f.suffix.lower() in SUPPORTED_EXTS:
                    yield f
        elif p.is_file():
            yield p
