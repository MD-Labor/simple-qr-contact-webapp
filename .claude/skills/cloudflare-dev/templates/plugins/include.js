import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

// Replaces <!-- @include partials/header.html --> with the file's contents at build time.
export default function include() {
	let root;
	return {
		name: 'html-include',
		configResolved(c) { root = c.root; },
		transformIndexHtml(html) {
			return html.replace(/<!--\s*@include\s+(\S+)\s*-->/g, (_, p) =>
				readFileSync(resolve(root, p), 'utf8'));
		},
	};
}
