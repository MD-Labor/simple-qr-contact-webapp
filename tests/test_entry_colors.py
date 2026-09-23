"""Colour validation on the API surface.

entry.py only runs on Workers, so the two runtime modules it imports are
stubbed here. Everything exercised below is plain Python.
"""
import sys
import types

import pytest

for name, attrs in (
    ("pyodide", {}),
    ("pyodide.ffi", {"to_js": lambda value: value}),
    ("workers", {"Response": object, "WorkerEntrypoint": type("WorkerEntrypoint", (), {})}),
):
    module = types.ModuleType(name)
    for attr, value in attrs.items():
        setattr(module, attr, value)
    sys.modules.setdefault(name, module)
sys.modules["pyodide"].ffi = sys.modules["pyodide.ffi"]

import entry  # noqa: E402  (needs the stubs above)


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
