import pytest

import mecard


class TestEscaping:
    def test_semicolon_is_escaped_because_it_ends_a_field(self):
        assert mecard.escape("a;b") == "a\\;b"

    def test_backslash_is_escaped(self):
        assert mecard.escape("a\\b") == "a\\\\b"

    def test_colon_is_not_escaped(self):
        """Parsers split each field on its first colon, so a URL needs no escape.

        Escaping it makes phones show a literal backslash in the URL.
        """
        assert mecard.escape("https://labor.maryland.gov/") == "https://labor.maryland.gov/"

    def test_comma_is_not_escaped_in_ordinary_values(self):
        assert mecard.escape("Baltimore, MD") == "Baltimore, MD"

    def test_comma_is_escaped_in_name_parts_where_it_separates_components(self):
        assert mecard.escape_name_part("Smith, Jr.") == "Smith\\, Jr."

    def test_newlines_collapse_to_spaces(self):
        assert mecard.escape("line1\r\nline2") == "line1 line2"


class TestNormalizePhone:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("555-555-5555", "+15555555555"),
            ("(410) 555-0199", "+14105550199"),
            ("410.555.0199", "+14105550199"),
            ("1-410-555-0199", "+14105550199"),
            ("+44 20 7123 4567", "+442071234567"),
            ("", ""),
            ("   ", ""),
        ],
    )
    def test_normalizes(self, raw, expected):
        assert mecard.normalize_phone(raw) == expected

    def test_unrecognized_length_passes_through_digits_rather_than_guessing(self):
        # An extension or partial number must not be mangled into a wrong number.
        assert mecard.normalize_phone("12345") == "12345"

    def test_letters_only_yields_empty(self):
        assert mecard.normalize_phone("call me") == ""


class TestBuild:
    def test_matches_the_documented_shape(self):
        assert mecard.build(
            first="Firstname",
            last="Lastname",
            phones=["+15550100"],
            email="email@example.com",
            url="https://example.com",
        ) == (
            "MECARD:N:Lastname,Firstname;TEL:+15550100;"
            "EMAIL:email@example.com;URL:https://example.com;;"
        )

    def test_terminates_with_two_semicolons(self):
        assert mecard.build(last="Huie").endswith(";;")

    def test_name_is_ordered_last_then_first(self):
        assert "N:Huie,Jay;" in mecard.build(first="Jay", last="Huie")

    def test_surname_only_omits_the_comma(self):
        assert "N:Huie;" in mecard.build(last="Huie")

    def test_empty_fields_are_omitted_entirely(self):
        out = mecard.build(last="Huie", email="", url="", org="")
        assert "EMAIL" not in out
        assert "URL" not in out
        assert "ORG" not in out

    def test_multiple_phones_become_repeated_tel_fields(self):
        out = mecard.build(last="Huie", phones=["410-555-0199", "410-555-0142"])
        assert out.count("TEL:") == 2

    def test_blank_phones_are_dropped(self):
        assert "TEL:" not in mecard.build(last="Huie", phones=["", "   "])

    def test_normalization_can_be_disabled(self):
        out = mecard.build(last="Huie", phones=["555-555-5555"], normalize_phones=False)
        assert "TEL:555-555-5555;" in out

    def test_a_card_with_no_fields_is_an_error(self):
        with pytest.raises(ValueError):
            mecard.build()

    def test_a_semicolon_in_a_value_cannot_forge_a_new_field(self):
        out = mecard.build(last="Huie", email="x@y.gov;TEL:+19999999999")
        assert "\\;TEL:" in out
        assert out.count("TEL:") == 1
