"""Download audio via yt-dlp Python API and probe media info via ffprobe."""

from pathlib import Path

from analyze_common.download import (  # noqa: F401
    compute_middle,
    download_audio,
    is_url,
    sanitize_filename,
)


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
