"""apps.labor.maryland.dev - QR code API.

Routes (everything else is served from site/ by the static assets binding):

    GET /api/qr[.png|.svg]      encode any string          ?data=<text>
    GET /api/vcard[.png|.svg]   build + encode a vCard     ?first=&last=&...
    GET /api/mecard[.png|.svg]  build + encode a MECARD    ?first=&last=&...
    GET /api                    endpoint reference (JSON)

vCard and MECARD take the same parameters. vCard labels each phone number;
MECARD is smaller but cannot. See src/vcard.py for the tradeoff.

The extension is a courtesy for callers that want to pin a format; ?format=
does the same thing, and the default is PNG because that is what email clients
can actually render inside a signature.
"""
import re
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from pyodide.ffi import to_js
from workers import Response, WorkerEntrypoint

import mecard
import qrrender
import vcard

from auth import get_auth_context

# Bundled logo assets must sit directly beside this file: pywrangler only ships
# files in the entrypoint's own directory, so a subdirectory would be missing at
# runtime (FileNotFoundError on /session/metadata/...).
HERE = Path(__file__).parent

# The SVG logo stays vector inside SVG output. PNG output needs a raster logo
# because rasterizing SVG would require cairosvg, which cannot run on Workers -
# scripts/bake_logo.py pre-renders this from the same source SVG.
LOGOS = {
    "md": {"svg": HERE / "maryland-logo.svg", "png": HERE / "maryland-logo.png"},
}

DEFAULT_LOGO = "md"
MAX_DATA_LEN = 2000

# PNG output is a bitmap, so its memory is the square of the image side - and
# the caller sets both factors: 'data' and 'ec' decide the module count, 'box'
# the pixels per module. The densest code this API will encode is 177 modules
# plus an 8-module quiet zone, which at box=40 is 7400px - ~220MB of RGBA
# pixels, more than the Worker isolate has, and Pillow holds two copies while
# converting. Capping the side covers both factors at once. 2048px costs ~17MB,
# prints cleanly at 300dpi, and still leaves the default box=10 usable for
# every code that fits in MAX_DATA_LEN (185 x 10 = 1850px). SVG has no such
# limit: it is text, and scales on the client.
MAX_PNG_SIDE = 2048

# Colour parameters are bounded and grammar-checked rather than passed through
# verbatim: they end up inside generated documents, and an arbitrarily long
# value is a cheap way to make the Worker build an enormous response. 64
# characters clears every form the grammar below allows, with room to spare.
MAX_COLOR_LEN = 64

# Named colour (including 'transparent'/'none'), #rgb/#rgba/#rrggbb/#rrggbbaa,
# or an rgb()/rgba()/hsl()/hsla() value. The functional forms allow only
# digits, letters, and the separators CSS uses there - no XML metacharacters
# can survive this, which keeps the escaping in qrrender a second line of
# defence rather than the only one.
COLOR_RE = re.compile(
    r"""
    (?:
        [A-Za-z]{1,32}
      | \#(?:[0-9A-Fa-f]{3,4}|[0-9A-Fa-f]{6}|[0-9A-Fa-f]{8})
      | (?:rgb|rgba|hsl|hsla)\([0-9A-Za-z.,%/+\s-]{1,40}\)
    )
    """,
    re.VERBOSE,
)

# Error correction for a logo'd code. qrrender defaults to H, which is right for
# the CLI (print, arbitrary size) but spends modules this API cannot afford: a
# logo at the default 0.22 scale covers under 6% of the code, while H reserves
# 30%. Measured on a name + two phones + org card, H yields 73 modules and stops
# decoding below ~240px; Q yields 65 and decodes cleanly from 160px up, still
# leaving about four times the headroom the logo actually needs.
LOGO_ERROR_LEVEL = "Q"

ORG_NAME = "Maryland Department of Labor"
ORG_URL = "https://labor.maryland.gov/"

