"""analyze-spectrum: audio spectral analysis tool."""

import subprocess
import sys

__version__ = "0.9.1"


def _subprocess_kwargs() -> dict:
    """Return platform-specific kwargs for subprocess calls.

    On frozen Windows builds (PyInstaller), hide the console window
    spawned by subprocess for ffmpeg / yt-dlp.
    """
    if sys.platform == "win32" and getattr(sys, "frozen", False):
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        return {"startupinfo": si}
    return {}
