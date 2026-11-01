"""Module Photoshop — PARCOURS DE BOUT EN BOUT (VRAI chemin) : Board -> document -> dessin -> calques -> opacité ->
sélection -> masque peint -> transformation -> réglage -> annuler / rétablir -> retour au Board -> enregistrement ->
fermeture -> réouverture -> tout retrouvé -> export PNG / TIFF relus par OpenImageIO -> pixels ET alpha comparés.
Plus le diagnostic des documents."""
import os as _os, sys as _sys  # jamais les vrais réglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import os
import sys
import unittest
from unittest import mock

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from _photoshop_case import PsCase, settle  # noqa: E402
from fm_board import serialization  # noqa: E402
from fm_photoshop import compose as C, diagnostics, dialogs, model as M, session as S, transform as T  # noqa: E402
from fm_photoshop.board_item import PsItem  # noqa: E402


class EndToEndTest(PsCase):
    def test_complete_user_journey(self):
        item = self.create_via_ui(96, 64, "Parcours", background="Transparent")
        std = self.open_standard_by_double_click(item)
        canvas, s, panel = std.canvas, std.session, std.layers_panel
        canvas.set_zoom(4.0)
        s.center = (48.0, 32.0)
        settle()
        start = C.flatten_u8(s.doc)
        s.brush.size, s.brush.hardness, s.brush.spacing = 8.0, 1.0, 0.1
        # 1. dessiner
        s.tool, s.fg = "brush", (255, 0, 0)
        self.drag(canvas, [self.at(canvas, 10, 12), self.at(canvas, 80, 12)])
        # 2. plusieurs calques
        panel.add()
        s.fg = (0, 0, 255)
        self.drag(canvas, [self.at(canvas, 10, 24), self.at(canvas, 80, 24)])
        panel.add()
        s.fg = (0, 160, 0)
        self.drag(canvas, [self.at(canvas, 10, 36), self.at(canvas, 80, 36)])
        self.assertEqual(len(s.doc.layers), 3)
        # 3. opacité
        s.select_layer(s.doc.layers[1])
        panel.opacity.field.setValue(50)
        panel.commit_live()
        self.assertAlmostEqual(s.doc.layers[1].opacity, 0.5)
        # 4. sélection, puis 5. masque créé et peint (la sélection limite la peinture)
        s.select_layer(s.doc.layers[2])
        s.tool = "rect_select"
        self.drag(canvas, [self.at(canvas, 40, 28), self.at(canvas, 70, 44)])
        self.assertEqual(s.selection.bounds(), (40, 28, 70, 44))
        panel.mask_add()
        panel.set_target("mask")
        s.tool, s.fg = "brush", (0, 0, 0)
        s.brush.size = 20.0
        self.drag(canvas, [self.at(canvas, 30, 36), self.at(canvas, 80, 36)])
        mask = s.doc.layers[2].mask.plane
        self.assertEqual(int(mask.read((55, 36, 56, 37))[0, 0, 0]), 0)                         # masqué dans la sélection
        self.assertEqual(int(mask.read((20, 36, 21, 37))[0, 0, 0]), 255)                       # intact hors sélection
        panel.set_target("pixels")
        canvas.actions.deselect()
        # 6. transformer un calque
        s.select_layer(s.doc.layers[0])
        canvas.actions.transform_layer(T.translation(5, 3), "nearest", "Transformation")
        # 7. appliquer un réglage (avec fenêtre d'aperçu)
        s.select_layer(s.doc.layers[1])
        dialog = dialogs.EffectDialog(s, "hue_saturation", std)
        dialog.fields["hue"][0].setValue(90)
        dialog.settle()
        dialog.accept()
        final = C.flatten_u8(s.doc)
        self.assertFalse(np.array_equal(final, start))
        # 8. annuler / rétablir tout l'historique (au clavier pour la première étape)
        steps = len(s.history.done)
        self.assertGreaterEqual(steps, 9)
        QTest.keyClick(canvas, Qt.Key_Z, Qt.ControlModifier)
        self.assertFalse(np.array_equal(C.flatten_u8(s.doc), final))
        QTest.keyClick(canvas, Qt.Key_Y, Qt.ControlModifier)
        self.assertTrue(np.array_equal(C.flatten_u8(s.doc), final))
        while s.history.can_undo():
            s.undo()
        self.assertTrue(np.array_equal(C.flatten_u8(s.doc), start))
        self.assertEqual(len(s.doc.layers), 1)
        while s.history.can_redo():
            s.redo()
        self.assertTrue(np.array_equal(C.flatten_u8(s.doc), final))
        names = [l.name for l in s.doc.layers]
        # 9. retour au Board, enregistrement, fermeture, réouverture
        std.back.click()
        settle()
        self.pane.save()
        self.pane._autosave.stop()
        S._REGISTRY.clear()
        pane2 = self.make_pane(self.path)
        loaded = [i for i in pane2.scene.board_items() if isinstance(i, PsItem)][0].session
        self.assertIsNone(loaded.error)
        self.assertEqual([l.name for l in loaded.doc.layers], names)
        self.assertAlmostEqual(loaded.doc.layers[1].opacity, 0.5)
        self.assertIsNotNone(loaded.doc.layers[2].mask)
        self.assertEqual(int(loaded.doc.layers[2].mask.plane.read((55, 36, 56, 37))[0, 0, 0]), 0)
        self.assertTrue(np.array_equal(C.flatten_u8(loaded.doc), final))
        # 10. exports relus par une bibliothèque indépendante : pixels et alpha
        import OpenImageIO as oiio
        pane2.set_module("photoshop")
        [i for i in pane2.scene.board_items() if isinstance(i, PsItem)][0].setSelected(True)
        self.assertGreater(int((final[..., 3] == 0).sum()), 100)                               # il y a de la vraie transparence
        for name in ("parcours.png", "parcours.tif"):
            target = self.tmp / name
            pane2.photoshop.export(str(target), wait=True)
            buf = oiio.ImageBuf(str(target))
            self.assertFalse(buf.has_error, buf.geterror())
            read = np.array(buf.get_pixels(oiio.UINT8), np.uint8).reshape(64, 96, -1)
            self.assertEqual(read.shape[2], 4, name)
            self.assertTrue(np.array_equal(read[..., 3], final[..., 3]), name + " : alpha")
            opaque = final[..., 3] == 255
            self.assertTrue(np.array_equal(read[opaque][:, :3], final[opaque][:, :3]), name + " : couleurs")


