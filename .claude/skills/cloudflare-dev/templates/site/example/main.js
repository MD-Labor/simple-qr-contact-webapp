import login from '/js/login.js';
import logout from '/js/logout.js';
import steps from '/js/steps.js';
import confirm from '/js/confirm.js';

// Step fragments for this board. Every license type under it uses these.
import loginHtml from './steps/login.html?raw';
import routeHtml from './steps/route.html?raw';
import examHtml from './steps/eligibility-exam.html?raw';
import reciprocityHtml from './steps/eligibility-reciprocity.html?raw';
import detailsHtml from './steps/details.html?raw';
import confirmHtml from './steps/confirm.html?raw';

// One controller for the whole board. Each license type's index.html loads this file and
// declares who it is via data-license-type; nothing below is duplicated per license type.
const app = document.getElementById('app');
const answers = { ...app.dataset }; // board + licenseType ride along on every payload

const STEPS = {
	login: loginHtml,
	route: routeHtml,
	details: detailsHtml,
	confirm: confirmHtml,
};

// The eligibility slot is the one step whose fragment depends on an answer rather than on
// the license type: same slot, different questions per route to licensure.
const ELIGIBILITY = {
	examination: examHtml,
	'local-reciprocity': reciprocityHtml,
	'state-reciprocity': reciprocityHtml,
};

// Which steps each license type asks for, in order. This is the only per-license-type
// wiring on the board — add a license type by adding a line here and an index.html.
const FLOWS = {
	apprentice: () => ['login', 'details', 'confirm'],
	journeyperson: () => ['login', 'route', ...(answers.route ? ['eligibility'] : []), 'details', 'confirm'],
};

const fragment = (name) => (name === 'eligibility' ? ELIGIBILITY[answers.route] : STEPS[name]);

// A function, so it is re-read after each step: picking a route rewrites what comes next.
const flow = steps(app, () => FLOWS[answers.licenseType]().map((name) => [name, fragment(name)]));

logout(document.getElementById('logout'));

app.addEventListener('step', ({ detail: { name } }) => {
	const form = app.querySelector('form');
	// Collecting the fields and advancing is the default; only the ends of the flow differ.
	if (name === 'login') login(form, () => flow.next());
	else if (name === 'confirm') confirm(form, answers);
	else form.addEventListener('submit', (e) => {
		e.preventDefault();
		Object.assign(answers, Object.fromEntries(new FormData(form)));
		flow.next();
	});
	app.querySelector('[data-back]')?.addEventListener('click', () => flow.back());
});

// Last, once the listener above is attached — see the note in js/steps.js.
flow.start();
