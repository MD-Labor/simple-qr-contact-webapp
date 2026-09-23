import { json } from '../../lib/respond.js';
import { clearSession } from '../../lib/session.js';

export async function logout() {
	return json({ ok: true }, 200, clearSession());
}
