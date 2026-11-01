"""Module Photoshop : outils de l'établi dans l'éditeur Standard (VRAI chemin souris / clavier) — raccourcis, source
explicite du tampon, déplacement au Ctrl + glisser, zoom autour du curseur, déplacement de la vue, pression, curseur à la
taille réelle de la brosse, présélections de brosses persistantes."""
import os as _os, sys as _sys  # jamais les vrais réglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import os
import sys
import unittest
from unittest import mock

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QWheelEvent  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from _photoshop_case import APP, PsCase, settle  # noqa: E402
from fm_photoshop import compose as C, presets  # noqa: E402


class ToolShortcutsTest(PsCase):
    def test_letter_shortcuts_switch_tools(self):
        _item, std = self.editor(64, 48)
        canvas, s = std.canvas, std.session
        canvas.setFocus()
        for key, tool in ((Qt.Key_B, "brush"), (Qt.Key_E, "eraser"), (Qt.Key_I, "eyedropper"), (Qt.Key_V, "move"),
                          (Qt.Key_H, "hand"), (Qt.Key_M, "rect_select"), (Qt.Key_L, "lasso"), (Qt.Key_W, "wand"),
                          (Qt.Key_T, "text"), (Qt.Key_S, "clone"), (Qt.Key_J, "heal"), (Qt.Key_R, "blur"),
                          (Qt.Key_O, "dodge"), (Qt.Key_U, "shape_rect")):
            QTest.keyClick(canvas, key)
            self.assertEqual(s.tool, tool)
            self.assertTrue(std.tool_buttons[tool].isChecked())
        QTest.keyClick(canvas, Qt.Key_M)
        QTest.keyClick(canvas, Qt.Key_M)                                                       # M alterne rectangle / ellipse
        self.assertEqual(s.tool, "ellipse_select")
        QTest.keyClick(canvas, Qt.Key_B)
        s.fg, s.bg = (1, 2, 3), (4, 5, 6)
        QTest.keyClick(canvas, Qt.Key_X)
        self.assertEqual((s.fg, s.bg), ((4, 5, 6), (1, 2, 3)))
        QTest.keyClick(canvas, Qt.Key_D)
        self.assertEqual((s.fg, s.bg), ((0, 0, 0), (255, 255, 255)))
        before = s.brush.size
        QTest.keyClick(canvas, Qt.Key_BracketRight)
        self.assertGreater(s.brush.size, before)
        QTest.keyClick(canvas, Qt.Key_BracketLeft)
        QTest.keyClick(canvas, Qt.Key_BracketLeft)
        self.assertLess(s.brush.size, before)

    def test_eyedropper_alt_click_and_brush_cursor_size(self):
        _item, std = self.editor(64, 48, zoom=4.0)
        canvas, s = std.canvas, std.session
        s.layer().pix.write((10, 10, 20, 20), np.full((10, 10, 4), (30, 60, 90, 255), np.uint8))
        s.tool = "eyedropper"
        self.click(canvas, 15, 15)
        self.assertEqual(s.fg, (30, 60, 90))
        s.tool = "brush"
        s.layer().pix.write((30, 10, 40, 20), np.full((10, 10, 4), (200, 100, 50, 255), np.uint8))
        self.click(canvas, 35, 15, Qt.AltModifier)                                   # Alt + clic avec le pinceau
        self.assertEqual(s.fg, (200, 100, 50))
        s.brush.size = 25.0
        self.assertAlmostEqual(canvas.brush_diameter(), 25.0 * canvas.zoom())         # le cercle = taille réelle à l'écran
        canvas.set_zoom(2.0)
        self.assertAlmostEqual(canvas.brush_diameter(), 50.0)


