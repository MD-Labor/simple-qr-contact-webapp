"""Shared QR rendering core: data -> SVG string or PNG bytes.

Extracted from the qr.py CLI so the CLI and the Cloudflare Worker share one
implementation of the geometry (logo sizing, grid snapping, backing rect,
error-correction defaults). Rendering returns bytes/str here; writing files is
the CLI's job.

Import-time dependencies are stdlib + qrcode (pure Python), so this module
loads on Cloudflare Python Workers. Heavier deps are imported lazily:

  - Pillow      -> PNG output. Ships in Pyodide, so it works on Workers.
  - cairosvg    -> only needed to rasterize an *SVG* logo into *PNG* output.
                   Native C, so NOT available on Workers. Give the PNG path a
                   pre-rasterized logo instead (see scripts/bake_logo.py).
"""
from __future__ import annotations

import base64
import io
import math
import xml.etree.ElementTree as ET
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

import qrcode
from qrcode.constants import (
    ERROR_CORRECT_H,
    ERROR_CORRECT_L,
    ERROR_CORRECT_M,
    ERROR_CORRECT_Q,
)

ERROR_LEVELS = {
    "L": ERROR_CORRECT_L,
    "M": ERROR_CORRECT_M,
    "Q": ERROR_CORRECT_Q,
    "H": ERROR_CORRECT_H,
}

RASTER_FORMATS = {"png": "PNG", "jpg": "JPEG", "jpeg": "JPEG"}
SUPPORTED_EXTENSIONS = set(RASTER_FORMATS) | {"svg"}
TRANSPARENT_ALIASES = {"transparent", "none"}

LOGO_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".webp": "image/webp",
}
LOGO_SVG_EXTS = {".svg"}
LOGO_RASTER_EXTS = set(LOGO_MIME)
LOGO_EXTS = LOGO_SVG_EXTS | LOGO_RASTER_EXTS

SVG_NS = "http://www.w3.org/2000/svg"

DEFAULT_LOGO_SCALE = 0.22
MAX_SAFE_LOGO_SCALE = 0.28


def is_transparent(color: str) -> bool:
    return color.strip().lower() in TRANSPARENT_ALIASES


def snap_rect_to_grid(
    x: float, y: float, w: float, h: float, module: int
) -> tuple[float, float, float, float]:
    """Expand a rect outward so all edges land on QR module boundaries."""
    left = math.floor(x / module) * module
    top = math.floor(y / module) * module
    right = math.ceil((x + w) / module) * module
    bottom = math.ceil((y + h) / module) * module
    return left, top, right - left, bottom - top


def infer_format(output: Path) -> str:
    ext = output.suffix.lower().lstrip(".")
    if not ext:
        raise ValueError(
            f"Output '{output}' has no extension; cannot infer format. "
            f"Use one of: {', '.join(sorted(SUPPORTED_EXTENSIONS))}."
        )
    if ext not in SUPPORTED_EXTENSIONS:
        raise ValueError(
            f"Unsupported output format '.{ext}'. "
            f"Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}."
        )
    return ext


def infer_logo_kind(logo: Path) -> str:
    ext = logo.suffix.lower()
    if ext in LOGO_SVG_EXTS:
        return "svg"
    if ext in LOGO_RASTER_EXTS:
        return "raster"
    raise ValueError(
        f"Unsupported logo format '{ext}'. Supported: {', '.join(sorted(LOGO_EXTS))}."
    )


def default_error_level(has_logo: bool) -> str:
    """A logo covers modules, so lean on maximum error correction."""
    return "H" if has_logo else "M"


def build_qr(data: str, error_level: int, box_size: int = 10, border: int = 4) -> qrcode.QRCode:
    qr = qrcode.QRCode(
        version=None,
        error_correction=error_level,
        box_size=box_size,
        border=border,
    )
    qr.add_data(data)
    qr.make(fit=True)
    return qr


