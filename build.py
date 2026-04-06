"""Build script for analyze-spectrum Windows installer.

Usage:
    python build.py                     # Download assets + verify + PyInstaller
    python build.py --installer         # + Inno Setup installer
    python build.py --skip-download     # Skip asset download (use existing)
    python build.py --update-checksums  # Download assets + update checksums.json

Prerequisites:
    pip install pyinstaller
    Inno Setup 6 (for --installer flag): https://jrsoftware.org/isinfo.php
"""

import argparse
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SPEC = ROOT / "analyze-spectrum.spec"
ISS = ROOT / "installer.iss"
DIST = ROOT / "dist" / "analyze-spectrum"
BIN_DIR = ROOT / "build_assets" / "bin"
VENDOR_DIR = ROOT / "frontend" / "vendor"
CHECKSUMS_FILE = ROOT / "build_assets" / "checksums.json"

UPLOT_VERSION = "1.6.31"

REQUIRED_BINS = ["ffmpeg.exe", "ffprobe.exe", "yt-dlp.exe"]


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
    """Verify all downloaded assets against checksums.json."""
    checksums = _load_checksums()
    if not checksums:
        print("WARNING: checksums.json not found -- skipping verification")
        print("  Run 'python build.py --update-checksums' to generate it")
        return

    errors = []
    for key, entry in checksums.items():
        for file_key, expected_hash in entry.items():
            if not file_key.startswith("sha256_"):
                continue
            filename = file_key.replace("sha256_", "", 1)
            if filename in ("zip",):
                continue
            if key == "uplot":
                path = VENDOR_DIR / filename
            else:
                path = BIN_DIR / filename
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


def download_assets() -> str:
    """Download or update all external assets. Returns yt-dlp version tag."""
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    VENDOR_DIR.mkdir(parents=True, exist_ok=True)

    ytdlp_tag = _download_ytdlp()
    _download_deno()
    _download_ffmpeg()
    _download_uplot()
    return ytdlp_tag


def _get_ytdlp_latest_tag() -> str:
    with urllib.request.urlopen(
        "https://api.github.com/repos/yt-dlp/yt-dlp/releases/latest"
    ) as r:
        return json.loads(r.read())["tag_name"]


def _download_ytdlp() -> str:
    """Download latest yt-dlp.exe. Returns the version tag."""
    dest = BIN_DIR / "yt-dlp.exe"
    print("Fetching latest yt-dlp release info...")
    tag = _get_ytdlp_latest_tag()

    if dest.exists():
        print(f"  yt-dlp.exe exists, updating to {tag}...")
    else:
        print(f"  Downloading yt-dlp {tag}...")

    url = f"https://github.com/yt-dlp/yt-dlp/releases/download/{tag}/yt-dlp.exe"
    urllib.request.urlretrieve(url, dest)
    print(f"  -> {dest} ({dest.stat().st_size // 1024 // 1024} MB)")
    return tag


def _download_deno():
    """Download latest deno.exe (required by yt-dlp for YouTube JS extraction)."""
    dest = BIN_DIR / "deno.exe"
    print("Fetching latest deno release info...")
    with urllib.request.urlopen(
        "https://api.github.com/repos/denoland/deno/releases/latest"
    ) as r:
        release = json.loads(r.read())
    tag = release["tag_name"]

    if dest.exists():
        print(f"  deno.exe exists, updating to {tag}...")
    else:
        print(f"  Downloading deno {tag}...")

    url = f"https://github.com/denoland/deno/releases/download/{tag}/deno-x86_64-pc-windows-msvc.zip"
    with urllib.request.urlopen(url) as r:
        data = io.BytesIO(r.read())

    with zipfile.ZipFile(data) as zf:
        with zf.open("deno.exe") as src, open(dest, "wb") as dst:
            shutil.copyfileobj(src, dst)
    print(f"  -> {dest} ({dest.stat().st_size // 1024 // 1024} MB)")


