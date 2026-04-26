# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for analyze-spectrum GUI application."""

import os
import sys

ROOT = os.path.abspath(".")
IS_WINDOWS = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"

_EXE = ".exe" if IS_WINDOWS else ""
_BINARIES = [
    (os.path.join(ROOT, f"build_assets/bin/ffmpeg{_EXE}"), "bin"),
    (os.path.join(ROOT, f"build_assets/bin/ffprobe{_EXE}"), "bin"),
    (os.path.join(ROOT, f"build_assets/bin/deno{_EXE}"), "bin"),
]

a = Analysis(
    ["src/analyze_spectrum/gui.py"],
    pathex=[
        os.path.join(ROOT, "src"),
        os.path.join(ROOT, "vendor/py-analyze-common/src"),
    ],
    binaries=_BINARIES,
    datas=[
        (os.path.join(ROOT, "frontend"), "frontend"),
        (os.path.join(ROOT, "THIRD_PARTY_LICENSES.txt"), "."),
        (os.path.join(ROOT, "build_assets/icon.ico"), "build_assets"),
    ],
    hiddenimports=[
        "analyze_spectrum",
        "analyze_spectrum.analysis",
        "analyze_spectrum.download",
        "analyze_spectrum.pcm",
        "analyze_spectrum.gui",
        "analyze_common",
        "analyze_common.platform",
        "analyze_common.theme",
        "analyze_common.ffmpeg",
        "analyze_common.download",
        "analyze_common.json_util",
        "webview",
        "scipy.signal._signaltools",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "matplotlib",
        "tkinter",
        "static_ffmpeg",
        "aws_sam_cli",
        "awscli",
        "botocore",
        "pytest",
        "cryptography",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

_ICON = None
if IS_WINDOWS and os.path.exists(os.path.join(ROOT, "build_assets/icon.ico")):
    _ICON = os.path.join(ROOT, "build_assets/icon.ico")
elif IS_MAC and os.path.exists(os.path.join(ROOT, "build_assets/icon.icns")):
    _ICON = os.path.join(ROOT, "build_assets/icon.icns")

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="analyze-spectrum",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=not IS_MAC,
    console=False,
    icon=_ICON,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=not IS_MAC,
    upx_exclude=[],
    name="analyze-spectrum",
)

if IS_MAC:
    app = BUNDLE(
        coll,
        name="Spectrum Analyzer.app",
        icon=_ICON,
        bundle_identifier="com.semnil.spectrum-analyzer",
        version="1.2.0",
        info_plist={
            "CFBundleName": "Spectrum Analyzer",
            "CFBundleDisplayName": "Spectrum Analyzer",
            "CFBundleShortVersionString": "1.2.0",
            "CFBundleVersion": "1.2.0",
            "LSMinimumSystemVersion": "11.0",
            "NSHighResolutionCapable": True,
            "LSEnvironment": {"PYTHONIOENCODING": "utf-8"},
        },
    )
