#!/usr/bin/env python3
"""Bake the source SVG logo into the assets the Worker bundles.

Run this whenever input/maryland-logo.svg changes:

    uv run --with resvg-py --with pillow python scripts/bake_logo.py

Why this exists: the Worker's SVG output embeds the logo as vector, but its PNG
output has to composite a raster logo, and rasterizing SVG needs a real SVG
renderer - native code, so it cannot run on Cloudflare Workers. We therefore
rasterize once here, at build time, and ship the PNG alongside the SVG.

We use resvg (a self-contained Rust wheel) rather than cairosvg because
cairosvg needs a system libcairo that Windows dev boxes generally lack. resvg
also handles the luminance mask in the Maryland logo correctly.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE_SVG = ROOT / "input" / "maryland-logo.svg"
ASSET_DIR = ROOT / "src" / "assets"

# Generously oversized so the Worker only ever downsamples (LANCZOS down looks
# far better than any upscale). The QR codes we emit top out around 650px wide
# and the logo occupies ~22% of that, so ~512px is several times what we need.
RASTER_WIDTH = 512


def main() -> int:
    if not SOURCE_SVG.is_file():
        print(f"error: missing source logo: {SOURCE_SVG}", file=sys.stderr)
        return 1

    try:
        import resvg_py
    except ImportError:
        print(
            "error: resvg-py is not installed. Run:\n"
            "  uv run --with resvg-py --with pillow python scripts/bake_logo.py",
            file=sys.stderr,
        )
        return 1

    ASSET_DIR.mkdir(parents=True, exist_ok=True)

    dest_svg = ASSET_DIR / SOURCE_SVG.name
    shutil.copyfile(SOURCE_SVG, dest_svg)
    print(f"copied  {dest_svg.relative_to(ROOT)}")

    raster = bytes(
        resvg_py.svg_to_bytes(svg_string=SOURCE_SVG.read_text(encoding="utf-8"), width=RASTER_WIDTH)
    )

    dest_png = dest_svg.with_suffix(".png")
    dest_png.write_bytes(raster)

    from PIL import Image

    with Image.open(dest_png) as img:
        if img.mode != "RGBA":
            print(
                f"warning: expected an RGBA logo, got {img.mode}. A logo without an "
                "alpha channel will paint an opaque box over the QR modules.",
                file=sys.stderr,
            )
        alpha = img.getchannel("A") if img.mode == "RGBA" else None
        transparent = "yes" if alpha and alpha.getextrema()[0] == 0 else "no"
        print(
            f"wrote   {dest_png.relative_to(ROOT)} "
            f"({img.width}x{img.height}, mode={img.mode}, transparency={transparent})"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
