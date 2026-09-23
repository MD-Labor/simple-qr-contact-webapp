import { defineConfig } from 'vite';
import { cloudflare } from '@cloudflare/vite-plugin';
import { resolve } from 'node:path';
import include from './plugins/include.js';

const file = (p) => resolve(import.meta.dirname, 'site', p);
const page = (p) => file(`${p}/index.html`);

export default defineConfig({
	root: 'site',
	appType: 'mpa',
	plugins: [include(), cloudflare({ configPath: '../wrangler.jsonc' })],
	build: {
		rollupOptions: {
			// Every page needs an entry here or it is not built at all — including 404.html.
			// The board front door, then one per license type.
			input: {
				404: file('404.html'),
				example: page('example'),
				'example/apprentice': page('example/apprentice'),
				'example/journeyperson': page('example/journeyperson'),
			},
		},
	},
});
