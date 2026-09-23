import { login as v1Login } from '../v1/login.js';

// Example override: wrap v1 and add a field to the response.
export async function login(ctx) {
	const res = await v1Login(ctx);
	const body = await res.json();
	return new Response(JSON.stringify({ ...body, version: 2 }), res);
}
