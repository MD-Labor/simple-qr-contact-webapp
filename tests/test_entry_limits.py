"""The PNG pixel budget on the API surface.

entry.py only runs on Workers - the real 'workers' package imports 'js', which
exists only inside Pyodide - so the two runtime modules it needs are stubbed
here. setdefault, so this stays correct if the stubs ever move to conftest.
"""
import sys
import types

import pytest

import qrrender


class FakeResponse:
    def __init__(self, body=None, headers=None, status=200):
        self.body = body
        self.headers = headers or {}
        self.status = status

    @classmethod
    def json(cls, payload, status=200):
        return cls(payload, status=status)


class FakeBuffer:
    """Stands in for the JS typed array to_js() returns."""

    def __init__(self, value):
        self.buffer = value


for _name, _attrs in (
    ("pyodide", {}),
    ("pyodide.ffi", {"to_js": FakeBuffer}),
    ("workers", {"Response": FakeResponse, "WorkerEntrypoint": type("W", (), {})}),
):
    _module = types.ModuleType(_name)
    for _attr, _value in _attrs.items():
        setattr(_module, _attr, _value)
    sys.modules.setdefault(_name, _module)
sys.modules["pyodide"].ffi = sys.modules["pyodide.ffi"]

import entry  # noqa: E402  (needs the stubs above)

# The densest code the API will encode: MAX_DATA_LEN caps 'data', and ec=H
# spends the most modules on error correction. 1775 ASCII characters at H is
# version 40 - 177 modules, 185 with the quiet zone, the most there is.
DENSEST = "A" * 1775
DENSE_PARAMS = {"ec": ["H"], "logo": ["none"]}


class TestPngPixelBudget:
    def test_the_densest_code_is_version_40(self):
        """If this ever stops holding, the numbers below need rechecking."""
        qr = qrrender.build_qr(DENSEST, qrrender.ERROR_LEVELS["H"], box_size=1)
        assert qr.version == 40
        assert len(qr.get_matrix()) == 185

    def test_the_densest_code_at_box_40_is_refused(self):
        """7400x7400 RGBA is ~220MB of pixels; the isolate has 128MB."""
        with pytest.raises(entry.ApiError) as exc:
            entry._render(DENSEST, {**DENSE_PARAMS, "box": ["40"]}, "png")
        assert exc.value.status == 400
        assert "7400x7400" in exc.value.message

    def test_the_default_box_is_never_refused(self):
        """box=10 has to keep working for every code that fits MAX_DATA_LEN."""
        for level in ("L", "M", "Q", "H"):
            response = entry._render(
                DENSEST, {"ec": [level], "logo": ["none"]}, "png"
            )
            assert response.status == 200

    def test_the_box_the_error_suggests_actually_renders(self):
        with pytest.raises(entry.ApiError) as exc:
            entry._render(DENSEST, {**DENSE_PARAMS, "box": ["40"]}, "png")
        suggested = int(exc.value.message.split("Use box=")[1].split()[0])
        params = {**DENSE_PARAMS, "box": [str(suggested)]}
        assert entry._render(DENSEST, params, "png").status == 200
        with pytest.raises(entry.ApiError):
            entry._render(DENSEST, {**params, "box": [str(suggested + 1)]}, "png")

    def test_nothing_that_renders_exceeds_the_cap(self):
        """The rasterized side is len(matrix) x box - what Pillow allocates."""
        qr = qrrender.build_qr(DENSEST, qrrender.ERROR_LEVELS["H"], box_size=11)
        assert len(qr.get_matrix()) * qr.box_size <= entry.MAX_PNG_SIDE
        # 2048px of RGBA is ~17MB per copy, and Pillow holds at most two.
        assert entry.MAX_PNG_SIDE ** 2 * 4 * 2 < 40_000_000

    def test_a_small_code_can_still_use_the_largest_box(self):
        response = entry._render("hi", {"box": ["40"], "logo": ["none"]}, "png")
        assert response.status == 200

    def test_svg_is_not_subject_to_the_pixel_budget(self):
        """SVG is text: box only changes the coordinate digits."""
        response = entry._render(DENSEST, {**DENSE_PARAMS, "box": ["40"]}, "svg")
        assert response.status == 200
        assert len(response.body) < 2_000_000
