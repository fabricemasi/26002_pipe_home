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


if __name__ == "__main__":
    unittest.main()
