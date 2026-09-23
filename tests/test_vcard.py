import pytest

import vcard

FULL = dict(
    first="Jay",
    last="Huie",
    email="jay.huie@maryland.gov",
    url="https://labor.maryland.gov/",
    org="Maryland Department of Labor",
)


def lines(payload):
    return payload.split("\r\n")


class TestEnvelope:
    def test_begins_and_ends_correctly(self):
        out = lines(vcard.build(**FULL))
        assert out[0] == "BEGIN:VCARD"
        assert out[1] == "VERSION:3.0"
        assert out[-1] == "END:VCARD"

    def test_lines_are_crlf_separated_as_the_spec_requires(self):
        payload = vcard.build(**FULL)
        assert "\r\n" in payload
        assert "\n" not in payload.replace("\r\n", "")

    def test_a_card_with_no_fields_is_an_error(self):
        with pytest.raises(ValueError):
            vcard.build()


class TestName:
    def test_n_uses_the_five_semicolon_separated_components(self):
        assert "N:Huie;Jay;;;" in lines(vcard.build(first="Jay", last="Huie"))

    def test_fn_is_the_display_order_name(self):
        assert "FN:Jay Huie" in lines(vcard.build(first="Jay", last="Huie"))

    def test_surname_only_still_produces_a_display_name(self):
        assert "FN:Huie" in lines(vcard.build(last="Huie"))

    def test_fn_is_always_present_because_vcard_3_requires_it(self):
        """A phone-only card still has to carry an FN."""
        out = lines(vcard.build(phones=[("cell", "410-555-0100")], org="MD Labor"))
        assert any(line.startswith("FN:") for line in out)

    def test_fn_falls_back_through_org_then_email(self):
        assert "FN:MD Labor" in lines(vcard.build(org="MD Labor", email="a@b.gov"))
        assert "FN:a@b.gov" in lines(vcard.build(email="a@b.gov"))


class TestPhoneLabels:
    """The whole reason this module exists: MECARD cannot do this."""

    @pytest.mark.parametrize(
        "kind,expected",
        [
            ("cell", "TEL;TYPE=CELL:+14105550100"),
            ("work", "TEL;TYPE=WORK,VOICE:+14105550100"),
            ("fax", "TEL;TYPE=WORK,FAX:+14105550100"),
            ("home", "TEL;TYPE=HOME,VOICE:+14105550100"),
        ],
    )
    def test_each_kind_gets_its_own_type(self, kind, expected):
        assert expected in lines(vcard.build(last="Huie", phones=[(kind, "410-555-0100")]))

    def test_three_numbers_keep_three_distinct_labels(self):
        out = vcard.build(
            last="Huie",
            phones=[("cell", "410-555-0100"), ("work", "410-555-0101"), ("fax", "410-555-0102")],
        )
        assert out.count("TEL;") == 3
        assert "TYPE=CELL" in out and "TYPE=WORK,VOICE" in out and "TYPE=WORK,FAX" in out

    def test_an_unknown_kind_falls_back_rather_than_emitting_a_bad_type(self):
        out = lines(vcard.build(last="Huie", phones=[("carrier-pigeon", "410-555-0100")]))
        assert "TEL;TYPE=WORK,VOICE:+14105550100" in out

    def test_numbers_are_normalized_to_e164(self):
        assert "TEL;TYPE=CELL:+14105550100" in lines(
            vcard.build(last="Huie", phones=[("cell", "(410) 555-0100")])
        )

    def test_normalization_can_be_disabled(self):
        out = lines(vcard.build(last="Huie", phones=[("cell", "x100")], normalize_phones=False))
        assert "TEL;TYPE=CELL:x100" in out

    def test_blank_numbers_are_dropped(self):
        assert "TEL" not in vcard.build(last="Huie", phones=[("cell", ""), ("work", "  ")])


class TestEscaping:
    def test_comma_and_semicolon_are_escaped(self):
        assert "ORG:Labor\\, Licensing \\; Regulation" in lines(
            vcard.build(last="Huie", org="Labor, Licensing ; Regulation")
        )

    def test_backslash_is_escaped_once_not_twice(self):
        assert vcard.escape("a\\b") == "a\\\\b"

    def test_newlines_become_the_literal_escape(self):
        assert vcard.escape("line1\r\nline2") == "line1\\nline2"

    def test_a_semicolon_in_a_value_cannot_forge_a_property(self):
        out = vcard.build(last="Huie", note="x\r\nTEL;TYPE=CELL:+19999999999")
        assert out.count("TEL;") == 0
        assert len(lines(out)) == 6  # BEGIN, VERSION, N, FN, NOTE, END

    def test_a_comma_in_a_name_does_not_split_the_component(self):
        assert "N:Huie\\, Jr.;Jay;;;" in lines(vcard.build(first="Jay", last="Huie, Jr."))


class TestOptionalFields:
    def test_empty_fields_are_omitted_entirely(self):
        out = vcard.build(last="Huie")
        for prop in ("TEL", "TITLE", "ORG", "EMAIL", "URL", "NOTE"):
            assert prop not in out

    def test_title_is_included_when_given(self):
        assert "TITLE:Chief Information Officer" in lines(
            vcard.build(last="Huie", title="Chief Information Officer")
        )


class TestDensityTradeoff:
    def test_vcard_is_larger_than_the_equivalent_mecard(self):
        """Documents the cost of labels, so a regression here is visible."""
        import mecard

        phones = [("cell", "410-555-0100"), ("work", "410-555-0101")]
        mine = vcard.build(phones=phones, **FULL)
        theirs = mecard.build(phones=[n for _, n in phones], **FULL)
        assert len(mine) > len(theirs)
        # Roughly double, and it must not quietly get worse than that.
        assert len(mine) < 2.2 * len(theirs)