def _get_ffmpeg_url() -> str:
    """Get the download URL for the latest ffmpeg win64 build."""
    print("Fetching latest ffmpeg release info...")
    with urllib.request.urlopen(
        "https://api.github.com/repos/BtbN/FFmpeg-Builds/releases"
    ) as r:
        releases = json.loads(r.read())

    # Prefer LGPL essentials build (smaller, no GPL-only codecs)
    # Fallback to GPL if LGPL not found
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
    """Download latest ffmpeg/ffprobe Windows build."""
    url = _get_ffmpeg_url()
    print(f"Downloading ffmpeg (win64)...")
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


def _download_uplot():
    """Download uPlot JS/CSS."""
    base = f"https://cdn.jsdelivr.net/npm/uplot@{UPLOT_VERSION}/dist"
    for filename in ("uPlot.iife.min.js", "uPlot.min.css"):
        dest = VENDOR_DIR / filename
        print(f"Downloading {filename}...")
        urllib.request.urlretrieve(f"{base}/{filename}", dest)
        print(f"  -> {dest}")


def update_checksums():
    """Download assets and compute checksums.json."""
    ytdlp_tag = download_assets()

    print("\nComputing checksums...")
    checksums = {}

    # yt-dlp
    ytdlp_path = BIN_DIR / "yt-dlp.exe"
    checksums["yt-dlp"] = {
        "version": ytdlp_tag,
        "sha256_yt-dlp.exe": _sha256(ytdlp_path),
    }
    print(f"  yt-dlp.exe ({tag}): {checksums['yt-dlp']['sha256_yt-dlp.exe'][:16]}...")

    # deno
    deno_path = BIN_DIR / "deno.exe"
    checksums["deno"] = {
        "sha256_deno.exe": _sha256(deno_path),
    }
    print(f"  deno.exe: {checksums['deno']['sha256_deno.exe'][:16]}...")

    # ffmpeg / ffprobe
    checksums["ffmpeg"] = {}
    for name in ("ffmpeg.exe", "ffprobe.exe"):
        path = BIN_DIR / name
        h = _sha256(path)
        checksums["ffmpeg"][f"sha256_{name}"] = h
        print(f"  {name}: {h[:16]}...")

    # uPlot
    checksums["uplot"] = {"version": UPLOT_VERSION}
    for filename in ("uPlot.iife.min.js", "uPlot.min.css"):
        path = VENDOR_DIR / filename
        h = _sha256(path)
        checksums["uplot"][f"sha256_{filename}"] = h
        print(f"  {filename}: {h[:16]}...")

    _save_checksums(checksums)


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


def build_pyinstaller():
    """Run PyInstaller to create the application bundle."""
    print("\n" + "=" * 60)
    print("  Building with PyInstaller...")
    print("=" * 60)
    subprocess.run(
        [sys.executable, "-m", "PyInstaller", str(SPEC), "--noconfirm"],
        check=True,
    )
    print(f"\nBuild output: {DIST}")
    print(f"Executable: {DIST / 'analyze-spectrum.exe'}")


def build_installer():
    """Run Inno Setup to create the installer."""
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
    subprocess.run([iscc, str(ISS)], check=True)
    output_dir = ROOT / "installer_output"
    print(f"\nInstaller output: {output_dir}")


def main():
    parser = argparse.ArgumentParser(description="Build analyze-spectrum")
    parser.add_argument("--installer", action="store_true",
                        help="Also build Inno Setup installer")
    parser.add_argument("--skip-download", action="store_true",
                        help="Skip downloading/updating external assets")
    parser.add_argument("--update-checksums", action="store_true",
                        help="Download assets and update checksums.json")
    args = parser.parse_args()

    if args.update_checksums:
        update_checksums()
        return

    if not args.skip_download:
        download_assets()

    print("\nVerifying checksums...")
    _verify_checksums()

    check_prerequisites()
    build_pyinstaller()

    if args.installer:
        build_installer()

    print("\nDone.")


if __name__ == "__main__":
    main()
