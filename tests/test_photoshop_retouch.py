"""Module Photoshop : outils de retouche du moteur de brosse (tampon de duplication à source explicite, correcteur par
séparation de fréquences, flou, netteté, doigt, densité) — valeurs de référence, sélection, annulation exacte."""
import os as _os, sys as _sys  # jamais les vrais réglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fm_photoshop import brush as B, model as M, selection as S
from fm_photoshop.history import History


def make_doc(w=64, h=64, fill=(128, 128, 128, 255)):
    doc = M.new_document(w, h, background=None)
    doc.layers[0].pix.set_all(0, 0, np.full((h, w, 4), fill, np.uint8))
    return doc, doc.layers[0]


def run(layer, doc, brush, points, retouch=None, selection=None):
    stroke = B.Stroke(layer, "pixels", brush, doc.rect(), selection, retouch)
    stroke.begin(*points[0])
    for p in points[1:]:
        stroke.move(*p)
    stroke.finish_to(*points[-1])
    return stroke.end(brush.mode)


class CloneTest(unittest.TestCase):
    def test_clone_copies_source_exactly_and_undoes(self):
        doc, layer = make_doc()
        rng = np.random.default_rng(2)
        layer.pix.write((0, 0, 20, 20), rng.integers(0, 255, (20, 20, 4), dtype=np.uint8) | np.array([0, 0, 0, 255], np.uint8))
        before = layer.pix.read(doc.rect())
        brush = B.Brush(size=12, hardness=1.0, mode="clone", spacing=0.1)
        history = History()
        history.push(run(layer, doc, brush, [(40, 40), (50, 40)], {"offset": (-30, -30)}))
        after = layer.pix.read(doc.rect())
        # le centre du trait reprend exactement les pixels situés 30 px plus haut et à gauche
        self.assertTrue(np.array_equal(after[40, 42:50], before[10, 12:20]))
        self.assertTrue(np.array_equal(after[0:20, 0:20], before[0:20, 0:20]))                          # source intacte
        history.undo()
        self.assertTrue(np.array_equal(layer.pix.read(doc.rect()), before))

    def test_source_is_required_and_selection_respected(self):
        doc, layer = make_doc()
        with self.assertRaises(ValueError):
            B.Stroke(layer, "pixels", B.Brush(mode="clone"), doc.rect())
        layer.pix.write((0, 0, 10, 10), np.full((10, 10, 4), (255, 0, 0, 255), np.uint8))
        sel = S.rectangle(doc.rect(), (30, 0, 64, 64))
        run(layer, doc, B.Brush(size=10, hardness=1.0, mode="clone"), [(5, 5), (45, 5)], {"offset": (0, 0)})
        self.assertEqual(tuple(layer.pix.read((5, 5, 6, 6))[0, 0]), (255, 0, 0, 255))
        # avec décalage et sélection : rien n'est copié hors de la sélection
        doc2, layer2 = make_doc()
        layer2.pix.write((0, 20, 64, 30), np.full((10, 64, 4), (0, 255, 0, 255), np.uint8))
        run(layer2, doc2, B.Brush(size=10, hardness=1.0, mode="clone", spacing=0.1), [(4, 45), (60, 45)],
            {"offset": (0, -20)}, S.rectangle(doc2.rect(), (30, 0, 64, 64)))
        self.assertEqual(tuple(layer2.pix.read((10, 45, 11, 46))[0, 0]), (128, 128, 128, 255))
        self.assertEqual(tuple(layer2.pix.read((50, 45, 51, 46))[0, 0]), (0, 255, 0, 255))


class HealTest(unittest.TestCase):
    def test_heal_keeps_destination_tones_and_source_texture(self):
        doc, layer = make_doc(96, 64, (0, 0, 0, 255))
        rng = np.random.default_rng(5)
        texture = rng.normal(0, 18, (64, 48)).astype(np.float32)
        left = np.clip(60 + texture, 0, 255)                               # source : texture sur gris 60
        right = np.full((64, 48), 200.0)                                   # destination : gris 200 uni (ton différent)
        data = np.zeros((64, 96, 4), np.uint8)
        data[:, :48, :3] = left[..., None].astype(np.uint8)
        data[:, 48:, :3] = right[..., None].astype(np.uint8)
        data[..., 3] = 255
        layer.pix.set_all(0, 0, data)
        brush = B.Brush(size=24, hardness=1.0, mode="heal", sigma=3.0, spacing=0.1)
        run(layer, doc, brush, [(72, 32), (76, 32)], {"offset": (-48, 0)})
        zone = layer.pix.read((68, 28, 80, 36))[..., 0].astype(np.float32)
        self.assertAlmostEqual(float(zone.mean()), 200.0, delta=12)                                     # tons de la destination
        self.assertGreater(float(zone.std()), 6.0)                                                      # texture de la source
        copy = run(layer, doc, B.Brush(size=24, hardness=1.0, mode="clone", spacing=0.1), [(72, 32), (76, 32)],
                   {"offset": (-48, 0)})
        cloned = layer.pix.read((68, 28, 80, 36))[..., 0].astype(np.float32)
        self.assertLess(abs(float(cloned.mean()) - 200.0), 200.0)                                       # le clone, lui, ramène 60
        self.assertLess(float(cloned.mean()), 100.0)

    def test_heal_never_touches_transparent_destination(self):
        doc, layer = make_doc(40, 20, (100, 100, 100, 255))
        layer.pix.write((20, 0, 40, 20), np.zeros((20, 20, 4), np.uint8))
        run(layer, doc, B.Brush(size=16, hardness=1.0, mode="heal"), [(30, 10), (34, 10)], {"offset": (-20, 0)})
        self.assertEqual(int(layer.pix.read((30, 10, 31, 11))[0, 0, 3]), 0)


