import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

import qrrender

SRC = Path(__file__).resolve().parent.parent / "src"
LOGO_SVG = SRC / "maryland-logo.svg"
LOGO_PNG = SRC / "maryland-logo.png"

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def build(data="https://maryland.gov", level="H", box=10):
    return qrrender.build_qr(data, qrrender.ERROR_LEVELS[level], box_size=box)


class TestBundledAssets:
    """These live beside entry.py because pywrangler only ships that directory."""

    def test_both_logo_assets_are_present(self):
        assert LOGO_SVG.is_file(), "run scripts/bake_logo.py"
        assert LOGO_PNG.is_file(), "run scripts/bake_logo.py"

    def test_the_raster_logo_keeps_an_alpha_channel(self):
        from PIL import Image

        with Image.open(LOGO_PNG) as img:
            assert img.mode == "RGBA"
            # Without transparency the logo paints an opaque box on the QR.
            assert img.getchannel("A").getextrema()[0] == 0


class TestSnapRectToGrid:
    def test_edges_land_on_module_boundaries(self):
        x, y, w, h = qrrender.snap_rect_to_grid(13, 27, 44, 51, 10)
        for value in (x, y, x + w, y + h):
            assert value % 10 == 0

    def test_the_rect_only_ever_grows(self):
        x, y, w, h = qrrender.snap_rect_to_grid(13, 27, 44, 51, 10)
        assert x <= 13 and y <= 27
        assert x + w >= 13 + 44
        assert y + h >= 27 + 51

    def test_an_aligned_rect_is_unchanged(self):
        assert qrrender.snap_rect_to_grid(10, 20, 30, 40, 10) == (10, 20, 30, 40)


class TestErrorLevelDefaults:
    def test_a_logo_forces_maximum_error_correction(self):
        assert qrrender.default_error_level(True) == "H"

    def test_a_bare_code_uses_the_balanced_default(self):
        assert qrrender.default_error_level(False) == "M"


class TestRenderSvg:
    def test_output_is_well_formed_xml(self):
        svg = qrrender.render_svg(build(), "black", "white", None, 0.22, "white", False)
        ET.fromstring(svg)

    def test_dimensions_follow_module_count_border_and_box_size(self):
        qr = build(box=10)
        svg = qrrender.render_svg(qr, "black", "white", None, 0.22, "white", False)
        expected = (len(qr.get_matrix()) + 2 * qr.border) * qr.box_size
        root = ET.fromstring(svg)
        assert root.get("width") == str(expected)
        assert root.get("viewBox") == f"0 0 {expected} {expected}"

    def test_a_transparent_background_emits_no_background_rect(self):
        svg = qrrender.render_svg(build(), "black", "transparent", None, 0.22, "white", False)
        assert 'width="100%"' not in svg

    def test_an_opaque_background_emits_a_background_rect(self):
        svg = qrrender.render_svg(build(), "black", "white", None, 0.22, "white", False)
        assert 'width="100%"' in svg

    def test_an_svg_logo_is_embedded_as_vector_not_a_bitmap(self):
        svg = qrrender.render_svg(build(), "black", "white", LOGO_SVG, 0.22, "white", False)
        assert "base64" not in svg
        assert svg.count("<svg") == 2

    def test_a_raster_logo_is_embedded_as_a_data_uri(self):
        svg = qrrender.render_svg(build(), "black", "white", LOGO_PNG, 0.22, "white", False)
        assert "data:image/png;base64," in svg

    def test_the_foreground_color_is_emitted_once_not_per_module(self):
        """Per-module fills would scale the document with len(fg) x modules."""
        color = "#" + "a" * 6
        svg = qrrender.render_svg(build(), color, "white", None, 0.22, "white", False)
        assert svg.count(color) == 1
        assert f'<g fill="{color}">' in svg

    def test_a_long_foreground_color_does_not_inflate_the_document(self):
        qr = build()
        short = qrrender.render_svg(qr, "black", "white", None, 0.22, "white", False)
        long = qrrender.render_svg(qr, "b" * 4000, "white", None, 0.22, "white", False)
        assert len(long) - len(short) < 4100

    def test_modules_inherit_the_group_fill(self):
        qr = build()
        svg = qrrender.render_svg(qr, "navy", "white", None, 0.22, "white", False)
        root = ET.fromstring(svg)
        group = root.find("{http://www.w3.org/2000/svg}g")
        assert group is not None and group.get("fill") == "navy"
        dark = sum(sum(1 for cell in row if cell) for row in qr.get_matrix())
        rects = group.findall("{http://www.w3.org/2000/svg}rect")
        assert len(rects) == dark
        assert all(rect.get("fill") is None for rect in rects)

    def test_the_logo_is_not_inside_the_foreground_group(self):
        """Inheriting the module colour would repaint the logo."""
        svg = qrrender.render_svg(build(), "navy", "white", LOGO_SVG, 0.22, "white", False)
        root = ET.fromstring(svg)
        group = root.find("{http://www.w3.org/2000/svg}g")
        assert group.find("{http://www.w3.org/2000/svg}svg") is None
        assert root.find("{http://www.w3.org/2000/svg}svg") is not None

    def test_colors_are_xml_escaped(self):
        svg = qrrender.render_svg(build(), 'black"/><script>', "white", None, 0.22, "white", False)
        ET.fromstring(svg)
        assert "<script>" not in svg


