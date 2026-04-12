"""analyze-spectrum: audio spectral analysis tool."""

import sys
from pathlib import Path

# Make the py-desktop-app-common submodule importable as `desktop_app_common`.
_VENDOR = Path(__file__).resolve().parents[2] / "vendor" / "py-desktop-app-common" / "src"
if _VENDOR.is_dir() and str(_VENDOR) not in sys.path:
    sys.path.insert(0, str(_VENDOR))

from desktop_app_common.platform import subprocess_kwargs as _subprocess_kwargs  # noqa: E402,F401

__version__ = "0.9.2"
