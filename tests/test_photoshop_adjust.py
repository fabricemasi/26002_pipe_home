"""Module Photoshop : réglages d'image et filtres (valeurs de référence, sélection partielle, recalcul depuis
l'original sans accumulation d'erreur, annulation exacte)."""
import os as _os, sys as _sys  # jamais les vrais réglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fm_photoshop import adjust as A, model as M, ops, selection as S
from fm_photoshop.history import History


def gray_layer(value=100, w=8, h=8, alpha=255):
    doc = M.new_document(w, h, background=None)
    layer = doc.layers[0]
    layer.pix.set_all(0, 0, np.full((h, w, 4), (value, value, value, alpha), np.uint8))
    return doc, layer


def apply_effect(doc, layer, name, params=None, selection=None):
    got = A.run(layer, name, params, selection, doc.rect())
    if got is None:
        return None
    rect, before, after = got
    return ops.replace_pixels(layer, rect, after, A.EFFECTS[name][0])


def px(layer, x=0, y=0):
    return tuple(int(v) for v in layer.pix.read((x, y, x + 1, y + 1))[0, 0])


class TableAdjustTest(unittest.TestCase):
    def test_invert_and_alpha_untouched(self):
        doc, layer = gray_layer(100, alpha=77)
        apply_effect(doc, layer, "invert")
        self.assertEqual(px(layer), (155, 155, 155, 77))

    def test_brightness_contrast_reference_values(self):
        doc, layer = gray_layer(128)
        self.assertIsNone(apply_effect(doc, layer, "brightness_contrast", {"brightness": 0.0, "contrast": 0.0}))
        apply_effect(doc, layer, "brightness_contrast", {"brightness": 0.2, "contrast": 0.0})
        self.assertAlmostEqual(px(layer)[0], 128 + 0.1 * 255, delta=1)                  # décalage de b/2
        doc2, layer2 = gray_layer(64)
        apply_effect(doc2, layer2, "brightness_contrast", {"brightness": 0.0, "contrast": 0.5})
        slope = np.tan(1.5 * np.pi / 4)
        self.assertAlmostEqual(px(layer2)[0], np.clip((64 / 255 - 0.5) * slope + 0.5, 0, 1) * 255, delta=1)

    def test_levels(self):
        doc, layer = gray_layer(128)
        apply_effect(doc, layer, "levels", {"in_black": 64, "in_white": 192})
        self.assertAlmostEqual(px(layer)[0], 128, delta=1)                              # le milieu reste au milieu
        doc, layer = gray_layer(64)
        apply_effect(doc, layer, "levels", {"in_black": 64, "in_white": 192})
        self.assertEqual(px(layer)[0], 0)
        doc, layer = gray_layer(128)
        apply_effect(doc, layer, "levels", {"gamma": 2.0})
        self.assertAlmostEqual(px(layer)[0], 255 * (128 / 255) ** 0.5, delta=1)         # gamma > 1 éclaircit

    def test_curves_identity_and_monotone(self):
        lut = A.curve_lut([(0, 0), (255, 255)])
        self.assertTrue(np.array_equal(lut, np.arange(256)))
        lut = A.curve_lut([(0, 0), (64, 128), (192, 128), (255, 255)])
        self.assertTrue((np.diff(lut.astype(int)) >= 0).all())                          # jamais de dépassement
        self.assertEqual(int(lut[64]), 128)
        doc, layer = gray_layer(64)
        apply_effect(doc, layer, "curves", {"points": [(0, 0), (64, 200), (255, 255)]})
        self.assertEqual(px(layer)[0], 200)

    def test_per_channel_curves(self):
        doc = M.new_document(2, 1, background=None)
        layer = doc.layers[0]
        layer.pix.set_all(0, 0, np.full((1, 2, 4), (64, 64, 64, 255), np.uint8))
        apply_effect(doc, layer, "curves", {"points": [(0, 0), (255, 255)], "red": [(0, 0), (64, 200), (255, 255)]})
        r, g, b, a = px(layer)
        self.assertEqual((r, g, b, a), (200, 64, 64, 255))                               # seul le rouge est modifié

    def test_exposure_one_stop_in_linear_light(self):
        doc, layer = gray_layer(128)
        apply_effect(doc, layer, "exposure", {"ev": 1.0})
        lin = ((128 / 255 + 0.055) / 1.055) ** 2.4 * 2
        expect = (1.055 * lin ** (1 / 2.4) - 0.055) * 255
        self.assertAlmostEqual(px(layer)[0], expect, delta=1)

    def test_black_white_weights(self):
        doc = M.new_document(2, 2, background=None)
        layer = doc.layers[0]
        layer.pix.set_all(0, 0, np.full((2, 2, 4), (200, 100, 0, 255), np.uint8))
        apply_effect(doc, layer, "black_white", {"red": 0.5, "green": 0.5, "blue": 0.0})
        self.assertEqual(px(layer), (150, 150, 150, 255))