class DiagnosticsTest(unittest.TestCase):
    def test_report_lists_the_real_problems(self):
        doc = M.new_document(40, 30, background=None)
        empty = doc.layers[0]
        outside = M.Layer("Dehors")
        outside.pix.set_all(500, 500, np.full((4, 4, 4), 255, np.uint8))
        clipped = M.Layer("Orphelin")
        clipped.clip = True
        hidden = M.Layer("Caché")
        hidden.visible = False
        hidden.pix.set_all(0, 0, np.full((2, 2, 4), 255, np.uint8))
        masked = M.Layer("Masqué")
        masked.pix.set_all(0, 0, np.full((2, 2, 4), 255, np.uint8))
        masked.mask = M.Mask(enabled=False)
        unknown = M.Layer("Futur")
        unknown.pix.set_all(0, 0, np.full((2, 2, 4), 255, np.uint8))
        unknown.extra["blend_unknown"] = "vivid_light"
        doc.layers = [clipped, empty, outside, hidden, masked, unknown]
        session = S.Session(doc)
        session.error = "Ressource du document absente du dossier du Board."
        text = diagnostics.report(doc, session)
        for expected in ("absente du dossier", "« Calque 1 » est vide", "« Dehors » est entièrement hors du document",
                         "« Orphelin » est écrêté", "1 calque(s) masqué(s)", "masque de « Masqué » est désactivé",
                         "vivid_light", "40 × 30", "aucun (sRVB supposé)", "8 bits"):
            self.assertIn(expected, text)
        self.assertEqual(diagnostics.diagnose(doc, session)[0][0], "erreur")


if __name__ == "__main__":
    unittest.main()
