"""Module Photoshop : calques de texte et de forme éditables (rendu, alignement, retour à la ligne, formes, outils à la
souris, fenêtres, modification annulable, conversion explicite en pixels, refus de peindre dessus, déplacement qui
entraîne la source, enregistrement / réouverture avec la source)."""
import os as _os, sys as _sys  # jamais les vrais réglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import os
import sys
import unittest

import numpy as np

os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")        # polices réelles en offscreen (sinon des carrés)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import Qt, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from _photoshop_case import APP, PsCase, settle  # noqa: E402
from fm_photoshop import brush as B, compose as C, container, ops, session as S, vector  # noqa: E402
from fm_photoshop.board_item import PsItem  # noqa: E402
from fm_photoshop.dialogs import ShapeDialog, TextDialog  # noqa: E402


def alpha_bounds(rgba):
    ys, xs = np.nonzero(rgba[..., 3])
    return (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)


class RenderTest(unittest.TestCase):
    def test_normalize_invalid_values(self):
        out = vector.normalize({"kind": "text", "size": "énorme", "align": "diagonale", "color": "rouge",
                                "line_height": 9999, "width": "x"})
        self.assertEqual((out["size"], out["align"], out["line_height"], out["width"]), (48, "left", 300.0, 0.0))
        self.assertEqual(out["color"], [0, 0, 0, 255])
        self.assertIsNone(vector.normalize({"kind": "inconnu"}))
        self.assertIsNone(vector.normalize("pas un dictionnaire"))
        shape = vector.normalize({"kind": "shape", "shape": "étoile", "stroke_width": -5, "fill": "?"})
        self.assertEqual((shape["shape"], shape["stroke_width"]), ("rect", 0.0))

    def test_text_color_size_and_empty(self):
        a = vector.render({"kind": "text", "content": "Hello", "size": 40, "color": [255, 0, 0, 255], "x": 10, "y": 20})
        b = vector.render({"kind": "text", "content": "Hello", "size": 80, "color": [255, 0, 0, 255], "x": 10, "y": 20})
        self.assertIsNotNone(a)
        (xa, ya, ra), (xb, yb, rb) = a, b
        self.assertGreater(rb.shape[1], ra.shape[1] * 1.6)                                             # corps ×2 -> largeur ≈ ×2
        solid = ra[ra[..., 3] == 255]
        self.assertGreater(len(solid), 20)
        self.assertTrue((solid[:, 0] == 255).all() and (solid[:, 1] == 0).all())                       # rouge pur, alpha droit
        self.assertEqual(ya, 20 - vector.PAD)
        self.assertIsNone(vector.render({"kind": "text", "content": "   "}))

    def test_alignment_and_wrapping(self):
        base = {"kind": "text", "content": "Un texte assez long pour passer à la ligne", "size": 30, "width": 200}
        wrapped = vector.render(base)
        self.assertLessEqual(wrapped[2].shape[1], 200 + 2 * vector.PAD + 1)
        self.assertGreater(wrapped[2].shape[0], 60)                                                     # plusieurs lignes
        two = {"kind": "text", "content": "Court\nUne ligne bien plus longue", "size": 30, "width": 400}
        bounds = {}
        for align in ("left", "right"):
            x, y, rgba = vector.render(dict(two, align=align))
            first_line = rgba[:rgba.shape[0] // 2]
            bounds[align] = alpha_bounds(first_line)
        self.assertLess(bounds["left"][0], 6)                                                           # collé à gauche
        self.assertGreater(bounds["right"][0], 100)                                                     # poussé à droite

    def test_shapes_known_pixels(self):
        x, y, rect = vector.render({"kind": "shape", "shape": "rect", "x": 10, "y": 5, "w": 20, "h": 10,
                                    "fill": [0, 128, 255, 255], "stroke": None})
        self.assertEqual((x + 2, y + 2), (10, 5))
        self.assertEqual(tuple(rect[5, 5]), (0, 128, 255, 255))
        self.assertEqual(int((rect[..., 3] > 0).sum()), 20 * 10)
        x, y, circle = vector.render({"kind": "shape", "shape": "ellipse", "x": 0, "y": 0, "w": 40, "h": 40,
                                      "fill": [255, 255, 255, 255]})
        self.assertAlmostEqual(float(circle[..., 3].sum() / 255.0), np.pi * 400, delta=25)
        x, y, line = vector.render({"kind": "shape", "shape": "line", "x": 0, "y": 0, "x1": 30, "y1": 0,
                                    "stroke": [0, 0, 0, 255], "stroke_width": 4})
        self.assertGreater(line.shape[1], 30)
        self.assertEqual(int(line[line.shape[0] // 2, line.shape[1] // 2, 3]), 255)
        _x, _y, outline = vector.render({"kind": "shape", "shape": "rect", "x": 0, "y": 0, "w": 30, "h": 30,
                                         "fill": None, "stroke": [255, 0, 0, 255], "stroke_width": 4})
        centre = outline[outline.shape[0] // 2, outline.shape[1] // 2]
        self.assertEqual(int(centre[3]), 0)                                                             # pas de remplissage
        self.assertIsNone(vector.render({"kind": "shape", "shape": "line", "x": 0, "y": 0, "x1": 5, "y1": 5,
                                         "stroke": None}))

    def test_source_survives_container_roundtrip_without_rerendering(self):
        from fm_photoshop import model as M
        doc = M.new_document(200, 100, background=None)
        layer = doc.layers[0]
        vector.apply_source(layer, {"kind": "text", "content": "Salut é", "x": 10, "y": 10, "size": 36})
        back = container.loads(container.dumps(doc))
        again = back.layers[0]
        self.assertEqual(again.source["content"], "Salut é")
        self.assertTrue(np.array_equal(again.pix.data, layer.pix.data))


class ToolsTest(PsCase):
    def fill_text_dialog(self, text, size=40, accept=True):
        def go():
            for widget in QApplication.topLevelWidgets():
                if isinstance(widget, TextDialog) and widget.isVisible():
                    widget.content.setPlainText(text)
                    widget.size.setValue(size)
                    widget.accept() if accept else widget.reject()
        QTimer.singleShot(60, go)

    def test_text_tool_creates_edits_and_undoes(self):
        _item, std = self.editor(200, 100, background="Blanc")
        canvas, s = std.canvas, std.session
        s.fg = (200, 0, 0)
        s.tool = "text"
        self.fill_text_dialog("Bonjour")
        self.click(canvas, 20, 20)
        self.assertEqual(len(s.doc.layers), 2)
        layer = s.layer()
        self.assertEqual((layer.name, layer.source["kind"], layer.source["color"][:3]), ("Bonjour", "text", [200, 0, 0]))
        shown = C.flatten_u8(s.doc)
        self.assertTrue(((shown[..., 0] == 200) & (shown[..., 1] == 0)).any())                         # rendu dans la composition
        # modifier : clic sur le calque de texte avec l'outil Texte
        self.fill_text_dialog("Au revoir", 60)
        self.click(canvas, 20, 20)
        self.assertEqual((layer.source["content"], layer.source["size"], layer.name), ("Au revoir", 60, "Au revoir"))
        self.assertEqual(s.history.labels()[0], "Modifier le texte")
        s.undo()
        self.assertEqual((layer.source["content"], layer.name), ("Bonjour", "Bonjour"))
        s.redo()
        self.assertEqual(layer.source["content"], "Au revoir")
        s.undo(); s.undo()
        self.assertEqual(len(s.doc.layers), 1)
        # annuler la fenêtre ne laisse rien
        self.fill_text_dialog("Fantôme", accept=False)
        self.click(canvas, 30, 30)
        self.assertEqual(len(s.doc.layers), 1)
        self.assertEqual(len(s.history.done), 0)

    def test_painting_on_text_is_refused_until_rasterized(self):
        _item, std = self.editor(120, 80)
        canvas, s = std.canvas, std.session
        layer = std.canvas.actions.add_text({"content": "Hop", "x": 10, "y": 10, "size": 40})
        with self.assertRaises(ValueError):
            B.Stroke(layer, "pixels", B.Brush(), s.doc.rect())
        a = canvas.actions
        self.assertEqual(a.fill_foreground(), a.REFUSED)
        self.assertEqual(a.apply_effect("invert"), a.REFUSED)
        self.assertEqual(a.transform_layer(((1, 0, 5), (0, 1, 0))), a.REFUSED)
        a.rasterize()
        self.assertIsNone(layer.source)
        stroke = B.Stroke(layer, "pixels", B.Brush(size=4, hardness=1.0), s.doc.rect())
        self.assertIsNotNone(stroke)
        s.undo()
        self.assertIsNotNone(layer.source)                                                              # conversion annulable

    def test_moving_a_text_layer_moves_its_source(self):
        _item, std = self.editor(200, 100)
        s = std.session
        layer = std.canvas.actions.add_text({"content": "Move", "x": 10, "y": 10, "size": 30})
        before = (layer.pix.x, layer.pix.y)
        cmd = ops.translate_layer(layer, 30, 12)
        self.assertEqual((layer.source["x"], layer.source["y"]), (40, 22))
        self.assertEqual((layer.pix.x, layer.pix.y), (before[0] + 30, before[1] + 12))
        cmd.undo()
        self.assertEqual((layer.source["x"], layer.source["y"]), (10, 10))
        ops.translate_layer(layer, 30, 12)
        std.canvas.actions.edit_source(layer, dict(layer.source, size=31), "Modifier le texte")
        self.assertEqual(layer.pix.x, vector.render(layer.source)[0])                                   # reste à la nouvelle place

    def test_shape_tools_and_dialog(self):
        _item, std = self.editor(120, 80)
        canvas, s = std.canvas, std.session
        s.fg, s.bg = (0, 0, 255), (255, 0, 0)
        s.tool = "shape_rect"
        self.drag(canvas, [self.at(canvas, 20, 20), self.at(canvas, 60, 50)])
        layer = s.layer()
        self.assertEqual((layer.name, layer.source["fill"][:3], layer.source["w"]), ("Rectangle", [0, 0, 255], 40.0))
        self.assertEqual(tuple(C.flatten_u8(s.doc, (30, 30, 31, 31))[0, 0]), (0, 0, 255, 255))
        s.tool = "shape_ellipse"
        self.drag(canvas, [self.at(canvas, 70, 10), self.at(canvas, 110, 40)])
        self.assertEqual(s.layer().source["shape"], "ellipse")
        s.tool = "shape_line"
        self.drag(canvas, [self.at(canvas, 5, 70), self.at(canvas, 100, 70)])
        self.assertEqual(s.layer().source["shape"], "line")
        self.assertEqual(len(s.doc.layers), 4)
        for _ in range(3):
            s.undo()
        self.assertEqual(len(s.doc.layers), 1)
        for _ in range(3):
            s.redo()
        rect = s.doc.layers[1]
        s.select_layer(rect)
        dialog = ShapeDialog(s, canvas.actions, rect, std)
        dialog.stroke_on.setChecked(True)
        dialog.width_box.setValue(6)
        dialog.radius.setValue(8)
        dialog.accept()
        self.assertEqual((rect.source["stroke_width"], rect.source["radius"], rect.source["stroke"][:3]),
                         (6.0, 8.0, [0, 0, 0]))
        s.undo()
        self.assertIsNone(rect.source["stroke"])

    def test_text_layer_saved_in_board_and_reopened(self):
        item, std = self.editor(160, 80)
        s = std.session
        layer = std.canvas.actions.add_text({"content": "Persistant", "x": 8, "y": 8, "size": 32,
                                             "color": [10, 20, 30, 255]})
        expect = layer.pix.data.copy()
        std.close_pane()
        settle()
        self.pane.save()
        self.pane._autosave.stop()
        S._REGISTRY.clear()
        pane2 = self.make_pane(self.path)
        loaded = [i for i in pane2.scene.board_items() if isinstance(i, PsItem)][0].session
        text = loaded.doc.layers[-1]
        self.assertEqual((text.source["content"], text.source["color"][:3]), ("Persistant", [10, 20, 30]))
        self.assertTrue(np.array_equal(text.pix.data, expect))


if __name__ == "__main__":
    unittest.main()
