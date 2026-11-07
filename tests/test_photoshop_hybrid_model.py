"""Module Photoshop : MODÈLE HYBRIDE de dépôt (forme / passage / densité séparés) et douceur du bord. Ces tests mesurent
la QUALITÉ du rendu (plateau homogène, transition de bord régulière, absence de double atténuation = « effet de tube »,
progression de l'accumulation, stabilité vis-à-vis de l'espacement), pas seulement les propriétés du modèle."""
import os as _os, sys as _sys  # jamais les vrais réglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import math
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fm_photoshop import brush as B, compose as C, model as M

D, Y = 20.0, 40.0                     # diamètre ; ordonnée du centre (frontière de pixel : section symétrique)


def stroke(brush, xs, ys=None, pressures=None, background=None, size=(140, 80)):
    doc = M.new_document(size[0], size[1], background=background)
    layer = doc.layers[0]
    ys = ys or [Y] * len(xs)
    pr = pressures or [1.0] * len(xs)
    s = B.Stroke(layer, "pixels", brush, doc.rect())
    s.begin(xs[0], ys[0], pr[0])
    for i in range(1, len(xs)):
        s.move(xs[i], ys[i], pr[i], t=i / 120.0)
    s.finish_to(xs[-1], ys[-1], 0.0)
    s.end()
    return doc, layer


def passes(n, x0=10.0, x1=130.0):
    xs = []
    for k in range(n):
        seg = [x0 + (x1 - x0) * i / 120.0 for i in range(121)]
        xs += seg if k % 2 == 0 else seg[::-1]
    return xs


def section(brush, n=1, x=70, **kw):
    """Alpha le long d'une colonne perpendiculaire au trait, côté y > Y (distance 0,5 ; 1,5 ; ...)."""
    _doc, layer = stroke(brush, passes(n), **kw)
    return layer.pix.read((x, int(Y), x + 1, int(Y) + 20))[:, 0, 3].astype(np.float32) / 255.0


def brush(**kw):
    kw.setdefault("size", D)
    kw.setdefault("hardness", 0.8)
    kw.setdefault("spacing", 0.08)
    kw.setdefault("color", (0, 0, 0))
    return B.Brush(**kw)


class FlatPlateauTest(unittest.TestCase):
    """Premier passage : plateau homogène, aucune bande délavée sur les côtés (plus d'effet de tube)."""

    def test_plateau_is_flat_for_every_opacity_flow_and_mode(self):
        for mode in ("wash", "buildup"):
            for opacity, flow in ((0.1, 1.0), (0.3, 1.0), (0.6, 1.0), (1.0, 1.0), (0.6, 0.5), (0.6, 0.3)):
                col = section(brush(opacity=opacity, flow=flow, paint_mode=mode))
                plateau = col[:6]                                                     # jusqu'à 6 px du centre (rayon de plein 8)
                self.assertLess(float(plateau.max() - plateau.min()), 0.006, f"{mode} opacité {opacity} débit {flow}")
                self.assertAlmostEqual(float(plateau.mean()), opacity * flow, delta=0.012, msg=f"{mode} {opacity} {flow}")

    def test_no_double_attenuation_the_edge_is_opacity_times_shape(self):
        # alpha(x) à 30 % = 0,3 × alpha(x) à 100 % : la douceur du bord vient de la SEULE forme, pas de la dose parcourue.
        for mode in ("wash", "buildup"):
            full = section(brush(opacity=1.0, paint_mode=mode))
            for opacity in (0.1, 0.3, 0.6):
                part = section(brush(opacity=opacity, paint_mode=mode))
                self.assertLess(float(np.abs(part - opacity * full).max()), 0.012, f"{mode} {opacity}")
            for flow in (0.5, 0.3):
                part = section(brush(opacity=0.6, flow=flow, paint_mode=mode))
                self.assertLess(float(np.abs(part - 0.6 * flow * full).max()), 0.012, f"{mode} débit {flow}")

    def test_no_wide_washed_out_band_on_the_sides(self):
        col = section(brush(opacity=0.3, paint_mode="buildup", hardness=0.8))
        band = int(((col > 0.02) & (col < 0.3 * 0.9)).sum())                          # pixels de transition (ni vides ni au plateau)
        self.assertLessEqual(band, 3)                                                  # transition = celle de la forme (2,2 px de douceur)

    def test_constant_pressure_keeps_the_opacity_along_the_whole_stroke(self):
        for mode in ("wash", "buildup"):
            doc, layer = stroke(brush(pressure_opacity=True, paint_mode=mode, hardness=1.0), passes(1), pressures=[0.5] * 121)
            row = layer.pix.read((25, int(Y), 118, int(Y) + 1))[0, :, 3].astype(np.float32) / 255.0
            self.assertLess(float(row.max() - row.min()), 0.006, mode)
            self.assertAlmostEqual(float(row.mean()), 0.5, delta=0.006, msg=mode)

    def test_apparent_diameter_is_regular_along_the_stroke(self):
        doc, layer = stroke(brush(hardness=0.9, opacity=0.5), passes(1))
        widths = [layer.pix.read((x, int(Y) - 14, x + 1, int(Y) + 14))[:, 0, 3].astype(np.float32).sum() / 255.0 / 0.5
                  for x in range(25, 118)]
        self.assertLess(float(np.ptp(widths)), 0.06, "largeur apparente irrégulière le long du trait")


