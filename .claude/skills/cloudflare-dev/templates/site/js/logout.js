export default function logout(el, url = '/api/logout') {
	el.addEventListener('click', async (e) => {
		e.preventDefault();
		await fetch(url, { method: 'POST' });
		location.reload();
	});
}
