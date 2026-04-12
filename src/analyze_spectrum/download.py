"""Download audio via yt-dlp Python API and probe media info via ffprobe."""

import re
import subprocess
from pathlib import Path

from yt_dlp import YoutubeDL

from analyze_spectrum import _subprocess_kwargs


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
                              encoding="utf-8", **_subprocess_kwargs())
    except subprocess.CalledProcessError as e:
        stderr_tail = (e.stderr or "")[-500:]
        raise RuntimeError(f"{cmd[0]} failed (exit {e.returncode}): {stderr_tail}") from e


def sanitize_filename(name: str) -> str:
    """Remove or replace characters that are unsafe for filenames."""
    name = re.sub(r'[\\/:*?"<>|]', "_", name)
    name = name.strip(". ")
    return name[:200] if name else "untitled"


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
    files = [f for f in Path(workdir).iterdir() if f.is_file()]
    if files:
        return str(files[0]), title
    raise FileNotFoundError("yt-dlp produced no audio file")


def compute_middle(total_sec: float, duration_min: float) -> tuple[float, float, str]:
    """Return (start_sec, extract_sec, info_message) for the middle segment."""
    if duration_min <= 0:
        raise ValueError(f"duration_min must be positive, got {duration_min}")
    extract_sec = duration_min * 60
    if total_sec <= extract_sec:
        msg = f"Source shorter than {duration_min}m -- using full duration ({total_sec:.0f}s)"
        return 0.0, total_sec, msg
    start = (total_sec - extract_sec) / 2
    msg = f"Total {total_sec:.0f}s -> extracting {start:.0f}s - {start + extract_sec:.0f}s"
    return start, extract_sec, msg
