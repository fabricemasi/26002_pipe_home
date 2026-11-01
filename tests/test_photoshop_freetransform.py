"""Module Photoshop : transformation libre à poignées — géométrie (poignées, échelle, rotation, déplacement), recalcul depuis
l'original, validation (Entrée) en une étape, annulation (Échap), annulation de l'étape, refus sur calque de texte."""
import os as _os, sys as _sys  # jamais les vrais réglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import math
import unittest

import numpy as np

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from _photoshop_case import PsCase, settle
from fm_photoshop import freetransform as F, model as M


def layer_doc():
    doc = M.new_document(100, 100, background=None)
    layer = doc.layers[0]
    layer.pix.set_all(20, 30, np.full((20, 40, 4), (255, 0, 0, 255), np.uint8))
    return doc, layer


class GeometryTest(unittest.TestCase):
    def test_handles_scale_rotate_move(self):
        doc, layer = layer_doc()
        f = F.FreeTransform(layer)
        self.assertEqual(f.hit(60, 50), "se")
        self.assertEqual(f.hit(40, 40), "body")
        self.assertIsNone(f.hit(5, 5))
        self.assertEqual(f.hit(*f.handle_points()["rot"]), "rot")
        f.begin("se", 60, 50)
        f.drag(100, 70)
        self.assertEqual((f.sx, f.sy), (3.0, 3.0))
        f.begin("e", 60, 40)
        f.drag(80, 40)                                              # poignée de côté : une seule échelle
        self.assertEqual((f.sx, f.sy), (2.0, 3.0))
        f.reset()
        f.begin("se", 60, 50)
        f.drag(100, 52, shift=True)                                 # Maj : proportions gardées
        self.assertEqual(f.sx, f.sy)
        f.reset()
        f.begin("rot", 40, 2)
        f.drag(80, 40)                                              # pointeur à droite du centre : +90°
        self.assertAlmostEqual(f.angle, 90.0)
        f.drag(79, 36, shift=True)
        self.assertEqual(f.angle % 15, 0)
        f.reset()
        f.begin("body", 40, 40)
        f.drag(50, 45)
        self.assertEqual((f.dx, f.dy), (10.0, 5.0))
        xs = [p[0] for p in f.corners()]
        self.assertEqual((min(xs), max(xs)), (30.0, 70.0))

    def test_preview_never_accumulates_and_final_equals_direct_resample(self):
        from fm_photoshop import transform as T
        doc, layer = layer_doc()
        original = layer.pix.data.copy()
        f = F.FreeTransform(layer)
        for angle in (10, 33, -20, 45):
            f.angle = angle
            f.preview()
        f.angle = 45
        f.sx = f.sy = 1.5
        f.preview()
        direct = T.resample(original, (20, 30), f.matrix(), "bilinear")
        self.assertTrue(np.array_equal(layer.pix.data, direct[2]))
        f.cancel()
        self.assertTrue(np.array_equal(layer.pix.data, original))
        self.assertEqual((layer.pix.x, layer.pix.y), (20, 30))
        self.assertTrue(f.is_identity() is False)
        f.reset()
        self.assertTrue(f.is_identity())

    def test_empty_layer_refused(self):
        with self.assertRaises(ValueError):
            F.FreeTransform(M.Layer("vide"))


class CanvasFlowTest(PsCase):
    def test_ctrl_t_drag_handles_enter_escape_undo(self):
        _item, std = self.editor(120, 80, background="Transparent")
        canvas, s = std.canvas, std.session
        layer = s.layer()
        layer.pix.set_all(40, 30, np.full((20, 40, 4), (0, 0, 255, 255), np.uint8))
        before = layer.pix.data.copy()
        canvas.setFocus()
        QTest.keyClick(canvas, Qt.Key_T, Qt.ControlModifier)
        self.assertIsNotNone(canvas._xf)
        se = canvas._xf.handle_points()["se"]                       # coin bas droit (80, 50)
        self.drag(canvas, [self.at(canvas, *se), self.at(canvas, se[0] + 40, se[1] + 20)])
        self.assertEqual((canvas._xf.sx, canvas._xf.sy), (3.0, 3.0))
        self.assertEqual(layer.pix.data.shape[:2], (60, 120))        # aperçu déjà posé dans le calque
        QTest.keyClick(canvas, Qt.Key_Escape)                       # annuler
        self.assertIsNone(canvas._xf)
        self.assertTrue(np.array_equal(layer.pix.data, before))
        self.assertEqual(len(s.history.done), 0)
        QTest.keyClick(canvas, Qt.Key_T, Qt.ControlModifier)
        se = canvas._xf.handle_points()["se"]
        self.drag(canvas, [self.at(canvas, *se), self.at(canvas, se[0] + 40, se[1] + 20)])
        QTest.keyClick(canvas, Qt.Key_Return)                       # valider : UNE étape
        self.assertIsNone(canvas._xf)
        self.assertEqual(len(s.history.done), 1)
        self.assertEqual(s.history.labels()[0], "Transformation libre")
        self.assertEqual(layer.pix.data.shape[:2], (60, 120))
        s.undo()
        self.assertTrue(np.array_equal(layer.pix.data, before))
        s.redo()
        self.assertEqual(layer.pix.data.shape[:2], (60, 120))
        # corps sans Ctrl : refusé ; avec Ctrl : déplacé
        QTest.keyClick(canvas, Qt.Key_T, Qt.ControlModifier)
        messages = []
        canvas.message.connect(messages.append)
        centre = canvas._xf.job.center()
        self.drag(canvas, [self.at(canvas, *centre), self.at(canvas, centre[0] + 10, centre[1])])
        self.assertTrue(any("Ctrl" in m for m in messages))
        self.assertTrue(canvas._xf.is_identity())
        QTest.keyClick(canvas, Qt.Key_Escape)

    def test_refused_on_text_locked_and_no_change_validation(self):
        _item, std = self.editor(100, 60)
        canvas, s = std.canvas, std.session
        text = canvas.actions.add_text({"content": "T", "x": 5, "y": 5, "size": 20})
        messages = []
        canvas.message.connect(messages.append)
        self.assertIsNone(canvas.start_free_transform())
        self.assertTrue(messages)
        s.select_layer(s.doc.layers[0])
        s.doc.layers[0].locked = True
        self.assertIsNone(canvas.start_free_transform())
        s.doc.layers[0].locked = False
        self.assertIsNotNone(canvas.start_free_transform())
        n = len(s.history.done)
        canvas.commit_free_transform()                              # rien changé : aucune étape
        self.assertEqual(len(s.history.done), n)
        # choisir un autre calque valide la transformation en cours
        s.select_layer(s.doc.layers[0])
        xf = canvas.start_free_transform()
        xf.sx = 1.2
        s.select_layer(text)
        self.assertIsNone(canvas._xf)
        self.assertEqual(s.history.labels()[0], "Transformation libre")


if __name__ == "__main__":
    unittest.main()
