"""Module Photoshop : banc d'ANTICRÉNELAGE des pointes. Trois notions séparées et testées séparément :
dureté (rayon de pleine densité), douceur (profil smoothstep) et anticrénelage (moyenne du profil sur l'aire de chaque
pixel, jamais un élargissement du dégradé). Références : intégrale numérique / suréchantillonnage 48 × 48."""
import os as _os, sys as _sys  # jamais les vrais réglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import math
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fm_photoshop import brush as B, model as M

DIAMETERS = (1, 2, 3, 4, 6, 12, 24, 48, 100)
HARDNESS = (0.0, 0.25, 0.5, 0.8, 1.0)


def reference(cx, cy, d, h, rect, ss=48):
    """Moyenne du profil sur ss × ss points par pixel (référence lente)."""
    r = max(0.02, d / 2.0)
    r0 = r * h
    w = r - r0
    if w < 5e-3 * r:
        r0, w = r, 0.0
    return B._dab_super(cx, cy, r0, w, rect, ss)


def profile_mass(d, h):
    """∫ 2π ρ f(ρ) dρ du profil (aire pondérée par la densité), intégration fine."""
    r = d / 2.0
    rho = np.linspace(0, r, 20001)
    f = B._profile(rho, r * h, r - r * h if r * (1 - h) > 5e-3 * r else 0.0)
    return float(np.trapezoid(2 * math.pi * rho * f, rho))


class DabCoverageTest(unittest.TestCase):
    """Couverture pure : la douceur ajoutée (`TUNING.feather`) est une notion SÉPARÉE, testée dans test_photoshop_hybrid_model."""

    def setUp(self):
        B.TUNING.feather = 0.0

    def tearDown(self):
        B.TUNING.reset()

    def test_dab_matches_the_supersampled_reference(self):
        rng = np.random.default_rng(1)
        for d in DIAMETERS:
            for h in HARDNESS:
                worst = 0.0
                for _ in range(4):
                    cx, cy = 30 + rng.random(), 30 + rng.random()
                    rect = (int(cx - d / 2 - 2), int(cy - d / 2 - 2), int(cx + d / 2 + 3), int(cy + d / 2 + 3))
                    got = B.dab_alpha(cx, cy, d, h, rect)
                    worst = max(worst, float(np.abs(got - reference(cx, cy, d, h, rect, 48 if d < 60 else 16)).max()))
                self.assertLess(worst, 0.07 if (h == 1.0 and d < 12) else 0.03, f"d={d} dureté={h} écart max {worst:.3f}")

    def test_diameter_is_never_deformed_and_independent_of_subpixel_position(self):
        # La masse du tampon (somme des alphas) suit l'intégrale du profil, QUELLE QUE SOIT la position sous le pixel.
        rng = np.random.default_rng(2)
        for d in DIAMETERS:
            for h in HARDNESS:
                expected = profile_mass(d, h)
                masses = []
                for _ in range(6):
                    cx, cy = 30 + rng.random(), 30 + rng.random()
                    rect = (int(cx - d / 2 - 2), int(cy - d / 2 - 2), int(cx + d / 2 + 3), int(cy + d / 2 + 3))
                    masses.append(float(B.dab_alpha(cx, cy, d, h, rect).sum()))
                tol = 0.02 if d >= 6 else 0.03
                self.assertLess(abs(np.mean(masses) / expected - 1), tol, f"d={d} h={h} : {np.mean(masses):.3f} / {expected:.3f}")
                self.assertLess((max(masses) - min(masses)) / expected, 0.06 if d < 6 else 0.03, f"d={d} h={h} {masses}")

    def test_no_halo_outside_the_nominal_diameter_and_full_core(self):
        for d in DIAMETERS:
            for h in HARDNESS:
                cx, cy = 40.3, 40.7
                rect = (0, 0, 81, 81)
                a = B.dab_alpha(cx, cy, d, h, rect)
                ys, xs = np.mgrid[0:81, 0:81]
                dist = np.hypot(xs + 0.5 - cx, ys + 0.5 - cy)
                self.assertLess(float(a[dist > d / 2.0 + 1.0].max()), 1e-6, f"halo d={d} h={h}")      # rien au-delà du rayon + 1 px
                self.assertLessEqual(float(a.max()), 1.0 + 1e-6)
                if d >= 6 and h > 0:
                    core = a[dist < d / 2.0 * h - 1.0]
                    if core.size:
                        self.assertGreater(float(core.min()), 0.999, f"cœur d={d} h={h}")

    def test_radial_transition_is_monotone_and_gradual(self):
        for d in (12, 24, 48):
            for h in HARDNESS:
                a = B.dab_alpha(60.0, 60.5, d, h, (0, 60, 121, 61))[0]
                right = a[60:]
                self.assertTrue(np.all(np.diff(right) <= 1e-5), f"d={d} h={h} : le profil remonte")
                if h < 1.0:
                    self.assertLess(float(np.abs(np.diff(right)).max()), 0.6 / max(1.0, d * (1 - h) / 24 + 0.2), f"d={d} h={h}")

    def test_hard_tip_is_crisp_not_blurred(self):
        # Pointe dure : bord net (transition de ~1 px), pas un flou. Sécurité contre « dur = flou systématique ».
        a = B.dab_alpha(60.0, 60.5, 40.0, 1.0, (0, 60, 121, 61))[0]
        transition = int(((a > 0.02) & (a < 0.98)).sum())
        self.assertLessEqual(transition, 4)
        soft = B.dab_alpha(60.0, 60.5, 40.0, 0.0, (0, 60, 121, 61))[0]
        self.assertGreater(int(((soft > 0.02) & (soft < 0.98)).sum()), 30)                  # pointe douce : vrai dégradé


