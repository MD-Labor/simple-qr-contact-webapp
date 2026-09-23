# simple-qr-contact-webapp

Two things that share one rendering engine:

1. **A web app** — the Maryland Department of Labor email signature generator, running on a Python Cloudflare Worker. Fill in a name, title, division and phone numbers; get a copy-paste-ready HTML signature with a QR contact card beside it.
2. **A CLI** — `qr.py`, a flexible QR code generator for any string, with optional logo overlay, in `.png`, `.jpg`, or `.svg`.

Both call the same `src/qrrender.py`, so a logo that sits correctly in a CLI-generated code sits identically in one the Worker serves.

## How it fits together

```
site/                     static assets, served directly by Cloudflare
├── index.html            front door
├── 404.html
├── favicon.svg
├── css/site.css
└── sig/
    ├── index.html        the signature generator
    └── main.js           form -> signature preview -> QR <img src>

src/                      the Worker (Python)
├── entry.py              router for /api/*
├── qrrender.py           shared render core (CLI + Worker)
├── vcard.py              vCard 3.0 builder - labelled phone numbers
├── mecard.py             MECARD builder - smaller, but no labels
├── maryland-logo.svg     bundled logo, vector, for SVG output
└── maryland-logo.png     bundled logo, pre-rasterized, for PNG output

qr.py                     the CLI, a thin wrapper over src/qrrender.py
scripts/bake_logo.py      build step: input/*.svg -> src/maryland-logo.png
tests/                    pytest suite for mecard.py and qrrender.py
```

The signature page is plain HTML and JS — no framework, no build step. It sets an `<img>` `src` to `/api/mecard.png?...` and lets the Worker render the code.

Two deliberate choices there:

- **The QR code is not part of the signature.** It has its own section on the page, and the copy button copies only the signature table. A QR embedded in a signature has to be fetched from this origin on every send, and recipients on other networks frequently would not see it at all — so it's offered as a download instead.
- **The QR request is debounced.** Without it, the API was asked to render every prefix of the name as it was typed, and a half-typed name could still be the image on screen when the final request lost the race.

Phone fields format as you type — `4105550100` becomes `(410) 555-0100`. Anything that isn't a plain North American number (an international number, a number with an extension) is left exactly as entered rather than reshaped into something wrong.

## Setup

