"""Module Photoshop : sélections (formes, baguette, plage de couleurs, combinaisons, inversion, adoucir, agrandir /
contracter) et filtres de base (flou gaussien, netteté, bruit) — valeurs numériques de référence."""
import os as _os, sys as _sys  # jamais les vrais réglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fm_photoshop import filters, selection as S
from fm_photoshop.planes import Plane

DOC = (0, 0, 40, 30)


def cov(sel, rect=DOC):
    return sel.coverage(rect)


class ShapeTest(unittest.TestCase):
    def test_rectangle_clipped_to_document(self):
        sel = S.rectangle(DOC, (10, 5, 100, 20))
        c = cov(sel)
        self.assertEqual(float(c[10, 20]), 1.0)
        self.assertEqual(float(c[4, 20]), 0.0)
        self.assertEqual(sel.bounds(), (10, 5, 40, 20))

    def test_ellipse_area_and_soft_edges(self):
        sel = S.ellipse(DOC, (5.0, 5.0, 35.0, 25.0))
        c = cov(sel)
        area = float(c.sum())
        self.assertAlmostEqual(area, np.pi * 15 * 10, delta=3.0)                       # π·a·b
        self.assertEqual(float(c[15, 20]), 1.0)
        self.assertEqual(float(c[0, 0]), 0.0)
        self.assertTrue(((c > 0.05) & (c < 0.95)).any())                                # bords adoucis, pas en escalier

    def test_polygon_triangle_area(self):
        sel = S.polygon(DOC, [(2, 2), (22, 2), (2, 22)])
        self.assertAlmostEqual(float(cov(sel).sum()), 200.0, delta=6.0)               # aire = 20·20/2

    def test_empty_and_degenerate(self):
        self.assertTrue(S.polygon(DOC, [(1, 1), (2, 2)]).is_empty())
        self.assertTrue(S.rectangle(DOC, (100, 100, 120, 120)).is_empty())
        self.assertIsNone(S.Selection().bounds())


class CombineTest(unittest.TestCase):
    def setUp(self):
        self.a = S.rectangle(DOC, (0, 0, 20, 30))
        self.b = S.rectangle(DOC, (10, 0, 40, 30))

    def test_modes(self):
        add = cov(S.combine(DOC, self.a, self.b, "add"))
        self.assertEqual(float(add.sum()), 40 * 30)
        sub = cov(S.combine(DOC, self.a, self.b, "subtract"))
        self.assertEqual(float(sub.sum()), 10 * 30)
        inter = cov(S.combine(DOC, self.a, self.b, "intersect"))
        self.assertEqual(float(inter.sum()), 10 * 30)
        self.assertEqual(S.combine(DOC, self.a, self.b, "replace"), self.b)

    def test_invert_and_all(self):
        inv = cov(S.invert(DOC, self.a))
        self.assertEqual(float(inv.sum()), 20 * 30)
        self.assertEqual(float(inv[:, :20].sum()), 0.0)
        self.assertEqual(float(cov(S.select_all(DOC)).sum()), 40 * 30)
        self.assertTrue(S.invert(DOC, S.select_all(DOC)).is_empty())

    def test_partial_coverage_survives_combination(self):
        half = S.Selection.from_array(DOC, np.full((30, 40), 128, np.uint8))
        out = cov(S.combine(DOC, half, S.rectangle(DOC, (0, 0, 40, 30)), "intersect"))
        self.assertAlmostEqual(float(out[3, 3]), 128 / 255, places=2)

    def test_feather_grow_shrink(self):
        sel = S.rectangle(DOC, (10, 8, 30, 22))
        soft = cov(S.feather(DOC, sel, 6))
        self.assertAlmostEqual(float(soft.sum()), 20 * 14, delta=8)                    # le flou conserve l'aire
        self.assertTrue(((soft > 0.05) & (soft < 0.95)).any())
        grown = S.resize(DOC, sel, 2)
        self.assertEqual(grown.bounds(), (8, 6, 32, 24))
        shrunk = S.resize(DOC, sel, -2)
        self.assertEqual(shrunk.bounds(), (12, 10, 28, 20))


