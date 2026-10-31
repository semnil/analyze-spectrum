"""Build script for analyze-spectrum: py-analyze-common's analyze_common.build with this app's names.

Usage:
    python build.py                     # Download assets + verify + PyInstaller
    python build.py --installer         # + platform installer (Inno Setup / DMG)
    python build.py --skip-download     # Skip asset download (use existing)
    python build.py --skip-build        # Skip PyInstaller build
    python build.py --update-checksums  # Download assets + update checksums.json
    python build.py --ffmpeg-only       # Download ffmpeg/ffprobe into build_assets/bin only

Prerequisites:
    pip install pyinstaller
    (Windows) Inno Setup 6: https://jrsoftware.org/isinfo.php
    (macOS)   create-dmg: brew install create-dmg
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

sys.path.insert(0, str(ROOT / "vendor" / "py-analyze-common" / "src"))
from analyze_common import build  # noqa: E402

APP = build.App(root=ROOT, package="analyze_spectrum", display_name="Spectrum Analyzer", uplot_version="1.6.31")

if __name__ == "__main__":
    build.main(APP)
