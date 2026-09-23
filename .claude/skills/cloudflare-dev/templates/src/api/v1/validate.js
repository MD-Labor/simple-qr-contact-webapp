import { json } from '../../lib/respond.js';

export async function validate({ request, session }) {
	if (!session) return json({ error: 'unauthorized' }, 401);
	const { field, value } = await request.json();
	// TODO: real validation against backend
	return json({ ok: Boolean(value), field });
}
