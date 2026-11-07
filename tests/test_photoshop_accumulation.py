"""Module Photoshop : ACCUMULATION de la peinture (opacité / débit / pression), deux comportements :
  - « wash » (plafond) : l'opacité est une limite, repasser dans le trait n'ajoute rien au-delà ;
  - « buildup » (accumulation) : chaque passage s'ajoute, alpha = ancien + apport · (1 − ancien), sans plafond.
Propriété de fond vérifiée partout : un pinceau noir normal sur fond blanc ne rend JAMAIS plus clair un pixel déjà peint
(dans un trait continu comme entre deux traits). Exceptions explicites : la gomme et les modes de retouche."""
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
from fm_photoshop.history import History

WHITE = (255, 255, 255, 255)


def line(x0, y0, x1, y1, n=None):
    n = n or max(2, int(math.hypot(x1 - x0, y1 - y0)))
    return [(x0 + (x1 - x0) * i / n, y0 + (y1 - y0) * i / n) for i in range(n + 1)]


def run(layer, doc, brush, path, pressures=None, check_monotone=False):
    """Un trait sur `layer` ; `check_monotone` : le pixel ne s'éclaircit jamais PENDANT le trait (relu à chaque point)."""
    pr = pressures or [1.0] * len(path)
    stroke = B.Stroke(layer, "pixels", brush, doc.rect())
    last = layer.pix.read(doc.rect()).astype(np.int32)

    def check():
        nonlocal last
        now = layer.pix.read(doc.rect()).astype(np.int32)
        assert (now[..., 0] <= last[..., 0] + 1).all(), "un pixel s'est éclairci pendant le trait"
        last = now

    stroke.begin(path[0][0], path[0][1], pr[0])
    for i in range(1, len(path)):
        stroke.move(path[i][0], path[i][1], pr[i], t=i / 120.0)
        if check_monotone and i % 4 == 0:
            check()
    stroke.finish_to(path[-1][0], path[-1][1], 0.0)
    if check_monotone:
        check()
    return stroke.end()


def blank(w=130, h=80, background=None):
    doc = M.new_document(w, h, background=background)
    return doc, doc.layers[0]


def alpha_at(layer, x, y):
    return float(layer.pix.read((x, y, x + 1, y + 1))[0, 0, 3]) / 255.0


def grey_at(layer, x, y):
    return float(layer.pix.read((x, y, x + 1, y + 1))[0, 0, 0])


def passes(a, b, n):
    """Trait qui repasse `n` fois entre deux points (aller-retour dans le MÊME trait)."""
    path = []
    for i in range(n):
        seg = line(*(a + b if i % 2 == 0 else b + a))
        path += seg if i == 0 else seg[1:]
    return path


class OpacityBuildUpTest(unittest.TestCase):
    """Mode accumulation : deux apports indépendants de 30 % font 1 − 0,7² = 51 %."""

    def brush(self, **kw):
        return B.Brush(size=10, hardness=1.0, spacing=0.1, color=(0, 0, 0), paint_mode="buildup", opacity=0.3, **kw)

    def test_one_pass_deposits_exactly_the_requested_dose(self):
        doc, layer = blank()
        run(layer, doc, self.brush(), line(10, 40, 110, 40))
        self.assertAlmostEqual(alpha_at(layer, 60, 40), 0.30, delta=0.01)

    def test_independent_inputs_accumulate_as_alpha_over(self):
        doc, layer = blank()
        run(layer, doc, self.brush(), line(10, 40, 110, 40))
        run(layer, doc, self.brush(), line(60, 10, 60, 70))                     # DEUX traits qui se croisent
        self.assertAlmostEqual(alpha_at(layer, 60, 40), 1 - 0.7 ** 2, delta=0.015)       # 51 %
        self.assertAlmostEqual(alpha_at(layer, 30, 40), 0.30, delta=0.01)                # le reste n'a pas bougé
        self.assertAlmostEqual(alpha_at(layer, 60, 15), 0.30, delta=0.01)

    def test_one_self_crossing_stroke_accumulates_too(self):
        doc, layer = blank()
        path = line(10, 40, 110, 40) + line(110, 40, 60, 70)[1:] + line(60, 70, 60, 10)[1:]
        run(layer, doc, self.brush(), path)
        self.assertAlmostEqual(alpha_at(layer, 60, 40), 1 - 0.7 ** 2, delta=0.02)        # croisement dans le même trait

    def test_ten_passes(self):
        doc, layer = blank()
        run(layer, doc, self.brush(), passes((15, 40), (105, 40), 10))
        self.assertAlmostEqual(alpha_at(layer, 60, 40), 1 - 0.7 ** 10, delta=0.02)

    def test_density_does_not_depend_on_the_stamp_density(self):
        values = []
        for dense in (0.03, 0.08, 0.16):
            B.TUNING.continuous_spacing = dense
            try:
                doc, layer = blank()
                run(layer, doc, B.Brush(size=10, hardness=1.0, spacing=0.3, color=(0, 0, 0), paint_mode="buildup",
                                        opacity=0.3), line(10, 40, 110, 40))
                values.append(alpha_at(layer, 60, 40))
            finally:
                B.TUNING.reset()
        self.assertLess(max(values) - min(values), 0.03, values)                          # 3 % → 16 % d'espacement : même peinture
        self.assertAlmostEqual(values[1], 0.30, delta=0.02)

    def test_stroke_with_fewer_dabs_is_not_lighter_nor_heavier(self):
        a = self.brush()
        a.spacing = 0.05
        b = self.brush()
        b.spacing = 0.1
        out = []
        for brush in (a, b):
            doc, layer = blank()
            run(layer, doc, brush, passes((15, 40), (105, 40), 3))
            out.append(alpha_at(layer, 60, 40))
        self.assertAlmostEqual(out[0], out[1], delta=0.02)


