"""Build script for analyze-spectrum.

Usage:
    python build.py                     # Download assets + verify + PyInstaller
    python build.py --installer         # + platform installer (Inno Setup / DMG)
    python build.py --skip-download     # Skip asset download (use existing)
    python build.py --update-checksums  # Download assets + update checksums.json

Prerequisites:
    pip install pyinstaller
    (Windows) Inno Setup 6: https://jrsoftware.org/isinfo.php
    (macOS)   create-dmg: brew install create-dmg
"""

import argparse
import hashlib
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

IS_WINDOWS = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"

ROOT = Path(__file__).resolve().parent
SPEC = ROOT / "analyze-spectrum.spec"
ISS = ROOT / "installer.iss"
DIST_BUNDLE = ROOT / "dist" / "analyze-spectrum"
DIST_APP = ROOT / "dist" / "Spectrum Analyzer.app"
BIN_DIR = ROOT / "build_assets" / "bin"
VENDOR_DIR = ROOT / "frontend" / "vendor"
CHECKSUMS_FILE = ROOT / "build_assets" / "checksums.json"

UPLOT_VERSION = "1.6.31"

_EXE = ".exe" if IS_WINDOWS else ""
REQUIRED_BINS = [f"ffmpeg{_EXE}", f"ffprobe{_EXE}", f"deno{_EXE}"]

# macOS 26 で「Intel プロセッサ用アプリの対応は終了します」警告を出さないため、
# arm64 ネイティブの ffmpeg/ffprobe を osxexperts.net から取得する (evermeet.cx は
# x86_64 専用ビルドのみ提供)。Intel Mac 向けの x86_64 サポートは行わない。
_OSXEXPERTS_ARM64 = {
    "ffmpeg": (
        "https://www.osxexperts.net/ffmpeg81arm.zip",
        "9a08d61f9328e8164ba560ee7a79958e357307fcfeea6fe626b7d66cdc287028",
    ),
    "ffprobe": (
        "https://www.osxexperts.net/ffprobe81arm.zip",
        "aab17ac7379c1178aaf400c3ef36cdb67db0b75b1a23eeef2cb9f658be8844e6",
    ),
}


def _read_version():
    import re
    init = ROOT / "src" / "analyze_spectrum" / "__init__.py"
    match = re.search(r'__version__\s*=\s*"([^"]+)"', init.read_text())
    return match.group(1)