class FilterToolsTest(unittest.TestCase):
    def edge_doc(self):
        doc, layer = make_doc(64, 32, (60, 60, 60, 255))
        layer.pix.write((32, 0, 64, 32), np.full((32, 32, 4), (200, 200, 200, 255), np.uint8))
        return doc, layer

    def test_blur_softens_the_edge_only_under_the_brush(self):
        doc, layer = self.edge_doc()
        run(layer, doc, B.Brush(size=14, hardness=1.0, mode="blur", sigma=3.0, spacing=0.1), [(32, 16), (33, 16)])
        row = layer.pix.read((24, 16, 40, 17))[0, :, 0].astype(int)
        self.assertTrue(((row > 70) & (row < 190)).any())                                               # dégradé au bord
        self.assertEqual(int(layer.pix.read((2, 2, 3, 3))[0, 0, 0]), 60)                               # loin du pinceau : intact
        self.assertEqual(int(layer.pix.read((60, 30, 61, 31))[0, 0, 0]), 200)

    def test_sharpen_increases_edge_contrast(self):
        doc, layer = make_doc(64, 32, (100, 100, 100, 255))
        layer.pix.write((32, 0, 64, 32), np.full((32, 32, 4), (150, 150, 150, 255), np.uint8))
        run(layer, doc, B.Brush(size=14, hardness=1.0, mode="sharpen", sigma=2.0, spacing=0.1), [(32, 16), (33, 16)])
        row = layer.pix.read((24, 16, 40, 17))[0, :, 0].astype(int)
        self.assertLess(int(row.min()), 100)                                                           # creux avant le bord
        self.assertGreater(int(row.max()), 150)                                                        # bosse après

    def test_dodge_burn_and_smudge(self):
        doc, layer = make_doc(64, 32, (100, 100, 100, 255))
        run(layer, doc, B.Brush(size=10, hardness=1.0, mode="dodge", opacity=0.5), [(16, 16)])
        self.assertAlmostEqual(int(layer.pix.read((16, 16, 17, 17))[0, 0, 0]), 100 + 155 * 0.5, delta=1)
        run(layer, doc, B.Brush(size=10, hardness=1.0, mode="burn", opacity=0.5), [(48, 16)])
        self.assertAlmostEqual(int(layer.pix.read((48, 16, 49, 17))[0, 0, 0]), 50, delta=1)
        doc2, layer2 = make_doc(64, 32, (0, 0, 255, 255))
        layer2.pix.write((0, 0, 20, 32), np.full((32, 20, 4), (255, 0, 0, 255), np.uint8))
        run(layer2, doc2, B.Brush(size=12, hardness=1.0, mode="smudge", opacity=0.9, spacing=0.1),
            [(10, 16), (45, 16)])
        trail = layer2.pix.read((30, 16, 31, 17))[0, 0]
        self.assertGreater(int(trail[0]), 60)                                                          # du rouge a été traîné
        self.assertEqual(tuple(layer2.pix.read((30, 2, 31, 3))[0, 0]), (0, 0, 255, 255))               # hors du trait : bleu

    def test_mask_target_refuses_retouch_modes(self):
        doc, layer = make_doc()
        layer.mask = M.Mask()
        with self.assertRaises(ValueError):
            B.Stroke(layer, "mask", B.Brush(mode="blur"), doc.rect())

    def test_undo_is_exact_for_every_mode(self):
        for mode in ("blur", "sharpen", "smudge", "dodge", "burn"):
            doc, layer = self.edge_doc()
            before = layer.pix.read(doc.rect())
            history = History()
            history.push(run(layer, doc, B.Brush(size=16, hardness=0.5, mode=mode, opacity=0.8),
                             [(20, 10), (44, 20)]))
            self.assertFalse(np.array_equal(layer.pix.read(doc.rect()), before), mode)
            history.undo()
            self.assertTrue(np.array_equal(layer.pix.read(doc.rect()), before), mode)


