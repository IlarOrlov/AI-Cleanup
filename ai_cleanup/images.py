"""Image cleaning: drop every metadata container (EXIF, XMP, IPTC, PNG text chunks,
C2PA / JUMBF content credentials, generator prompts) by rebuilding the file from pixels."""
from __future__ import annotations

import re
from pathlib import Path

from .report import Options, Report

IMAGE_EXTS = {".jpg", ".jpeg", ".jpe", ".jfif", ".png", ".webp", ".gif", ".tif", ".tiff",
              ".bmp", ".avif"}

AI_HINTS = re.compile(
    rb"(c2pa|jumbf|contentauth|trainedAlgorithmicMedia|compositeWithTrainedAlgorithmicMedia|"
    rb"DALL[-\xb7 ]?E|Midjourney|Stable ?Diffusion|ComfyUI|Automatic1111|InvokeAI|NovelAI|Firefly|"
    rb"Imagen|Gemini|OpenAI|ChatGPT|GPT-4o|sora|Leonardo\.Ai|Ideogram|Flux|SynthID|Bing Image Creator|"
    rb"Made with AI|AI[- ]generated|Generated with)",
    re.I,
)


def _scan(path: Path, img, report: Report) -> None:
    raw = path.read_bytes()
    hints = {m.group(0).decode("latin-1").lower() for m in AI_HINTS.finditer(raw)}
    if hints:
        report.note("AI markers found: " + ", ".join(sorted(hints)[:12]))
        report.add("AI provenance marker", len(hints))
    info = getattr(img, "info", {}) or {}
    if "exif" in info or img.getexif():
        report.add("EXIF block")
    if any(k in info for k in ("xmp", "XML:com.adobe.xmp")) or b"<x:xmpmeta" in raw:
        report.add("XMP block")
    text_keys = [k for k, v in info.items() if isinstance(v, str) and k not in ("xmp",)]
    if text_keys:
        report.add("embedded text field", len(text_keys))
        for k in ("parameters", "prompt", "workflow", "Comment", "Description", "Software"):
            if k in info:
                report.note(f"removed '{k}' field")
    if b"caBX" in raw or b"jumb" in raw:
        report.add("C2PA content credential")
    if "comment" in info:
        report.add("comment block")


def _strip_frame(frame, keep_icc: bool, icc):
    from PIL import Image

    clean = Image.frombytes(frame.mode, frame.size, frame.tobytes())
    if frame.mode in ("P", "PA"):
        pal = frame.getpalette()
        if pal:
            clean.putpalette(pal)
    if "transparency" in frame.info and frame.mode in ("P", "L", "RGB", "LA", "PA"):
        clean.info["transparency"] = frame.info["transparency"]
    return clean


def clean_image(src: Path, dst: Path, opts: Options, report: Report) -> Path:
    from PIL import Image, ImageOps, ImageSequence

    with Image.open(src) as img:
        img.load()
        fmt = (img.format or src.suffix.lstrip(".")).upper()
        _scan(src, img, report)
        icc = img.info.get("icc_profile") if opts.keep_icc else None
        if img.info.get("icc_profile") and not opts.keep_icc:
            report.add("ICC profile")

        n_frames = getattr(img, "n_frames", 1)
        save_kw: dict = {}
        if icc:
            save_kw["icc_profile"] = icc

        if n_frames > 1 and fmt in ("GIF", "WEBP", "PNG", "TIFF"):
            frames, durations = [], []
            for fr in ImageSequence.Iterator(img):
                durations.append(fr.info.get("duration", 100))
                frames.append(_strip_frame(fr.copy(), opts.keep_icc, icc))
            save_kw.update(save_all=True, append_images=frames[1:], duration=durations,
                           loop=img.info.get("loop", 0))
            if fmt == "GIF" and "disposal" in img.info:
                save_kw["disposal"] = img.info["disposal"]
            first = frames[0]
        else:
            oriented = ImageOps.exif_transpose(img)  # bake rotation in before dropping EXIF
            first = _strip_frame(oriented, opts.keep_icc, icc)
            if oriented is not img and img.getexif().get(0x0112, 1) != 1:
                report.note("EXIF orientation baked into pixels")

        if fmt in ("JPEG", "MPO"):
            fmt = "JPEG"
            try:
                from PIL import JpegImagePlugin
                save_kw["qtables"] = img.quantization
                save_kw["subsampling"] = JpegImagePlugin.get_sampling(img)
            except Exception:
                save_kw["quality"] = 95
            if first.mode not in ("RGB", "L", "CMYK"):
                first = first.convert("RGB")
        elif fmt == "WEBP":
            raw_head = src.read_bytes()[:64]
            if b"VP8L" in raw_head:
                save_kw["lossless"] = True
            else:
                save_kw["quality"] = 95
            save_kw["exif"] = b""
        elif fmt == "PNG":
            save_kw["optimize"] = False
        elif fmt == "BMP":
            save_kw.pop("icc_profile", None)

        first.save(dst, format=fmt, **save_kw)
    return dst
