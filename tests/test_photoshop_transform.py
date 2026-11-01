"""Module Photoshop : transformations (rééchantillonnage exact sur cas connus, aucune dégradation cumulée pendant un
geste, halos, recadrage, taille de l'image et de la zone de travail, symétries, annulation exacte)."""
import os as _os, sys as _sys  # jamais les vrais réglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fm_photoshop import compose as C, model as M, transform as T
from fm_photoshop.history import History


def pattern(w=6, h=4):
    rng = np.random.default_rng(3)
    data = rng.integers(0, 256, (h, w, 4), dtype=np.uint8)
    data[..., 3] = 255
    return data


def doc_with(data, x=0, y=0, w=20, h=20):
    doc = M.new_document(w, h, background=None)
    doc.layers[0].pix.set_all(x, y, data)
    return doc


class ResampleTest(unittest.TestCase):
    def test_identity_and_integer_translation_are_exact(self):
        data = pattern()
        for quality in T.QUALITIES:
            x, y, out = T.resample(data, (0, 0), T.IDENTITY, quality)
            self.assertEqual((x, y), (0, 0))
            self.assertTrue(np.array_equal(out, data), quality)
            x, y, moved = T.resample(data, (2, 3), T.translation(5, -1), quality)
            self.assertEqual((x, y), (7, 2))
            self.assertTrue(np.array_equal(moved, data), quality)

    def test_quarter_turns_are_exact_permutations(self):
        data = pattern(6, 4)
        for quality in ("nearest", "bilinear", "bicubic"):
            x, y, out = T.resample(data, (0, 0), T.rotation(90), quality)
            self.assertTrue(np.array_equal(out, np.rot90(data, -1)), quality)       # sens horaire en y vers le bas
            self.assertEqual((x, y), (-4, 0))
            x, y, out = T.resample(data, (0, 0), T.rotation(180, 3, 2), quality)
            self.assertTrue(np.array_equal(out, data[::-1, ::-1]), quality)

    def test_scale_nearest_and_area_average(self):
        data = pattern(4, 4)
        x, y, big = T.resample(data, (0, 0), T.scaling(2, 2), "nearest")
        self.assertTrue(np.array_equal(big, data.repeat(2, 0).repeat(2, 1)))
        flat = np.zeros((4, 4, 4), np.uint8)
        flat[:, :2] = (200, 0, 0, 255)
        flat[:, 2:] = (0, 0, 200, 255)
        x, y, small = T.resample(flat, (0, 0), T.scaling(0.5, 0.5), "bilinear")
        self.assertEqual(small.shape[:2], (2, 2))
        self.assertTrue((small[:, 0] == (200, 0, 0, 255)).all() and (small[:, 1] == (0, 0, 200, 255)).all())

    def test_no_dark_halo_on_rotated_transparent_edges(self):
        data = np.full((12, 12, 4), (255, 0, 0, 255), np.uint8)
        x, y, out = T.resample(data, (0, 0), T.rotation(30, 6, 6), "bicubic")
        edge = out[(out[..., 3] > 0) & (out[..., 3] < 255)]
        self.assertGreater(len(edge), 10)
        self.assertTrue((edge[:, 0] >= 250).all() and (edge[:, 1] <= 5).all())       # rouge pur sur les bords doux

    def test_fully_outside_returns_none(self):
        self.assertIsNone(T.resample(pattern(), (0, 0), T.scaling(0, 0), "bilinear"))


