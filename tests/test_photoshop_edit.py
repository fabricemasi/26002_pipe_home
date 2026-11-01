"""Module Photoshop, édition dans l'éditeur Standard (VRAI chemin, souris et clavier sur l'établi) : outils de sélection
(rectangle, ellipse, lasso, lasso polygonal, baguette) et modes de combinaison, sélection respectée par le pinceau,
copier / couper / coller, calque via copier / couper, remplir / effacer, menus, fenêtres de réglages avec aperçu
(périmé rejeté, annulation exacte, une seule étape), transformation numérique, taille de l'image et de la zone."""
import os as _os, sys as _sys  # jamais les vrais réglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QPoint, QTimer, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from _photoshop_case import APP, PsCase, settle  # noqa: E402
from fm_photoshop import adjust, compose as C, dialogs  # noqa: E402


def flat(session):
    return C.flatten_u8(session.doc)


class SelectionToolsTest(PsCase):
    def test_rectangle_ellipse_modes_and_deselect(self):
        _item, std = self.editor(64, 48)
        canvas, s = std.canvas, std.session
        s.tool = "rect_select"
        self.drag(canvas, [self.at(canvas, 10, 10), self.at(canvas, 30, 30)])
        self.assertEqual(s.selection.bounds(), (10, 10, 30, 30))
        self.drag(canvas, [self.at(canvas, 40, 5), self.at(canvas, 50, 15)], Qt.ShiftModifier)          # ajouter
        self.assertEqual(s.selection.bounds(), (10, 5, 50, 30))
        self.drag(canvas, [self.at(canvas, 0, 0), self.at(canvas, 20, 20)], Qt.AltModifier)            # soustraire
        self.assertEqual(float(s.selection.coverage((10, 10, 20, 20)).sum()), 0.0)
        self.assertEqual(float(s.selection.coverage((25, 25, 26, 26)).sum()), 1.0)
        self.drag(canvas, [self.at(canvas, 5, 5), self.at(canvas, 45, 45)], Qt.ShiftModifier | Qt.AltModifier)  # ∩
        self.assertLessEqual(s.selection.bounds()[2], 45)
        self.click(canvas, 60, 40)                                                                      # clic = désélectionne
        self.assertIsNone(s.selection)
        s.tool = "ellipse_select"
        self.drag(canvas, [self.at(canvas, 10, 8), self.at(canvas, 50, 40)])
        cover = s.selection.coverage((0, 0, 64, 48))
        self.assertEqual(float(cover[24, 30]), 1.0)
        self.assertEqual(float(cover[8, 10]), 0.0)                                                      # coin hors ellipse
        self.assertAlmostEqual(float(cover.sum()), np.pi * 20 * 16, delta=12)

    def test_lasso_polygonal_and_wand(self):
        _item, std = self.editor(64, 48)
        canvas, s = std.canvas, std.session
        s.tool = "lasso"
        self.drag(canvas, [self.at(canvas, 10, 10), self.at(canvas, 40, 10), self.at(canvas, 40, 30),
                           self.at(canvas, 10, 30)])
        self.assertAlmostEqual(float(s.selection.coverage((0, 0, 64, 48)).sum()), 30 * 20, delta=40)
        self.actions = canvas.actions
        self.actions.deselect()
        s.tool = "poly_lasso"
        for x, y in ((5, 5), (25, 5), (25, 25)):
            self.click(canvas, x, y)
        QTest.keyClick(canvas, Qt.Key_Return)                                                           # ferme le polygone
        self.assertAlmostEqual(float(s.selection.coverage((0, 0, 64, 48)).sum()), 200.0, delta=20)       # triangle 20×20/2
        # baguette : rectangle rouge sur fond blanc, tolérance et contiguïté
        self.actions.deselect()
        s.layer().pix.write((10, 10, 20, 20), np.full((10, 10, 4), (255, 0, 0, 255), np.uint8))
        s.layer().pix.write((40, 10, 50, 20), np.full((10, 10, 4), (255, 0, 0, 255), np.uint8))
        s.tool = "wand"
        s.options.update(tolerance=10, contiguous=True)
        self.click(canvas, 15, 15)
        self.assertGreater(float(s.selection.coverage((10, 10, 20, 20)).min()), 0.4)                    # bords adoucis
        self.assertEqual(float(s.selection.coverage((40, 10, 50, 20)).sum()), 0.0)
        s.options["contiguous"] = False
        self.click(canvas, 15, 15)
        self.assertGreater(float(s.selection.coverage((40, 10, 50, 20)).sum()), 80.0)

    def test_selection_is_a_history_step_and_limits_the_brush(self):
        _item, std = self.editor(64, 48)
        canvas, s = std.canvas, std.session
        s.tool = "rect_select"
        self.drag(canvas, [self.at(canvas, 20, 10), self.at(canvas, 44, 38)])
        s.undo()
        self.assertIsNone(s.selection)
        s.redo()
        self.assertEqual(s.selection.bounds(), (20, 10, 44, 38))
        s.tool, s.fg = "brush", (255, 0, 0)
        s.brush.size, s.brush.hardness = 10.0, 1.0
        self.drag(canvas, [self.at(canvas, 4, 24), self.at(canvas, 60, 24)])
        row = flat(s)[24]
        self.assertEqual(tuple(row[10]), (255, 255, 255, 255))                                          # hors sélection
        self.assertEqual(tuple(row[30]), (255, 0, 0, 255))                                              # dedans
        self.assertEqual(tuple(row[55]), (255, 255, 255, 255))