class TestRenderRaster:
    def test_png_output_has_a_png_header(self):
        blob = qrrender.render_raster(build(), "png", "black", "white", None, 0.22, "white", False)
        assert blob.startswith(PNG_MAGIC)

    def test_a_raster_logo_is_composited(self):
        blob = qrrender.render_raster(build(), "png", "black", "white", LOGO_PNG, 0.22, "white", False)
        assert blob.startswith(PNG_MAGIC)

    def test_jpeg_rejects_a_transparent_background(self):
        with pytest.raises(ValueError, match="JPEG does not support transparent"):
            qrrender.render_raster(build(), "jpg", "black", "transparent", None, 0.22, "white", False)

    def test_an_svg_logo_into_raster_fails_with_a_usable_message(self):
        """Workers has no cairo, so this path must explain itself rather than crash."""
        try:
            import cairosvg  # noqa: F401
        except ImportError:
            pass
        else:
            pytest.skip("cairosvg is installed, so this path succeeds here")

        with pytest.raises(ValueError, match="pre-rasterized"):
            qrrender.render_raster(build(), "png", "black", "white", LOGO_SVG, 0.22, "white", False)


class TestFormatAndLogoValidation:
    @pytest.mark.parametrize("name,expected", [("a.png", "png"), ("a.SVG", "svg"), ("a.jpeg", "jpeg")])
    def test_recognized_extensions(self, name, expected):
        assert qrrender.infer_format(Path(name)) == expected

    @pytest.mark.parametrize("name", ["a.bmp", "a.gif", "noextension"])
    def test_rejected_outputs(self, name):
        with pytest.raises(ValueError):
            qrrender.infer_format(Path(name))

    def test_logo_kinds(self):
        assert qrrender.infer_logo_kind(Path("a.svg")) == "svg"
        assert qrrender.infer_logo_kind(Path("a.png")) == "raster"
        with pytest.raises(ValueError):
            qrrender.infer_logo_kind(Path("a.pdf"))


class TestLogoAspect:
    def test_svg_and_raster_agree_on_the_same_logo(self):
        """The two render paths must size the logo identically."""
        assert qrrender.get_logo_aspect(LOGO_SVG) == pytest.approx(
            qrrender.get_logo_aspect(LOGO_PNG), rel=0.02
        )

    def test_the_maryland_logo_is_wider_than_tall(self):
        assert qrrender.get_logo_aspect(LOGO_SVG) > 1.0
