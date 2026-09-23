// Attach to a login <form>; posts to form.action, cookie is set by the server.

// Turnstile renders the widget itself only for markup that was in the page when its script
// loaded. This form arrives later, from steps.js, so we render it — otherwise the div stays
// empty, the post carries no cf-turnstile-response, and api/login rejects it as a bot.
// The script is async, so it may not have arrived yet; 'load' waits for it. If it never
// arrives, no widget and no token: the server still refuses, which is the safe direction.
function turnstileWidget(form) {
	const widget = form.querySelector('.cf-turnstile');
	if (!widget) return;
	const render = () => window.turnstile?.render(widget, { sitekey: widget.dataset.sitekey });
	if (window.turnstile) render();
	else window.addEventListener('load', render, { once: true });
}

export default function login(form, onSuccess) {
	turnstileWidget(form);
	form.addEventListener('submit', async (e) => {
		e.preventDefault();
		const res = await fetch(form.action, { method: 'POST', body: new FormData(form) });
		if (res.ok) onSuccess(await res.json());
		else alert('Login failed');
	});
}
