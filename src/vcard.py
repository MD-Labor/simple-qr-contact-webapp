"""Build vCard 3.0 payloads for contact QR codes.

MECARD cannot label a phone number: its TEL field takes no type parameter, so a
card carrying a desk, a mobile and a fax number arrives on the phone as three
identical 'phone' entries. vCard has TYPE, and both iOS Camera and Android read
it from a QR code.

The cost is bytes. vCard spends them on BEGIN/VERSION/END, on property names
that are longer than MECARD's, and on CRLF between every line - roughly twice
the payload for the same contact, which is one or two QR versions denser. Use
mecard.py when a code has to stay small and the labels do not matter.

Version 3.0 rather than 4.0 deliberately: 3.0's TYPE=CELL/WORK/FAX vocabulary is
what the widest range of phones actually recognizes.
"""
from __future__ import annotations

from mecard import normalize_phone

# Maps our own phone kinds onto vCard 3.0 TYPE values. The phone decides how to
# label these; in practice iOS shows 'mobile', 'work' and 'work fax'.
PHONE_TYPES = {
    "cell": "CELL",
    "work": "WORK,VOICE",
    "fax": "WORK,FAX",
    "home": "HOME,VOICE",
}

DEFAULT_PHONE_KIND = "work"


def escape(value: str) -> str:
    """Escape a vCard text value.

    Backslash first - doubling it after adding escapes would double those too.
    """
    value = value.replace("\\", "\\\\")
    value = value.replace("\r\n", "\\n").replace("\r", "\\n").replace("\n", "\\n")
    value = value.replace(",", "\\,").replace(";", "\\;")
    return value.strip()


def build(
    *,
    first: str = "",
    last: str = "",
    phones: list[tuple[str, str]] | None = None,
    email: str = "",
    url: str = "",
    org: str = "",
    title: str = "",
    note: str = "",
    normalize_phones: bool = True,
) -> str:
    """Assemble a vCard 3.0 record, omitting every empty field.

    `phones` is a list of (kind, number) pairs, where kind is a key of
    PHONE_TYPES. An unknown kind falls back to a plain work number rather than
    emitting a TYPE the phone would not understand.

    Lines are deliberately not folded at 75 octets. Folding is in the spec, but
    it costs three bytes per wrap in a payload where bytes are QR modules, and
    every scanner tested reads the unfolded form.
    """
    body: list[str] = []

    for kind, number in phones or []:
        value = normalize_phone(number) if normalize_phones else number
        if not value:
            continue
        tel_type = PHONE_TYPES.get(kind, PHONE_TYPES[DEFAULT_PHONE_KIND])
        body.append(f"TEL;TYPE={tel_type}:{escape(value)}")

    if title:
        body.append(f"TITLE:{escape(title)}")
    if org:
        body.append(f"ORG:{escape(org)}")
    if email:
        body.append(f"EMAIL:{escape(email)}")
    if url:
        body.append(f"URL:{escape(url)}")
    if note:
        body.append(f"NOTE:{escape(note)}")

    display = " ".join(part for part in (first.strip(), last.strip()) if part)

    if not (display or body):
        raise ValueError("A vCard needs at least one field (name, phone, or email).")

    head: list[str] = []
    if display:
        # N is Family;Given;Middle;Prefix;Suffix - the trailing separators are
        # required even when empty.
        head.append(f"N:{escape(last)};{escape(first)};;;")

    # FN is mandatory in vCard 3.0, so a card with no name still needs one. Org
    # then email is the least surprising thing to show as the contact's title.
    head.append(f"FN:{escape(display or org or email or url)}")

    return "\r\n".join(["BEGIN:VCARD", "VERSION:3.0"] + head + body + ["END:VCARD"])