Requires [uv](https://docs.astral.sh/uv/) and Node (for `wrangler`).

```bash
git clone https://github.com/maryland-state-innovation-team/simple-qr-contact-webapp.git
cd simple-qr-contact-webapp

uv sync                   # Python deps, including the dev group
npm install               # wrangler
```

`uv sync` creates and manages `.venv/` for you — don't create one by hand, and don't use `pip`.

To put an **SVG** logo on **raster** output from the CLI, you also need `cairosvg` and a system Cairo:

```bash
uv sync --extra svg-logo
```

On Debian/Ubuntu: `sudo apt install libcairo2`. macOS ships Cairo. On Windows the `cairocffi` wheels frequently *don't* find `libcairo-2.dll` and fail with `OSError: no library called "cairo-2" was found` — if that happens, rasterize the logo first (see [Baking the logo](#baking-the-logo)) and pass the PNG. Everything else in the CLI works without Cairo.

## Running the web app

```bash
npm run dev               # uv run pywrangler dev  -> http://127.0.0.1:8787
npm test                  # uv run pytest -q
npm run build             # uv run pytest -q && uv run pywrangler sync
npm run deploy            # uv run pywrangler deploy
```

Then open <http://127.0.0.1:8787/sig>.

`pywrangler` refuses to start if a `requirements.txt` exists in the project root — dependencies live in `pyproject.toml`. It also requires reasonably current toolchains (uv ≥ 0.12.3, wrangler ≥ 4.127.1); `uv self update` and `npm install` cover that.

### The Worker name

`wrangler.jsonc` sets `name` to **`intranet-apps-simple-qr-contact-webapp`** — the Worker that owns the hostname and the Access policy — not `simple-qr-contact-webapp`, which is only what this repository is called. Wrangler deploys by that field, so a mismatch doesn't error: it creates a second, bare Worker under the repo's name and leaves the real one serving the old code. Rename the Worker and this field together, never one alone.

### The hostname

One custom domain serves both production and previews:

| | Hostname |
| --- | --- |
| Production | `apps.labor.maryland.dev` |
| Preview (latest on a branch) | `<preview-name>.apps.labor.maryland.dev` |
| A specific deploy | `<deployment-id>-<preview-name>.apps.labor.maryland.dev` |

That's the `previews_enabled: true` + `enabled: true` pair on the route. Cloudflare creates the `*.apps.labor.maryland.dev` wildcard DNS record and an advanced certificate pack covering it the first time a Preview exists — no Total TLS or manual certificate needed at this subdomain depth, though issuance isn't instant.

`workers_dev: false` is stated rather than assumed, because Wrangler *re-enables* the `workers.dev` route on deploy unless the config says not to — disabling it in the dashboard alone doesn't stick. `preview_urls` is deliberately absent: it governs only the `workers.dev` preview hostname (off here), and Wrangler leaves that setting alone when the key is omitted. Custom-domain previews are the route's `previews_enabled` flag, not this key — easy to conflate.

### Behind Cloudflare Access

Access is applied at the **Worker** level rather than bound to a single hostname, which covers the custom domain, its preview subdomains and `workers.dev` in one policy. It gates `/api/*` as well as the pages. Three consequences:

- **The page still works.** `<img src="/api/vcard.png?...">` is same-origin, so the browser sends the Access cookie with it, and so do the download links.
- **Scanning still works, for now.** The QR encodes a vCard — the payload *is* the contact data, and a phone reading it never contacts this origin. That stops being true the moment someone generates a code whose data is a URL back here: phones would scan their way to a login page. Use `/api/qr?data=` with an off-origin URL for anything meant to be scanned by the public.
- **Preview hostnames are only as protected as the policy's scope.** Worker-level Access covers them; a policy bound to the literal hostname `apps.labor.maryland.dev` would not. After changing Access, load a preview URL in a private window and confirm it prompts for sign-in.

### Continuous deployment (Workers Builds)

Connecting the repo to a Worker in the Cloudflare dashboard needs these build settings:

| Setting | Value |
| --- | --- |
| Build command | `npm run build` |
| Deploy command | `npx wrangler deploy` (the default) |
| Preview command | `npx wrangler preview` (the default) |

**The build command is not optional here, and getting it wrong fails quietly.** Python dependencies are vendored into `python_modules/`, which Wrangler bundles automatically but never creates — `pywrangler sync` does, and `python_modules/` is gitignored, so a fresh CI checkout doesn't have one. With no build command, `wrangler deploy` uploads a Worker with no `qrcode` and no Pillow: the build goes green, the static pages serve fine, and every `/api/*` request returns a 500 with `ModuleNotFoundError` in the logs.

`npm run build` also runs the test suite first (about half a second), so a broken card builder can't reach the hostname.

`uv` is preinstalled in the build image and runs `uv sync` on its own once it sees `uv.lock`, which is why `npm run build` can call `uv run` directly.

## API

Four endpoints. The path extension (`.png` / `.svg`) is a courtesy for callers that want to pin a format; `?format=` does the same. The default is PNG, because that's what email clients can actually render inside a signature — Gmail and Outlook display neither inline SVG nor data-URI images there.

### `GET /api/qr[.png|.svg]`

Encode any string.

| Parameter | Description |
| --- | --- |
| `data` | **Required.** The text to encode. 2000 character limit. |

```
/api/qr.png?data=https%3A%2F%2Flabor.maryland.gov%2F
/api/qr.svg?data=WIFI%3AT%3AWPA%3BS%3AGuestNet%3BP%3Ahunter2%3B%3B&logo=none
```

### `GET /api/vcard[.png|.svg]` and `GET /api/mecard[.png|.svg]`

Build a contact card and encode it. Both take the same parameters. Every field is optional, but a card needs at least a name, phone number, or email.

**Which one:** vCard labels each phone number, MECARD cannot. MECARD's `TEL` field takes no type parameter at all, so a card with a desk, a mobile and a fax number arrives on the phone as three identical "phone" entries. vCard emits `TEL;TYPE=CELL`, `TYPE=WORK,VOICE` and `TYPE=WORK,FAX`, which phones show as mobile, work and work fax.

The cost is size. For the same contact with two numbers, vCard is roughly twice the payload — 221 bytes against 113 — because of `BEGIN`/`VERSION`/`END`, longer property names, and CRLF between every line. With three numbers that's 81 modules against 69, which is why the signature page displays its code at 300px. Use `/api/mecard` when the code has to stay small and the labels don't matter.

| Parameter | Description |
| --- | --- |
| `first`, `last` | Given and family name. |
| `mobile` | Mobile number. vCard labels it `CELL`. |
| `office`, `tel` | Work numbers. vCard labels them `WORK,VOICE`. |
| `fax` | Fax number. vCard labels it `WORK,FAX`. |
| `title` | Job title. **vCard only** — MECARD has no field for it. |
| `email` | Email address. |
| `url` | Website. Defaults to `https://labor.maryland.gov/`. |
| `org` | Organization. Defaults to `Maryland Department of Labor`; pass `org=none` to omit it. |
| `note` | Free-text note. |

```
/api/vcard.png?first=Jay&last=Huie&mobile=555-555-5555&fax=410-555-0101&email=jay.huie%40maryland.gov
/api/mecard.png?first=Jay&last=Huie&mobile=555-555-5555&email=jay.huie%40maryland.gov
```

In MECARD the name is always emitted with both components — `N:Huie,Jay`, or `N:Huie,` when only a surname is known. A single-component `N:Huie` is ambiguous, and scanners resolve it as the *given* name, which saves the contact to a phone with the surname "Unknown". vCard has the same trap and the same fix: `N:Huie;Jay;;;` always carries its five components, and `FN` is always present because vCard 3.0 requires it.

### Shared options

Both image endpoints accept:

| Parameter | Description | Default |
| --- | --- | --- |
| `format` | `png` or `svg`. A path extension wins over this. | `png` |
| `logo` | `md` for the Maryland logo, or `none` for a bare code. | `md` |
| `ec` | Error correction: `L`, `M`, `Q`, `H`. | `Q` with a logo, else `M` |
| `scale` | Logo size as a fraction of the QR width. | `0.22` |
| `fg` / `color` | Foreground color. | `black` |
| `bg` | Background color, or `transparent`. | `white` |
| `backing` | Solid color drawn behind the logo. | `white` |
| `square` | `1` to force a square logo backing. | off |
| `box` | Pixels per QR module, 1–40. PNG output is additionally capped at 2048px on a side. | `10` |

PNG is a bitmap, so its cost is the square of the image: the densest code this API encodes (2000 characters at `ec=H`, 185 modules with the quiet zone) would be 7400×7400 at `box=40`, about 220MB of pixels — more than a Worker isolate has. A PNG request over 2048px on a side is refused with a `400` naming the largest `box` that fits, so a dense code tops out around `box=11` while a short one still takes `box=40`. The default `box=10` always fits. SVG has no such limit: it is text, and the client scales it.

Above `scale=0.28` the response carries an `X-QR-Warning` header: the request is still honored, but the code may not decode. This isn't theoretical — decoding real output back with OpenCV, `scale=0.35` fails outright while `0.22` and `0.26` round-trip cleanly.

The `Q` default for logo'd codes is measured, not guessed. The CLI defaults a logo'd code to `H`, which is right for print at arbitrary size, but `H` reserves a 30% damage budget for a logo that covers under 6% of the code. On a name + two phones + organization card, `H` produces 73 modules and stops decoding below about 240px, while `Q` produces 65 and decodes from 160px up — still roughly four times the headroom the logo needs. Pass `ec=H` explicitly if the code is going to print.

### `GET /api`

Returns the above as JSON, so the API documents itself.

### Errors

Errors come back as JSON (`{"error": "..."}`) with `400` for a bad parameter and `404` for an unknown endpoint or unsupported extension.

## CLI usage

```
qr.py [-h] -o OUTPUT [-e {L,M,Q,H}] [-c COLOR] [-b BACKGROUND]
      [--logo PATH] [--logo-scale FLOAT] [--logo-backing COLOR] [--square-backing]
      data
```

Run it with `uv run`:

```bash
uv run python qr.py "https://maryland.gov" -o maryland.png
```

### Arguments

| Argument | Description | Default |
| --- | --- | --- |
| `data` (positional) | Text to encode. Typically a URL, but any string works. Quote it if it contains spaces or shell metacharacters. | — (required) |
| `-o`, `--output` | Output filename. The format is inferred from the extension: `.png`, `.jpg`/`.jpeg`, or `.svg`. | — (required) |
| `-e`, `--error-correction` | Error correction level. Higher levels tolerate more damage but produce denser codes. `L` ≈ 7%, `M` ≈ 15%, `Q` ≈ 25%, `H` ≈ 30%. | `M`, auto-upgraded to `H` when `--logo` is used |
| `-c`, `--color` | Foreground (module) color. Named color (`black`, `navy`, `red`) or hex (`#1a1a1a`). | `black` |
| `-b`, `--background` | Background color. Named color, hex, or `transparent` / `none` for an alpha-channel background (PNG and SVG only — JPEG has no alpha). | `white` |
| `--logo` | Path to a logo image (PNG, JPG, or SVG) to overlay in the center. | none |
| `--logo-scale` | Logo size as a fraction of the QR width. Values > 0 and < 1. Above ~0.28 the code often stops scanning. | `0.22` |
| `--logo-backing` | Solid color drawn behind the logo. Any named color, hex, or `transparent`. Useful when the logo has transparent pixels — a small opaque backing keeps QR modules from bleeding through. | `white` |
| `--square-backing` | Flag. By default the backing rect matches the logo's aspect ratio (a wide logo gets a wide backing). Pass this to force a square backing — good for near-square logos where a square looks tidier than a slightly-off rectangle. | off |

### Examples

Higher error correction (useful when the code will be printed small or partially covered by a logo):

```bash
uv run python qr.py "https://maryland.gov" -o maryland.png -e H
```

Custom colors — Maryland state red on cream:

```bash
uv run python qr.py "https://maryland.gov" -o maryland-brand.png -c "#c8102e" -b "#f7f4ec"
```

Vector output for print material:

```bash
uv run python qr.py "https://maryland.gov" -o maryland.svg -c navy -b white
```

Transparent background — PNG or SVG only, so the code can sit on any colored surface:

```bash
uv run python qr.py "https://maryland.gov" -o maryland.png -b transparent
```

JPEG (smaller file, but lossy — prefer PNG or SVG for crisp scanning):

```bash
uv run python qr.py "mailto:hello@example.com" -o contact.jpg
```

Encoding non-URL text works too:

```bash
uv run python qr.py "WIFI:T:WPA;S:GuestNet;P:hunter2;;" -o wifi.png -e Q
```

A contact card, the same payload the web app builds:

```bash
uv run python qr.py "MECARD:N:Huie,Jay;TEL:+15555555555;EMAIL:jay.huie@maryland.gov;URL:https://labor.maryland.gov/;;" \
    -o contact.png --logo src/maryland-logo.png
```

Add a logo in the center. Error correction auto-bumps to `H` so the code stays scannable:

```bash
uv run python qr.py "https://maryland.gov" -o branded.png --logo input/maryland-logo.svg
```

An SVG logo embedded in SVG output stays fully vector — good for print:

```bash
uv run python qr.py "https://maryland.gov" -o poster.svg --logo input/maryland-logo.svg
```

Larger logo on a transparent QR, with a matching transparent backing (only works if your logo already has opaque pixels covering the QR modules underneath — otherwise leave `--logo-backing` at its default):

```bash
uv run python qr.py "https://maryland.gov" -o hero.svg --logo input/maryland-logo.svg \
    --logo-scale 0.26 -b transparent --logo-backing transparent
```

### Exit codes

- `0` — success
- `1` — a runtime error occurred (e.g. couldn't write the output file, invalid color)
- `2` — bad arguments (unknown/missing extension, unknown flag, etc.)

## Baking the logo

The Worker can't rasterize SVG. `cairosvg` needs a system Cairo library that isn't present in the Workers runtime, so PNG output uses a logo rasterized ahead of time:

```bash
npm run bake-logo
```

That reads `input/maryland-logo.svg` and writes `src/maryland-logo.png` at 512px wide, plus a copy of the source SVG to `src/`. It uses [`resvg-py`](https://pypi.org/project/resvg-py/) — a self-contained Rust wheel with no system dependencies, which also renders the logo's `mask-type: luminance` mask correctly. Re-run it whenever the source logo changes, and commit both outputs.

The script warns if the result isn't RGBA or has no transparent pixels; without an alpha channel the logo paints an opaque box over the QR.

## Notes on the Worker

Two things about Python Workers cost real time to discover, and are worth keeping in mind before editing:

- **Non-`.py` files are not bundled unless you declare them.** The bundled logos only ship because `wrangler.jsonc` declares `rules` for `Data` (`**/*.png`) and `Text` (`**/*.svg`). Without those the Worker fails at runtime with `FileNotFoundError` on `/session/metadata/...`.
- **Only the entrypoint's own directory ships.** That's why `maryland-logo.svg` and `maryland-logo.png` sit directly beside `entry.py` instead of in a tidier `src/assets/`.

`run_worker_first` lists both `/api` and `/api/*`, because `/api/*` doesn't match the bare path — without the first entry, `GET /api` falls through to the static 404 page.

## How logos work on a QR code

QR codes have no native "logo hole" in the spec. Every logo QR you've seen exploits Reed-Solomon error correction — the decoder treats logo-covered modules as damage and recovers them, provided the total damaged area stays under the error correction budget (~30% at level `H`). The three big square finder patterns in the corners aren't error-correctable, which is why logos always go in the middle.

The logo's backing rectangle is snapped outward onto module boundaries, so it covers whole modules rather than clipping them partway — partial modules confuse decoders more than missing ones do.

Test your generated codes with a real phone camera before printing — anything above a logo scale of `0.28` tends to fail.

## Choosing an error correction level

- **L** — smallest / lowest density. Fine for large, clean prints.
- **M** *(default)* — good general-purpose balance.
- **Q** — resilient against smudging and moderate damage.
- **H** — use when overlaying a logo or when the QR will live on stickers, packaging, or anywhere it might get scuffed.

Higher error correction means more modules, so the code becomes denser at the same physical size — scan it back after generation to confirm your camera picks it up.

## Choosing an output format

- **PNG** — best default, and the only sensible choice for an email signature. Lossless, small, universally supported.
- **SVG** — vector. Scales to any print size without pixelation. Ideal for posters, signage, and embedding in other vector artwork.
- **JPG / JPEG** — CLI only. Lossy compression can introduce artifacts around the module edges. Use only when a downstream system specifically requires JPEG.

## Colors

Colors accept anything Pillow accepts for raster output (CSS named colors, `#rgb`, `#rrggbb`) and anything valid as an SVG `fill` attribute for SVG output. In practice, named colors and 6-digit hex codes work in both.

Keep contrast high. Very light foreground or very dark background will make the code hard to scan — aim for at least a 4.5:1 contrast ratio between foreground and background.

## License

MIT — see [LICENSE](LICENSE).
