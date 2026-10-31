"""Module Illustrator, tranche 11 : pinceaux et largeur variable : contour-surface (profils, pointe calligraphique,
tracés fermés), rendu vérifié au pixel, outil Largeur (Maj+W), Pinceau (B), Forme de tache (Maj+B, fusion des
taches de même couleur), Vectoriser le contour, SVG, une étape d'annulation par geste."""
import os as _os, sys as _sys  # jamais les vrais réglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import math
import unittest
import xml.etree.ElementTree as ET

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt

from test_illustrator_masks import MaskTestCase
from fm_board import model
from fm_illustrator import brushes as br, bezier as bz, model as im, svg


class BrushModelTest(unittest.TestCase):
    def test_profile_and_calligraphic_widths(self):
        data = {"subpaths": bz.line(0, 0, 100, 0), "stroke_width": 10.0, "width_profile": br.PROFILES["spindle"][1]}
        out = br.outline(data)
        self.assertEqual(len(out), 1)
        self.assertAlmostEqual(br.factor_at(data["width_profile"], 0.5), 1.0)
        self.assertTrue(bz.point_inside(out, (50, 4)))                 # milieu : large
        self.assertFalse(bz.point_inside(out, (5, 4)))                 # bout : effilé
        brush = dict(br.CALLIGRAPHIC, angle=0.0, roundness=0.2, size=10.0)
        self.assertAlmostEqual(br.nib_width(brush, 0.0), 2.0)          # le long du grand axe : fin
        self.assertAlmostEqual(br.nib_width(brush, math.pi / 2), 10.0)  # en travers : toute la taille
        ring = br.outline({"subpaths": bz.ellipse(0, 0, 50, 50), "stroke_width": 10.0})
        self.assertEqual(len(ring), 2)
        self.assertFalse(bz.point_inside(ring, (0, 0)))
        self.assertTrue(bz.point_inside(ring, (52, 0)))

    def test_locate_and_normalize(self):
        d, t, p = br.locate({"subpaths": bz.line(0, 0, 200, 0)}, (50, 7))
        self.assertAlmostEqual(t, 0.25)
        self.assertAlmostEqual(d, 7.0)
        item = model.normalize_item({"id": "p", "type": "ill_path", "width_profile": [[2, 1], [0.5, -3], "x"],
                                     "brush": {"type": "calligraphic", "roundness": 9}})
        self.assertEqual(item["width_profile"], [[0.5, 0.0], [1.0, 1.0]])
        self.assertEqual(item["brush"]["roundness"], 1.0)
        self.assertIsNone(model.normalize_item({"id": "q", "type": "ill_path", "brush": {"type": "x"}})["brush"])

    def test_svg_exports_brushed_stroke_as_surface(self):
        data = im.new_entity(im.PATH, subpaths=bz.line(0, 0, 100, 0), fill="", stroke="#ff0000", stroke_width=8.0,
                             width_profile=br.PROFILES["taper_end"][1])
        data["type"] = im.PATH
        root = ET.fromstring(svg.export_svg([data], (-10.0, -10.0, 120.0, 20.0)))
        ns = f"{{{svg.SVG_NS}}}"
        paths = root.findall(f".//{ns}path")
        self.assertEqual([(p.get("fill"), p.get("stroke")) for p in paths], [("none", None), ("#ff0000", None)])


