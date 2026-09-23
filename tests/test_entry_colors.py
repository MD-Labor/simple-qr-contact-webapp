"""Colour validation on the API surface.

conftest.py stubs the two Workers-only modules entry.py imports; everything
exercised below is plain Python.
"""
import pytest

import entry


class TestColorValidation:
    @pytest.mark.parametrize(
        "value",
        [
            "black",
            "transparent",
            "none",
            "#fff",
            "#ffff",
            "#1a1a1a",
            "#1a1a1aff",
            "rgb(255, 0, 0)",
            "rgba(255, 0, 0, 0.5)",
            "hsl(210 100% 50%)",
        ],
    )
    def test_accepted(self, value):
        assert entry._check_color("fg", value) == value

    @pytest.mark.parametrize(
        "value",
        [
            "a" * 65,
            "#12345",
            "#gggggg",
            'black"/><script>alert(1)</script>',
            "url(#x)",
            "rgb(255, 0, 0",
            "black; fill:red",
        ],
    )
    def test_rejected(self, value):
        with pytest.raises(entry.ApiError):
            entry._check_color("fg", value)

    def test_a_multi_kilobyte_color_is_refused_without_echoing_it(self):
        """The amplification input: one fg used to be copied per dark module."""
        huge = "b" * 14000
        with pytest.raises(entry.ApiError) as exc:
            entry._check_color("fg", huge)
        assert str(entry.MAX_COLOR_LEN) in exc.value.message
        assert huge not in exc.value.message
        assert exc.value.status == 400

    def test_a_trailing_newline_does_not_slip_past_the_grammar(self):
        with pytest.raises(entry.ApiError):
            entry._check_color("fg", "red\n")


class TestRenderColors:
    """_render is the only caller; params arrive shaped like parse_qs output."""

    def test_a_huge_fg_is_refused_before_anything_is_rendered(self):
        with pytest.raises(entry.ApiError) as exc:
            entry._render("hello", {"fg": ["b" * 14000], "logo": ["none"]}, "svg")
        assert exc.value.status == 400

    def test_the_color_alias_is_named_in_its_own_error(self):
        with pytest.raises(entry.ApiError) as exc:
            entry._render("hello", {"color": ["b" * 100], "logo": ["none"]}, "svg")
        assert exc.value.message.startswith("'color'")

    def test_a_color_svg_takes_but_pillow_cannot_read_is_a_400_not_a_500(self):
        params = {"fg": ["rgba(255, 0, 0, 0.5)"], "logo": ["none"]}
        assert entry._render("hello", params, "svg").status == 200
        with pytest.raises(entry.ApiError) as exc:
            entry._render("hello", params, "png")
        assert exc.value.status == 400

    def test_the_rendered_svg_carries_the_color_once(self):
        response = entry._render(
            "hello", {"fg": ["#123456"], "logo": ["none"]}, "svg"
        )
        assert response.body.count("#123456") == 1