class HslTest(unittest.TestCase):
    def test_hue_rotation_of_primaries(self):
        doc = M.new_document(3, 1, background=None)
        layer = doc.layers[0]
        layer.pix.set_all(0, 0, np.array([[[255, 0, 0, 255], [0, 255, 0, 255], [0, 0, 255, 255]]], np.uint8))
        apply_effect(doc, layer, "hue_saturation", {"hue": 120})
        self.assertEqual([px(layer, i)[:3] for i in range(3)], [(0, 255, 0), (0, 0, 255), (255, 0, 0)])

    def test_desaturate_and_lightness(self):
        doc = M.new_document(1, 1, background=None)
        layer = doc.layers[0]
        layer.pix.set_all(0, 0, np.array([[[200, 50, 50, 255]]], np.uint8))
        apply_effect(doc, layer, "hue_saturation", {"saturation": -1.0})
        r, g, b, _ = px(layer)
        self.assertEqual((r, g), (g, b))                                                # gris
        apply_effect(doc, layer, "hue_saturation", {"lightness": 1.0})
        self.assertEqual(px(layer)[:3], (255, 255, 255))

    def test_color_balance_shifts_shadows_only(self):
        doc = M.new_document(2, 1, background=None)
        layer = doc.layers[0]
        layer.pix.set_all(0, 0, np.array([[[30, 30, 30, 255], [230, 230, 230, 255]]], np.uint8))
        apply_effect(doc, layer, "color_balance", {"shadows": (0.6, 0, 0), "preserve_luminosity": False})
        self.assertGreater(px(layer, 0)[0], px(layer, 0)[1])                            # ombres plus rouges
        self.assertEqual(px(layer, 1)[:3], (230, 230, 230))                             # hautes lumières intactes


class FilterTest(unittest.TestCase):
    def test_gaussian_spreads_into_transparent_neighbours_without_dark_halo(self):
        doc = M.new_document(20, 20, background=None)
        layer = doc.layers[0]
        layer.pix.write((8, 8, 12, 12), np.full((4, 4, 4), (255, 0, 0, 255), np.uint8))
        apply_effect(doc, layer, "gaussian_blur", {"radius": 3.0})
        edge = layer.pix.read((6, 10, 7, 11))[0, 0]
        self.assertGreater(int(edge[3]), 0)                                              # le flou déborde du carré
        self.assertEqual(tuple(int(v) for v in edge[:3]), (255, 0, 0))                   # couleur droite : rouge pur

    def test_filter_respects_partial_selection(self):
        doc, layer = gray_layer(0, 16, 16)
        layer.pix.write((0, 0, 8, 16), np.full((16, 8, 4), (255, 255, 255, 255), np.uint8))
        sel = S.Selection.from_array(doc.rect(), np.full((16, 16), 128, np.uint8))
        apply_effect(doc, layer, "invert", None, sel)
        self.assertEqual(px(layer, 2, 2)[0], round(255 + (0 - 255) * 128 / 255))         # mélange à 50 %
        sel2 = S.rectangle(doc.rect(), (0, 0, 4, 16))
        doc2, layer2 = gray_layer(10, 16, 16)
        apply_effect(doc2, layer2, "invert", None, sel2)
        self.assertEqual((px(layer2, 1, 1)[0], px(layer2, 10, 1)[0]), (245, 10))

    def test_recompute_from_original_no_error_accumulation_and_undo(self):
        doc, layer = gray_layer(90)
        original = layer.pix.read(doc.rect())
        history = History()
        for value in (0.1, 0.5, -0.3, 0.2):                                              # curseur qui bouge : on recalcule
            got = A.run(layer, "brightness_contrast", {"brightness": value}, None, doc.rect())
            self.assertTrue(np.array_equal(layer.pix.read(doc.rect()), original))        # `run` ne modifie rien
        rect, before, after = got
        history.push(ops.replace_pixels(layer, rect, after, "Luminosité"))
        history.undo()
        self.assertTrue(np.array_equal(layer.pix.read(doc.rect()), original))
        history.redo()
        self.assertTrue(np.array_equal(layer.pix.read(doc.rect()), after))

    def test_noise_reproducible_and_params_cleaned(self):
        doc, layer = gray_layer(128)
        a = A.run(layer, "noise", {"amount": 0.1}, None, doc.rect(), seed=5)[2]
        b = A.run(layer, "noise", {"amount": 0.1}, None, doc.rect(), seed=5)[2]
        self.assertTrue(np.array_equal(a, b))
        self.assertEqual(A.clean_params("noise", {"amount": "x", "inconnu": 3})["amount"], 0.1)
        self.assertEqual(A.clean_params("gaussian_blur", {"radius": 9999})["radius"], 250.0)

    def test_empty_layer_and_empty_selection_do_nothing(self):
        doc = M.new_document(4, 4, background=None)
        self.assertIsNone(A.run(doc.layers[0], "invert", None, None, doc.rect()))
        _doc, layer = gray_layer(50)
        self.assertIsNone(A.run(layer, "invert", None, S.Selection(), _doc.rect()))


if __name__ == "__main__":
    unittest.main()
