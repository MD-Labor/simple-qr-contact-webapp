/*
 * Signature generator controller.
 *
 * Builds the signature preview and the contact QR code from the form, then
 * copies the preview as rich HTML so it can be pasted into Gmail or Outlook.
 *
 * The QR <img> deliberately points at an absolute URL on this origin. Mail
 * clients fetch signature images from their own network, so a relative path or
 * a data: URI would simply not render for the recipient.
 */

const PHONE_TYPES = [
	{ key: 'Mobile', suffix: '(M)' },
	{ key: 'Office', suffix: '(O)' },
	{ key: 'Fax', suffix: '(F)' },
];

const PLACEHOLDERS = {
	name: 'Firstname Lastname',
	title: 'Job Title',
	division: 'Division',
	email: 'name@maryland.gov',
	mobile: '555-555-5555 (M)',
};

const ORG_NAME = 'Maryland Department of Labor';

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

function phoneValue(type) {
	return $('chk' + type).checked ? $('in' + type).value.trim() : '';
}

/* Absolute so the copied signature resolves from a mail client. */
function qrUrl(format) {
	const name = $('inName').value.trim();
	const email = $('inEmail').value.trim();
	const mobile = phoneValue('Mobile');
	const office = phoneValue('Office');

	// Nothing identifying yet - the API would reject an empty card.
	if (!name && !email && !mobile && !office) return null;

	const { first, last } = splitName(name);
	const params = new URLSearchParams();
	if (first) params.set('first', first);
	if (last) params.set('last', last);
	if (mobile) params.set('mobile', mobile);
	if (office) params.set('office', office);
	if (email) params.set('email', email);
	if ($('chkQrOrg').checked) params.set('org', ORG_NAME);

	return new URL(`/api/mecard.${format}?${params}`, location.origin).href;
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

	updateQr();
}

function updateQr() {
	const cell = $('outQrCell');
	const img = $('outQr');
	const png = qrUrl('png');
	const wanted = $('chkQr').checked && png !== null;

	cell.style.display = wanted ? 'table-cell' : 'none';
	$('chkQrOrg').disabled = !$('chkQr').checked;

	if (wanted) {
		if (img.getAttribute('src') !== png) img.src = png;
		const who = $('inName').value.trim();
		img.alt = who ? `QR code with ${who}'s contact details` : 'QR code with this contact’s details';
	} else {
		img.removeAttribute('src');
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
		$('chk' + key).addEventListener('change', () => {
			togglePhone(key);
			updateQr();
		});
	}

	$('chkQr').addEventListener('change', updateQr);
	$('chkQrOrg').addEventListener('change', updateQr);
	$('btnCopy').addEventListener('click', copySignature);

	$('outQr').addEventListener('error', () => {
		flash('The QR code could not be generated - check the details above.');
	});

	if (['localhost', '127.0.0.1', '[::1]'].includes(location.hostname)) {
		$('devNote').hidden = false;
	}

	for (const { key } of PHONE_TYPES) togglePhone(key);
	updateSig();
}

init();
