// POST a field to the API for server-side validation; returns { ok, message }.
export default async function validate(field, value, url = '/api/validate') {
	const res = await fetch(url, {
		method: 'POST',
		headers: { 'content-type': 'application/json' },
		body: JSON.stringify({ field, value }),
	});
	return res.json();
}
