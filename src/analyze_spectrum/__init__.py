"""analyze-spectrum: audio spectral analysis tool."""

import os
import sys
from pathlib import Path

# Make the py-desktop-app-common submodule importable as `desktop_app_common`.
_VENDOR = Path(__file__).resolve().parents[2] / "vendor" / "py-desktop-app-common" / "src"
if _VENDOR.is_dir() and str(_VENDOR) not in sys.path:
    sys.path.insert(0, str(_VENDOR))

from desktop_app_common.platform import subprocess_kwargs as _subprocess_kwargs  # noqa: E402,F401


def _ffmpeg_kwargs() -> dict:
    """Return subprocess kwargs with LC_ALL=C for ffmpeg / ffprobe.

    Some ffmpeg / ffprobe stderr / stdout text paths depend on the C locale
    (e.g. '.' as decimal separator).  Non-C locales can substitute ',' and
    break downstream parsing.  Apply unconditionally so new stderr parsers
    added later stay robust.
    """
    kwargs = dict(_subprocess_kwargs())
    env = dict(kwargs["env"]) if "env" in kwargs else os.environ.copy()
    env["LC_ALL"] = "C"
    env["LANG"] = "C"
    kwargs["env"] = env
    return kwargs


__version__ = "0.9.5"

SCHEMA_VERSION = 1


def make_meta(source: str) -> dict:
    """Build the shared meta payload attached to single/compare JSON output."""
    from datetime import datetime, timezone
    return {
        "schema_version": SCHEMA_VERSION,
        "version": __version__,
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
        "source": source,
    }
