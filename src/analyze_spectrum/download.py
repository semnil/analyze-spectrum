"""Download audio via yt-dlp Python API and probe media info via ffprobe."""

import math
import re
import subprocess
from pathlib import Path

from yt_dlp import YoutubeDL

from analyze_spectrum import _ffmpeg_kwargs


def is_url(s: str) -> bool:
    """Check if a string looks like an HTTP(S) URL."""
    return s.startswith("http://") or s.startswith("https://")


def resolve_source(source: str, workdir: str) -> tuple[str, str]:
    """Resolve source to (audio_path, label).

    Downloads from URL if needed, otherwise uses local path.
    """
    if is_url(source):
        path, title = download_audio(source, workdir)
        return path, title
    p = Path(source)
    if not p.exists():
        raise FileNotFoundError(f"File not found: {source}")
    return str(p), p.stem


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, check=True, capture_output=True, text=True,
                              encoding="utf-8", **_ffmpeg_kwargs())
    except subprocess.CalledProcessError as e:
        stderr_tail = (e.stderr or "")[-200:]
        raise RuntimeError(f"{cmd[0]} failed (exit {e.returncode}): {stderr_tail}") from e


_WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def sanitize_filename(name: str) -> str:
    """Remove or replace characters that are unsafe for filenames.

    Rejects null byte and ASCII control characters (0x00-0x1F) in addition to
    the usual Windows-reserved set, so upstream open(dest, "wb") cannot fail
    with ValueError('embedded null byte') on crafted X-Filename headers.
    Prefixes "_" when the stem matches a Windows-reserved device name
    (CON, PRN, COM1-9, LPT1-9, ...).
    """
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", name)
    name = name.strip(". ")
    if not name:
        return "untitled"
    stem, _dot, _ext = name.partition(".")
    if stem.upper() in _WINDOWS_RESERVED_NAMES:
        name = "_" + name
    return name[:200]


def download_audio(url: str, workdir: str) -> tuple[str, str]:
    """Download audio track via yt-dlp Python API and return (file_path, title)."""
    template = str(Path(workdir) / "%(id)s.%(ext)s")
    opts = {
        "format": "bestaudio/best",
        "outtmpl": template,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "opus",
            "preferredquality": "0",
        }],
    }
    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except Exception as e:
        raise RuntimeError(f"yt-dlp failed: {e}") from e

    title = (info or {}).get("title") or "Untitled"
    files = sorted(
        (f for f in Path(workdir).iterdir() if f.is_file()),
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )
    if files:
        return str(files[0]), title
    raise FileNotFoundError("yt-dlp produced no audio file")


def compute_middle(total_sec: float, duration_min: float) -> tuple[float, float, str]:
    """Return (start_sec, extract_sec, info_message) for the middle segment."""
    if not math.isfinite(total_sec) or total_sec <= 0:
        raise ValueError(f"total_sec must be a positive finite number, got {total_sec}")
    if not math.isfinite(duration_min) or duration_min <= 0:
        raise ValueError(f"duration_min must be a positive finite number, got {duration_min}")
    extract_sec = duration_min * 60
    if total_sec <= extract_sec:
        msg = f"Source shorter than {duration_min}m -- using full duration ({total_sec:.0f}s)"
        return 0.0, total_sec, msg
    start = (total_sec - extract_sec) / 2
    msg = f"Total {total_sec:.0f}s -> extracting {start:.0f}s - {start + extract_sec:.0f}s"
    return start, extract_sec, msg