class BrushToolsTest(MaskTestCase):
    def line_item(self, profile=(), width=20.0):
        item = self.ctl.new_path(bz.line(0, 0, 200, 0), QPointF(100, 200),
                                 dict(self.ctl.style, fill="", stroke="#ff0000", stroke_width=width,
                                      fill_gradient=None))
        self.ctl.commit_new(item, "l")
        if profile:
            self.ctl.set_width_profile(list(profile))
        return item

    def test_profile_render_and_undo(self):
        item = self.line_item(br.PROFILES["spindle"][1])
        area = QRectF(80, 170, 240, 60)
        image = self.render(area)
        self.assertEqual(self.pixel(image, 200, 208, area).name(), "#ff0000")     # milieu épais
        self.assertEqual(self.pixel(image, 110, 208, area).name(), self.background(image, area))
        self.ctl.select([item])
        self.scene.undo.undo()
        self.assertEqual(item.data["width_profile"], [])

    def test_width_tool_drag_sets_a_width_point(self):
        item = self.line_item()
        self.key(Qt.Key_W, Qt.ShiftModifier, "W")
        self.assertEqual(self.ctl.tool, "width")
        count = self.scene.undo.count()
        self.drag(QPointF(200, 200), QPointF(200, 230))                 # 30 de chaque côté : facteur 3
        profile = item.data["width_profile"]
        mid = [p for p in profile if abs(p[0] - 0.5) < 0.02]
        self.assertTrue(mid)
        self.assertAlmostEqual(mid[0][1], 3.0, delta=0.05)
        self.assertEqual(self.scene.undo.count(), count + 1)
        self.click(QPointF(200, 200), mods=Qt.AltModifier)             # Alt + clic : point retiré
        self.assertFalse([p for p in item.data["width_profile"] if abs(p[0] - 0.5) < 0.02])

    def test_paintbrush_and_calligraphic_live(self):
        self.key(Qt.Key_B, text="b")
        self.assertEqual(self.ctl.tool, "paintbrush")
        pts = [QPointF(100 + i * 10, 300 + 20 * math.sin(i / 3)) for i in range(20)]
        self.mouse(QEvent.MouseButtonPress, pts[0])
        for p in pts[1:]:
            self.mouse(QEvent.MouseMove, p, buttons=Qt.LeftButton)
        self.mouse(QEvent.MouseButtonRelease, pts[-1])
        item = self.paths()[-1]
        self.assertEqual(item.data["brush"]["type"], "calligraphic")
        self.assertEqual(item.data["fill"], "")
        self.ctl.select([item])
        count = self.scene.undo.count()
        for size in (12.0, 16.0, 20.0):
            self.ctl.set_brush(dict(self.ctl.brush, size=size), live=True)
        self.scene.commit_live()
        self.assertEqual(self.scene.undo.count(), count + 1)
        self.assertEqual(item.data["brush"]["size"], 20.0)
        self.assertEqual(self.ctl.brush["size"], 20.0)

    def test_blob_brush_merges_same_color(self):
        self.ctl.set_tool("blob")
        self.ctl.blob_size = 20.0
        self.drag(QPointF(100, 400), QPointF(200, 400))
        self.drag(QPointF(190, 400), QPointF(190, 480))                # touche la première : réunie
        blobs = self.paths()
        self.assertEqual(len(blobs), 1)
        r = blobs[0].geometry_rect()
        self.assertAlmostEqual(r.bottom(), 490, delta=1)
        self.ctl.style["stroke"] = "#00ff00"
        self.drag(QPointF(150, 400), QPointF(150, 450))                # autre couleur : séparée
        self.assertEqual(len(self.paths()), 2)
        self.scene.undo.undo()
        self.scene.undo.undo()
        self.assertEqual(len(self.paths()), 1)
        self.assertAlmostEqual(self.paths()[0].geometry_rect().bottom(), 410, delta=1)

    def test_outline_stroke_uses_variable_width(self):
        item = self.line_item(br.PROFILES["taper_end"][1], width=20.0)
        self.ctl.select([item])
        new = self.ctl.outline_stroke()
        self.assertEqual(len(new), 1)
        surface = new[0]
        self.assertEqual((surface.data["fill"], surface.data["stroke"], surface.data["width_profile"]),
                         ("#ff0000", "", []))
        r = surface.geometry_rect()
        self.assertAlmostEqual(r.height(), 20, delta=0.5)
        self.assertAlmostEqual(r.width(), 200, delta=0.5)


if __name__ == "__main__":
    unittest.main()
