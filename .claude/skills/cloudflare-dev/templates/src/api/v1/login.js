import { json } from '../../lib/respond.js';
import { setSession } from '../../lib/session.js';
import { verifyTurnstile } from '../../lib/turnstile.js';

export async function login({ request, env }) {
	const form = await request.formData();
	const human = await verifyTurnstile(form.get('cf-turnstile-response'), env, request.headers.get('cf-connecting-ip'));
	if (!human) return json({ error: 'turnstile' }, 403);
	// TODO: check form.get('username') / form.get('password') against backend
	const user = { id: 'HELLO WORLD', username: form.get('username') };
	return json({ user }, 200, await setSession(user, env));
}
