"""analyze-spectrum: audio spectral analysis tool."""

import sys
from pathlib import Path

_VENDOR = Path(__file__).resolve().parents[2] / "vendor" / "py-analyze-common" / "src"
if _VENDOR.is_dir() and str(_VENDOR) not in sys.path:
    sys.path.insert(0, str(_VENDOR))

from analyze_common.ffmpeg import ffmpeg_kwargs as _ffmpeg_kwargs  # noqa: E402,F401

__version__ = "1.5.0"

SCHEMA_VERSION = 1


def make_meta(source: str, duration_min: float | None = None) -> dict:
    """Build the shared meta payload attached to single/compare JSON output.

    duration_min is the length in minutes the analysis was asked to cut out of
    the middle of the source; a full-length analysis has no such field.
    """
    from datetime import datetime, timezone
    meta = {
        "schema_version": SCHEMA_VERSION,
        "version": __version__,
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
        "source": source,
    }
    if duration_min is not None:
        meta["duration_min"] = duration_min
    return meta
