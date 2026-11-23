"""Command-line interface (Linux, macOS, Windows).

Examples:
  ai-cleanup report.docx photo.png              -> report.cleaned.docx, photo.cleaned.png
  ai-cleanup ./folder -o ./clean                -> cleans every supported file recursively
  ai-cleanup draft.md --in-place                -> overwrite the original
  ai-cleanup --check essay.txt                  -> only report, write nothing (exit 1 if dirty)
  echo "text" | ai-cleanup -                    -> clean stdin to stdout
  ai-cleanup --reveal essay.txt                 -> print text with hidden chars made visible
  ai-cleanup --gui                              -> open the graphical interface
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .engine import clean_file, iter_files, read_text_file
from .report import Options, Report
from .text import clean_text, reveal


def _utf8_console() -> None:
    # Windows consoles default to a legacy code page; never crash on emoji/Hebrew/etc.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ai-cleanup",
        description="Strip AI fingerprints from files: invisible/zero-width characters, hidden "
                    "Unicode tags, chatbot citation artifacts, AI typography, and metadata "
                    "(EXIF/XMP/C2PA, document properties, generator tags).",
        epilog=__doc__.split("Examples:", 1)[1] and "Examples:" + __doc__.split("Examples:", 1)[1],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("paths", nargs="*", help="files or folders to clean, or '-' for stdin")
    p.add_argument("-o", "--output", metavar="DIR", help="write cleaned files into DIR")
    p.add_argument("-i", "--in-place", action="store_true", help="overwrite the original files")
    p.add_argument("-s", "--suffix", default=".cleaned", help="suffix for output names (default: .cleaned)")
    p.add_argument("-n", "--check", "--dry-run", dest="dry_run", action="store_true",
                   help="report what would be removed without writing anything; exit code 1 if anything found")
    p.add_argument("--no-recursive", action="store_true", help="do not descend into sub-folders")
    p.add_argument("--reveal", action="store_true", help="print text files with hidden characters made visible")
    p.add_argument("--json", action="store_true", help="machine-readable JSON output")
    p.add_argument("-q", "--quiet", action="store_true", help="only print errors")
    p.add_argument("--gui", action="store_true", help="launch the graphical interface")
    p.add_argument("--version", action="version", version=f"ai-cleanup {__version__}")

    g = p.add_argument_group("what to clean (all on by default except --symbols)")
    g.add_argument("--keep-invisible", action="store_true", help="do not remove invisible characters")
    g.add_argument("--keep-spaces", action="store_true", help="do not normalise exotic spaces")
    g.add_argument("--keep-typography", action="store_true", help="keep em/en dashes, smart quotes, ellipses")
    g.add_argument("--keep-citations", action="store_true", help="keep chatbot citation artifacts")
    g.add_argument("--keep-metadata", action="store_true", help="keep file metadata")
    g.add_argument("--symbols", action="store_true", help="also strip decorative emoji/icons (✅ 🚀 ⓘ ✨)")
    g.add_argument("--strict", action="store_true",
                   help="also remove ZWJ/ZWNJ/variation selectors needed by emoji and Arabic/Indic scripts")
    g.add_argument("--drop-icc", action="store_true", help="also remove image colour profiles")
    return p


def options_from_args(a: argparse.Namespace) -> Options:
    return Options(invisible=not a.keep_invisible, spaces=not a.keep_spaces,
                   typography=not a.keep_typography, citations=not a.keep_citations,
                   metadata=not a.keep_metadata, symbols=a.symbols,
                   preserve_legit=not a.strict, keep_icc=not a.drop_icc)


def main(argv: list[str] | None = None) -> int:
    _utf8_console()
    args = build_parser().parse_args(argv)

    if args.gui or not args.paths:
        if not args.paths and not args.gui and sys.stdin is not None and not sys.stdin.isatty():
            args.paths = ["-"]
        else:
            from .gui import run
            return run()

    opts = options_from_args(args)

    if args.paths == ["-"]:
        data = sys.stdin.buffer.read().decode("utf-8", errors="replace")
        if args.reveal:
            sys.stdout.write(reveal(data))
            return 0
        cleaned, rep = clean_text(data, opts)
        if not args.dry_run:
            sys.stdout.write(cleaned)
        if not args.quiet:
            print(f"stdin: {rep.summary()}", file=sys.stderr)
        return 1 if args.dry_run and rep.total else 0

    if args.in_place and args.output:
        print("error: --in-place and --output are mutually exclusive", file=sys.stderr)
        return 2

    files = list(iter_files(args.paths, recursive=not args.no_recursive, suffix=args.suffix))
    missing = [p for p in args.paths if not Path(p).exists()]
    for m in missing:
        print(f"error: not found: {m}", file=sys.stderr)
    if not files:
        print("error: no supported files found", file=sys.stderr)
        return 2

    if args.reveal:
        for f in files:
            text, _ = read_text_file(f, Report())
            print(f"===== {f}")
            print(reveal(text))
        return 0

    results = []
    dirty = errors = 0
    for f in files:
        r = clean_file(f, args.output, opts, args.suffix, args.in_place, args.dry_run)
        results.append(r)
        if r.error:
            errors += 1
            if not args.json:
                print(f"[FAIL] {f}: {r.error}", file=sys.stderr)
            continue
        if r.report.total:
            dirty += 1
        if not args.quiet and not args.json:
            tag = "FOUND" if args.dry_run and r.report.total else ("CLEAN" if not r.report.total else "FIXED")
            dest = "" if args.dry_run or r.dst is None else f" -> {r.dst}"
            print(f"[{tag}] {f}{dest}\n        {r.report.summary()}")
            for n in r.report.notes:
                print(f"        note: {n}")

    if args.json:
        print(json.dumps([{"file": str(r.src), "output": str(r.dst) if r.dst else None,
                           "type": r.kind, "error": r.error, "removed": dict(r.report.changes),
                           "notes": r.report.notes} for r in results], ensure_ascii=False, indent=2))
    elif not args.quiet:
        print(f"\n{len(files)} file(s): {dirty} had AI traces, {errors} failed")

    if errors:
        return 3
    return 1 if args.dry_run and dirty else 0


if __name__ == "__main__":
    raise SystemExit(main())
