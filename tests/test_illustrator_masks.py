"""Module Illustrator, tranche 12 : masques d'écrêtage (Ctrl+7 / Ctrl+Alt+7) et d'opacité : groupe et masque en une
étape, rendu vérifié au pixel (écrêté, luminance, inversé), clic seulement dans la partie visible, boîte de
sélection réduite au masque, annulation, enregistrement, SVG aller-retour (`clip-path`, `mask`)."""
import os as _os, sys as _sys  # jamais les vrais réglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import unittest
import xml.etree.ElementTree as ET

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter

from test_illustrator import IllTestCase, settle
from fm_board import model, ui as board_ui
from fm_illustrator import bezier as bz, model as im, svg


class MaskTestCase(IllTestCase):
    def render(self, rect: QRectF) -> QImage:
        """Rendu de la scène (sans la sélection ni l'overlay) d'une zone, 1 px par unité."""
        self.ctl.clear_selection()
        self.ctl.hover = None
        settle()
        image = QImage(int(rect.width()), int(rect.height()), QImage.Format_ARGB32)
        image.fill(QColor("#808080"))
        p = QPainter(image)
        self.scene.render(p, QRectF(0, 0, rect.width(), rect.height()), rect)
        p.end()
        return image

    def pixel(self, image, x, y, rect) -> QColor:
        return image.pixelColor(int(x - rect.x()), int(y - rect.y()))

    def background(self, image, rect) -> str:
        """Fond du board (hors de tout objet) : ce que montre une partie masquée."""
        return self.pixel(image, rect.x() + 2, rect.y() + 2, rect).name()

    def red_square_and_circle_mask(self, kind="clip"):
        art = self.ctl.new_path(bz.rect(0, 0, 200, 200), QPointF(100, 100), dict(self.ctl.style, fill="#ff0000",
                                                                                stroke=""))
        self.ctl.commit_new(art, "a")
        mask = self.ctl.new_path(bz.ellipse(50, 50, 50, 50), QPointF(150, 150),
                                 dict(self.ctl.style, fill="#ffffff", stroke=""))
        self.ctl.commit_new(mask, "m")
        self.ctl.select([art, mask])
        if kind == "clip":
            self.key(Qt.Key_7, Qt.ControlModifier)
        else:
            self.ctl.make_mask("opacity")
        return art, mask


class ClipMaskTest(MaskTestCase):
    def test_ctrl7_groups_and_clips_in_one_step(self):
        art, mask = self.red_square_and_circle_mask()
        self.assertEqual(mask.data["mask"], "clip")
        self.assertEqual(art.data["group"], mask.data["group"])
        self.assertEqual((mask.data["fill"], mask.data["stroke"]), ("", ""))
        area = QRectF(80, 80, 240, 240)
        image = self.render(area)
        self.assertEqual(self.pixel(image, 200, 200, area).name(), "#ff0000")      # dans le cercle
        self.assertEqual(self.pixel(image, 110, 110, area).name(), self.background(image, area))  # écrêté
        self.assertIs(self.ctl.object_at(QPointF(200, 200)), art)
        self.assertIsNone(self.ctl.object_at(QPointF(110, 110)))                    # partie cachée : pas de clic
        self.ctl.select([art, mask])
        r = self.ctl.selection_rect()
        self.assertEqual((round(r.x()), round(r.width())), (150, 100))
        self.scene.undo.undo()
        self.assertEqual(mask.data["mask"], "")
        self.assertEqual(self.pixel(self.render(area), 110, 110, area).name(), "#ff0000")

    def test_release_and_save_reopen(self):
        art, mask = self.red_square_and_circle_mask()
        self.assertTrue(self.pane.save())
        pane = board_ui.BoardPane(self.host)
        from test_illustrator import _PANES
        _PANES.append(pane)
        self.assertTrue(pane.open(self.path))
        again = pane.scene.item(art.item_id)
        self.assertIsNotNone(again.mask_item())
        self.ctl.select([art])
        self.key(Qt.Key_7, Qt.ControlModifier | Qt.AltModifier)
        self.assertEqual((art.data["group"], mask.data["mask"]), ("", ""))
        self.assertIsNone(art.mask_item())

    def test_move_group_keeps_clip(self):
        art, mask = self.red_square_and_circle_mask()
        self.ctl.set_tool("select")
        self.click(QPointF(200, 200))
        self.assertEqual(set(self.ctl.selection()), {art, mask})
        self.drag(QPointF(200, 200), QPointF(300, 200), mods=Qt.ControlModifier)
        area = QRectF(180, 80, 240, 240)
        image = self.render(area)
        self.assertEqual(self.pixel(image, 300, 200, area).name(), "#ff0000")
        self.assertEqual(self.pixel(image, 215, 115, area).name(), self.background(image, area))


