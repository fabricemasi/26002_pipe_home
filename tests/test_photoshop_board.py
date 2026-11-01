"""Module Photoshop dans le Board (VRAI chemin) : icône de la barre des modules -> barre du module -> nouveau document
(fenêtre) -> élément du Board -> double-clic -> éditeur Standard -> traits à la souris, calques, masque, opacité,
annulation au clavier -> retour au Board (même session, mêmes tuiles) -> enregistrement automatique -> fermeture ->
réouverture (aussi après déplacement du dossier) -> export PNG / TIFF relus par OpenImageIO. Plusieurs documents
indépendants, Ctrl + glisser, ressource absente, écrasement évité."""
import os as _os, sys as _sys  # jamais les vrais réglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from _photoshop_case import APP, PsCase, settle  # noqa: E402
from fm_board import serialization  # noqa: E402
from fm_photoshop import compose as C, session as S  # noqa: E402
from fm_photoshop.board_item import PsItem  # noqa: E402


class BoardPathTest(PsCase):
    def test_full_user_path(self):
        item = self.create_via_ui(64, 48, "Essai")
        self.assertEqual((item.session.doc.width, item.session.doc.height), (64, 48))
        self.assertEqual(item.kind, "ps_doc")
        before_tiles = item.session.tiles.computed if hasattr(item.session, "tiles") else 0
        std = self.open_standard_by_double_click(item)
        self.assertIsNotNone(std, "le double-clic doit ouvrir l'éditeur Standard")
        self.assertIs(std.session, item.session)                       # MÊME session : rien de rechargé
        canvas = std.canvas
        canvas.set_zoom(4.0)
        canvas.session.center = (32.0, 24.0)
        settle()
        s = item.session
        s.fg = (255, 0, 0)
        s.brush.size, s.brush.hardness = 6.0, 1.0
        c = canvas.rect().center()
        a, b = QPoint(c.x() - 40, c.y()), QPoint(c.x() + 40, c.y())
        self.drag(canvas, [a, b])
        row = C.flatten_u8(s.doc)[24]
        self.assertTrue((row[26:38] == [255, 0, 0, 255]).all(), "le trait rouge est dans les pixels")
        # annuler / rétablir AU CLAVIER
        canvas.setFocus()
        QTest.keyClick(canvas, Qt.Key_Z, Qt.ControlModifier)
        self.assertTrue((C.flatten_u8(s.doc)[24, 26:38] == [255, 255, 255, 255]).all())
        QTest.keyClick(canvas, Qt.Key_Y, Qt.ControlModifier)
        self.assertTrue((C.flatten_u8(s.doc)[24, 26:38] == [255, 0, 0, 255]).all())
        # calques : nouveau calque, trait bleu, opacité, masque et peinture du masque
        panel = std.layers_panel
        panel.add()
        self.assertEqual(len(s.doc.layers), 2)
        s.fg = (0, 0, 255)
        self.drag(canvas, [QPoint(c.x(), c.y() - 30), QPoint(c.x(), c.y() + 30)])
        top = s.layer()
        self.assertEqual(int(top.pix.read((32, 24, 33, 25))[0, 0, 3]), 255)
        panel.opacity.field.setValue(50)
        panel.commit_live()
        self.assertAlmostEqual(top.opacity, 0.5)
        self.assertEqual(tuple(C.flatten_u8(s.doc, (32, 18, 33, 19))[0, 0]), (128, 128, 255, 255))
        panel.mask_add()
        panel.set_target("mask")
        s.fg = (0, 0, 0)
        self.drag(canvas, [QPoint(c.x(), c.y() - 4), QPoint(c.x(), c.y() + 4)])
        self.assertLess(int(top.mask.plane.read((32, 24, 33, 25))[0, 0, 0]), 10)       # masque noir au centre
        self.assertEqual(int(top.pix.read((32, 24, 33, 25))[0, 0, 3]), 255)            # pixels intacts
        # annuler en chaîne jusqu'au bout, puis tout rétablir
        flat_final = C.flatten_u8(s.doc)
        while s.history.can_undo():
            s.undo()
        self.assertEqual(len(s.doc.layers), 1)
        self.assertTrue((C.flatten_u8(s.doc) == 255).all())
        while s.history.can_redo():
            s.redo()
        self.assertTrue(np.array_equal(C.flatten_u8(s.doc), flat_final))
        # retour au Board : même session, mêmes tuiles, rien de recomposé
        computed = s.tiles.computed
        std.back.click()
        settle()
        self.assertIsNone(getattr(self.pane, "_photoshop_standard", None))
        self.assertIs(item.session, s)
        image = item.grab() if hasattr(item, "grab") else None
        self.assertLessEqual(s.tiles.computed - computed, 4)                      # seulement ce qui a changé
        # enregistrement, fermeture, réouverture
        self.pane.save()
        assets = list(serialization.assets_dir(self.path).glob("*.fmps"))
        self.assertEqual(len(assets), 1)
        self.pane._autosave.stop()
        S._REGISTRY.clear()
        pane2 = self.make_pane(self.path)
        again = [i for i in pane2.scene.board_items() if isinstance(i, PsItem)]
        self.assertEqual(len(again), 1)
        s2 = again[0].session
        self.assertIsNone(s2.error)
        self.assertTrue(np.array_equal(C.flatten_u8(s2.doc), flat_final))
        self.assertEqual([l.name for l in s2.doc.layers], [l.name for l in s.doc.layers])
        self.assertIsNotNone(s2.doc.layers[1].mask)
        self.assertAlmostEqual(s2.doc.layers[1].opacity, 0.5)
        # export PNG / TIFF relus par OpenImageIO (bibliothèque indépendante de l'écriture)
        import OpenImageIO as oiio
        pane2.set_module("photoshop")
        again[0].setSelected(True)
        for name in ("sortie.png", "sortie.tif"):
            target = self.tmp / name
            pane2.photoshop.export(str(target), wait=True)
            buf = oiio.ImageBuf(str(target))
            self.assertFalse(buf.has_error, buf.geterror())
            pixels = np.array(buf.get_pixels(oiio.UINT8), np.uint8).reshape(48, 64, -1)
            self.assertTrue(np.array_equal(pixels[..., :4], flat_final), name)

    def test_two_documents_are_independent_and_ctrl_drag_moves(self):
        a = self.create_via_ui(40, 30, "A")
        b = self.create_via_ui(50, 20, "B")
        self.assertIsNot(a.session, b.session)
        self.assertEqual((a.session.doc.width, b.session.doc.width), (40, 50))
        a.session.layer().pix.write((0, 0, 1, 1), np.array([[[9, 9, 9, 255]]], np.uint8))
        self.assertEqual(int(b.session.layer().pix.read((0, 0, 1, 1))[0, 0, 0]), 255)
        # sans Ctrl : l'élément ne bouge pas ; avec Ctrl : il bouge
        view = self.pane.view
        a.setSelected(True)
        start = a.pos()
        p0 = view.mapFromScene(a.mapToScene(QPointF(60, 60)))
        QTest.mousePress(view.viewport(), Qt.LeftButton, Qt.NoModifier, p0)
        QTest.mouseMove(view.viewport(), p0 + QPoint(80, 40))
        QTest.mouseRelease(view.viewport(), Qt.LeftButton, Qt.NoModifier, p0 + QPoint(80, 40))
        settle()
        self.assertEqual(a.pos(), start)
        QTest.mousePress(view.viewport(), Qt.LeftButton, Qt.ControlModifier, p0)
        QTest.mouseMove(view.viewport(), p0 + QPoint(80, 40), delay=10)
        QTest.mouseMove(view.viewport(), p0 + QPoint(90, 50), delay=10)
        QTest.mouseRelease(view.viewport(), Qt.LeftButton, Qt.ControlModifier, p0 + QPoint(90, 50))
        settle()
        self.assertNotEqual(a.pos(), start)

    def test_missing_asset_is_reported_and_never_overwritten(self):
        item = self.create_via_ui(30, 30, "Perdu")
        item.session.layer().pix.write((0, 0, 2, 2), np.full((2, 2, 4), 200, np.uint8))
        item.session.notify("committed", None)
        self.pane.save()
        name = item.data["asset"]
        self.assertTrue(name.endswith(".fmps"))
        self.pane._autosave.stop()
        S._REGISTRY.clear()
        serialization.asset_path(self.path, name).unlink()
        pane2 = self.make_pane(self.path)
        lost = [i for i in pane2.scene.board_items() if isinstance(i, PsItem)][0]
        self.assertIn("absente", lost.session.error)
        pane2.scene.contentChanged.emit()
        pane2.save()
        again = [d for d in serialization.load(self.path)["items"] if d["type"] == "ps_doc"][0]
        self.assertEqual(again["asset"], name)                       # la référence d'origine n'est PAS écrasée

    def test_board_folder_moved_keeps_documents(self):
        item = self.create_via_ui(20, 20, "Mobile")
        item.session.layer().pix.write((0, 0, 3, 3), np.full((3, 3, 4), (1, 2, 3, 255), np.uint8))
        item.session.notify("committed", None)
        self.pane.save()
        self.pane._autosave.stop()
        expect = C.flatten_u8(item.session.doc)
        moved = self.tmp / "ailleurs"
        moved.mkdir()
        shutil.copy2(self.path, moved / "essai.mro")
        shutil.copytree(serialization.assets_dir(self.path), serialization.assets_dir(moved / "essai.mro"))
        S._REGISTRY.clear()
        pane2 = self.make_pane(moved / "essai.mro")
        loaded = [i for i in pane2.scene.board_items() if isinstance(i, PsItem)][0]
        self.assertIsNone(loaded.session.error)
        self.assertTrue(np.array_equal(C.flatten_u8(loaded.session.doc), expect))

    def test_import_image_creates_document_and_layer_import(self):
        from PIL import Image
        png = self.tmp / "photo.png"
        Image.fromarray(np.dstack([np.full((10, 20), 200, np.uint8)] * 3 + [np.full((10, 20), 128, np.uint8)]),
                        "RGBA").save(png)
        self.pane.set_module("photoshop")
        item = self.pane.photoshop.import_file(str(png))
        self.assertEqual((item.session.doc.width, item.session.doc.height), (20, 10))
        self.assertEqual(tuple(C.flatten_u8(item.session.doc)[0, 0]), (200, 200, 200, 128))      # alpha conservé
        std = self.open_standard_by_double_click(item)
        layer = std.import_layer(str(png))
        self.assertEqual(len(item.session.doc.layers), 2)
        self.assertIsNotNone(layer)
        item.session.undo()
        self.assertEqual(len(item.session.doc.layers), 1)
        bad = self.tmp / "faux.png"
        bad.write_bytes(b"x")
        from unittest import mock
        with mock.patch("PySide6.QtWidgets.QMessageBox.warning"):
            self.assertIsNone(self.pane.photoshop.import_file(str(bad)))


if __name__ == "__main__":
    unittest.main()
