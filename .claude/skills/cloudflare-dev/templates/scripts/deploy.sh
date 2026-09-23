#!/usr/bin/env bash
set -euo pipefail
npm run build

# Push local secrets to the deployed Worker. Wrangler prefers .dev.vars over .env
# and ignores .env entirely when .dev.vars exists, so pick the same one it would.
# `secret bulk` reads dotenv itself (one request, no hand-rolled parsing).
for f in .dev.vars .env; do
	if [[ -f $f ]]; then
		npx wrangler secret bulk "$f" "$@"
		break
	fi
done

npx wrangler deploy "$@"