class AccumulationProgressionTest(unittest.TestCase):
    def test_returns_add_paint_progressively(self):
        for n in range(1, 7):
            col = section(brush(opacity=0.3, paint_mode="buildup"), n=n)
            self.assertAlmostEqual(float(col[:6].mean()), 1 - 0.7 ** n, delta=0.02, msg=f"{n} passages")
            self.assertLess(float(col[:6].max() - col[:6].min()), 0.012, f"{n} passages : plateau")

    def test_ends_of_a_back_and_forth_stroke_accumulate_like_the_middle(self):
        # demi-tour : sans détection, le bout du trait resterait UN passage (disque plus clair)
        doc, layer = stroke(brush(opacity=0.3, paint_mode="buildup", hardness=1.0, size=14), passes(2))
        row = layer.pix.read((8, int(Y), 134, int(Y) + 1))[0, :, 3].astype(np.float32) / 255.0
        middle = float(row[40:90].mean())
        self.assertAlmostEqual(middle, 0.51, delta=0.02)
        self.assertGreater(float(row[10 + 8 - 8 + 4]), 0.40)                                # près du bout gauche (retour)
        self.assertGreater(float(row[-14]), 0.40)                                          # près du bout droit (demi-tour)

    def test_denser_resampling_does_not_count_as_more_passes(self):
        results = []
        for dense in (0.03, 0.08, 0.2):
            B.TUNING.continuous_spacing = dense
            try:
                results.append(section(brush(opacity=0.3, paint_mode="buildup", spacing=0.3), n=2))
            finally:
                B.TUNING.reset()
        for other in results[1:]:
            self.assertLess(float(np.abs(other - results[0]).max()), 0.02)
        single = []
        for dense in (0.03, 0.2):
            B.TUNING.continuous_spacing = dense
            try:
                single.append(section(brush(opacity=0.3, paint_mode="wash", flow=0.5, spacing=0.3)))
            finally:
                B.TUNING.reset()
        self.assertLess(float(np.abs(single[0] - single[1]).max()), 0.015)

    def test_tremor_of_a_slow_hand_is_not_a_return(self):
        xs = [20.0 + i * 0.5 + (0.9 if i % 2 else 0.0) for i in range(200)]                  # avance lente avec recul de 0,4 px
        doc, layer = stroke(brush(opacity=0.3, paint_mode="buildup", hardness=1.0, size=14), xs)
        row = layer.pix.read((35, int(Y), 100, int(Y) + 1))[0, :, 3].astype(np.float32) / 255.0
        self.assertAlmostEqual(float(row.mean()), 0.30, delta=0.012)

    def test_weaker_input_never_erases_stronger_paint(self):
        for mode in ("wash", "buildup"):
            strong = brush(opacity=0.8, paint_mode=mode)
            weak = brush(opacity=0.2, paint_mode=mode)
            doc, layer = stroke(strong, passes(1))
            before = layer.pix.read(doc.rect())[..., 3].astype(np.int32)
            s = B.Stroke(layer, "pixels", weak, doc.rect())
            xs = passes(1)
            s.begin(xs[0], Y, 1.0)
            for i, x in enumerate(xs[1:], 1):
                s.move(x, Y, 1.0, t=i / 120.0)
            s.finish_to(xs[-1], Y, 1.0)
            s.end()
            after = layer.pix.read(doc.rect())[..., 3].astype(np.int32)
            self.assertTrue((after >= before - 1).all(), mode)