class StrokeAntiAliasTest(unittest.TestCase):
    def setUp(self):
        B.TUNING.feather = 0.0

    def tearDown(self):
        B.TUNING.reset()

    def stroke(self, path, brush, size=(120, 90), background=None):
        doc = M.new_document(size[0], size[1], background=background)
        layer = doc.layers[0]
        s = B.Stroke(layer, "pixels", brush, doc.rect())
        s.begin(*path[0])
        for i, p in enumerate(path[1:], 1):
            s.move(p[0], p[1], 1.0, t=i / 120.0)
        s.finish_to(*path[-1])
        s.end()
        return layer.pix.read(doc.rect()).astype(np.float32) / 255.0

    @staticmethod
    def segment(a, b, step=1.0):
        n = max(2, int(math.hypot(b[0] - a[0], b[1] - a[1]) / step))
        return [(a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n) for i in range(n + 1)]

    def test_thin_lines_carry_their_nominal_amount_of_paint(self):
        # « Pas délavé » : l'épaisseur perçue (somme des alphas d'une section) est le diamètre demandé, à toute position.
        for d in (1, 2, 3, 4, 6):
            for y in (40.0, 40.25, 40.5, 40.8):
                got = self.stroke(self.segment((10, y), (110, y)), B.Brush(size=float(d), hardness=1.0, spacing=0.08))
                column = got[:, 60, 3]
                self.assertAlmostEqual(float(column.sum()), float(d), delta=0.06 * d + 0.03, msg=f"d={d} y={y}")

    def test_thin_diagonal_has_no_holes_between_stamps(self):
        for d in (1, 2, 3):
            got = self.stroke(self.segment((10, 10), (100, 70)), B.Brush(size=float(d), hardness=1.0, spacing=0.08))
            alpha = got[..., 3]
            ys, xs = np.mgrid[0:90, 0:120]
            ux, uy = 90.0, 60.0
            n = math.hypot(ux, uy)
            along = ((xs + 0.5 - 10) * ux + (ys + 0.5 - 10) * uy) / n
            across = np.abs(((xs + 0.5 - 10) * uy - (ys + 0.5 - 10) * ux) / n)
            mass = np.array([alpha[(along >= s) & (along < s + 5) & (across < d + 2)].sum() for s in range(8, int(n) - 8, 5)])
            self.assertGreater(float(mass.min()), 0.92 * 5 * d, f"d={d} trou {mass.min():.2f} / {5 * d}")
            self.assertLess(float(mass.max()), 1.08 * 5 * d)

    def test_partial_pressure_and_opacity_keep_graded_edges(self):
        # Beaucoup de niveaux d'alpha sur le bord d'une diagonale, même à 30 % d'opacité.
        for kw in ({"opacity": 0.3}, {"opacity": 1.0}, {"opacity": 0.3, "flow": 0.5}):
            got = self.stroke(self.segment((10, 10), (100, 70)), B.Brush(size=12, hardness=1.0, spacing=0.08, **kw))
            levels = np.unique(np.round(got[..., 3][got[..., 3] > 0.01] * 255))
            self.assertGreater(len(levels), 8, f"{kw} : {len(levels)} niveaux")

    def test_each_hardness_on_white_and_on_transparent(self):
        for bg in (None, (255, 255, 255, 255)):
            for h in HARDNESS:
                got = self.stroke(self.segment((10, 45.3), (110, 45.3)), B.Brush(size=14, hardness=h, spacing=0.08), background=bg)
                column = got[:, 60, 3] if bg is None else 1.0 - got[:, 60, 0]
                self.assertAlmostEqual(float(column.max()), 1.0, delta=0.01, msg=f"h={h} bg={bg}")
                mass = float(column.sum())
                expected = 7.0 * 2 * (h + (1 - h) / 2) if h < 1.0 else 14.0                    # 2 · (R·h + largeur/2) si la douceur est lisse
                if h >= 0.6:
                    self.assertAlmostEqual(mass, expected, delta=0.35, msg=f"h={h} bg={bg}")
                elif h > 0:                                                              # pointe douce : union « sur » (plus de matière au cœur)
                    self.assertTrue(expected - 0.35 <= mass <= 1.2 * expected, f"h={h} bg={bg} masse {mass:.2f} / {expected:.2f}")
                self.assertTrue(np.all(np.abs(np.diff(column[: 46])) < 0.9))

    def test_variable_diameter_stroke_is_smooth(self):
        doc = M.new_document(140, 60, background=None)
        layer = doc.layers[0]
        brush = B.Brush(size=24, hardness=1.0, spacing=0.08, pressure_size=True)
        s = B.Stroke(layer, "pixels", brush, doc.rect())
        path = self.segment((10, 30), (130, 30))
        s.begin(*path[0], 0.05)
        for i, p in enumerate(path[1:], 1):
            s.move(p[0], p[1], 0.05 + 0.95 * i / len(path), t=i / 120.0)
        s.finish_to(*path[-1])
        s.end()
        alpha = layer.pix.read(doc.rect())[..., 3].astype(np.float32) / 255.0
        widths = alpha.sum(axis=0)[15:125]
        self.assertTrue(np.all(np.diff(widths) > -0.35), "le diamètre ne doit pas osciller")
        self.assertLess(float(np.abs(np.diff(widths, 2)).max()), 0.6, "pas de marche dans l'épaisseur")


if __name__ == "__main__":
    unittest.main()
