"""Module Photoshop : aperçu du déplacement d'un calque (sans recomposer la pile à chaque évènement), exactitude finale
après relâchement, approximation temporaire annoncée, annulation, déplacements sans effet."""
import os as _os, sys as _sys  # jamais les vrais réglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import os
import sys
import unittest

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

APP = QApplication.instance() or QApplication([])

from fm_photoshop import compose as C, model as M, ops, render  # noqa: E402
from fm_photoshop.canvas import CanvasView  # noqa: E402
from fm_photoshop.movepreview import MovePreview  # noqa: E402
from fm_photoshop.session import Session  # noqa: E402


def solid(w, h, rgba):
    return np.broadcast_to(np.array(rgba, np.uint8), (h, w, 4)).copy()


def make_doc(blend="normal", opacity=1.0):
    doc = M.new_document(256, 256, background=None)
    doc.layers.clear()
    base = M.Layer("fond")
    base.pix.set_all(0, 0, solid(256, 256, (200, 180, 40, 255)))
    middle = M.Layer("milieu")
    rng = np.random.default_rng(2)
    middle.pix.set_all(100, 100, rng.integers(0, 255, (60, 60, 4), dtype=np.uint8))
    top = M.Layer("haut")
    top.pix.set_all(20, 20, solid(50, 40, (30, 90, 220, 200)))
    top.blend, top.opacity = blend, opacity
    doc.layers = [base, middle, top]
    return doc, top, middle


def preview_tile(preview, rect):
    """Rendu de l'aperçu (tuile de base + calque par-dessus) sur la zone `rect` (une tuile), en RGBA droit."""
    w, h = rect[2] - rect[0], rect[3] - rect[1]
    image = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
    image.fill(0)
    painter = QPainter(image)
    painter.translate(-rect[0], -rect[1])
    painter.drawImage(rect[0], rect[1], preview.base_image((rect[0] // render.TILE, rect[1] // render.TILE)))
    preview.paint_layer(painter)
    painter.end()
    image = image.convertToFormat(QImage.Format_RGBA8888)
    return np.frombuffer(image.constBits(), np.uint8, h * image.bytesPerLine()).reshape(h, image.bytesPerLine())[:, :w * 4] \
        .reshape(h, w, 4).copy()


class PreviewTest(unittest.TestCase):
    def test_preview_matches_the_final_result_for_the_top_layer(self):
        for blend, opacity, tolerance in (("normal", 1.0, 1), ("normal", 0.5, 2), ("multiply", 0.8, 4), ("screen", 1.0, 4)):
            doc, top, _middle = make_doc(blend, opacity)
            preview = MovePreview(doc, top)
            preview.set_offset(35, 25)
            shown = preview_tile(preview, (0, 0, 256, 256))
            ops.shift_layer(top, 35, 25)
            exact = C.flatten_u8(doc)
            diff = np.abs(shown.astype(int) - exact.astype(int)).max()
            self.assertLessEqual(int(diff), tolerance, f"{blend} {opacity}")

    def test_model_untouched_during_the_gesture_and_dirty_zone(self):
        doc, top, _middle = make_doc()
        preview = MovePreview(doc, top)
        before = top.pix.data.copy()
        dirty = preview.set_offset(10, 5)
        self.assertEqual(dirty, (20, 20, 80, 65))                                      # ancienne ∪ nouvelle position
        self.assertTrue(np.array_equal(top.pix.data, before))
        self.assertEqual((top.pix.x, top.pix.y), (20, 20))
        self.assertIn((0, 0), preview.touched)

    def test_a_layer_below_another_is_an_announced_approximation(self):
        doc, top, middle = make_doc()
        top.pix.set_all(100, 100, solid(60, 60, (255, 0, 0, 255)))                    # le calque du dessus recouvre « milieu »
        preview = MovePreview(doc, middle)
        preview.set_offset(0, 0)
        shown = preview_tile(preview, (0, 0, 256, 256))
        exact = C.flatten_u8(doc)
        self.assertFalse(np.array_equal(shown, exact))                                # l'aperçu pose « milieu » au-dessus
        self.assertEqual(tuple(exact[130, 130]), (255, 0, 0, 255))


class CanvasMoveTest(unittest.TestCase):
    def setUp(self):
        self.doc, self.top, self.middle = make_doc()
        self.session = Session(self.doc)
        self.canvas = CanvasView(self.session)
        self.canvas.resize(500, 400)
        self.canvas.show()
        self.session.zoom, self.session.center = 1.0, (128.0, 128.0)
        self.session.select_layer(self.top)

    def tearDown(self):
        self.canvas.detach()
        self.canvas.deleteLater()

    def test_gesture_commits_once_exactly_and_undoes(self):
        c = self.canvas
        c.begin_move(30, 30, True)
        for i in range(1, 8):
            c.extend_move(30 + i * 5, 30 + i * 3)
            c.repaint()
        self.assertEqual((self.top.pix.x, self.top.pix.y), (20, 20))                   # rien de décalé pendant le geste
        self.assertEqual(len(self.session.history.done), 0)
        c.end_move()
        self.assertEqual((self.top.pix.x, self.top.pix.y), (55, 41))
        self.assertEqual(len(self.session.history.done), 1)
        # après relâchement, la tuile du cache est le résultat EXACT
        key = (0, 0)
        tile = c.cache.tile(key)
        shown = np.array(c.cache.tiles[key][0])
        exact = C.to_premult_u8(C.compose(self.doc.layers, (0, 0, 256, 256)))
        self.assertTrue(np.array_equal(shown, exact))
        self.session.undo()
        self.assertEqual((self.top.pix.x, self.top.pix.y), (20, 20))
        exact_back = C.to_premult_u8(C.compose(self.doc.layers, (0, 0, 256, 256)))
        self.assertTrue(np.array_equal(np.array(c.cache.tile((0, 0)) and c.cache.tiles[(0, 0)][0]), exact_back))

    def test_no_move_without_ctrl_or_on_locked_or_empty_layer(self):
        c = self.canvas
        messages = []
        c.message.connect(messages.append)
        c.begin_move(30, 30, False)
        self.assertIsNone(c._move)
        self.assertTrue(messages and "Ctrl" in messages[0])
        self.top.locked = True
        c.begin_move(30, 30, True)
        self.assertIsNone(c._move)
        self.top.locked = False
        c.begin_move(30, 30, True)
        c.end_move()                                                                   # aucun décalage : aucune étape
        self.assertEqual(len(self.session.history.done), 0)
        empty = M.Layer("vide")
        self.doc.layers.append(empty)
        self.session.select_layer(empty)
        c.begin_move(30, 30, True)
        self.assertIsNone(c._move)


if __name__ == "__main__":
    unittest.main()