class StrokeSmoothnessTest(unittest.TestCase):
    """Trait fluide à la manière des logiciels de dessin : courbe de milieu en milieu, pression filtrée."""

    def _width_profile(self, brush, points):
        doc, layer = make_doc(160, 60, (0, 0, 0, 0))
        stroke = B.Stroke(layer, "pixels", brush, doc.rect())
        stroke.begin(*points[0])
        for p in points[1:]:
            stroke.move(*p)
        stroke.finish_to(*points[-1][:2], points[-1][2])
        stroke.end()
        a = layer.pix.read(doc.rect())[..., 3]
        return np.array([(a[:, x] > 128).sum() for x in range(20, 140)], float)

    def test_noisy_pressure_gives_a_regular_width(self):
        brush = B.Brush(size=30, hardness=1.0, spacing=0.1, pressure_size=True)
        noisy = [(10 + 6 * i, 30, 0.9 if i % 2 else 0.35) for i in range(23)]
        steady = [(10 + 6 * i, 30, 0.62) for i in range(23)]
        jump = np.abs(np.diff(self._width_profile(brush, noisy))).max()
        reference = np.abs(np.diff(self._width_profile(brush, steady))).max()
        self.assertLessEqual(jump, 3)                                  # pas d'à-coups de plusieurs pixels d'une colonne à l'autre
        self.assertLessEqual(reference, 1)

    def test_tuning_controls_change_the_stroke(self):
        self.addCleanup(B.TUNING.reset)
        brush = B.Brush(size=30, hardness=1.0, spacing=0.1, pressure_size=True)
        light = [(10 + 6 * i, 30, 0.1) for i in range(23)]
        thin = self._width_profile(brush, light).max()
        self.assertAlmostEqual(thin, 3.0, delta=1.0)                  # courbe linéaire : 30 px x 0,1
        B.TUNING.min_diameter = 0.5                                   # diamètre minimum : la pression nulle garde la moitié
        self.assertGreater(self._width_profile(brush, light).max(), thin + 5)
        B.TUNING.reset()
        B.TUNING.size_gamma = 0.5                                     # courbe en racine : un appui léger reste épais
        self.assertGreater(self._width_profile(brush, light).max(), thin + 5)
        B.TUNING.reset()
        B.TUNING.pressure_filter = 0.2                                # pression lissée : un changement brutal arrive en retard
        jump = [(10 + 6 * i, 30, 0.1 if i < 8 else 1.0) for i in range(23)]
        late = self._width_profile(brush, jump)
        B.TUNING.reset()
        raw = self._width_profile(brush, jump)
        self.assertLess(late[40:50].mean(), raw[40:50].mean())

    def test_lagging_tip_keeps_the_pressure_it_had(self):
        self.addCleanup(B.TUNING.reset)
        brush = B.Brush(size=24, hardness=1.0, spacing=0.1, smoothing=0.6, pressure_size=True)
        pts = [(10 + 4 * i, 30, 1.0 if 10 + 4 * i < 70 else 0.1) for i in range(26)]

        def thick(on):
            B.TUNING.pressure_at_tip = on
            profile = self._width_profile(brush, pts)
            return int((profile > 18).sum())
        self.assertGreater(thick(True), thick(False))                 # la pointe en retard est encore épaisse là où le curseur a allégé

    def test_catch_up_during_a_pause_reaches_the_cursor(self):
        doc, layer = make_doc(160, 40, (0, 0, 0, 0))
        stroke = B.Stroke(layer, "pixels", B.Brush(size=6, hardness=1.0, spacing=0.1, smoothing=0.8), doc.rect())
        stroke.begin(10, 20)
        for x in range(14, 100, 4):
            stroke.move(x, 20)
        self.assertLess(stroke._pos[0], 90)                            # la corde retient la pointe
        for _ in range(60):                                            # (une zone vide = aucun tampon posé ce tour-ci, pas la fin)
            stroke.idle()
        self.assertAlmostEqual(stroke._pos[0], stroke._cursor[0], delta=0.6)
        stroke.finish_to(100, 20)
        stroke.end()
        self.assertGreater(int(layer.pix.read(doc.rect())[20, 96, 3]), 200)

    def test_tuning_text_and_reset(self):
        B.TUNING.oe_beta = 0.5
        self.assertIn("oe_beta=0.5", B.TUNING.as_text())
        B.TUNING.reset()
        self.assertEqual(B.TUNING, B.Tuning())

    def test_direct_mode_follows_sparse_samples_exactly(self):
        doc, layer = make_doc(100, 100, (0, 0, 0, 0))
        stroke = B.Stroke(layer, "pixels", B.Brush(size=6, hardness=1.0, spacing=0.1), doc.rect())
        pts = [(10, 50), (40, 20), (70, 50), (90, 80)]                  # échantillons très espacés
        stroke.begin(*pts[0])
        for p in pts[1:]:
            stroke.move(*p)
        stroke.finish_to(*pts[-1])
        stroke.end()
        alpha = layer.pix.read(doc.rect())[..., 3]
        self.assertGreater(int(alpha[80, 90]), 200)                    # dernier point atteint
        self.assertGreater(int(alpha[20, 40]), 200)                    # le sommet est ATTEINT : aucun angle coupé, aucune courbe ajoutée
        self.assertGreater(int(alpha[35, 25]), 200)                    # et la trajectoire est la polyligne exacte (y = 60 - x)

    def test_stabilizer_rounds_sparse_samples(self):
        doc, layer = make_doc(100, 100, (0, 0, 0, 0))
        brush = B.Brush(size=6, hardness=1.0, spacing=0.1, smoothing=0.01, smoothing_mode="stabilizer")
        stroke = B.Stroke(layer, "pixels", brush, doc.rect())
        pts = [(10, 50), (40, 20), (70, 50), (90, 80)]
        stroke.begin(*pts[0])
        for p in pts[1:]:
            stroke.move(*p)
        stroke.finish_to(*pts[-1])
        stroke.end()
        alpha = layer.pix.read(doc.rect())[..., 3]
        self.assertEqual(int(alpha[20, 40]), 0)                        # le stabilisateur contourne le sommet (courbe)
        self.assertGreater(int(alpha[35, 25:30].max()), 100)

    def test_rope_smoothing_lags_behind_the_cursor_like_photoshop(self):
        doc, layer = make_doc(200, 40, (0, 0, 0, 0))
        brush = B.Brush(size=6, hardness=1.0, spacing=0.1, smoothing=0.5)          # corde de 50 px
        stroke = B.Stroke(layer, "pixels", brush, doc.rect())
        stroke.begin(10, 20)
        for x in range(11, 71, 2):
            stroke.move(x, 20)
        stroke.finish_to(70, 20)
        stroke.end()
        a = layer.pix.read(doc.rect())[..., 3]
        self.assertGreater(int(a[20, 15]), 200)
        self.assertEqual(int(a[20, 40]), 0)                            # la pointe reste à 50 px derrière le curseur : trait court
        self.assertEqual(int(a[20, 60]), 0)                            # (pas de rattrapage à la fin, comme Photoshop par défaut)

    def test_low_flow_stroke_has_no_beads(self):
        doc, layer = make_doc(160, 40, (0, 0, 0, 0))
        brush = B.Brush(size=24, hardness=0.5, spacing=0.3, flow=0.2, opacity=1.0)
        stroke = B.Stroke(layer, "pixels", brush, doc.rect())
        stroke.begin(20, 20)
        stroke.move(140, 20)
        stroke.finish_to(140, 20)
        stroke.end()
        centre = layer.pix.read((40, 20, 120, 21))[0, :, 3].astype(int)
        self.assertLessEqual(int(centre.max() - centre.min()), 6)        # alpha régulier le long du trait (pas de perles)

    def _jittery_line(self, **brush_kw):
        import random
        random.seed(1)
        doc, layer = make_doc(200, 40, (0, 0, 0, 0))
        brush = B.Brush(size=24, hardness=1.0, spacing=0.1, pressure_size=True, **brush_kw)
        stroke = B.Stroke(layer, "pixels", brush, doc.rect())
        pts = [(10 + 1.5 * i, 20 + random.uniform(-0.7, 0.7)) for i in range(80)]    # ligne droite + tremblement de ±0,7 px
        stroke.begin(*pts[0], 0.5)
        for i, p in enumerate(pts[1:], 1):
            stroke.move(*p, 0.5, t=i / 120.0)
        stroke.finish_to(*pts[-1], 0.5)
        stroke.end()
        a = layer.pix.read(doc.rect())[..., 3].astype(float)
        centre = [(a[:, x] * np.arange(40)).sum() / a[:, x].sum() for x in range(25, 120)]
        return float(np.std(np.diff(centre)))

    def test_adaptive_mode_filters_hand_jitter_that_direct_mode_keeps(self):
        direct = self._jittery_line()
        adaptive = self._jittery_line(smoothing=0.7, smoothing_mode="adaptive")
        self.assertGreater(direct, 0.1)                                # mode « aucun » : la trajectoire du périphérique, telle quelle
        self.assertLess(adaptive, direct * 0.6)                        # adaptatif : tremblement lent nettement atténué


if __name__ == "__main__":
    unittest.main()