def _sha256(path: Path) -> str:
    """Compute SHA256 hex digest for a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_checksums() -> dict:
    if CHECKSUMS_FILE.exists():
        return json.loads(CHECKSUMS_FILE.read_text(encoding="utf-8"))
    return {}


def _save_checksums(checksums: dict):
    CHECKSUMS_FILE.parent.mkdir(parents=True, exist_ok=True)
    CHECKSUMS_FILE.write_text(
        json.dumps(checksums, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"\nChecksums saved: {CHECKSUMS_FILE}")


def _verify_checksums():
    """Verify uPlot CDN assets against checksums.json. ffmpeg/ffprobe arm64 は
    `_download_ffmpeg_macos()` 内で個別 SHA 検証する。deno と Windows ffmpeg は
    動的ソース (latest tag / master build) のため事前固定対象外。"""
    all_checksums = _load_checksums()
    uplot = all_checksums.get("uplot") if all_checksums else None
    if not uplot:
        print("WARNING: checksums.json missing or has no uplot entry -- skipping")
        print("  Run 'python build.py --update-checksums' to generate it")
        return

    errors = []
    for file_key, expected_hash in uplot.items():
        if not file_key.startswith("sha256_"):
            continue
        filename = file_key.replace("sha256_", "", 1)
        path = VENDOR_DIR / filename
        if not path.exists():
            errors.append(f"  {path.name}: file not found")
            continue
        actual = _sha256(path)
        if actual != expected_hash:
            errors.append(
                f"  {path.name}: MISMATCH\n"
                f"    expected: {expected_hash}\n"
                f"    actual:   {actual}"
            )
        else:
            print(f"  {path.name}: OK")

    if errors:
        print("\nChecksum verification FAILED:")
        for e in errors:
            print(e)
        print("\nIf assets were intentionally updated, run:")
        print("  python build.py --update-checksums")
        sys.exit(1)
    else:
        print("All checksums verified.")


def download_assets() -> None:
    """Download or update all external assets."""
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    VENDOR_DIR.mkdir(parents=True, exist_ok=True)

    _download_deno()
    _download_ffmpeg()
    _download_uplot()


def _make_executable(path: Path) -> None:
    if not IS_WINDOWS:
        path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def _github_api_open(url: str):
    """Open a GitHub API URL, adding auth header if GITHUB_TOKEN is set (avoids 60/hr rate limit)."""
    req = urllib.request.Request(url)
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    return urllib.request.urlopen(req)


def _download_deno():
    """Download latest deno binary (required by yt-dlp for YouTube JS extraction)."""
    deno_exe = f"deno{_EXE}"
    dest = BIN_DIR / deno_exe
    print("Fetching latest deno release info...")
    with _github_api_open(
        "https://api.github.com/repos/denoland/deno/releases/latest"
    ) as r:
        release = json.loads(r.read())
    tag = release["tag_name"]

    if dest.exists():
        print(f"  {deno_exe} exists, updating to {tag}...")
    else:
        print(f"  Downloading deno {tag}...")

    if IS_WINDOWS:
        asset = "deno-x86_64-pc-windows-msvc.zip"
    elif IS_MAC:
        # Universal2 is not provided; grab arm64 for Apple Silicon runners.
        asset = "deno-aarch64-apple-darwin.zip"
    else:
        asset = "deno-x86_64-unknown-linux-gnu.zip"

    url = f"https://github.com/denoland/deno/releases/download/{tag}/{asset}"
    with urllib.request.urlopen(url) as r:
        data = io.BytesIO(r.read())

    member = "deno.exe" if IS_WINDOWS else "deno"
    with zipfile.ZipFile(data) as zf:
        with zf.open(member) as src, open(dest, "wb") as dst:
            shutil.copyfileobj(src, dst)
    _make_executable(dest)
    print(f"  -> {dest} ({dest.stat().st_size // 1024 // 1024} MB)")


def _get_ffmpeg_win_url() -> str:
    """Get the download URL for the latest ffmpeg win64 build."""
    print("Fetching latest ffmpeg release info (BtbN/FFmpeg-Builds)...")
    with _github_api_open(
        "https://api.github.com/repos/BtbN/FFmpeg-Builds/releases"
    ) as r:
        releases = json.loads(r.read())

    # Prefer LGPL essentials build (smaller, no GPL-only codecs)
    for prefer in ("lgpl", "gpl"):
        for release in releases:
            for asset in release.get("assets", []):
                name = asset["name"]
                if ("win64" in name and prefer in name
                        and name.endswith(".zip") and "shared" not in name):
                    print(f"  Found: {name}")
                    return asset["browser_download_url"]

    raise RuntimeError("Could not find a suitable ffmpeg build")


def _download_ffmpeg():
    """Download latest ffmpeg/ffprobe build for the current platform."""
    if IS_WINDOWS:
        _download_ffmpeg_windows()
    elif IS_MAC:
        _download_ffmpeg_macos()
    else:
        raise RuntimeError(f"Unsupported platform: {sys.platform}")


def _download_ffmpeg_windows():
    url = _get_ffmpeg_win_url()
    print("Downloading ffmpeg (win64)...")
    with urllib.request.urlopen(url) as r:
        data = io.BytesIO(r.read())

    with zipfile.ZipFile(data) as zf:
        for name in zf.namelist():
            basename = Path(name).name
            if basename in ("ffmpeg.exe", "ffprobe.exe"):
                dest = BIN_DIR / basename
                with zf.open(name) as src, open(dest, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                print(f"  -> {dest} ({dest.stat().st_size // 1024 // 1024} MB)")


def _extract_zip_to(data: bytes, member_basename: str, dest: Path):
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        member = next(m for m in zf.namelist() if Path(m).name == member_basename)
        with zf.open(member) as src, open(dest, "wb") as dst:
            shutil.copyfileobj(src, dst)


def _download_ffmpeg_macos():
    """Download arm64-native ffmpeg/ffprobe (osxexperts.net) with SHA256 verification."""
    for name in ("ffmpeg", "ffprobe"):
        arm_url, arm_sha = _OSXEXPERTS_ARM64[name]
        print(f"Downloading {name} arm64 (osxexperts.net)...")
        with urllib.request.urlopen(arm_url) as r:
            arm_data = r.read()
        dest = BIN_DIR / name
        _extract_zip_to(arm_data, name, dest)
        actual = _sha256(dest)
        if actual != arm_sha:
            raise RuntimeError(
                f"{name} arm64 SHA256 mismatch: expected {arm_sha}, got {actual}"
            )
        _make_executable(dest)
        size_mb = dest.stat().st_size // 1024 // 1024
        print(f"  -> {dest} ({size_mb} MB, arm64)")


def _download_uplot():
    """Download uPlot JS/CSS."""
    base = f"https://cdn.jsdelivr.net/npm/uplot@{UPLOT_VERSION}/dist"
    for filename in ("uPlot.iife.min.js", "uPlot.min.css"):
        dest = VENDOR_DIR / filename
        print(f"Downloading {filename}...")
        urllib.request.urlretrieve(f"{base}/{filename}", dest)
        print(f"  -> {dest}")


def update_checksums():
    """Download assets and compute checksums.json for static CDN-hosted uPlot.

    deno (latest), ffmpeg/ffprobe (BtbN master / osxexperts version-pinned)
    は更新ペースが速くプラットフォーム間でも内容が異なるため事前 SHA 固定の
    対象外。osxexperts arm64 は build.py 内 `_OSXEXPERTS_ARM64` で個別検証する。
    """
    download_assets()

    print("\nComputing checksums for uPlot CDN assets...")
    uplot_entry = {"version": UPLOT_VERSION}
    for filename in ("uPlot.iife.min.js", "uPlot.min.css"):
        h = _sha256(VENDOR_DIR / filename)
        uplot_entry[f"sha256_{filename}"] = h
        print(f"  {filename}: {h[:16]}...")

    _save_checksums({"uplot": uplot_entry})


def check_prerequisites():
    """Verify all build requirements are met."""
    errors = []

    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        errors.append("PyInstaller not installed: pip install pyinstaller")

    for name in REQUIRED_BINS:
        if not (BIN_DIR / name).exists():
            errors.append(f"Missing binary: build_assets/bin/{name}")

    if errors:
        print("Build prerequisites not met:")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)


def _build_icns_macos():
    """Generate icon.icns from icon.iconset/ on macOS so .app bundles carry the icon."""
    if not IS_MAC:
        return
    iconset = ROOT / "build_assets" / "icon.iconset"
    icns = ROOT / "build_assets" / "icon.icns"
    if not iconset.is_dir():
        print(f"WARNING: {iconset} not found -- .app will lack an icon")
        return
    iconutil = shutil.which("iconutil")
    if not iconutil:
        print("WARNING: iconutil not found -- .app will lack an icon")
        return
    print("Building icon.icns from icon.iconset/ ...")
    subprocess.run(
        [iconutil, "-c", "icns", str(iconset), "-o", str(icns)],
        check=True,
    )
    print(f"  -> {icns}")


def build_pyinstaller():
    """Run PyInstaller to create the application bundle."""
    _build_icns_macos()
    print("\n" + "=" * 60)
    print("  Building with PyInstaller...")
    print("=" * 60)
    subprocess.run(
        [sys.executable, "-m", "PyInstaller", str(SPEC), "--noconfirm"],
        check=True,
    )
    out = DIST_APP if IS_MAC else DIST_BUNDLE
    print(f"\nBuild output: {out}")


def build_installer():
    """Dispatch to the platform-specific installer builder."""
    if IS_WINDOWS:
        _build_inno()
    elif IS_MAC:
        _build_dmg()
    else:
        print(f"No installer builder configured for {sys.platform}.")


def _build_dmg():
    """Run create-dmg to package the macOS .app into a DMG."""
    if not DIST_APP.exists():
        print(f"\n.app bundle not found: {DIST_APP}. Skipping DMG creation.")
        return

    create_dmg = shutil.which("create-dmg")
    if not create_dmg:
        print("\ncreate-dmg not found. Install with: brew install create-dmg")
        return

    output_dir = ROOT / "installer_output"
    output_dir.mkdir(parents=True, exist_ok=True)
    dmg_path = output_dir / "Spectrum-Analyzer.dmg"
    if dmg_path.exists():
        dmg_path.unlink()

    print("\n" + "=" * 60)
    print("  Building DMG with create-dmg...")
    print("=" * 60)
    subprocess.run(
        [
            create_dmg,
            "--volname", "Spectrum Analyzer",
            "--window-size", "600", "400",
            "--icon-size", "100",
            "--icon", "Spectrum Analyzer.app", "150", "180",
            "--app-drop-link", "450", "180",
            "--no-internet-enable",
            str(dmg_path),
            str(DIST_APP),
        ],
        check=True,
    )
    print(f"\nInstaller output: {dmg_path}")


def _build_inno():
    """Run Inno Setup to create the Windows installer."""
    iscc = shutil.which("iscc")
    if not iscc:
        local_appdata = os.environ.get("LOCALAPPDATA", "")
        for path in [
            r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
            r"C:\Program Files\Inno Setup 6\ISCC.exe",
            os.path.join(local_appdata, r"Programs\Inno Setup 6\ISCC.exe"),
        ]:
            if Path(path).exists():
                iscc = path
                break

    if not iscc:
        print("\nInno Setup (ISCC.exe) not found. Skipping installer creation.")
        print("Install from: https://jrsoftware.org/isinfo.php")
        return

    print("\n" + "=" * 60)
    print("  Building installer with Inno Setup...")
    print("=" * 60)
    version = _read_version()
    subprocess.run([iscc, f"/DMyAppVersion={version}", str(ISS)], check=True)
    output_dir = ROOT / "installer_output"
    print(f"\nInstaller output: {output_dir}")


def main():
    parser = argparse.ArgumentParser(description="Build analyze-spectrum")
    parser.add_argument("--installer", action="store_true",
                        help="Also build Inno Setup installer")
    parser.add_argument("--skip-download", action="store_true",
                        help="Skip downloading/updating external assets")
    parser.add_argument("--skip-build", action="store_true",
                        help="Skip PyInstaller build (assumes dist/ already exists)")
    parser.add_argument("--update-checksums", action="store_true",
                        help="Download assets and update checksums.json")
    args = parser.parse_args()

    if args.update_checksums:
        update_checksums()
        return

    if not args.skip_download:
        download_assets()

    if not args.skip_build:
        print("\nVerifying checksums...")
        _verify_checksums()
        check_prerequisites()
        build_pyinstaller()

    if args.installer:
        build_installer()

    print("\nDone.")


if __name__ == "__main__":
    main()
