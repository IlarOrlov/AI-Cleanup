# AI-Cleanup

Removes the traces AI tools leave inside files: invisible Unicode characters, hidden "tag" text, chatbot citation leftovers, AI-style typography, and metadata or generator fingerprints in documents, images, PDFs and media.

It has a desktop GUI (drag and drop) and a scriptable CLI, and works on Linux, Windows and macOS.

## What it removes

| Category | Details |
|---|---|
| **Invisible characters** | Zero-width space/joiner/non-joiner, word joiner, BOM, soft hyphen, bidi overrides (`U+202A-202E`, `U+2066-2069`), Unicode **tag characters** (hidden "ASCII smuggling" text), variation selectors, Hangul/Braille blank fillers, control characters, other format (`Cf`) chars |
| **Exotic spaces** | NBSP, narrow NBSP, thin/hair/figure/em spaces, ideographic space, line/paragraph separators |
| **AI typography** | Em/en dashes, curly quotes, ellipsis -> ASCII (quotes are left alone in code/JSON/CSV so they stay valid) |
| **Chatbot artifacts** | ChatGPT private-use citation markers (`U+E200...`), `【4:0†source】`, `:contentReference[oaicite:N]{index=N}`, `citeturn0search3` leftovers, Grok `<grok:render>` tags, `?utm_source=chatgpt.com` (also perplexity, copilot, claude.ai, gemini...), ChatGPT copy attributes (`data-start`/`data-end`) in HTML |
| **Decorative emoji** *(opt-in)* | ✅ 🚀 ✨ ⓘ ⚠️ and friends; form checkboxes ☐ ☑ ☒ are kept |
| **Image metadata** | EXIF, XMP, IPTC, **C2PA content credentials**, Stable Diffusion / ComfyUI / A1111 `parameters`/`prompt`/`workflow` chunks, Software tags (DALL-E, Midjourney, Firefly...). Pixels are re-encoded losslessly, or reusing the original JPEG quantisation tables, and EXIF rotation is baked in |
| **Office / ODF / EPUB** | Text in every XML part is cleaned; creator/last-modified-by/description/keywords are blanked; `custom.xml` is dropped (custom/AI labels); **generator fingerprints** are normalised: an empty `app.xml` (docx.js, python-docx...) is rebuilt the way Word writes it, millisecond timestamps are trimmed, empty generator-made comment parts are removed; ODF `meta:generator` is cleared |
| **PDF** | Info dictionary (Producer/Creator/Author...), XMP stream, PieceInfo, embedded C2PA manifests. Hidden characters in page text are *reported*. Rewriting PDF text safely isn't possible, so regenerate the PDF from a cleaned source |
| **Audio / video** | Remux with ffmpeg (no re-encode), dropping all global/stream metadata, chapters, data streams and C2PA boxes |

ZWJ/ZWNJ and variation selectors that emoji, Persian/Arabic or Indic scripts actually need are kept by default; `--strict` removes them too.

## Install

Requires Python 3.9+. ffmpeg is optional and is only needed for audio/video.

```bash
git clone https://github.com/IlarOrlov/AI-Cleanup.git
cd AI-Cleanup
python -m pip install ".[gui]"        # CLI + GUI   (CLI only: python -m pip install .)
```

On Windows use `py -m pip install ".[gui]"`. This installs two commands on both platforms:

- `ai-cleanup`: command line (running it with no arguments opens the GUI)
- `ai-cleanup-gui`: GUI without a console window

Without installing: `pip install -r requirements.txt`, then `python -m ai_cleanup`.

## GUI

```bash
ai-cleanup-gui            # or: ai-cleanup --gui   /   python -m ai_cleanup
```

- **Files tab:** drop files or folders, then use **Scan only** (report, write nothing) or **Clean files**. Output goes next to the original as `name.cleaned.ext`, into a folder you choose, or over the originals (asks first). Select a row to see exactly what was removed.
- **Paste text tab:** paste text to get the cleaned version live. Hidden characters are highlighted in red and listed with their positions and Unicode names. Use **Copy cleaned text** to copy the result.

## CLI

```bash
ai-cleanup report.docx photo.png            # -> report.cleaned.docx, photo.cleaned.png
ai-cleanup ./project -o ./clean             # whole folder (recursive) into ./clean
ai-cleanup essay.md --in-place              # overwrite the original
ai-cleanup --check ./docs                   # scan only; exit code 1 if anything found (CI-friendly)
ai-cleanup --symbols --strict notes.txt     # also strip decorative emoji + all joiners
ai-cleanup --reveal suspicious.txt          # print text with hidden chars shown as ⟦ZERO WIDTH SPACE⟧
ai-cleanup --json ./docs > report.json      # machine-readable report

# pipes (Linux/macOS)
pbpaste | ai-cleanup - | pbcopy
xclip -o -sel clip | ai-cleanup - | xclip -sel clip

# pipes (Windows PowerShell)
Get-Clipboard | ai-cleanup - | Set-Clipboard
```

Turn individual cleaners off with `--keep-invisible`, `--keep-spaces`, `--keep-typography`, `--keep-citations` or `--keep-metadata`. Use `--drop-icc` to also remove image colour profiles. Run `ai-cleanup --help` for everything.

Exit codes: `0` ok, `1` traces found (with `--check`), `2` usage error / nothing to do, `3` some files failed.

## Python API

```python
from ai_cleanup import clean_text, clean_file, Options

text, report = clean_text(chatbot_output)
print(report.summary())

clean_file("draft.docx", out_dir="clean", opts=Options(symbols=True))
```

## Limits

- **Pixel-level watermarks** (Google SynthID, the invisible DWT/DCT watermarks some image generators embed, audio watermarks) are part of the image or audio signal itself, not metadata. This tool does not attempt to remove them.
- **Writing style** is not changed. Only characters, artifacts and metadata are.
- Text inside PDFs is reported but not rewritten (see above).

## Development

```bash
python -m pip install -e ".[dev]"
python -m pytest
```

CI runs the test suite on Linux, Windows and macOS.
