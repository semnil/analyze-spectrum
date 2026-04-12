"""Generate icon.ico, icon.png rasters, and icon.iconset/ from icon_draft.svg.

Output:
  build_assets/icon.ico              — Windows ico (16-256)
  build_assets/icon.png              — 1024x1024 master PNG
  build_assets/icon.iconset/         — macOS iconset dir (input for iconutil)

On macOS (CI), `iconutil -c icns build_assets/icon.iconset` produces icon.icns.
"""

from pathlib import Path

import resvg_py
from PIL import Image

ROOT = Path(__file__).resolve().parent
SVG = ROOT / "icon_draft.svg"
ICO = ROOT / "icon.ico"
PNG = ROOT / "icon.png"
ICONSET = ROOT / "icon.iconset"

# (filename, size) for macOS iconset naming convention
ICONSET_SIZES = [
    ("icon_16x16.png", 16),
    ("icon_16x16@2x.png", 32),
    ("icon_32x32.png", 32),
    ("icon_32x32@2x.png", 64),
    ("icon_128x128.png", 128),
    ("icon_128x128@2x.png", 256),
    ("icon_256x256.png", 256),
    ("icon_256x256@2x.png", 512),
    ("icon_512x512.png", 512),
    ("icon_512x512@2x.png", 1024),
]

ICO_SIZES = [16, 24, 32, 48, 64, 128, 256]


def render_png(size: int, dest: Path) -> None:
    data = resvg_py.svg_to_bytes(svg_path=str(SVG), width=size, height=size)
    dest.write_bytes(bytes(data))


def build_ico() -> None:
    # Render each size independently from the SVG (not scaled from a single raster)
    # so low-res sizes use sharper source geometry instead of resampled pixels.
    biggest = max(ICO_SIZES)
    tmp_big = ROOT / f"_tmp_{biggest}.png"
    render_png(biggest, tmp_big)
    base = Image.open(tmp_big)
    base.load()
    base.save(ICO, format="ICO", sizes=[(s, s) for s in ICO_SIZES])
    base.close()
    tmp_big.unlink(missing_ok=True)
    print(f"  -> {ICO}")


def build_iconset() -> None:
    ICONSET.mkdir(exist_ok=True)
    for name, size in ICONSET_SIZES:
        render_png(size, ICONSET / name)
    print(f"  -> {ICONSET}/ ({len(ICONSET_SIZES)} files)")


def build_master() -> None:
    render_png(1024, PNG)
    print(f"  -> {PNG}")


def main() -> None:
    if not SVG.exists():
        raise SystemExit(f"Source SVG not found: {SVG}")
    print("Rendering icons from", SVG.name)
    build_master()
    build_ico()
    build_iconset()
    print("Done.")


if __name__ == "__main__":
    main()
