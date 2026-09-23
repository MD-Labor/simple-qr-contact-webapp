import { routes as v1 } from './api/v1/index.js';
import { routes as v2 } from './api/v2/index.js';
import { getSession } from './lib/session.js';
import { json } from './lib/respond.js';

const versions = { v1, v2 };
const latest = v2;

export default {
	async fetch(request, env) {
		const parts = new URL(request.url).pathname.split('/').filter(Boolean); // api, [vN], ...name
		// run_worker_first is scoped to /api/*, so non-API paths normally never get here; this is
		// the fallback if that ever widens.
		if (parts.shift() !== 'api') return env.ASSETS.fetch(request);
		const routes = versions[parts[0]] ? versions[parts.shift()] : latest;
		const handler = routes[parts.join('/')];
		if (!handler) return json({ error: 'not found' }, 404);
		const session = await getSession(request, env);
		return handler({ request, env, session });
	},
};