class EditActionsTest(PsCase):
    def test_keyboard_copy_paste_layer_via_copy_cut_fill_delete(self):
        _item, std = self.editor(64, 48)
        canvas, s = std.canvas, std.session
        a = canvas.actions
        s.layer().pix.write((10, 10, 20, 20), np.full((10, 10, 4), (0, 0, 255, 255), np.uint8))
        s.tool = "rect_select"
        self.drag(canvas, [self.at(canvas, 8, 8), self.at(canvas, 22, 22)])
        QTest.keyClick(canvas, Qt.Key_C, Qt.ControlModifier)
        QTest.keyClick(canvas, Qt.Key_V, Qt.ControlModifier)                                            # collé : nouveau calque
        self.assertEqual(len(s.doc.layers), 2)
        self.assertEqual(s.layer().name, "Calque collé")
        s.undo()
        self.assertEqual(len(s.doc.layers), 1)
        QTest.keyClick(canvas, Qt.Key_J, Qt.ControlModifier)                                            # via copier
        self.assertEqual(len(s.doc.layers), 2)
        self.assertEqual(tuple(s.layer().pix.read((12, 12, 13, 13))[0, 0]), (0, 0, 255, 255))
        before = flat(s)
        QTest.keyClick(canvas, Qt.Key_J, Qt.ControlModifier | Qt.ShiftModifier)                         # via couper
        self.assertEqual(len(s.doc.layers), 3)
        self.assertEqual(s.history.labels()[0], "Calque via couper")
        self.assertEqual(tuple(s.doc.layers[1].pix.read((12, 12, 13, 13))[0, 0])[3], 0)                 # source vidée
        s.undo()                                                                                       # UNE étape
        self.assertEqual(len(s.doc.layers), 2)
        self.assertEqual(tuple(s.doc.layers[1].pix.read((12, 12, 13, 13))[0, 0]), (0, 0, 255, 255))
        s.select_layer(s.doc.layers[0])
        s.fg = (10, 200, 30)
        QTest.keyClick(canvas, Qt.Key_Backspace, Qt.AltModifier)                                        # remplir
        self.assertEqual(tuple(s.layer().pix.read((15, 15, 16, 16))[0, 0]), (10, 200, 30, 255))
        self.assertEqual(tuple(s.layer().pix.read((2, 2, 3, 3))[0, 0]), (255, 255, 255, 255))           # hors sélection
        QTest.keyClick(canvas, Qt.Key_Delete)
        self.assertEqual(int(s.layer().pix.read((15, 15, 16, 16))[0, 0, 3]), 0)
        for _ in range(4):
            QTest.keyClick(canvas, Qt.Key_Z, Qt.ControlModifier)
        QTest.keyClick(canvas, Qt.Key_A, Qt.ControlModifier)
        QTest.keyClick(canvas, Qt.Key_I, Qt.ControlModifier | Qt.ShiftModifier)                         # inverser tout = vide
        self.assertTrue(s.selection is None or s.selection.is_empty())
        QTest.keyClick(canvas, Qt.Key_D, Qt.ControlModifier)
        self.assertIsNone(s.selection)

    def test_crop_to_selection_and_sizes_through_menus(self):
        _item, std = self.editor(64, 48)
        canvas, s = std.canvas, std.session
        s.tool = "rect_select"
        self.drag(canvas, [self.at(canvas, 8, 8), self.at(canvas, 40, 32)])
        menu = std.menubar.menu_for("image")
        texts = [a.text().split("\t")[0] for a in menu.actions() if a.text()]
        self.assertIn("Recadrer sur la sélection", texts)
        next(a for a in menu.actions() if a.text().startswith("Recadrer")).trigger()
        settle()
        self.assertEqual((s.doc.width, s.doc.height), (32, 24))
        s.undo()
        s.undo()
        self.assertEqual((s.doc.width, s.doc.height), (64, 48))
        canvas.actions.image_size(32, 24, "bilinear")
        self.assertEqual((s.doc.width, s.doc.height, s.layer().pix.data.shape[:2]), (32, 24, (24, 32)))
        canvas.actions.canvas_size(40, 30, (0, 0))
        self.assertEqual((s.doc.width, s.doc.height), (40, 30))
        s.undo()
        s.undo()
        self.assertEqual((s.doc.width, s.doc.height), (64, 48))