class PressureOpacityTest(unittest.TestCase):
    """La pression pilote l'opacité : sa baisse ne retire jamais la peinture déjà déposée."""

    def brush(self, **kw):
        return B.Brush(size=10, hardness=1.0, spacing=0.1, color=(0, 0, 0), pressure_opacity=True, paint_mode="buildup", **kw)

    def test_pressure_and_deposit_mode_are_independent(self):
        # (avant : la pression sur l'opacité activait silencieusement l'accumulation)
        self.assertEqual(B.Brush(size=10, pressure_opacity=True).paint_kind(), "wash")
        self.assertEqual(B.Brush(size=10).paint_kind(), "wash")
        self.assertEqual(self.brush().paint_kind(), "buildup")
        self.assertEqual(B.Brush(size=10, paint_mode="buildup", pressure_opacity=False).paint_kind(), "buildup")

    def test_constant_pressure_30_percent(self):
        doc, layer = blank()
        path = line(10, 40, 110, 40) + line(110, 40, 60, 70)[1:] + line(60, 70, 60, 10)[1:]
        run(layer, doc, self.brush(), path, [0.3] * len(path))
        self.assertAlmostEqual(alpha_at(layer, 30, 40), 0.30, delta=0.01)
        self.assertAlmostEqual(alpha_at(layer, 60, 40), 0.51, delta=0.02)                # avant : 0,30 (le croisement n'ajoutait rien)

    def test_pressure_dip_at_the_crossing_never_erases(self):
        doc, layer = blank()
        first = line(10, 40, 110, 40)
        second = line(110, 40, 60, 70)[1:] + line(60, 70, 60, 10)[1:]
        path = first + second
        pr = [0.8] * len(first)
        for i, (x, y) in enumerate(second):                                             # 80 % → 20 % → 80 % autour du croisement
            dist = abs(y - 40)
            pr.append(0.2 + 0.6 * min(1.0, dist / 12.0) if x == 60 else 0.8)
        run(layer, doc, self.brush(), path, pr, check_monotone=True)
        before = 0.8                                                                     # peinture déjà déposée par la 1ère portion
        self.assertGreaterEqual(alpha_at(layer, 60, 40), before - 0.005)                 # jamais plus clair
        self.assertGreater(alpha_at(layer, 60, 40), before + 0.02)                       # ... et le passage faible s'AJOUTE

    def test_weak_over_strong_and_strong_over_weak(self):
        for first_p, second_p in ((0.8, 0.2), (0.2, 0.8)):
            doc, layer = blank()
            horizontal = line(10, 40, 110, 40)
            run(layer, doc, self.brush(), horizontal, [first_p] * len(horizontal))
            seg = line(60, 10, 60, 70)
            run(layer, doc, self.brush(), seg, [second_p] * len(seg))
            expected = 1 - (1 - first_p) * (1 - second_p)
            self.assertAlmostEqual(alpha_at(layer, 60, 40), expected, delta=0.02, msg=f"{first_p} puis {second_p}")
            self.assertGreaterEqual(alpha_at(layer, 60, 40), max(first_p, second_p) - 0.005)

    def test_rising_and_falling_pressure_are_monotone(self):
        doc, layer = blank()
        path = line(10, 40, 110, 40)
        up = [0.1 + 0.8 * i / len(path) for i in range(len(path))]
        run(layer, doc, self.brush(), path, up, check_monotone=True)
        row = [alpha_at(layer, x, 40) for x in range(20, 100, 5)]
        self.assertTrue(all(b >= a - 0.01 for a, b in zip(row, row[1:])), row)           # le trait s'assombrit avec la pression
        doc, layer = blank()
        run(layer, doc, self.brush(), path, up[::-1], check_monotone=True)
        row = [alpha_at(layer, x, 40) for x in range(20, 100, 5)]
        self.assertTrue(all(b <= a + 0.01 for a, b in zip(row, row[1:])), row)