# Phone query parameters, in the order they should appear on a card, mapped to
# the kind of number each one means. vCard turns these into TYPE labels; MECARD
# discards them, having no field to put a label in.
PHONE_FIELDS = (
    ("mobile", "cell"),
    ("office", "work"),
    ("fax", "fax"),
    ("tel", "work"),
)

CACHE_CONTROL = "public, max-age=86400"


class ApiError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.message = message
        self.status = status


def _one(params, key, default=None):
    values = params.get(key)
    if not values:
        return default
    value = values[0].strip()
    return value if value else default


def _flag(params, key, default=False):
    value = _one(params, key)
    if value is None:
        return default
    return value.lower() in ("1", "true", "yes", "on")


def _float(params, key, default):
    value = _one(params, key)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        raise ApiError(f"'{key}' must be a number, got {value!r}")


def _int(params, key, default, minimum, maximum):
    value = _one(params, key)
    if value is None:
        return default
    try:
        number = int(value)
    except ValueError:
        raise ApiError(f"'{key}' must be a whole number, got {value!r}")
    if not minimum <= number <= maximum:
        raise ApiError(f"'{key}' must be between {minimum} and {maximum}, got {number}")
    return number


def _check_color(key, value):
    """Reject colours that are too long or not a colour at all."""
    if len(value) > MAX_COLOR_LEN:
        # Deliberately does not echo the value back.
        raise ApiError(
            f"'{key}' is {len(value)} characters; the limit is {MAX_COLOR_LEN}."
        )
    # fullmatch, not match: '$' would let a trailing newline through.
    if not COLOR_RE.fullmatch(value):
        raise ApiError(
            f"'{key}' must be a color name, a #rgb/#rrggbb hex code, or an "
            f"rgb()/hsl() value - got {value!r}."
        )
    return value


def _resolve_logo(params, fmt):
    """Return the logo file for this output format, or None for a bare code."""
    name = (_one(params, "logo", DEFAULT_LOGO) or "").lower()
    if name in ("none", "off", "no"):
        return None
    if name not in LOGOS:
        known = ", ".join(sorted(LOGOS) + ["none"])
        raise ApiError(f"Unknown logo {name!r}. Available: {known}.")
    return LOGOS[name]["svg" if fmt == "svg" else "png"]


