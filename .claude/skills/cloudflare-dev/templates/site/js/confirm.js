// Render collected answers into <dl id="review"> and submit them on confirm.
export default function confirm(form, answers) {
	const dl = form.querySelector('#review');
	dl.innerHTML = Object.entries(answers).map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join('');
	form.addEventListener('submit', async (e) => {
		e.preventDefault();
		const res = await fetch(form.action, {
			method: 'POST',
			headers: { 'content-type': 'application/json' },
			body: JSON.stringify(answers),
		});
		alert(res.ok ? 'Submitted' : 'Submit failed');
	});
}