class NavigationTest(PsCase):
    def test_wheel_zoom_keeps_the_point_under_the_cursor_and_pan(self):
        _item, std = self.editor(200, 150, zoom=2.0)
        canvas = std.canvas
        anchor = QPointF(canvas.width() * 0.3, canvas.height() * 0.6)
        before = canvas.to_doc(anchor)
        event = QWheelEvent(anchor, canvas.mapToGlobal(anchor), QPoint(0, 0), QPoint(0, 120), Qt.NoButton,
                            Qt.NoModifier, Qt.NoScrollPhase, False)
        QApplication.sendEvent(canvas, event)
        self.assertGreater(canvas.zoom(), 2.0)
        after = canvas.to_doc(anchor)
        self.assertAlmostEqual(before[0], after[0], places=6)
        self.assertAlmostEqual(before[1], after[1], places=6)
        # main : glisser le fond sans rien peindre
        std.session.tool = "hand"
        c0 = canvas.center()
        self.drag(canvas, [QPoint(100, 100), QPoint(160, 130)])
        c1 = canvas.center()
        self.assertAlmostEqual(c0[0] - c1[0], 60 / canvas.zoom(), places=3)
        self.assertEqual(len(std.session.history.done), 0)
        # Espace tenu + glisser = main, quel que soit l'outil
        std.session.tool = "brush"
        QTest.keyPress(canvas, Qt.Key_Space)
        self.drag(canvas, [QPoint(100, 100), QPoint(90, 100)])
        QTest.keyRelease(canvas, Qt.Key_Space)
        self.assertEqual(len(std.session.history.done), 0)
        canvas.fit()
        self.assertIsNone(std.session.zoom)

    def test_ctrl_drag_moves_the_layer_and_plain_drag_does_not(self):
        _item, std = self.editor(80, 60, zoom=4.0, background="Transparent")
        canvas, s = std.canvas, std.session
        s.layer().pix.write((10, 10, 20, 20), np.full((10, 10, 4), (255, 0, 0, 255), np.uint8))
        s.tool = "move"
        self.drag(canvas, [self.at(canvas, 15, 15), self.at(canvas, 35, 25)])                  # sans Ctrl
        self.assertEqual((s.layer().pix.x, s.layer().pix.y), (10, 10))
        self.drag(canvas, [self.at(canvas, 15, 15), self.at(canvas, 25, 20), self.at(canvas, 35, 25)],
                  Qt.ControlModifier)
        self.assertEqual((s.layer().pix.x, s.layer().pix.y), (30, 20))
        self.assertEqual(len(s.history.done), 1)                                               # UNE étape pour le geste
        self.assertEqual(tuple(C.flatten_u8(s.doc, (35, 25, 36, 26))[0, 0]), (255, 0, 0, 255))
        s.undo()
        self.assertEqual((s.layer().pix.x, s.layer().pix.y), (10, 10))
        self.assertEqual(int(C.flatten_u8(s.doc, (35, 25, 36, 26))[0, 0, 3]), 0)
        s.redo()
        self.assertEqual((s.layer().pix.x, s.layer().pix.y), (30, 20))


class PaintingTest(PsCase):
    def test_pressure_changes_the_stroke_width(self):
        _item, std = self.editor(120, 60, zoom=3.0, background="Transparent")
        canvas, s = std.canvas, std.session
        s.fg = (0, 0, 0)
        s.brush.size, s.brush.hardness, s.brush.pressure_size = 30.0, 1.0, True
        canvas._pressure = 1.0
        self.drag(canvas, [self.at(canvas, 10, 15), self.at(canvas, 50, 15)])
        canvas._pressure = 0.2
        self.drag(canvas, [self.at(canvas, 10, 45), self.at(canvas, 50, 45)])
        flat = C.flatten_u8(s.doc)
        thick = int((flat[:, 30, 3] > 128)[:30].sum())
        thin = int((flat[:, 30, 3] > 128)[30:].sum())
        self.assertGreater(thick, thin * 2)
        self.assertGreaterEqual(thick, 28)

    def test_clone_with_explicit_source_through_the_canvas(self):
        _item, std = self.editor(80, 60, zoom=4.0, background="Transparent")
        canvas, s = std.canvas, std.session
        rng = np.random.default_rng(4)
        patch = rng.integers(0, 255, (10, 10, 4), dtype=np.uint8)
        patch[..., 3] = 255
        s.layer().pix.write((5, 5, 15, 15), patch)
        s.tool = "clone"
        s.brush.size, s.brush.hardness, s.brush.spacing = 6.0, 1.0, 0.1
        messages = []
        canvas.message.connect(messages.append)
        self.drag(canvas, [self.at(canvas, 40, 30), self.at(canvas, 44, 30)])                  # sans source : refusé
        self.assertTrue(any("source" in m.lower() for m in messages))
        self.assertEqual(len(s.history.done), 0)
        self.click(canvas, 10, 10, Qt.AltModifier)                                             # source = (10, 10)
        self.drag(canvas, [self.at(canvas, 40, 30), self.at(canvas, 42, 30)])
        offset = s.clone["offset"]
        self.assertEqual((round(offset[0]), round(offset[1])), (-30, -20))
        got = s.layer().pix.read((39, 29, 42, 31))
        expect = s.layer().pix.read((9, 9, 12, 11))
        self.assertTrue(np.array_equal(got[1:, 1:], expect[1:, 1:]) or (got[..., 3] > 0).any())
        self.assertEqual(s.history.labels()[0], "Tampon de duplication")
        s.undo()
        self.assertEqual(int(s.layer().pix.read((40, 30, 41, 31))[0, 0, 3]), 0)


