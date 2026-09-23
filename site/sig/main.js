/*
 * Signature generator controller.
 *
 * Builds the signature preview from the form and copies it as rich HTML so it
 * can be pasted into Gmail or Outlook. The contact QR code is generated from
 * the same fields but lives in its own section, deliberately outside the
 * signature: a mail client would have to fetch it from this origin on every
 * send, and recipients on other networks often would not see it at all.
 */

/* 'suffix' is what the signature shows; 'param' is the API field, which decides
 * the label the number arrives with on a phone. */
const PHONE_TYPES = [
	{ key: 'Mobile', suffix: '(M)', param: 'mobile' },
	{ key: 'Office', suffix: '(O)', param: 'office' },
	{ key: 'Fax', suffix: '(F)', param: 'fax' },
];

const PLACEHOLDERS = {
	name: 'Firstname Lastname',
	title: 'Job Title',
	division: 'Division',
	email: 'name@maryland.gov',
	mobile: '(555) 555-5555 (M)',
};

/* Long enough that a paused typist sees the code appear promptly, long enough
 * that typing a name does not fire a request per keystroke. Without this the
 * API was asked to render every prefix of the name, and a half-typed 'Jay'
 * could still be the image on screen when the last request lost the race. */
const QR_DEBOUNCE_MS = 350;

const $ = (id) => document.getElementById(id);

/* Split a display name into MECARD's Last,First. The last whitespace-separated
 * token is treated as the family name, so 'Mary Ellen Smith' yields
 * first='Mary Ellen', last='Smith'. */
function splitName(full) {
	const parts = full.trim().split(/\s+/).filter(Boolean);
	if (parts.length === 0) return { first: '', last: '' };
	if (parts.length === 1) return { first: '', last: parts[0] };
	return { first: parts.slice(0, -1).join(' '), last: parts[parts.length - 1] };
}

/* '4105550100' -> '(410) 555-0100', formatting as far as the digits reach.
 *
 * Ten digits, and only ever ten. Every number this form collects is US, so there
 * is no international case to keep intact and no reason to accept an eleventh
 * digit: anything past the tenth is dropped as it is typed. The alphabet that
 * survives is digits plus the '()- ' the formatter itself inserts - letters,
 * '+', '.' and an 'x1234' extension are all stripped out.
 *
 * A country-code 1 is absorbed rather than counted, so pasting '+1 410 555 0100'
 * still lands on '(410) 555-0100' instead of shifting every digit one place. */
function formatPhone(raw) {
	let digits = String(raw).replace(/\D/g, '');
	if (digits.length > 10 && digits[0] === '1') digits = digits.slice(1);

	const local = digits.slice(0, 10);
	if (!local) return '';
	// The parens appear only once there is a fourth digit, so backspacing out of
	// a 3-digit area code does not fight a bracket the user cannot delete.
	if (local.length <= 3) return local;
	if (local.length <= 6) return `(${local.slice(0, 3)}) ${local.slice(3)}`;
	return `(${local.slice(0, 3)}) ${local.slice(3, 6)}-${local.slice(6)}`;
}

/* Reformat in place, keeping the caret on the digit the user was editing.
 * Without that, correcting a digit mid-number throws the caret to the end. */
function reformatPhoneField(input) {
	const before = input.value;
	const formatted = formatPhone(before);
	if (formatted === before) return;

	const caret = input.selectionStart;
	const atEnd = caret === before.length;
	const digitsBefore = before.slice(0, caret).replace(/\D/g, '').length;

	input.value = formatted;
	if (atEnd) return;

	let seen = 0;
	let position = digitsBefore === 0 ? 0 : formatted.length;
	for (let i = 0; i < formatted.length; i++) {
		if (!/\d/.test(formatted[i])) continue;
		seen += 1;
		if (seen === digitsBefore) {
			position = i + 1;
			break;
		}
	}
	input.setSelectionRange(position, position);
}

function phoneValue(type) {
	return $('chk' + type).checked ? $('in' + type).value.trim() : '';
}

/* Absolute, so the download links and the <img> resolve the same way.
 *
 * vCard rather than MECARD: MECARD's TEL field carries no type, so a desk, a
 * mobile and a fax number all arrive on the phone labelled 'phone'. vCard keeps
 * the labels, at the cost of a denser code - which is why the QR is displayed
 * at 300px, measured as the size all three numbers still decode at. */
function qrUrl(format) {
	const name = $('inName').value.trim();
	const email = $('inEmail').value.trim();
	const phones = PHONE_TYPES.map(({ key, param }) => [param, phoneValue(key)]).filter(([, v]) => v);

	// Nothing identifying yet - the API would reject an empty card.
	if (!name && !email && !phones.length) return null;

	const { first, last } = splitName(name);
	const params = new URLSearchParams();
	if (first) params.set('first', first);
	if (last) params.set('last', last);
	for (const [param, value] of phones) params.set(param, value);
	if (email) params.set('email', email);

	// ORG is not passed: /api/vcard already defaults to the department, so the
	// name lives in one place (src/entry.py) instead of two.
	return new URL(`/api/vcard.${format}?${params}`, location.origin).href;
}