class SpacingStabilityTest(unittest.TestCase):
    def test_section_is_stable_across_stamp_spacings(self):
        for mode in ("wash", "buildup"):
            profiles = []
            for dense in (0.03, 0.08, 0.16):
                B.TUNING.continuous_spacing = dense
                try:
                    profiles.append(section(brush(opacity=0.5, paint_mode=mode, spacing=0.3)))
                finally:
                    B.TUNING.reset()
            self.assertLess(float(max(np.abs(p - profiles[1]).max() for p in profiles)), 0.02, mode)


class LayerAndColorTest(unittest.TestCase):
    def test_transparent_layer_and_opaque_background_agree(self):
        for mode in ("wash", "buildup"):
            _d1, transparent = stroke(brush(opacity=0.4, paint_mode=mode), passes(2))
            _d2, opaque = stroke(brush(opacity=0.4, paint_mode=mode), passes(2), background=(255, 255, 255, 255))
            alpha = transparent.pix.read((60, 20, 61, 60))[:, 0, 3].astype(np.float32)
            grey = 255.0 - opaque.pix.read((60, 20, 61, 60))[:, 0, 0].astype(np.float32)
            self.assertLess(float(np.abs(alpha - grey).max()), 1.5, mode)

    def test_premultiplied_colours_composite_correctly(self):
        colour = (200, 40, 90)
        for mode in ("wash", "buildup"):
            doc, layer = stroke(brush(opacity=0.5, paint_mode=mode, color=colour), passes(2))
            pixels = layer.pix.read(doc.rect())
            seen = pixels[pixels[..., 3] > 8]
            self.assertTrue((np.abs(seen[:, :3].astype(int) - np.array(colour)).max() <= 2), "couleur DROITE altérée par l'alpha")
            flat = C.flatten_u8(doc)                                                  # sur le fond du document (transparent) : rien d'autre
            self.assertTrue(np.array_equal(flat[..., 3], pixels[..., 3]))
            a = pixels[..., 3:4].astype(np.float32) / 255.0
            white = 255.0 * (1 - a) + pixels[..., :3].astype(np.float32) * a
            expected = 255.0 * (1 - a) + np.array(colour, np.float32) * a
            self.assertLess(float(np.abs(white - expected)[pixels[..., 3] > 0].max()), 2.5, mode)