def _render(data, params, fmt):
    if len(data) > MAX_DATA_LEN:
        raise ApiError(
            f"'data' is {len(data)} characters; the limit is {MAX_DATA_LEN}. "
            "A QR code this dense would not scan reliably."
        )

    logo = _resolve_logo(params, fmt)

    level_name = (_one(params, "ec", "") or "").upper()
    if not level_name:
        level_name = LOGO_ERROR_LEVEL if logo is not None else qrrender.default_error_level(False)
    if level_name not in qrrender.ERROR_LEVELS:
        raise ApiError(
            f"'ec' must be one of L, M, Q, H - got {level_name!r}."
        )

    logo_scale = _float(params, "scale", qrrender.DEFAULT_LOGO_SCALE)
    if logo is not None and not 0.0 < logo_scale < 1.0:
        raise ApiError(f"'scale' must be greater than 0 and less than 1, got {logo_scale}.")

    fg_key = "fg" if _one(params, "fg") else "color"
    fg = _check_color(fg_key, _one(params, "fg") or _one(params, "color", "black"))
    bg = _check_color("bg", _one(params, "bg", "white"))
    backing = _check_color("backing", _one(params, "backing", "white"))
    square = _flag(params, "square")
    box = _int(params, "box", 10, 1, 40)

    try:
        qr = qrrender.build_qr(data, qrrender.ERROR_LEVELS[level_name], box_size=box)
    except Exception as exc:
        raise ApiError(f"Could not encode that data: {exc}")

    if fmt != "svg":
        # get_matrix() already includes the quiet zone, and that is what Pillow
        # rasterizes: the image is len(matrix) * box_size on each side.
        span = len(qr.get_matrix())
        side = span * box
        if side > MAX_PNG_SIDE:
            raise ApiError(
                f"this code is {span} modules wide with its quiet zone, so "
                f"'box' {box} would render it at {side}x{side} pixels; the "
                f"limit is {MAX_PNG_SIDE}. Use box={max(1, MAX_PNG_SIDE // span)} "
                "or lower, or ask for .svg, which scales to any size."
            )

    # Verified by decoding real output: at scale 0.35 the logo swallows more
    # modules than error correction can rebuild and the code stops decoding
    # entirely. We still honour the request - the CLI does - but say so.
    warning = None
    if logo is not None and logo_scale > qrrender.MAX_SAFE_LOGO_SCALE:
        warning = (
            f"logo scale {logo_scale} is above {qrrender.MAX_SAFE_LOGO_SCALE}; "
            "this code may not scan. Test it with a phone before using it."
        )

    if fmt == "svg":
        body = qrrender.render_svg(qr, fg, bg, logo, logo_scale, backing, square)
        headers = {
            "Content-Type": "image/svg+xml; charset=utf-8",
            "Cache-Control": CACHE_CONTROL,
        }
        if warning:
            headers["X-QR-Warning"] = warning
        return Response(body, headers=headers)

    # PNG colours go through Pillow, which reads fewer forms than SVG does:
    # no 'transparent' foreground, no fractional rgba() alpha, no space-
    # separated hsl(). A colour the grammar above allows but Pillow cannot
    # read is the caller's mistake, so answer 400 rather than letting the
    # ValueError escape as a 500.
    try:
        png = qrrender.render_raster(qr, "png", fg, bg, logo, logo_scale, backing, square)
    except ValueError as exc:
        raise ApiError(f"Could not render that PNG: {exc}")
    headers = {"Content-Type": "image/png", "Cache-Control": CACHE_CONTROL}
    if warning:
        headers["X-QR-Warning"] = warning
    return Response(to_js(png).buffer, headers=headers)


def _card_from_params(params, kind):
    """Build a MECARD or vCard payload from the shared contact parameters."""
    phones = []
    for key, phone_kind in PHONE_FIELDS:
        value = _one(params, key)
        if value:
            phones.append((phone_kind, value))

    first = _one(params, "first", "") or ""
    last = _one(params, "last", "") or ""
    email = _one(params, "email", "") or ""

    # 'url' and 'org' have defaults, so without this check a request carrying no
    # fields at all would still encode successfully - as a card holding nothing
    # but our website, which is not a contact.
    if not (first or last or email or phones):
        raise ApiError(
            "A contact card needs at least a name, phone number, or email. "
            f"Example: /api/{kind}.png?first=Jay&last=Huie&email=jay.huie@maryland.gov"
        )

    # ORG defaults on, matching URL: this is the department's own API, so a card
    # it builds says where the person works. Pass org=none to leave it out. It
    # costs ~33 characters, which pushes a typical card from QR version 9 to 11
    # (61 -> 69 modules) - worth knowing if you shrink the code below ~180px.
    org = _one(params, "org", ORG_NAME) or ""
    if org.lower() in ("none", "off", "no"):
        org = ""

    fields = dict(
        first=first,
        last=last,
        email=email,
        url=_one(params, "url", ORG_URL) or "",
        org=org,
        note=_one(params, "note", "") or "",
    )

    try:
        if kind == "vcard":
            return vcard.build(
                phones=phones, title=_one(params, "title", "") or "", **fields
            )
        # MECARD has no way to label a number, so only the numbers survive.
        return mecard.build(phones=[number for _, number in phones], **fields)
    except ValueError as exc:
        raise ApiError(str(exc))