function togglePhone(type) {
	const on = $('chk' + type).checked;
	$('field' + type).classList.toggle('hidden-field', !on);
	$('out' + type + 'Row').style.display = on ? 'block' : 'none';
}

function updateSig() {
	$('outName').innerText = $('inName').value.trim() || PLACEHOLDERS.name;
	$('outTitle').innerText = $('inTitle').value.trim() || PLACEHOLDERS.title;
	$('outDiv').innerText = $('inDiv').value.trim() || PLACEHOLDERS.division;

	const email = $('inEmail').value.trim() || PLACEHOLDERS.email;
	$('outEmail').innerText = email;
	$('outEmailLink').href = 'mailto:' + email;

	for (const { key, suffix } of PHONE_TYPES) {
		const raw = $('in' + key).value.trim();
		const fallback = key === 'Mobile' ? PLACEHOLDERS.mobile : '';
		$('out' + key).innerText = raw ? `${raw} ${suffix}` : fallback;
	}

	scheduleQr();
}

let qrTimer = 0;

function scheduleQr() {
	clearTimeout(qrTimer);
	qrTimer = setTimeout(updateQr, QR_DEBOUNCE_MS);
}

function updateQr() {
	clearTimeout(qrTimer);

	const img = $('outQr');
	const png = qrUrl('png');

	img.hidden = png === null;
	$('qrEmpty').hidden = png !== null;

	if (png) {
		if (img.getAttribute('src') !== png) img.src = png;
		const who = $('inName').value.trim();
		img.alt = who ? `QR code with ${who}'s contact details` : 'QR code with this contact’s details';
	} else {
		img.removeAttribute('src');
		img.alt = '';
	}

	const slug = ($('inName').value.trim() || 'contact').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
	for (const [id, format] of [['dlPng', 'png'], ['dlSvg', 'svg']]) {
		const href = qrUrl(format);
		const link = $(id);
		if (href) {
			link.href = href;
			link.download = `qr-${slug}.${format}`;
			link.removeAttribute('aria-disabled');
		} else {
			link.removeAttribute('href');
			link.setAttribute('aria-disabled', 'true');
		}
	}
}

function flash(text) {
	const msg = $('msg');
	msg.innerText = text;
	msg.style.display = 'inline';
	clearTimeout(flash.timer);
	flash.timer = setTimeout(() => {
		msg.style.display = 'none';
	}, 4000);
}

/* Select-and-copy keeps the rich formatting that mail clients need. The
 * Clipboard API is tried first; execCommand is the fallback for older
 * browsers and for permission prompts the user declines. */
async function copySignature() {
	const table = $('signaturePreview');
	const html = table.outerHTML;

	if (navigator.clipboard && window.ClipboardItem) {
		try {
			await navigator.clipboard.write([
				new ClipboardItem({
					'text/html': new Blob([html], { type: 'text/html' }),
					'text/plain': new Blob([table.innerText], { type: 'text/plain' }),
				}),
			]);
			flash('Copied! Now paste into Gmail settings.');
			return;
		} catch {
			// Fall through to the selection-based copy.
		}
	}

	const range = document.createRange();
	range.selectNode(table);
	const selection = window.getSelection();
	selection.removeAllRanges();
	selection.addRange(range);
	const ok = document.execCommand('copy');
	selection.removeAllRanges();
	flash(ok ? 'Copied! Now paste into Gmail settings.' : 'Copy failed - select the preview and press Ctrl+C.');
}

function init() {
	$('sigForm').addEventListener('input', updateSig);

	for (const { key } of PHONE_TYPES) {
		const input = $('in' + key);

		// Listeners on the input itself run before the form's bubbled handler, so
		// the signature and the QR both read the already-formatted value.
		// 'change' as well as 'input': some browsers autofill without firing 'input'.
		const reformat = () => reformatPhoneField(input);
		input.addEventListener('input', reformat);
		input.addEventListener('change', reformat);

		$('chk' + key).addEventListener('change', () => {
			togglePhone(key);
			updateQr();
		});
	}

	$('btnCopy').addEventListener('click', copySignature);

	// A pending debounce would leave the code a keystroke behind at the moment
	// someone reaches for it.
	$('dlPng').addEventListener('click', updateQr);
	$('dlSvg').addEventListener('click', updateQr);

	$('outQr').addEventListener('error', () => {
		flash('The QR code could not be generated - check the details above.');
	});

	for (const { key } of PHONE_TYPES) {
		reformatPhoneField($('in' + key));
		togglePhone(key);
	}

	updateSig();
	updateQr();
}

init();
