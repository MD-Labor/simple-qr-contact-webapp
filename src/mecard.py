"""Build MECARD payloads for contact QR codes.

MECARD (NTT DoCoMo) is the compact contact format both iOS Camera and Android
recognize natively, which is why it beats vCard for a QR code - fewer bytes
means a lower QR version and a less dense, more scannable code.

Shape:

    MECARD:N:Lastname,Firstname;TEL:+15550100;EMAIL:a@b.gov;URL:https://x;;

Note the terminating ';;' - one ';' closes the final field and one closes the
record. Scanners are picky about it.
"""
from __future__ import annotations

import re

# Only these two genuinely break a record: '\' starts an escape and ';' ends a
# field. We deliberately do NOT escape ':' - parsers split each field on its
# first colon only, so 'URL:https://x' is unambiguous, and escaping it makes
# phones display a literal backslash in the URL.
_MECARD_SPECIALS = "\\;"

# ',' separates the components of N, so it is escaped in name parts only.
_NAME_SPECIALS = _MECARD_SPECIALS + ","

_DIGITS = re.compile(r"\D")


def _escape_with(value: str, specials: str) -> str:
    value = value.replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
    out = []
    for ch in value:
        if ch in specials:
            out.append("\\")
        out.append(ch)
    return "".join(out).strip()


def escape(value: str) -> str:
    """Escape MECARD structural characters in a field value."""
    return _escape_with(value, _MECARD_SPECIALS)


def escape_name_part(value: str) -> str:
    """Escape a single component of the N field, where ',' is structural."""
    return _escape_with(value, _NAME_SPECIALS)


def normalize_phone(raw: str, default_country: str = "1") -> str:
    """Best-effort E.164. Falls back to the cleaned original when unsure.

    '555-555-5555' -> '+15555555555'; '+44 20 7123 4567' -> '+442071234567'.
    A number we cannot confidently interpret is passed through digits-only
    rather than mangled, since a wrong number is worse than an unpretty one.
    """
    raw = raw.strip()
    if not raw:
        return ""
    had_plus = raw.startswith("+")
    digits = _DIGITS.sub("", raw)
    if not digits:
        return ""
    if had_plus:
        return "+" + digits
    # Strip a US long-distance trunk prefix before length-testing.
    if len(digits) == 11 and digits.startswith(default_country):
        return "+" + digits
    if len(digits) == 10:
        return "+" + default_country + digits
    return digits


def build(
    *,
    first: str = "",
    last: str = "",
    phones: list[str] | None = None,
    email: str = "",
    url: str = "",
    org: str = "",
    note: str = "",
    normalize_phones: bool = True,
) -> str:
    """Assemble a MECARD record, omitting every empty field.

    `phones` may hold several numbers; MECARD allows repeated TEL entries and
    scanners surface them as separate numbers on the contact.
    """
    fields: list[str] = []

    # MECARD orders the name as Last,First - reversed from how it is displayed.
    if last or first:
        name = escape_name_part(last)
        if first:
            name = f"{name},{escape_name_part(first)}"
        fields.append(f"N:{name}")

    for phone in phones or []:
        number = normalize_phone(phone) if normalize_phones else phone
        if number:
            fields.append(f"TEL:{escape(number)}")

    if email:
        fields.append(f"EMAIL:{escape(email)}")
    if url:
        fields.append(f"URL:{escape(url)}")
    if org:
        fields.append(f"ORG:{escape(org)}")
    if note:
        fields.append(f"NOTE:{escape(note)}")

    if not fields:
        raise ValueError("A MECARD needs at least one field (name, phone, or email).")

    return "MECARD:" + ";".join(fields) + ";;"