class ContextAndColorRangeTest(PsCase):
    def test_context_menus_and_color_range(self):
        from PySide6.QtGui import QContextMenuEvent
        _item, std = self.editor(64, 48)
        canvas, s = std.canvas, std.session
        s.layer().pix.write((10, 10, 20, 20), np.full((10, 10, 4), (255, 0, 0, 255), np.uint8))
        s.layer().pix.write((40, 30, 50, 40), np.full((10, 10, 4), (250, 5, 5, 255), np.uint8))
        s.fg = (255, 0, 0)
        # menu de la barre : plage de couleurs (tolérance 32 : les deux rectangles rouges, contigus ou non)
        action = next(a for a in std.menubar.menu_for("selection").actions() if a.text().startswith("Plage de couleurs"))
        action.trigger()
        settle()
        self.assertEqual(float(s.selection.coverage((0, 0, 64, 48)).sum()), 200.0)
        self.assertEqual(s.history.labels()[0], "Plage de couleurs")
        # clic droit sur l'établi : menu Sélection (une sélection existe), sinon Édition
        event = QContextMenuEvent(QContextMenuEvent.Mouse, self.at(canvas, 30, 20), canvas.mapToGlobal(self.at(canvas, 30, 20)))
        QApplication.sendEvent(canvas, event)
        texts = [a.text() for a in canvas._context_menu.actions()]
        self.assertTrue(any(t.startswith("Inverser") for t in texts))
        canvas._context_menu.close()
        canvas.actions.deselect()
        QApplication.sendEvent(canvas, event)
        texts = [a.text() for a in canvas._context_menu.actions()]
        self.assertTrue(any(t.startswith("Coller") for t in texts))
        canvas._context_menu.close()
        self.assertEqual(std.layers_panel.list.contextMenuPolicy(), Qt.CustomContextMenu)
        self.assertTrue(any(a.text().startswith("Transformer") for a in std.menubar.menu_for("layer").actions()))


