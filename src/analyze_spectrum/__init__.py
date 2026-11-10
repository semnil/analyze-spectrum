"""analyze-spectrum: audio spectral analysis tool."""

import sys
from pathlib import Path

_VENDOR = Path(__file__).resolve().parents[2] / "vendor" / "py-analyze-common" / "src"
if _VENDOR.is_dir() and str(_VENDOR) not in sys.path:
    sys.path.insert(0, str(_VENDOR))

from analyze_common.ffmpeg import ffmpeg_kwargs as _ffmpeg_kwargs  # noqa: E402,F401

__version__ = "1.6.2"

SCHEMA_VERSION = 2


def recorded_minutes(duration_min: float | None, start_sec: float | None) -> float | None:
    """The minutes to record for an analysis asked for duration_min that started at start_sec.

    None when it has no start, which is an analysis of the whole source.
    """
    return duration_min if start_sec else None


def _meta(fields: dict, duration_min: float | None) -> dict:
    from datetime import datetime, timezone
    meta = {
        "schema_version": SCHEMA_VERSION,
        "version": __version__,
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
        **fields,
    }
    if duration_min is not None:
        meta["duration_min"] = duration_min
    return meta


def make_meta(source: str, duration_min: float | None = None) -> dict:
    """Build the meta payload attached to single JSON output.

    duration_min is the length in minutes the analysis cut out of the middle of
    the source; an analysis of the whole source has no such field.
    """
    return _meta({"source": source}, duration_min)


def make_compare_meta(sources: list[str], duration_min: float | None = None) -> dict:
    """Build the meta payload attached to comparison JSON output.

    duration_min is the length in minutes cut out of the middle of the sources; a
    comparison where every track is its whole source has no such field.
    """
    return _meta({"sources": list(sources)}, duration_min)
