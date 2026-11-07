"""Download audio via yt-dlp Python API and probe media info via ffprobe."""

from pathlib import Path

from analyze_common.download import (  # noqa: F401
    compute_middle,
    download_audio,
    is_url,
    sanitize_filename,
)


def middle_of(total_sec: float, duration_min: float) -> tuple[float | None, float | None, str]:
    """compute_middle(), with no start and no length when it uses the whole source.

    ffmpeg then reads to the end of the source, which can lie past the length ffprobe estimated.
    """
    start, length, message = compute_middle(total_sec, duration_min)
    return (start, length, message) if start else (None, None, message)


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