def _split_route(path):
    """'/api/qr.svg' -> ('qr', 'svg'). Missing extension yields the PNG default."""
    route = path[len("/api/"):]
    for ext in ("png", "svg"):
        if route.endswith("." + ext):
            return route[: -(len(ext) + 1)], ext
    if "." in route:
        bad = route.rsplit(".", 1)[1]
        raise ApiError(f"Unsupported format '.{bad}'. Use .png or .svg.", status=404)
    return route, None


def _index():
    return Response.json(
        {
            "endpoints": {
                "GET /api/qr[.png|.svg]": {
                    "description": "Encode any string as a QR code.",
                    "required": {"data": "text to encode"},
                },
                "GET /api/vcard[.png|.svg]": {
                    "description": "Build a vCard 3.0 contact card and encode it. "
                                   "Unlike MECARD, each number keeps its label "
                                   "(mobile, work, work fax) - at roughly twice "
                                   "the payload, so a denser code.",
                    "optional": {
                        "same as /api/mecard, plus": "title (job title)",
                    },
                },
                "GET /api/mecard[.png|.svg]": {
                    "description": "Build a MECARD contact card and encode it. "
                                   "More compact than vCard, but every number "
                                   "arrives unlabelled as 'phone'.",
                    "optional": {
                        "first": "given name",
                        "last": "family name",
                        "mobile": "mobile number",
                        "office": "office number",
                        "fax": "fax number",
                        "tel": "additional number",
                        "email": "email address",
                        "org": f"organization (default: {ORG_NAME}); "
                               "'none' omits it, for a shorter, less dense code",
                        "url": f"website (default: {ORG_URL})",
                        "note": "free-text note",
                    },
                },
            },
            "shared_options": {
                "format": "png (default) or svg; the path extension wins",
                "logo": f"{DEFAULT_LOGO} (default) or none",
                "ec": f"error correction L, M, Q, H (default {LOGO_ERROR_LEVEL} with a logo, else M)",
                "scale": f"logo size as a fraction of width (default {qrrender.DEFAULT_LOGO_SCALE}; "
                         f"above {qrrender.MAX_SAFE_LOGO_SCALE} often stops scanning)",
                "fg": "foreground color (default black); a color name, "
                      "#rgb/#rrggbb hex, or an rgb()/hsl() value, at most "
                      f"{MAX_COLOR_LEN} characters",
                "bg": "background color, or 'transparent' (default white); "
                      "same grammar as fg",
                "backing": "color behind the logo (default white); same "
                           "grammar as fg",
                "square": "1 to force a square logo backing",
                "box": "pixels per QR module, 1-40 (default 10); PNG output "
                       f"is also capped at {MAX_PNG_SIDE}px on a side, so a "
                       "dense code needs a smaller box or .svg",
            },
        }
    )


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        url = urlparse(request.url)
        path = url.path.rstrip("/") or "/"

        ctx = await get_auth_context(request, self.env)
        #if ctx.is_authenticated: ## Logging all items for now - should never be unauthenticated access
        print(json.dumps({
            "message": "MD Labor Apps Access",
            "path": path,
            "authenticated": ctx.is_authenticated,
            "by": ctx.email,
        }))

        if path == "/api":
            return _index()

        if not path.startswith("/api/"):
            return Response.json({"error": f"No such endpoint: {path}"}, status=404)

        try:
            route, ext = _split_route(path)

            fmt = ext or (_one(parse_qs(url.query), "format", "png") or "png").lower()
            if fmt not in ("png", "svg"):
                raise ApiError(f"Unsupported format {fmt!r}. Use png or svg.")

            params = parse_qs(url.query, keep_blank_values=False)

            if route == "qr":
                data = _one(params, "data")
                if data is None:
                    raise ApiError("'data' is required. Example: /api/qr.svg?data=hello")
                return _render(data, params, fmt)

            if route in ("mecard", "vcard"):
                return _render(_card_from_params(params, route), params, fmt)

            raise ApiError(f"No such endpoint: {path}", status=404)

        except ApiError as exc:
            return Response.json({"error": exc.message}, status=exc.status)
