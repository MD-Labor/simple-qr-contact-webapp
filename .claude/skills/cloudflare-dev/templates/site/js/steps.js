// Mounts one step fragment at a time into a container; returns start/next/back.
// `plan` is a list of [name, html] pairs, or a function returning one. A function is
// re-read on every move, so a slot's fragment can vary by what the applicant answered
// (e.g. a different eligibility step per route to licensure) and slots can be added or
// dropped. Steps are identified by name, not index, so main.js wiring survives that.
//
// Nothing is shown until start(). That is deliberate: the first step dispatches 'step'
// like any other, so the caller must be listening before it fires or step one's form
// never gets wired and its submit falls through to a native page POST.
export default function steps(container, plan) {
	const list = () => (typeof plan === 'function' ? plan() : plan);
	let i = 0;
	const show = () => {
		const [name, html] = list()[i];
		container.innerHTML = html;
		// Swapping innerHTML would otherwise drop focus to <body> and leave a screen reader
		// with no idea the page changed. Move it to the new step's heading.
		const heading = container.querySelector('h1, h2, h3') ?? container;
		heading.setAttribute('tabindex', '-1');
		heading.focus();
		container.dispatchEvent(new CustomEvent('step', { detail: { name, index: i, total: list().length } }));
	};
	return {
		start() { i = 0; show(); },
		next() { if (i < list().length - 1) { i++; show(); } },
		back() { if (i > 0) { i--; show(); } },
		get index() { return i; },
	};
}