class SoftnessTest(unittest.TestCase):
    """Douceur du bord (`TUNING.feather`) : indépendante de l'anticrénelage, jamais sur les pointes dures ni minuscules."""

    def tearDown(self):
        B.TUNING.reset()

    def alpha(self, d, h, feather, rect=(0, 0, 61, 61)):
        B.TUNING.feather = feather
        return B.dab_alpha(30.37, 30.61, d, h, rect)

    def test_hard_tip_stays_crisp_whatever_the_feather(self):
        for d in (3, 12, 48):
            self.assertTrue(np.array_equal(self.alpha(d, 1.0, 0.0), self.alpha(d, 1.0, 3.0)), f"d={d}")

    def test_tiny_tips_are_not_softened(self):
        for d in (1, 2, 3):
            self.assertTrue(np.array_equal(self.alpha(d, 0.8, 0.0), self.alpha(d, 0.8, 3.0)), f"d={d}")

    def test_feather_widens_the_edge_but_keeps_the_apparent_diameter_and_the_centre(self):
        def radial(d, h, feather):
            rng = np.random.default_rng(0)
            rs, vs = [], []
            for _ in range(24):
                cx, cy = 30 + rng.random(), 30 + rng.random()
                B.TUNING.feather = feather
                a = B.dab_alpha(cx, cy, d, h, (0, 0, 61, 61))
                ys, xs = np.mgrid[0:61, 0:61]
                rs.append(np.hypot(xs + 0.5 - cx, ys + 0.5 - cy).ravel())
                vs.append(a.ravel())
            r, v = np.concatenate(rs), np.concatenate(vs)
            bins = np.arange(0, d / 2 + 4, 0.1)
            idx = np.digitize(r, bins)
            prof = np.array([v[idx == i].mean() if (idx == i).any() else np.nan for i in range(1, len(bins))])
            return bins[:-1] + 0.05, prof

        def at(r, p, level):
            ok = ~np.isnan(p)
            r, p = r[ok], p[ok]
            return float(r[np.where(p <= level)[0][0]])

        for d in (12, 24, 48):
            widths = []
            for feather in (0.0, 1.0, 2.0, 3.0):
                r, p = radial(d, 0.8, feather)
                widths.append(at(r, p, 0.1) - at(r, p, 0.9))
                self.assertAlmostEqual(at(r, p, 0.5), at(*radial(d, 0.8, 0.0), 0.5), delta=0.15, msg=f"d={d} diamètre à 50 %")
                self.assertGreater(float(np.nanmin(p[:8])), 0.999, f"d={d} densité du centre")
            self.assertGreater(widths[-1], widths[0] + 0.3, f"d={d} : la douceur doit élargir la transition {widths}")
            self.assertTrue(all(b >= a - 0.12 for a, b in zip(widths, widths[1:])), widths)

    def test_hard_tip_extra_softness_is_optional_independent_and_keeps_the_diameter(self):
        # `hard_feather` (0 par défaut) : adoucissement facultatif du bord d'une pointe DURE, indépendant de la dureté.
        rect = (0, 0, 61, 61)
        B.TUNING.hard_feather = 0.0
        crisp = B.dab_alpha(30.37, 30.61, 24, 1.0, rect)
        B.TUNING.hard_feather = 0.8
        soft = B.dab_alpha(30.37, 30.61, 24, 1.0, rect)
        transition = lambda a: int(((a > 0.02) & (a < 0.98)).sum())
        self.assertGreater(transition(soft), transition(crisp))
        self.assertAlmostEqual(float(soft.sum()), float(crisp.sum()), delta=0.01 * float(crisp.sum()))      # même diamètre apparent
        self.assertGreater(float(soft[30, 30]), 0.999)                                                       # cœur net
        B.TUNING.hard_feather = 0.8
        tiny = B.dab_alpha(10.4, 10.4, 1.0, 1.0, (0, 0, 21, 21))
        B.TUNING.hard_feather = 0.0
        ref = B.dab_alpha(10.4, 10.4, 1.0, 1.0, (0, 0, 21, 21))
        self.assertAlmostEqual(float(tiny.sum()), float(ref.sum()), delta=0.03)                              # une pointe de 1 px ne disparaît pas

    def test_feather_never_extends_far_beyond_the_nominal_radius(self):
        for d in (6, 12, 48):
            for h in (0.0, 0.5, 0.9, 0.99):
                a = self.alpha(d, h, 3.0)
                ys, xs = np.mgrid[0:61, 0:61]
                dist = np.hypot(xs + 0.5 - 30.37, ys + 0.5 - 30.61)
                self.assertLess(float(a[dist > d / 2.0 + 2.0].max()), 1e-6, f"d={d} h={h}")      # la boîte du tampon (R + 1 px) suffit

    def test_soft_stroke_profile_is_regular_and_monotone(self):
        steps = []
        for feather in (0.0, 1.5, 3.0):
            B.TUNING.feather = feather
            col = section(brush(hardness=0.8, size=24))
            self.assertTrue(np.all(np.diff(col[8:]) <= 1e-4), f"feather {feather}")           # décroît sans remonter
            steps.append(float(np.abs(np.diff(col)).max()))
        self.assertLess(steps[0], 0.6)                                                       # pas de marche, même sans douceur ajoutée
        self.assertTrue(steps[0] > steps[1] > steps[2], steps)                               # plus de douceur = pente plus douce


if __name__ == "__main__":
    unittest.main()