class OpacityMaskTest(MaskTestCase):
    def test_luminance_and_invert(self):
        art, mask = self.red_square_and_circle_mask("opacity")
        self.assertEqual(mask.data["mask"], "opacity")
        self.assertEqual(mask.data["fill"], "#ffffff")              # le masque d'opacité garde ses couleurs
        area = QRectF(80, 80, 240, 240)
        image = self.render(area)
        self.assertEqual(self.pixel(image, 200, 200, area).name(), "#ff0000")      # blanc : opaque
        self.assertEqual(self.pixel(image, 110, 110, area).name(), self.background(image, area))  # caché
        self.ctl.select([art])
        self.ctl.invert_opacity_mask()
        image = self.render(area)
        self.assertEqual(self.pixel(image, 200, 200, area).name(), self.background(image, area))
        self.assertEqual(self.pixel(image, 110, 110, area).name(), "#ff0000")

    def test_gray_mask_gives_half_opacity(self):
        art, mask = self.red_square_and_circle_mask("opacity")
        self.ctl.select([mask])
        self.ctl.set_style("fill", "#808080")
        area = QRectF(80, 80, 240, 240)
        image = self.render(area)
        c = self.pixel(image, 200, 200, area)
        bg = QColor(self.background(image, area))                     # rouge à ~50 % sur le fond
        self.assertAlmostEqual(c.green(), bg.green() / 2, delta=6)
        self.assertAlmostEqual(c.red(), (255 + bg.red()) / 2, delta=6)


class MaskSvgTest(unittest.TestCase):
    def test_export_and_import_clip_and_mask(self):
        art = im.new_entity(im.PATH, subpaths=bz.rect(0, 0, 100, 100), fill="#ff0000", stroke="", group="g1")
        clip = im.new_entity(im.PATH, subpaths=bz.ellipse(50, 50, 40, 40), fill="", stroke="", group="g1",
                             mask="clip")
        art2 = im.new_entity(im.PATH, subpaths=bz.rect(0, 0, 50, 50), fill="#00ff00", stroke="", group="g2",
                             x=200.0)
        lum = im.new_entity(im.PATH, subpaths=bz.rect(0, 0, 50, 50), fill="#ffffff", stroke="", group="g2",
                            mask="opacity", x=200.0)
        for d in (art, clip, art2, lum):
            d["type"] = im.PATH
        text = svg.export_svg([art, clip, art2, lum], (0.0, 0.0, 300.0, 120.0))
        root = ET.fromstring(text)
        ns = f"{{{svg.SVG_NS}}}"
        self.assertIsNotNone(root.find(f"{ns}defs/{ns}clipPath"))
        self.assertIsNotNone(root.find(f"{ns}defs/{ns}mask"))
        groups = root.findall(f"{ns}g")
        self.assertEqual([("clip-path" in g.attrib, "mask" in g.attrib) for g in groups], [(True, False),
                                                                                         (False, True)])
        self.assertEqual(sum(len(g.findall(f"{ns}path")) for g in groups), 2)      # masques dans <defs> seulement
        back = svg.import_svg(text)
        kinds = [(e["fill"], e["mask"]) for e in back]
        self.assertIn(("", "clip"), kinds)
        self.assertIn(("#ffffff", "opacity"), kinds)
        clip_back = next(e for e in back if e["mask"] == "clip")
        red = next(e for e in back if e["fill"] == "#ff0000")
        self.assertEqual(clip_back["group"], red["group"])
        self.assertTrue(red["group"])

    def test_normalize_drops_mask_without_group(self):
        item = model.normalize_item({"id": "p", "type": "ill_path", "mask": "clip", "group": ""})
        self.assertEqual(item["mask"], "")
        item = model.normalize_item({"id": "p", "type": "ill_path", "mask": "bizarre", "group": "g"})
        self.assertEqual(item["mask"], "")


if __name__ == "__main__":
    unittest.main()