class WashTest(unittest.TestCase):
    """Mode plafond : l'opacité est une limite que plusieurs passages ne dépassent jamais."""

    def test_many_passes_never_exceed_the_ceiling(self):
        doc, layer = blank()
        run(layer, doc, B.Brush(size=10, hardness=1.0, spacing=0.1, opacity=0.3, color=(0, 0, 0)), passes((15, 40), (105, 40), 12))
        self.assertAlmostEqual(alpha_at(layer, 60, 40), 0.30, delta=0.005)

    def test_ceiling_is_reached_at_the_flow_rate_and_not_exceeded(self):
        doc, layer = blank()
        brush = B.Brush(size=10, hardness=1.0, spacing=0.1, opacity=0.5, flow=0.3, color=(0, 0, 0))
        run(layer, doc, brush, line(15, 40, 105, 40))
        self.assertAlmostEqual(alpha_at(layer, 60, 40), 0.5 * 0.3, delta=0.01)           # un passage : débit × plafond
        run(layer, doc, brush, passes((15, 40), (105, 40), 1))                            # (un autre trait : repart du plafond)
        doc2, layer2 = blank()
        run(layer2, doc2, brush, passes((15, 40), (105, 40), 14))
        self.assertAlmostEqual(alpha_at(layer2, 60, 40), 0.5, delta=0.01)                 # plafond atteint, jamais dépassé

    def test_pressure_dip_does_not_erase_in_wash(self):
        doc, layer = blank()
        brush = B.Brush(size=10, hardness=1.0, spacing=0.1, color=(0, 0, 0), pressure_opacity=True, paint_mode="wash")
        path = passes((15, 40), (105, 40), 2)
        n = len(path)
        pr = [0.9 if i < n // 2 else 0.2 for i in range(n)]
        run(layer, doc, brush, path, pr, check_monotone=True)
        self.assertAlmostEqual(alpha_at(layer, 60, 40), 0.9, delta=0.01)                 # le passage faible n'écrase rien

    def test_edge_of_a_partial_opacity_stroke_keeps_its_antialiasing(self):
        # Avant : min(couverture, opacité) aplatissait tout le bord à 30 % (0,63 → 0,30 ; 0,37 → 0,30) : bord binaire.
        doc, layer = blank()
        run(layer, doc, B.Brush(size=10, hardness=1.0, spacing=0.1, opacity=0.3, color=(0, 0, 0)), line(10, 40.37, 110, 40.37))
        col = np.array([alpha_at(layer, 60, y) for y in range(33, 48)])
        self.assertAlmostEqual(col[2], 0.3 * 0.63, delta=0.015)
        self.assertAlmostEqual(col[12], 0.3 * 0.37, delta=0.015)
        self.assertAlmostEqual(float(col.max()), 0.30, delta=0.005)


class BlackOnWhiteMonotonicTest(unittest.TestCase):
    """Un pinceau noir sur fond blanc ne rend jamais un pixel plus clair — au sein d'un trait ET entre deux traits."""

    def _random_path(self, rng, n=90):
        pts, x, y, a = [], rng.uniform(15, 115), rng.uniform(15, 65), rng.uniform(0, 6.28)
        for _ in range(n):
            a += rng.normal(0, 0.45)
            x = min(120, max(10, x + 2.0 * math.cos(a)))
            y = min(70, max(10, y + 2.0 * math.sin(a)))
            pts.append((x, y))
        return pts

    def test_random_strokes_pressure_curves_and_modes(self):
        rng = np.random.default_rng(11)
        for mode in ("", "wash", "buildup"):
            for pressure_opacity in (False, True):
                doc, layer = blank(background=WHITE)
                brush = B.Brush(size=12, hardness=0.7, spacing=0.1, color=(0, 0, 0), opacity=0.6, flow=0.7, paint_mode=mode,
                                pressure_opacity=pressure_opacity, pressure_size=True)
                for _stroke in range(3):                                                   # (3 traits distincts)
                    path = self._random_path(rng)
                    pr = list(np.clip(0.5 + 0.45 * np.sin(np.arange(len(path)) / 5.0 + rng.uniform(0, 6)), 0.05, 1.0))
                    before = layer.pix.read(doc.rect())[..., 0].astype(np.int32)
                    run(layer, doc, brush, path, pr, check_monotone=True)
                    after = layer.pix.read(doc.rect())[..., 0].astype(np.int32)
                    self.assertTrue((after <= before + 1).all(), f"mode={mode!r} pression={pressure_opacity}")

    def test_transparent_layer_alpha_never_decreases(self):
        rng = np.random.default_rng(5)
        doc, layer = blank()
        brush = B.Brush(size=9, hardness=0.9, spacing=0.1, color=(20, 40, 200), opacity=0.5, pressure_opacity=True)
        for _ in range(3):
            path = self._random_path(rng)
            pr = list(np.clip(0.5 + 0.45 * np.sin(np.arange(len(path)) / 4.0), 0.05, 1.0))
            before = layer.pix.read(doc.rect())[..., 3].astype(np.int32)
            run(layer, doc, brush, path, pr)
            after = layer.pix.read(doc.rect())[..., 3].astype(np.int32)
            self.assertTrue((after >= before - 1).all())
        rgba = layer.pix.read(doc.rect())
        seen = rgba[rgba[..., 3] > 40]
        self.assertTrue((np.abs(seen[:, 0].astype(int) - 20) <= 2).all() and (np.abs(seen[:, 2].astype(int) - 200) <= 2).all())


class LayerStatesTest(unittest.TestCase):
    def test_partially_opaque_layer(self):
        doc, layer = blank()
        layer.pix.write((0, 0, 130, 80), np.full((80, 130, 4), (255, 0, 0, 128), np.uint8))
        run(layer, doc, B.Brush(size=10, hardness=1.0, spacing=0.1, color=(0, 0, 0), paint_mode="buildup", opacity=0.3),
            line(10, 40, 110, 40))
        pixel = layer.pix.read((60, 40, 61, 41))[0, 0]
        old_a = 128 / 255.0
        self.assertAlmostEqual(pixel[3] / 255.0, old_a + 0.3 * (1 - old_a), delta=0.01)    # alpha_final = ancien + apport (1 − ancien)
        self.assertLess(int(pixel[0]), 255)                                              # la couleur tire vers le noir

    def test_undo_redo_of_an_accumulating_stroke(self):
        doc, layer = blank(background=WHITE)
        base = layer.pix.read(doc.rect()).copy()
        history = History()
        brush = B.Brush(size=10, hardness=0.5, spacing=0.1, color=(0, 0, 0), pressure_opacity=True)
        path = passes((15, 40), (105, 40), 4)
        history.push(run(layer, doc, brush, path, [0.4] * len(path)))
        painted = layer.pix.read(doc.rect()).copy()
        self.assertFalse(np.array_equal(base, painted))
        history.undo()
        self.assertTrue(np.array_equal(layer.pix.read(doc.rect()), base))
        history.redo()
        self.assertTrue(np.array_equal(layer.pix.read(doc.rect()), painted))

    def test_small_brush_accumulation_state_is_consistent(self):
        # Pointe fine (état au sous-pixel) : mêmes lois que la grande pointe.
        doc, layer = blank()
        brush = B.Brush(size=4, hardness=1.0, spacing=0.1, color=(0, 0, 0), paint_mode="buildup", opacity=0.3)
        run(layer, doc, brush, passes((15, 40.5), (105, 40.5), 2))
        self.assertAlmostEqual(alpha_at(layer, 60, 40), 1 - 0.7 ** 2, delta=0.03)

    def test_eraser_keeps_its_own_behaviour(self):
        doc, layer = blank(background=WHITE)
        run(layer, doc, B.Brush(size=10, hardness=1.0, spacing=0.1, eraser=True, opacity=0.5), line(10, 40, 110, 40))
        self.assertAlmostEqual(alpha_at(layer, 60, 40), 0.5, delta=0.01)                  # la gomme RETIRE (exception explicite)
        run(layer, doc, B.Brush(size=10, hardness=1.0, spacing=0.1, eraser=True, opacity=0.5), line(60, 10, 60, 70))
        self.assertAlmostEqual(alpha_at(layer, 60, 40), 0.25, delta=0.02)                 # opacité plafond : 2 traits = 0,5 × 0,5

    def test_old_presets_keep_their_behaviour(self):
        old = B.Brush.from_dict({"size": 20, "opacity": 0.5, "flow": 0.5, "pressure_opacity": True})
        self.assertEqual(old.paint_mode, "wash")                                       # migration explicite : plafond
        self.assertEqual(old.paint_kind(), "wash")
        self.assertEqual(B.Brush.from_dict({"paint_mode": ""}).paint_mode, "wash")
        self.assertEqual(B.Brush.from_dict({"paint_mode": "n'importe quoi"}).paint_mode, "wash")
        self.assertEqual(B.Brush.from_dict({"paint_mode": "buildup"}).paint_kind(), "buildup")


if __name__ == "__main__":
    unittest.main()
