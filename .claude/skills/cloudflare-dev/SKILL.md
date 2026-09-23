---
name: cloudflare-dev
description: Target architecture and starter files for applications based on Cloudflare Workers — pure HTML/JS/CSS (no TypeScript, no React/Angular/frameworks), Vite + @cloudflare/vite-plugin, and - if necessary - use a versioned same-origin /api layer, Turnstile, and/or stateless signed session cookies. Use this whenever creating a new Worker project, adding new internal applications, or when the user mentions "using our default application environment" or "following our typical project structure". Even for small changes, read this first so new files land in the right place.
---

# Cloudflare Applications: SPA + Worker structure

One Worker serves the static application pages and - if necessary an `/api/*` layer. Each application is its own
Vite page at its own URL, but the machinery behind it — the controller, the step fragments, the
browser JS, the API handlers — is shared, and inherited from the level above. Copy `templates/` for a
new project; copy individual files from it when extending an existing one.

## What this is for

Online applications for Maryland Department of Labor staff. The idea is to quickly be able to create, deploy, and easily manage internal applications.

## Overall project layout

```
package.json  vite.config.js  wrangler.jsonc  .dev.vars.example  scripts/deploy.sh  plugins/include.js
site/                            Vite root → static assets
  404.html                       served by assets.not_found_handling
  partials/                      head.html header.html footer.html  (build-time includes)
  public/css/site.css            single stylesheet, blank in the template — copied verbatim
  js/                            shared browser code, one concern per file
                                 (login.js logout.js steps.js validate.js confirm.js)
  <app>/index.html             front door: plain page, one link per license type
  <app>/main.js                ONE controller for every license type on the board
  <app>/steps/*.html           shared step fragments, used by every license type
  <app>/<license-type>/        index.html and nothing else — see "inherit by default"
src/                             Worker
  index.js                       router: /api/vN/<name> → versions['vN'].routes[name]
                                         /api/<name>    → latest version
  lib/                           session.js turnstile.js respond.js
  api/v1/                        index.js exports `routes`; one handler per file
  api/v2/                        index.js: `{ ...v1, overridden }`; only changed handlers here
```

## Rules

- **Pure web stack.** HTML forms, ES modules, `fetch`. No frameworks, no TypeScript, no build-step
  CSS framework (Tailwind, Bootstrap). Behavior goes in `.js`, markup in `.html`, style only in
  `site/public/css/site.css`. A CDN design system — MDWDS `usa-*` / `mdgov-*` from
  `cdn.maryland.gov` — is not what this rule excludes; link it from `partials/head.html` and use
  its classes.
- **Progressive enhancement and a11y are requirements, not polish.** These are public government
  forms. Real `<form>`/`<label>`/`<fieldset>` markup, keyboard reachable. Each page has exactly one
  `<h1>` — the application title, stable across steps — and each step fragment contributes an
  `<h2>`. `steps()` moves focus to that `<h2>` on every step change, because replacing `innerHTML`
  otherwise drops focus to `<body>` silently.
- **Inherit by default; override only when strictly necessary.** Everything common lives as high up
  as it can — shared JS in `site/js/`, one `main.js` and one `steps/` per board, one handler per
  endpoint for all boards — and a license type takes it as-is. Do not pre-emptively split a file
  "so each license type can customize later"; split it the day one of them actually differs, and
  then only that file. Two license types starting from a copy is the failure mode this rule exists
  to prevent: the copies drift, and a fix to the shared bug lands in one of them.
- **One `main.js` per app, not per license type.** It holds the main application logic and the
  handler wiring. An applications `index.html` contains no script of its own
  — it loads `/<app>/main.js`.
- **Same name, two sides.** If there is an API to support a UI/UX action then
  `site/js/login.js` handles the form, `src/api/v1/login.js` handles the
  request. Keep the pairing for every endpoint.
- **Endpoints live in HTML.** Each step's `<form action="/api/login">` declares its endpoint;
  shared JS posts to `form.action`. The one step that needs a different endpoint changes that
  attribute — no JS, and no second copy of the JS.
- **Versioning.** `/api/<name>` = latest, for the app's own pages. `/api/vN/<name>` pins, for
  anything you cannot redeploy in lockstep. A new version is a new folder whose `index.js` spreads
  the previous `routes` and overrides only what changed; an override may wrap the previous handler
  (`api/v2/login.js`).