class DialogsTest(PsCase):
    def test_effect_dialog_preview_apply_cancel_and_stale_results(self):
        _item, std = self.editor(32, 32)
        s = std.session
        s.layer().pix.write((0, 0, 32, 32), np.full((32, 32, 4), (100, 100, 100, 255), np.uint8))
        original = s.layer().pix.read(s.doc.rect())
        # annuler : l'original est remis octet pour octet
        dialog = dialogs.EffectDialog(s, "brightness_contrast", std)
        dialog.fields["brightness"][0].setValue(50)
        dialog.settle()
        self.assertFalse(np.array_equal(s.layer().pix.read(s.doc.rect()), original))                 # aperçu visible
        dialog.reject()
        self.assertTrue(np.array_equal(s.layer().pix.read(s.doc.rect()), original))
        self.assertEqual(len(s.history.done), 0)
        # valider : UNE étape ; le curseur a bougé plusieurs fois, sans erreur cumulée
        dialog = dialogs.EffectDialog(s, "brightness_contrast", std)
        for value in (10, 80, -30, 40):
            dialog.fields["brightness"][0].setValue(value)
        dialog.settle()
        expected = adjust.run(dialog.shadow, "brightness_contrast", {"brightness": 0.4}, None, s.doc.rect())[2]
        dialog.accept()
        self.assertEqual(len(s.history.done), 1)
        self.assertTrue(np.array_equal(s.layer().pix.read(s.doc.rect()), expected))
        s.undo()
        self.assertTrue(np.array_equal(s.layer().pix.read(s.doc.rect()), original))
        # un résultat PÉRIMÉ est rejeté
        dialog = dialogs.EffectDialog(s, "invert", std)
        dialog.settle()
        applied = dialog._applied
        dialog._on_result(dialog._generation - 5, (s.doc.rect(), original, original + 1))
        self.assertIs(dialog._applied, applied)
        dialog.reject()
        self.assertTrue(np.array_equal(s.layer().pix.read(s.doc.rect()), original))

    def test_every_effect_menu_entry_opens_and_applies(self):
        _item, std = self.editor(24, 24)
        s = std.session
        s.layer().pix.write((4, 4, 20, 20), np.random.default_rng(1).integers(0, 255, (16, 16, 4), dtype=np.uint8))
        for key in ("adjust", "filter"):
            for action in std.menubar.menu_for(key).actions():
                self.assertTrue(action.text())
        for name in adjust.EFFECTS:
            dialog = dialogs.EffectDialog(s, name, std)
            dialog.settle()
            dialog.reject()
        self.assertEqual(len(s.history.done), 0)
        std.menubar.effect("invert")                                                                    # sans paramètre : direct
        self.assertEqual(s.history.labels()[0], "Négatif")

    def test_transform_dialog_numeric_and_cancel(self):
        _item, std = self.editor(40, 40)
        s = std.session
        s.layer().pix.set_all(10, 10, np.full((10, 20, 4), (255, 0, 0, 255), np.uint8))
        dialog = dialogs.TransformDialog(s, std)
        dialog.angle.setValue(90)
        dialog._render()
        data = s.layer().pix.data
        self.assertEqual(data.shape[:2], (20, 10))                                                      # tourné de 90°
        dialog.reject()
        self.assertEqual(s.layer().pix.data.shape[:2], (10, 20))
        dialog = dialogs.TransformDialog(s, std)
        dialog.dx.setValue(5)
        dialog.dy.setValue(-3)
        dialog.quality.setCurrentIndex(0)
        dialog.accept()
        self.assertEqual((s.layer().pix.x, s.layer().pix.y), (15, 7))
        s.undo()
        self.assertEqual((s.layer().pix.x, s.layer().pix.y), (10, 10))

    def test_size_dialog_and_value_dialog(self):
        _item, std = self.editor(40, 20)
        dialog = dialogs.SizeDialog(std.session.doc, False, std)
        dialog.width_field.setValue(80)
        self.assertEqual(dialog.values(), (80, 40))                                                      # proportions liées
        dialog = dialogs.SizeDialog(std.session.doc, True, std)
        dialog.width_field.setValue(60)
        self.assertEqual(dialog.values(), (60, 20))
        value = dialogs.ValueDialog("t", "l", 1, 100, 7)
        self.assertEqual(value.value(), 7)

    def test_layer_export_through_pane(self):
        _item, std = self.editor(16, 16)
        s = std.session
        s.layer().pix.write((0, 0, 16, 16), np.full((16, 16, 4), (1, 2, 3, 255), np.uint8))
        target = self.tmp / "calque.png"
        job = std.export(str(target), s.layer(), wait=True)
        self.assertTrue(job.done and job.error is None)
        self.assertEqual(job.notes, [])
        self.assertTrue(target.exists())


if __name__ == "__main__":
    unittest.main()