def load_logo_as_pil(logo_path: Path, target_px: int):
    from PIL import Image

    kind = infer_logo_kind(logo_path)
    if kind == "svg":
        try:
            import cairosvg
        except ImportError as exc:  # pragma: no cover - Workers has no cairo
            raise ValueError(
                f"Rasterizing an SVG logo ('{logo_path.name}') into PNG output needs "
                "cairosvg, which is not available in this environment. Pass a "
                "pre-rasterized PNG logo instead (see scripts/bake_logo.py)."
            ) from exc
        png_bytes = cairosvg.svg2png(
            url=str(logo_path),
            output_width=max(target_px * 2, 64),
        )
        img = Image.open(io.BytesIO(png_bytes))
    else:
        img = Image.open(logo_path)
    img = img.convert("RGBA")
    w, h = img.size
    scale = target_px / max(w, h)
    new_size = (max(1, int(round(w * scale))), max(1, int(round(h * scale))))
    return img.resize(new_size, Image.LANCZOS)


def render_raster(
    qr: qrcode.QRCode,
    ext: str,
    fg: str,
    bg: str,
    logo: Path | None,
    logo_scale: float,
    logo_backing: str,
    square_backing: bool,
) -> bytes:
    """Render to PNG/JPEG bytes. Needs Pillow."""
    from PIL import ImageDraw

    save_format = RASTER_FORMATS[ext]
    if is_transparent(bg):
        if save_format == "JPEG":
            raise ValueError(
                "JPEG does not support transparent backgrounds. Use PNG or SVG."
            )
        bg = "transparent"

    img = qr.make_image(fill_color=fg, back_color=bg)
    pil = img.get_image() if hasattr(img, "get_image") else img
    pil = pil.convert("RGBA")

    if logo is not None:
        total_w, total_h = pil.size
        logo_target = max(1, int(min(total_w, total_h) * logo_scale))
        logo_img = load_logo_as_pil(logo, logo_target)
        lw, lh = logo_img.size
        padding = max(4, logo_target // 20)
        if square_backing:
            side = max(lw, lh) + 2 * padding
            bw = bh = side
        else:
            bw = lw + 2 * padding
            bh = lh + 2 * padding
        bx = (total_w - bw) / 2
        by = (total_h - bh) / 2
        bx, by, bw, bh = snap_rect_to_grid(bx, by, bw, bh, qr.box_size)
        bx, by, bw, bh = int(bx), int(by), int(bw), int(bh)
        if not is_transparent(logo_backing):
            draw = ImageDraw.Draw(pil)
            draw.rectangle([bx, by, bx + bw - 1, by + bh - 1], fill=logo_backing)
        lx = bx + (bw - lw) // 2
        ly = by + (bh - lh) // 2
        pil.paste(logo_img, (lx, ly), logo_img)

    if save_format == "JPEG" and pil.mode != "RGB":
        pil = pil.convert("RGB")
    buf = io.BytesIO()
    pil.save(buf, format=save_format)
    return buf.getvalue()


def _parse_length(value: str | None) -> float:
    if value is None:
        return 100.0
    value = value.strip()
    if not value:
        return 100.0
    for suffix in ("px", "pt", "mm", "cm", "in", "em", "ex", "%"):
        if value.endswith(suffix):
            value = value[: -len(suffix)]
            break
    try:
        return float(value)
    except ValueError:
        return 100.0


def get_logo_aspect(logo_path: Path) -> float:
    """Return width / height of the logo (>1 = wider than tall)."""
    kind = infer_logo_kind(logo_path)
    if kind == "svg":
        tree = ET.parse(logo_path)
        root = tree.getroot()
        viewbox = root.get("viewBox")
        if viewbox:
            parts = viewbox.split()
            if len(parts) == 4:
                try:
                    w, h = float(parts[2]), float(parts[3])
                    if h > 0 and w > 0:
                        return w / h
                except ValueError:
                    pass
        w = _parse_length(root.get("width"))
        h = _parse_length(root.get("height"))
        return w / h if h > 0 else 1.0
    from PIL import Image

    with Image.open(logo_path) as img:
        return img.width / img.height if img.height else 1.0


def embed_svg_logo(logo_path: Path, x: float, y: float, width: float, height: float) -> str:
    kind = infer_logo_kind(logo_path)
    if kind == "raster":
        mime = LOGO_MIME[logo_path.suffix.lower()]
        b64 = base64.b64encode(logo_path.read_bytes()).decode("ascii")
        return (
            f'<image x="{x}" y="{y}" width="{width}" height="{height}" '
            f'preserveAspectRatio="xMidYMid meet" '
            f'xlink:href="data:{mime};base64,{b64}" '
            f'href="data:{mime};base64,{b64}"/>'
        )
    ET.register_namespace("", SVG_NS)
    tree = ET.parse(logo_path)
    root = tree.getroot()
    viewbox = root.get("viewBox")
    if viewbox:
        parts = viewbox.split()
        if len(parts) == 4:
            vb = f"{parts[0]} {parts[1]} {parts[2]} {parts[3]}"
        else:
            vb = "0 0 100 100"
    else:
        vb_w = _parse_length(root.get("width"))
        vb_h = _parse_length(root.get("height"))
        vb = f"0 0 {vb_w} {vb_h}"
    root.set("viewBox", vb)
    root.set("x", str(x))
    root.set("y", str(y))
    root.set("width", str(width))
    root.set("height", str(height))
    root.set("preserveAspectRatio", "xMidYMid meet")
    return ET.tostring(root, encoding="unicode")


def render_svg(
    qr: qrcode.QRCode,
    fg: str,
    bg: str,
    logo: Path | None,
    logo_scale: float,
    logo_backing: str,
    square_backing: bool,
) -> str:
    """Render to an SVG document. Pure stdlib - no Pillow, no cairo."""
    matrix = qr.get_matrix()
    box = qr.box_size
    border = qr.border
    modules = len(matrix)
    total = (modules + 2 * border) * box
    fg_e = xml_escape(fg, {'"': "&quot;"})
    bg_e = xml_escape(bg, {'"': "&quot;"})
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'xmlns:xlink="http://www.w3.org/1999/xlink" '
            f'width="{total}" height="{total}" viewBox="0 0 {total} {total}" '
            f'shape-rendering="crispEdges">'
        ),
    ]
    if not is_transparent(bg):
        parts.append(f'<rect width="100%" height="100%" fill="{bg_e}"/>')
    for y, row in enumerate(matrix):
        for x, cell in enumerate(row):
            if cell:
                px = (x + border) * box
                py = (y + border) * box
                parts.append(
                    f'<rect x="{px}" y="{py}" width="{box}" height="{box}" fill="{fg_e}"/>'
                )
    if logo is not None:
        max_dim = total * logo_scale
        aspect = get_logo_aspect(logo)
        if aspect >= 1.0:
            lw = max_dim
            lh = max_dim / aspect
        else:
            lh = max_dim
            lw = max_dim * aspect
        padding = max(box, int(max_dim // 20))
        if square_backing:
            side = max(lw, lh) + 2 * padding
            bw = bh = side
        else:
            bw = lw + 2 * padding
            bh = lh + 2 * padding
        bx = (total - bw) / 2
        by = (total - bh) / 2
        bx, by, bw, bh = snap_rect_to_grid(bx, by, bw, bh, box)
        if not is_transparent(logo_backing):
            backing_e = xml_escape(logo_backing, {'"': "&quot;"})
            parts.append(
                f'<rect x="{bx}" y="{by}" width="{bw}" '
                f'height="{bh}" fill="{backing_e}"/>'
            )
        lx = bx + (bw - lw) / 2
        ly = by + (bh - lh) / 2
        parts.append(embed_svg_logo(logo, lx, ly, lw, lh))
    parts.append("</svg>")
    return "\n".join(parts)