- **Includes.** Partials use `<!-- @include partials/x.html -->`, resolved at build time by
  `plugins/include.js`. Step fragments are imported by the board's `main.js` as
  `import x from './steps/x.html?raw'`. Nothing else is templated — there is no Jekyll here.
- **Root-absolute imports.** Reference shared code as `/js/login.js` and `/css/site.css` from any
  depth; never `../../`. Only `./steps/*.html?raw` is relative. The two resolve differently even
  though the URLs match: `/js/*.js` is an import specifier Vite resolves against the root and
  bundles, while `/css/site.css` is a plain `<link>` served from `site/public/` and copied verbatim.
  That is why the stylesheet lives under `public/` and the JS does not.
- **Every app needs a `vite.config.js` entry, `404.html` included.** A page missing from
  `build.rollupOptions.input` is silently not built — no error, it just never appears in the output
  and 404s in production. After adding a page, check the build's file list.
- **The Worker only sees `/api/*`.** `run_worker_first: ["/api/*"]` in `wrangler.jsonc` — the
  inverse of this repo's current setup, where static assets win every path. Default
  `html_handling` gives clean URLs (`site/x/y/index.html` → `/x/y`) with no routing code.
- **Auth.** Turnstile is verified server-side in `login` only (`lib/turnstile.js`); its tokens are
  single-use, not sessions. Sessions are HMAC-signed `HttpOnly; Secure; SameSite=Strict` cookies
  (`lib/session.js`) — no KV, no D1. Handlers receive `{ request, env, session }`; check `session`
  on every protected route.
- **Turnstile must be interaction-only.** Its script is loaded and an implicit scan is the preferred
  option here, for internal apps it's not critical but might be helpful.
- **Secrets.** `SESSION_SECRET` and `TURNSTILE_SECRET_KEY` go in `.dev.vars` (gitignored); copy
  `.dev.vars.example` to start. `.env` works too and `scripts/deploy.sh` accepts either, but use
  only one — wrangler ignores `.env` when `.dev.vars` exists. `deploy.sh` pushes the file with
  `wrangler secret bulk`, then deploys, passing any args (`npm run deploy -- --env test`) to both.
  Never put a secret in `wrangler.jsonc`. On a Windows dev box, check what `bash` on PATH actually
  is before wiring the `.sh` into `npm run deploy` — if it is `WindowsApps\bash.exe` it is the WSL
  launcher, and the script will run inside a Linux distribution with its own PATH and `/mnt/c`
  paths. Port it to Node there (`scripts/deploy.mjs` in this repo is the same three steps). The Turnstile *site* key is public and belongs in the
  login step's `data-sitekey` attribute.
- **Formatting.** Tabs, CRLF, 140 columns, single quotes, semicolons — per `.editorconfig` and
  `.prettierrc`, which the templates already match. The one exception is `scripts/deploy.sh`: shell
  scripts stay LF, enforced by `*.sh text eol=lf` in `.gitattributes`, because bash fails on the CR.

## Adding an Application

1. Copy `templates/site/example/` to `site/<app>/` — front door, `main.js`, `steps/`, and its
   necessary sub-directories. This is the one place copying is right: independent apps do not share much.
2. Add `'<app>': page('<app>')` and one `'<app>/'` entry per app to `build.rollupOptions.input` in `vite.config.js`.
3. Only touch `src/` if a new app needs new API routes.

## Adding an API endpoint

1. `src/api/v1/<name>.js` exporting `async function <name>({ request, env, session })`; return via
   `lib/respond.js`.
2. Register it in `src/api/v1/index.js` `routes`. Later versions inherit it automatically.
3. Add `site/js/<name>.js` if the browser needs matching behavior.

## Coexisting with the current repo

The near-term goal is a real `/api` on `apps.labor.maryland.dev` without breaking any existing
sites or work.

So new work lives under `/api/<name>` or `/api/vN/<name>`, and a board prefix inside that
(`/api/electrician/login`) is available when a board's handler really is its own. When a legacy path
is eventually retired, its replacement is a normal route key and the old path can redirect.

## Commands

```bash
cp .dev.vars.example .dev.vars   # then fill in the secrets
npm run dev                      # Vite + the Workers runtime, one server
npm run build
npm run deploy                   # build, push secrets, wrangler deploy
```
