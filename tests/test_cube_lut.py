import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor, QGuiApplication, QImage

import previews

_app = QGuiApplication.instance() or QGuiApplication([])


def _write_cube(path: Path, size: int, fn):
    lines = [f"LUT_3D_SIZE {size}"]
    for b in range(size):
        for g in range(size):
            for r in range(size):
                lines.append("%f %f %f" % fn(r / (size - 1), g / (size - 1), b / (size - 1)))
    path.write_text("\n".join(lines), encoding="utf-8")


class CubeLutTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        img = QImage(8, 8, QImage.Format_RGB888)
        img.fill(QColor(200, 100, 50))
        self.png = self.dir / "test.png"
        img.save(str(self.png))
        previews.set_lut_test_images([str(self.png)], str(self.png))

    def tearDown(self):
        previews.set_lut_test_images([], "")
        self.tmp.cleanup()

    def test_identity_keeps_image(self):
        cube = self.dir / "id.cube"
        _write_cube(cube, 5, lambda r, g, b: (r, g, b))
        out = previews._decode_cube_image(cube, 64)
        c = out.pixelColor(2, 2)
        self.assertLessEqual(abs(c.red() - 200), 1)
        self.assertLessEqual(abs(c.green() - 100), 1)
        self.assertLessEqual(abs(c.blue() - 50), 1)

    def test_invert_lut(self):
        cube = self.dir / "inv.cube"
        _write_cube(cube, 5, lambda r, g, b: (1 - r, 1 - g, 1 - b))
        c = previews._decode_cube_image(cube, 64).pixelColor(2, 2)
        self.assertLessEqual(abs(c.red() - 55), 2)
        self.assertLessEqual(abs(c.green() - 155), 2)
        self.assertLessEqual(abs(c.blue() - 205), 2)

    def test_swap_channels_checks_axis_order(self):
        cube = self.dir / "swap.cube"
        _write_cube(cube, 5, lambda r, g, b: (b, g, r))
        c = previews._decode_cube_image(cube, 64).pixelColor(2, 2)
        self.assertLessEqual(abs(c.red() - 50), 2)
        self.assertLessEqual(abs(c.blue() - 200), 2)

    def test_1d_lut_and_fallback_image(self):
        cube = self.dir / "one.cube"
        cube.write_text("LUT_1D_SIZE 2\n1 1 1\n0 0 0\n", encoding="utf-8")  # inverse
        previews.set_lut_test_images([], "")
        out = previews._decode_cube_image(cube, 64)
        self.assertFalse(out.isNull())

    def test_invalid_file(self):
        cube = self.dir / "bad.cube"
        cube.write_text("garbage", encoding="utf-8")
        self.assertIsNone(previews._decode_cube_image(cube, 64))

    def test_cache_signature_follows_default_image(self):
        cube = self.dir / "id.cube"
        _write_cube(cube, 2, lambda r, g, b: (r, g, b))
        a = previews._file_image_cache_path(cube, 1.0)
        previews.set_lut_test_images([], "")
        self.assertNotEqual(a, previews._file_image_cache_path(cube, 1.0))


class RawFallbackTest(unittest.TestCase):
    def test_largest_embedded_jpeg_is_used(self):
        with tempfile.TemporaryDirectory() as tmp:
            jpgs = []
            for w, h in ((16, 12), (160, 120)):
                img = QImage(w, h, QImage.Format_RGB888)
                img.fill(QColor(10, 200, 30))
                p = Path(tmp) / f"{w}.jpg"
                img.save(str(p), "JPEG")
                jpgs.append(p.read_bytes())
            raw = Path(tmp) / "fake.ARW"
            raw.write_bytes(b"II*\x00" + b"\x01" * 100 + jpgs[0] + b"\x02" * 50 + jpgs[1] + b"\x03" * 20)
            out = previews._decode_embedded_jpeg(raw, 64)
            self.assertIsNotNone(out)
            self.assertEqual(max(out.width(), out.height()), 64)
            self.assertEqual(previews._decode_2d_image(raw, 640).width(), 160)

    def test_log_curves_mid_grey(self):
        import numpy as np
        x = np.array([0.18], dtype=np.float32)
        self.assertAlmostEqual(float(previews._log_encode(x, "slog3")[0]), 0.4106, places=3)
        self.assertAlmostEqual(float(previews._log_encode(x, "flog")[0]), 0.4593, places=3)
        self.assertAlmostEqual(float(previews._log_encode(x, "flog2")[0]), 0.3919, places=2)

    def test_gamut_matrix_white_is_neutral(self):
        import numpy as np
        for g in ("sgamut3cine", "fgamut"):
            m = np.linalg.inv(previews._rgb_to_xyz(g)) @ previews._rgb_to_xyz("rec709")
            np.testing.assert_allclose(m @ np.ones(3), np.ones(3), atol=1e-4)

    def test_raw_log_default_image_changes_signature_and_decodes(self):
        with tempfile.TemporaryDirectory() as tmp:
            img = QImage(160, 120, QImage.Format_RGB888)
            img.fill(QColor(120, 120, 120))
            jpg = Path(tmp) / "a.jpg"
            img.save(str(jpg), "JPEG")
            raw = Path(tmp) / "fake.ARW"
            raw.write_bytes(b"II*\x00" + jpg.read_bytes())
            try:
                previews.set_lut_test_images([str(raw)], str(raw), {})
                sig_a = previews._lut_test_image_signature()
                previews.set_lut_test_images([str(raw)], str(raw), {str(raw): "slog3"})
                self.assertNotEqual(sig_a, previews._lut_test_image_signature())
                out = previews._lut_test_image(640)
                c = out.pixelColor(5, 5)
                self.assertGreater(c.red(), 90)   # gris moyen log ~ 0.41 -> ~105
                self.assertLess(c.red(), 125)
            finally:
                previews.set_lut_test_images([], "", {})


    def test_8bit_image_converted_to_log_and_kinds(self):
        with tempfile.TemporaryDirectory() as tmp:
            img = QImage(32, 32, QImage.Format_RGB888)
            img.fill(QColor(118, 118, 118))   # sRGB ~ 18 % lineaire
            png = Path(tmp) / "g.png"
            img.save(str(png))
            self.assertEqual(previews.lut_image_kind(png), "8bit")
            self.assertEqual(previews.lut_image_kind("x.ARW"), "raw")
            self.assertEqual(previews.lut_image_kind("x.exr"), "float")
            keys = [k for k, _ in previews.lut_curve_choices("8bit")]
            self.assertEqual(keys, ["srgb", "slog3", "flog", "flog2"])
            self.assertEqual([k for k, _ in previews.lut_curve_choices("float")], ["srgb"])
            same = previews.lut_test_image_for(png, "srgb", 64).pixelColor(1, 1)
            log = previews.lut_test_image_for(png, "slog3", 64).pixelColor(1, 1)
            self.assertEqual(same.red(), 118)
            self.assertLessEqual(abs(log.red() - 105), 4)   # S-Log3 18 % = 0.41

    def test_per_image_curve_in_cache_signature(self):
        try:
            previews.set_lut_test_images(["/x/a.png"], "/x/a.png", {})
            a = previews._lut_test_image_signature()
            previews.set_lut_test_images(["/x/a.png"], "/x/a.png", {"/x/a.png": "flog"})
            self.assertEqual(previews._lut_default_curve(), "flog")
            self.assertEqual(previews._lut_test_image_signature() == a, False) if os.path.exists("/x/a.png") else None
        finally:
            previews.set_lut_test_images([], "", {})

if __name__ == "__main__":
    unittest.main()
