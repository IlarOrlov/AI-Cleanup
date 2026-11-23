"""Audio/video: remux with ffmpeg dropping all global/stream metadata, chapters and data
streams (C2PA boxes, encoder tags, creation tool atoms). Streams are copied, never re-encoded."""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from .report import Options, Report

MEDIA_EXTS = {".mp4", ".m4v", ".mov", ".mkv", ".webm", ".avi", ".mp3", ".m4a", ".aac", ".wav",
              ".flac", ".ogg", ".oga", ".opus", ".wma", ".wmv"}


def ffmpeg_path() -> str | None:
    return shutil.which("ffmpeg")


def _probe_tags(src: Path) -> int:
    probe = shutil.which("ffprobe")
    if not probe:
        return 0
    try:
        out = subprocess.run([probe, "-v", "quiet", "-show_entries", "format_tags:stream_tags",
                              "-of", "default=nw=1", str(src)], capture_output=True, text=True,
                             timeout=60, **_no_window()).stdout
        return sum(1 for line in out.splitlines() if line.startswith("TAG:"))
    except Exception:
        return 0


def _no_window() -> dict:
    if sys.platform == "win32":
        return {"creationflags": 0x08000000}  # CREATE_NO_WINDOW: no console flash from the GUI
    return {}


def clean_media(src: Path, dst: Path, opts: Options, report: Report) -> Path:
    ff = ffmpeg_path()
    if not ff:
        raise RuntimeError("ffmpeg not found on PATH - install it to clean audio/video files")
    tags = _probe_tags(src)
    cmd = [ff, "-nostdin", "-y", "-v", "error", "-i", str(src),
           "-map", "0:v?", "-map", "0:a?", "-map", "0:s?",
           "-map_metadata", "-1", "-map_chapters", "-1", "-c", "copy",
           "-fflags", "+bitexact", "-flags:v", "+bitexact", "-flags:a", "+bitexact"]
    if dst.suffix.lower() in (".mp4", ".m4v", ".mov", ".m4a"):
        cmd += ["-movflags", "+faststart"]
    cmd.append(str(dst))
    res = subprocess.run(cmd, capture_output=True, text=True, **_no_window())
    if res.returncode != 0:
        raise RuntimeError("ffmpeg failed: " + res.stderr.strip()[-400:])
    report.add("media metadata tag", tags)
    report.add("container metadata stripped")
    return dst
