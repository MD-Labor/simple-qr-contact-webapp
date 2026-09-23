import { json } from '../../lib/respond.js';

export async function submit({ request, session }) {
	if (!session) return json({ error: 'unauthorized' }, 401);
	const answers = await request.json();
	// TODO: POST to backend
	return json({ ok: true, received: Object.keys(answers) });
}
