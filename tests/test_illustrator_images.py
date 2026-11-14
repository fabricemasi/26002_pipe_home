"""Module Illustrator, tranche 14 : images placées : importer (copie dans le dossier du board, une étape), dépôt de
fichiers, rendu vérifié au pixel, mise à l'échelle / rotation (matrice), recadrage par masque, effets, Pathfinder qui
ignore les images, enregistrement, SVG aller-retour (`<image>` incorporée en URI data:), import SVG qui garde le type
des textes et des images."""
import os as _os, sys as _sys  # jamais les vrais réglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import unittest
import xml.etree.ElementTree as ET

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QColor, QImage

from test_illustrator_masks import MaskTestCase
from fm_board import serialization, ui as board_ui
from fm_illustrator import bezier as bz, svg
from fm_illustrator.items import IllImageItem, IllTextItem


class ImageTestCase(MaskTestCase):
    def png(self, name="photo.png", w=80, h=40, color="#00aa00"):
        image = QImage(w, h, QImage.Format_RGB32)
        image.fill(QColor(color))
        path = self.tmp / name
        image.save(str(path))
        return path

    def images(self):
        return [i for i in self.paths() if isinstance(i, IllImageItem)]


class PlaceTest(ImageTestCase):
    def test_place_copies_into_assets_in_one_step(self):
        item = self.ctl.place_image(self.png(), QPointF(200, 200))
        self.assertIsInstance(item, IllImageItem)
        self.assertTrue(serialization.asset_path(self.path, item.data["asset"]).is_file())
        self.assertEqual((item.data["w"], item.data["h"]), (80.0, 40.0))
        r = item.geometry_rect()
        self.assertEqual((r.x(), r.y(), r.width(), r.height()), (160.0, 180.0, 80.0, 40.0))
        area = QRectF(150, 170, 100, 60)
        self.assertEqual(self.pixel(self.render(area), 200, 200, area).name(), "#00aa00")
        self.scene.undo.undo()
        self.assertEqual(self.images(), [])

    def test_paste_image_becomes_selectable_illustrator_image(self):
        # Ctrl+V d'une image copiée ailleurs (2026-11-13) : un objet image du module (choisi au clic, vectorisable),
        # jamais une image du board que l'outil Sélection ignore.
        from PySide6.QtWidgets import QApplication
        image = QImage(60, 90, QImage.Format_RGB32)
        image.fill(QColor("#123456"))
        QApplication.clipboard().setImage(image)
        self.view.paste()
        items = self.images()
        self.assertEqual(len(items), 1)
        self.assertEqual((items[0].data["w"], items[0].data["h"]), (60.0, 90.0))
        self.ctl.select([])
        self.click(items[0].geometry_rect().center())
        self.assertIn(items[0], self.ctl.selection())

    def test_drop_files_and_transforms(self):
        self.assertTrue(self.ctl.drop_files([self.png()], QPointF(200, 200)))
        item = self.images()[0]
        self.ctl.select([item])
        self.ctl.rotate_selection(90)
        r = item.geometry_rect()
        self.assertAlmostEqual(r.width(), 40.0, places=3)
        self.assertAlmostEqual(r.height(), 80.0, places=3)
        rect = self.ctl.selection_rect()
        self.ctl.transform_selection(bz.scale(2, 2, rect.center().x(), rect.center().y()), "Échelle")
        self.assertAlmostEqual(item.geometry_rect().width(), 80.0, places=3)
        area = QRectF(150, 100, 100, 200)
        self.assertEqual(self.pixel(self.render(area), 200, 200, area).name(), "#00aa00")

    def test_crop_with_mask_and_pathfinder_ignores_images(self):
        item = self.ctl.place_image(self.png(w=200, h=100), QPointF(200, 200))
        self.ctl.select([item])
        self.ctl.crop_with_mask()
        mask = item.mask_item()
        self.assertIsNotNone(mask)
        self.ctl.select([mask])
        self.ctl.transform_selection(bz.scale(0.5, 1, 100, 150), "Rétrécir le masque")    # garde la moitié gauche
        area = QRectF(90, 140, 220, 120)
        image = self.render(area)
        self.assertEqual(self.pixel(image, 140, 200, area).name(), "#00aa00")
        self.assertEqual(self.pixel(image, 260, 200, area).name(), self.background(image, area))
        rect = self.rect(400, 100, 50, 50)
        self.ctl.select([item, rect])
        self.assertEqual(self.ctl.shapes(), [rect])
        self.assertEqual(self.ctl.pathfinder("unite"), [])

    def test_effect_on_image(self):
        item = self.ctl.place_image(self.png(), QPointF(200, 200))
        self.ctl.select([item])
        self.ctl.add_effect("shadow")
        self.ctl.set_effect("shadow", "dx", 30.0)
        self.ctl.set_effect("shadow", "dy", 0.0)
        self.ctl.set_effect("shadow", "opacity", 1.0)
        self.scene.commit_live()
        area = QRectF(150, 170, 140, 60)
        self.assertLess(self.pixel(self.render(area), 262, 200, area).lightness(), 90)


class ImageSvgTest(ImageTestCase):
    def test_export_embeds_and_reimport(self):
        item = self.ctl.place_image(self.png(), QPointF(200, 200))
        self.ctl.select([item])
        self.ctl.rotate_selection(30)
        board = self.ctl.add_artboard(QRectF(0, 0, 400, 400))
        target = self.ctl.export_svg(self.tmp / "image.svg", board)
        root = ET.parse(target).getroot()
        el = root.find(f"{{{svg.SVG_NS}}}image")
        self.assertTrue(el.get("href").startswith("data:image/png;base64,"))
        self.assertIn("matrix(", el.get("transform"))
        before = len(self.images())
        new = self.ctl.import_svg(target, QPointF(700, 700))
        self.assertEqual(len(self.images()), before + 1)
        again = new[0]
        self.assertIsInstance(again, IllImageItem)
        self.assertTrue(serialization.asset_path(self.path, again.data["asset"]).is_file())
        self.assertAlmostEqual(again.geometry_rect().width(), item.geometry_rect().width(), places=2)

    def test_import_keeps_text_type(self):
        path = self.tmp / "texte.svg"
        path.write_text('<svg xmlns="http://www.w3.org/2000/svg"><text x="10" y="40" font-size="20">Salut</text>'
                        '<rect x="0" y="50" width="20" height="10"/></svg>', encoding="utf-8")
        new = self.ctl.import_svg(path, QPointF(300, 300))
        self.assertEqual(sorted(type(i).__name__ for i in new), ["IllPathItem", "IllTextItem"])
        text = next(i for i in new if isinstance(i, IllTextItem))
        self.assertEqual(text.data["text"], "Salut")

    def test_save_reopen_keeps_image(self):
        item = self.ctl.place_image(self.png(), QPointF(200, 200))
        self.assertTrue(self.pane.save())
        pane = board_ui.BoardPane(self.host)
        from test_illustrator import _PANES
        _PANES.append(pane)
        self.assertTrue(pane.open(self.path))
        again = pane.scene.item(item.item_id)
        self.assertIsInstance(again, IllImageItem)
        self.assertIsNotNone(again.pixmap())
        self.assertEqual(again.pixmap().width(), 80)


if __name__ == "__main__":
    unittest.main()
