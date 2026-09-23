#!/usr/bin/env python3
"""simple-qr-cli: generate QR codes from the command line.

The rendering itself lives in src/qrrender.py, which the Cloudflare Worker
imports too, so the CLI and the web API place logos identically.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

import qrrender  # noqa: E402  (needs the sys.path entry above)
from qrrender import ERROR_LEVELS, infer_format, infer_logo_kind  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="qr",
        description="Generate a QR code image (PNG, JPG, or SVG), optionally with a center logo.",
    )
    parser.add_argument(
        "data",
        help="Data to encode (typically a URL, but any text works).",
    )
    parser.add_argument(
        "-o", "--output",
        required=True,
        help="Output filename. Format is inferred from the extension (.png, .jpg, .jpeg, .svg).",
    )
    parser.add_argument(
        "-e", "--error-correction",
        default=None,
        choices=list(ERROR_LEVELS),
        help="Error correction level: L (~7%%), M (~15%%), Q (~25%%), H (~30%%). "
             "Default: M, or H when --logo is set.",
    )
    parser.add_argument(
        "-c", "--color",
        default="black",
        help="Foreground (module) color. Named color or hex. Default: black.",
    )
    parser.add_argument(
        "-b", "--background",
        default="white",
        help="Background color. Named color, hex, or 'transparent' (PNG/SVG only). Default: white.",
    )
    parser.add_argument(
        "--logo",
        default=None,
        help="Path to a logo file (PNG, JPG, or SVG) to place in the center of the code.",
    )
    parser.add_argument(
        "--logo-scale",
        type=float,
        default=qrrender.DEFAULT_LOGO_SCALE,
        help=f"Logo size as a fraction of the QR width, 0 < x < 1. "
             f"Default: {qrrender.DEFAULT_LOGO_SCALE}. "
             f"Values above ~{qrrender.MAX_SAFE_LOGO_SCALE} make the code unlikely to scan.",
    )
    parser.add_argument(
        "--logo-backing",
        default="white",
        help="Solid color drawn behind the logo (named color, hex, or 'transparent'). Default: white.",
    )
    parser.add_argument(
        "--square-backing",
        action="store_true",
        help="Force the logo backing to be square instead of matching the logo's aspect ratio. "
             "Useful for near-square logos where a square backing looks cleaner.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    output = Path(args.output)

    try:
        ext = infer_format(output)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    logo_path: Path | None = None
    if args.logo:
        logo_path = Path(args.logo)
        if not logo_path.is_file():
            print(f"error: logo file not found: {logo_path}", file=sys.stderr)
            return 2
        try:
            infer_logo_kind(logo_path)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        if not 0.0 < args.logo_scale < 1.0:
            print(
                f"error: --logo-scale must be > 0 and < 1 (got {args.logo_scale})",
                file=sys.stderr,
            )
            return 2

    if args.error_correction is None:
        level_name = qrrender.default_error_level(logo_path is not None)
    else:
        level_name = args.error_correction

    qr = qrrender.build_qr(args.data, ERROR_LEVELS[level_name])

    try:
        if ext == "svg":
            svg = qrrender.render_svg(
                qr, args.color, args.background,
                logo_path, args.logo_scale, args.logo_backing,
                args.square_backing,
            )
            output.write_text(svg, encoding="utf-8")
        else:
            blob = qrrender.render_raster(
                qr, ext, args.color, args.background,
                logo_path, args.logo_scale, args.logo_backing,
                args.square_backing,
            )
            output.write_bytes(blob)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    msg = f"wrote {output} ({ext.upper()}) [error correction: {level_name}"
    if logo_path is not None:
        msg += f", logo: {logo_path.name} @ {args.logo_scale}"
    msg += "]"
    print(msg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