class SessionTest(unittest.TestCase):
    def test_preview_steps_never_accumulate_error(self):
        data = pattern(30, 20)
        doc = doc_with(data)
        layer = doc.layers[0]
        session = T.TransformSession(layer)
        for degrees in (5, 17, -40, 33, 10):                                          # un geste : plusieurs pas d'aperçu
            session.render(T.rotation(degrees, 15, 10), "bilinear")
        final = session.render(T.rotation(10, 15, 10), "bilinear")
        direct = T.resample(data, (0, 0), T.rotation(10, 15, 10), "bilinear")
        self.assertTrue(np.array_equal(layer.pix.data, direct[2]))                    # = une seule passe depuis l'original

    def test_cancel_restores_exactly_and_command_roundtrip(self):
        data = pattern(30, 20)
        doc = doc_with(data)
        layer = doc.layers[0]
        session = T.TransformSession(layer)
        session.render(T.scaling(1.5, 1.5, 0, 0), "bilinear")
        session.cancel()
        self.assertTrue(np.array_equal(layer.pix.data, data))
        session.render(T.rotation(25, 15, 10))
        history = History()
        history.push(session.command("bicubic"))
        done = layer.pix.read((-10, -10, 50, 50))
        history.undo()
        self.assertTrue(np.array_equal(layer.pix.data, data))
        self.assertEqual((layer.pix.x, layer.pix.y), (0, 0))
        history.redo()
        self.assertTrue(np.array_equal(layer.pix.read((-10, -10, 50, 50)), done))

    def test_mask_follows_the_layer(self):
        doc = doc_with(pattern(8, 8))
        layer = doc.layers[0]
        layer.mask = M.Mask()
        layer.mask.plane.set_all(0, 0, np.full((8, 8, 1), 90, np.uint8))
        session = T.TransformSession(layer)
        session.render(T.translation(4, 2))
        self.assertEqual((layer.pix.x, layer.pix.y, layer.mask.plane.x, layer.mask.plane.y), (4, 2, 4, 2))
        self.assertEqual(int(layer.mask.plane.data[0, 0, 0]), 90)


class DocumentTest(unittest.TestCase):
    def test_crop_and_undo(self):
        data = pattern(10, 10)
        doc = doc_with(data, 0, 0, 20, 20)
        history = History()
        before = doc.layers[0].pix.read((0, 0, 20, 20))
        history.push(T.crop(doc, (2, 3, 8, 9)))
        self.assertEqual((doc.width, doc.height), (6, 6))
        self.assertTrue(np.array_equal(doc.layers[0].pix.data, data[3:9, 2:8]))
        history.undo()
        self.assertEqual((doc.width, doc.height), (20, 20))
        self.assertTrue(np.array_equal(doc.layers[0].pix.read((0, 0, 20, 20)), before))
        history.redo()
        self.assertEqual((doc.width, doc.height), (6, 6))
        with self.assertRaises(ValueError):
            T.crop(doc, (100, 100, 120, 120))

    def test_canvas_size_anchor(self):
        data = pattern(4, 4)
        doc = doc_with(data, 0, 0, 4, 4)
        cmd = T.canvas_size(doc, 10, 8, (0.5, 0.5))
        self.assertEqual((doc.width, doc.height, doc.layers[0].pix.x, doc.layers[0].pix.y), (10, 8, 3, 2))
        cmd.undo()
        self.assertEqual((doc.width, doc.height, doc.layers[0].pix.x), (4, 4, 0))
        T.canvas_size(doc, 6, 6, (0, 0))
        self.assertEqual(doc.layers[0].pix.x, 0)

    def test_resize_image_scales_every_layer_once(self):
        data = pattern(8, 8)
        doc = doc_with(data, 0, 0, 8, 8)
        extra = M.Layer("b")
        extra.pix.set_all(2, 2, np.full((2, 2, 4), (9, 9, 9, 255), np.uint8))
        doc.layers.append(extra)
        history = History()
        history.push(T.resize_image(doc, 16, 16, "nearest"))
        self.assertEqual((doc.width, doc.height), (16, 16))
        self.assertTrue(np.array_equal(doc.layers[0].pix.data, data.repeat(2, 0).repeat(2, 1)))
        self.assertEqual((extra.pix.x, extra.pix.y, extra.pix.data.shape[:2]), (4, 4, (4, 4)))
        history.undo()
        self.assertEqual((doc.width, extra.pix.x, extra.pix.data.shape[0]), (8, 2, 2))
        self.assertTrue(np.array_equal(doc.layers[0].pix.data, data))

    def test_flip_canvas_is_exact_and_involutive(self):
        data = pattern(6, 4)
        doc = doc_with(data, 1, 2, 10, 8)
        before = C.flatten_u8(doc)
        T.flip_canvas(doc, True)
        self.assertTrue(np.array_equal(C.flatten_u8(doc), before[:, ::-1]))
        T.flip_canvas(doc, True)
        self.assertTrue(np.array_equal(C.flatten_u8(doc), before))
        cmd = T.flip_canvas(doc, False)
        self.assertTrue(np.array_equal(C.flatten_u8(doc), before[::-1]))
        cmd.undo()
        self.assertTrue(np.array_equal(C.flatten_u8(doc), before))


if __name__ == "__main__":
    unittest.main()