class WandTest(unittest.TestCase):
    def image(self):
        img = np.zeros((30, 40, 4), np.uint8)
        img[...] = (255, 255, 255, 255)
        img[5:15, 5:15] = (255, 0, 0, 255)           # carré rouge A
        img[5:15, 25:35] = (255, 0, 0, 255)          # carré rouge B (non contigu)
        img[20:25, 5:15] = (250, 10, 10, 255)        # presque rouge
        return img

    def test_contiguous_vs_global(self):
        img = self.image()
        one = S.wand(DOC, img, 8, 8, tolerance=5, contiguous=True, anti_alias=False)
        both = S.wand(DOC, img, 8, 8, tolerance=5, contiguous=False, anti_alias=False)
        self.assertEqual(float(cov(one).sum()), 100.0)
        self.assertEqual(float(cov(both).sum()), 200.0)

    def test_tolerance(self):
        img = self.image()
        strict = S.wand(DOC, img, 8, 8, tolerance=2, contiguous=False, anti_alias=False)
        loose = S.wand(DOC, img, 8, 8, tolerance=15, contiguous=False, anti_alias=False)
        self.assertEqual(float(cov(strict).sum()), 200.0)
        self.assertEqual(float(cov(loose).sum()), 200.0 + 50.0)

    def test_outside_and_color_range(self):
        img = self.image()
        self.assertTrue(S.wand(DOC, img, 500, 500).is_empty())
        rng = S.color_range(DOC, img, (255, 0, 0), tolerance=3)
        self.assertEqual(float(cov(rng).sum()), 200.0)

    def test_large_image_is_fast(self):
        import time
        big = np.zeros((2000, 3000, 4), np.uint8)
        big[...] = (10, 10, 10, 255)
        big[::2, ::7] = (200, 0, 0, 255)             # beaucoup de petits segments
        t = time.perf_counter()
        sel = S.wand((0, 0, 3000, 2000), big, 1, 1, tolerance=3, anti_alias=False)
        self.assertLess(time.perf_counter() - t, 6.0)
        self.assertFalse(sel.is_empty())


class FilterTest(unittest.TestCase):
    def test_gaussian_preserves_mean_and_flat(self):
        flat = np.full((20, 20, 4), 0.4, np.float32)
        self.assertTrue(np.allclose(filters.gaussian_blur(flat, 3.0), 0.4, atol=1e-5))
        rng = np.random.default_rng(0).random((64, 64, 1), dtype=np.float32)
        blurred = filters.gaussian_blur(rng, 2.0)
        self.assertAlmostEqual(float(blurred.mean()), float(rng.mean()), delta=0.02)
        self.assertLess(float(blurred.std()), float(rng.std()) * 0.5)

    def test_gaussian_impulse_is_symmetric_gaussian_like(self):
        impulse = np.zeros((41, 41, 1), np.float32)
        impulse[20, 20] = 1.0
        out = filters.gaussian_blur(impulse, 3.0)[..., 0]
        self.assertAlmostEqual(float(out.sum()), 1.0, places=3)
        self.assertTrue(np.allclose(out, out.T, atol=1e-6))
        self.assertTrue(np.allclose(out, out[::-1, ::-1], atol=1e-6))
        std = float(np.sqrt((out * (np.arange(41)[None, :] - 20) ** 2).sum()))
        self.assertAlmostEqual(std, 3.0, delta=0.35)                                 # écart-type voulu

    def test_blur_premultiplied_has_no_dark_halo(self):
        premult = np.zeros((9, 9, 4), np.float32)
        premult[:, :4] = (1.0, 0.0, 0.0, 1.0)                                         # rouge opaque à gauche
        out = filters.gaussian_blur(premult, 1.5)
        alpha = out[..., 3:4]
        straight = np.where(alpha > 1e-4, out[..., :3] / np.maximum(alpha, 1e-4), 0)
        edge = straight[4, 3:6]
        self.assertTrue(np.allclose(edge[..., 0], 1.0, atol=1e-3))                    # reste rouge pur, jamais plus sombre

    def test_unsharp_and_noise(self):
        step = np.zeros((10, 20, 4), np.float32)
        step[..., 3] = 1.0
        step[:, 10:, :3] = 0.5
        sharp = filters.unsharp(step, 1.0, 1.5)
        self.assertLessEqual(float(sharp[..., :3].max()), 1.0)
        self.assertGreater(float(sharp[5, 10, 0]), 0.5)                                # surcroît au bord clair
        flat = np.full((16, 16, 4), 0.5, np.float32)
        flat[..., 3] = 1.0
        a, b = filters.add_noise(flat, 0.1, seed=3), filters.add_noise(flat, 0.1, seed=3)
        self.assertTrue(np.array_equal(a, b))                                          # reproductible
        self.assertTrue(np.array_equal(a[..., 3], flat[..., 3]))                       # alpha inchangé
        self.assertAlmostEqual(float((a[..., 0] - 0.5).std()), 0.1, delta=0.03)


if __name__ == "__main__":
    unittest.main()
