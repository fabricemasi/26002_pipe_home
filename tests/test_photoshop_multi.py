"""Module Photoshop : sélection de PLUSIEURS calques (liste, Ctrl + clic) — grouper (Ctrl+G), dupliquer, supprimer, déplacer
ensemble (Ctrl + glisser, UNE étape), refus sur calque verrouillé, annulation."""
import os as _os, sys as _sys  # jamais les vrais réglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import unittest

import numpy as np

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from _photoshop_case import PsCase, settle
from fm_photoshop import compose as C


class MultiTest(PsCase):
    def setup_layers(self):
        _item, std = self.editor(120, 80, background="Transparent")
        s, panel = std.session, std.layers_panel
        s.layer().pix.set_all(10, 10, np.full((10, 10, 4), (255, 0, 0, 255), np.uint8))
        for color, x in (((0, 255, 0), 40), ((0, 0, 255), 70)):
            panel.add()
            s.layer().pix.set_all(x, 10, np.full((10, 10, 4), color + (255,), np.uint8))
        settle(0.05)
        return std, s, panel

    def select_rows(self, panel, rows):
        panel.list.clearSelection()
        for r in rows:
            panel.list.item(r).setSelected(True)
        panel.list.setCurrentRow(rows[0])
        settle(0.02)

    def test_multi_selection_group_duplicate_delete_move(self):
        std, s, panel = self.setup_layers()
        self.assertEqual(panel.list.count(), 3)
        self.select_rows(panel, [0, 1])                                  # les deux calques du haut
        names = [l.name for l in s.selected_layers()]
        self.assertEqual(len(names), 2)
        # déplacer ENSEMBLE : une seule étape
        canvas = std.canvas
        s.tool = "move"
        n = len(s.history.done)
        canvas.begin_move(50, 15, True)
        canvas.extend_move(60, 25)
        canvas.end_move()
        self.assertEqual(len(s.history.done), n + 1)
        top, mid, bottom = s.doc.layers[2], s.doc.layers[1], s.doc.layers[0]
        self.assertEqual((top.pix.x, top.pix.y, mid.pix.x, mid.pix.y), (80, 20, 50, 20))
        self.assertEqual((bottom.pix.x, bottom.pix.y), (10, 10))             # le troisième n'a pas bougé
        s.undo()
        self.assertEqual((top.pix.x, mid.pix.x), (70, 40))
        # grouper (bouton « Groupe » avec plusieurs sélectionnés)
        self.select_rows(panel, [0, 1])
        panel.add_group()
        self.assertEqual(len(s.doc.layers), 2)
        group = s.doc.layers[1]
        self.assertTrue(group.is_group() and len(group.children) == 2)
        before = C.flatten_u8(s.doc)
        s.undo()
        self.assertEqual(len(s.doc.layers), 3)
        s.redo()
        self.assertTrue(np.array_equal(C.flatten_u8(s.doc), before))
        s.undo()
        # dupliquer
        self.select_rows(panel, [0, 1])
        panel.duplicate()
        self.assertEqual(len(s.doc.layers), 5)
        s.undo()
        self.assertEqual(len(s.doc.layers), 3)
        # supprimer plusieurs : une étape ; le dernier calque est protégé
        self.select_rows(panel, [0, 1])
        panel.remove()
        self.assertEqual(len(s.doc.layers), 1)
        s.undo()
        self.assertEqual(len(s.doc.layers), 3)
        self.select_rows(panel, [0, 1, 2])
        panel.remove()
        self.assertEqual(len(s.doc.layers), 1)                              # au moins un calque reste
        s.undo()

    def test_ctrl_g_locked_and_single_selection(self):
        std, s, panel = self.setup_layers()
        canvas = std.canvas
        messages = []
        canvas.message.connect(messages.append)
        s.select_layer(s.doc.layers[0])
        self.assertIn("deux calques", canvas.actions.group_selected())
        self.select_rows(panel, [0, 2])
        canvas.setFocus()
        QTest.keyClick(canvas, Qt.Key_G, Qt.ControlModifier)
        self.assertEqual(len(s.doc.layers), 2)
        # déplacement refusé si un calque sélectionné est verrouillé
        self.select_rows(panel, [0, 1])
        s.selected_layers()[0].locked = True
        canvas.begin_move(50, 15, True)
        self.assertIsNone(canvas._move)
        s.selected_layers()[0].locked = False


if __name__ == "__main__":
    unittest.main()


class ReorderTest(PsCase):
    def test_ctrl_drag_in_the_layer_list_reorders_in_one_step(self):
        _item, std = self.editor(60, 40)
        s, panel = std.session, std.layers_panel
        panel.add(); panel.add()
        settle(0.05)
        names = [l.name for l in s.doc.layers]                      # bas -> haut
        self.assertEqual(panel.list.count(), 3)
        top_item = panel.list.item(0)                                # ligne du haut = dernier de la pile
        bottom_item = panel.list.item(2)
        from PySide6.QtCore import QPoint
        pos = lambda item: panel.list.visualItemRect(item).center()
        n = len(s.history.done)
        QTest.mousePress(panel.list.viewport(), Qt.LeftButton, Qt.NoModifier, pos(top_item))      # sans Ctrl : sélection seule
        QTest.mouseRelease(panel.list.viewport(), Qt.LeftButton, Qt.NoModifier, pos(bottom_item))
        self.assertEqual([l.name for l in s.doc.layers], names)
        self.assertEqual(len(s.history.done), n)
        QTest.mousePress(panel.list.viewport(), Qt.LeftButton, Qt.ControlModifier, pos(top_item))
        QTest.mouseRelease(panel.list.viewport(), Qt.LeftButton, Qt.ControlModifier, pos(bottom_item))
        self.release_modifiers(panel.list.viewport())
        self.assertEqual([l.name for l in s.doc.layers], [names[2], names[0], names[1]])
        self.assertEqual(len(s.history.done), n + 1)
        s.undo()
        self.assertEqual([l.name for l in s.doc.layers], names)
        s.redo()
        self.assertEqual(s.doc.layers[0].name, names[2])