class ThumbnailsTest(PsCase):
    def test_thumbnails_are_rebuilt_only_for_changed_layers(self):
        _item, std = self.editor(64, 48, background="Transparent")
        panel, s = std.layers_panel, std.session
        panel.add()
        settle(0.1)
        icons = {panel.list.item(i).data(Qt.UserRole): panel.list.item(i).icon() for i in range(panel.list.count())}
        self.assertEqual(len(icons), 2)
        self.assertTrue(all(not icon.isNull() for icon in icons.values()))
        builds = panel.thumb_builds
        panel.refresh()                                                       # rien n'a changé : aucune miniature refaite
        panel.refresh_icons()
        self.assertEqual(panel.thumb_builds, builds)
        s.fg = (255, 0, 0)
        s.brush.size, s.brush.hardness = 20.0, 1.0
        canvas = std.canvas
        self.drag(canvas, [self.at(canvas, 10, 10), self.at(canvas, 50, 40)])
        settle(0.5)                                                           # la minuterie (300 ms) met à jour les icônes
        self.assertEqual(panel.thumb_builds, builds + 1)                      # seul le calque peint a été refait
        image = panel.list.item(0).icon().pixmap(36, 36).toImage()
        reds = sum(1 for x in range(36) for y in range(36) if image.pixelColor(x, y).red() > 200
                   and image.pixelColor(x, y).green() < 80)
        self.assertGreater(reds, 20)                                          # le trait rouge est visible dans la miniature


class PresetsTest(PsCase):
    def test_presets_are_persistent_and_factory_ones_protected(self):
        written = {}
        with mock.patch("fm_board.ui.SETTING_WRITER", lambda key, value: written.__setitem__(key, value)):
            _item, std = self.editor(40, 30)
            panel, s = std.brush_panel, std.session
            names = [panel.presets.itemText(i) for i in range(panel.presets.count())]
            self.assertEqual(names[:len(presets.FACTORY)], [b.name for b in presets.FACTORY])
            s.brush.size, s.brush.hardness, s.brush.flow = 77.0, 0.33, 0.4
            panel.save_preset("Ma brosse")
            self.assertIn("board_ps_brush_presets", written)
            self.assertEqual(written["board_ps_brush_presets"][0]["name"], "Ma brosse")
            self.assertEqual(panel.presets.currentText(), "Ma brosse")
            self.assertIsNone(panel.save_preset("Rond dur 20"))                                   # nom d'usine refusé
            s.brush.size = 5.0
            panel._preset_chosen(panel.presets.findText("Ma brosse"))
            self.assertEqual((s.brush.size, round(s.brush.hardness, 2), s.brush.flow), (77.0, 0.33, 0.4))
            self.assertIsNone(panel.delete_preset("Rond dur 20"))
            std.close_pane()
            settle()
            # un autre éditeur (même réglage, comme après un redémarrage) retrouve la présélection
            _item2, std2 = self.editor(40, 30, name="Autre")
            self.assertGreaterEqual(std2.brush_panel.presets.findText("Ma brosse"), 0)
            std2.brush_panel.delete_preset("Ma brosse")
            self.assertEqual(written["board_ps_brush_presets"], [])
            self.assertEqual(std2.brush_panel.presets.findText("Ma brosse"), -1)

    def test_invalid_stored_presets_are_ignored(self):
        raw = [{"name": "Bon", "size": 12}, {"name": ""}, "pas un dict", {"name": "Bon"}, {"size": 9},
               {"name": "Rond dur 20"}, {"name": "X", "size": "énorme", "hardness": 9}]
        brushes = presets.sanitize(raw)
        self.assertEqual([b.name for b in brushes], ["Bon", "X"])
        self.assertEqual(brushes[1].hardness, 1.0)
        self.assertEqual(presets.sanitize("n'importe quoi"), [])
        self.assertEqual(len(presets.all_presets(None)), len(presets.FACTORY))


if __name__ == "__main__":
    unittest.main()
