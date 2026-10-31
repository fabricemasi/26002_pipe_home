"""Module Illustrator, tranche 10 : texte (point, captif, curviligne) : mise en page, outil Texte (T), édition sur
place (une étape, vide = rien), double-clic, attributs (police, corps, alignement), mise à l'échelle / rotation,
créer les contours (Ctrl+Maj+O), Pathfinder qui ignore le texte, SVG (export `<text>` / `<textPath>`, import),
enregistrement."""
import os as _os, sys as _sys  # jamais les vrais réglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import unittest
import xml.etree.ElementTree as ET

from PySide6.QtCore import QEvent, QPointF, Qt

from test_illustrator import APP, IllTestCase, settle
from fm_board import model, ui as board_ui
from fm_illustrator import bezier as bz, model as im, svg, text as tx
from fm_illustrator.items import IllPathItem, IllTextItem

assert APP is not None


class LayoutTest(unittest.TestCase):
    def test_point_text_lines_and_alignment(self):
        data = im.new_entity(im.TEXT, text="Bonjour\nle monde", font_size=20.0, leading=1.5)
        lay = tx.layout(data)
        self.assertEqual(len(lay.lines), 2)
        self.assertEqual(lay.lines[0][2], 0.0)                     # 1re ligne de base = origine
        self.assertAlmostEqual(lay.lines[1][2], 30.0)              # interligne 1,5 × 20
        self.assertLess(lay.box.top(), 0)
        centered = tx.layout(dict(data, align="center"))
        self.assertLess(centered.box.left(), 0)
        self.assertAlmostEqual(centered.box.center().x(), 0.0, delta=1.0)

    def test_area_text_wraps_and_overflows(self):
        data = im.new_entity(im.TEXT, text="un deux trois quatre cinq six sept huit neuf dix", mode="area",
                             w=80.0, h=1000.0, font_size=12.0)
        lay = tx.layout(data)
        self.assertGreater(len(lay.lines), 2)
        self.assertFalse(lay.overflow)
        self.assertLessEqual(lay.path.boundingRect().right(), 81.0)
        small = tx.layout(dict(data, h=20.0))
        self.assertTrue(small.overflow)
        self.assertEqual(len(small.lines), 1)

    def test_text_on_path_follows_the_curve(self):
        sub = {"closed": False, "nodes": [bz.node(0, 0, None, None, 100, -100), bz.node(300, 0, 200, -100)]}
        data = im.new_entity(im.TEXT, text="sur la courbe", mode="path", subpaths=[sub], font_size=14.0)
        lay = tx.layout(data)
        self.assertFalse(lay.path.isEmpty())
        self.assertLess(lay.path.boundingRect().top(), -50)        # les lettres suivent l'arche
        far = tx.layout(dict(data, path_offset=0.98))
        self.assertTrue(far.overflow)

    def test_outline_subpaths(self):
        lay = tx.layout(im.new_entity(im.TEXT, text="O", font_size=50.0))
        subs = tx.outline_subpaths(lay.path)
        self.assertGreaterEqual(len(subs), 2)                       # contour extérieur + contre-forme
        self.assertTrue(all(s["closed"] for s in subs))

    def test_svg_export_and_import(self):
        data = im.new_entity(im.TEXT, text="Ligne 1\nLigne 2", font_size=20.0, fill="#ff0000", x=10.0, y=50.0,
                             bold=True)
        data["type"] = im.TEXT
        text = svg.export_svg([data], (0.0, 0.0, 200.0, 100.0), text_svg=tx.svg_text)
        root = ET.fromstring(text)
        el = root.find(f"{{{svg.SVG_NS}}}text")
        self.assertEqual(el.get("font-size"), "20")
        spans = el.findall(f"{{{svg.SVG_NS}}}tspan")
        self.assertEqual([s.text for s in spans], ["Ligne 1", "Ligne 2"])
        self.assertEqual((spans[0].get("x"), spans[0].get("y")), ("10", "50"))
        back = svg.import_svg(text)[0]
        self.assertEqual(back["type"], im.TEXT)
        self.assertEqual(back["text"], "Ligne 1\nLigne 2")
        self.assertEqual((back["x"], back["y"], back["fill"], back["bold"]), (10.0, 50.0, "#ff0000", True))

    def test_svg_text_on_path(self):
        data = im.new_entity(im.TEXT, text="abc", mode="path", subpaths=bz.line(0, 0, 100, 0))
        data.update(type=im.TEXT, id="t1")
        root = ET.fromstring(svg.export_svg([data], (0.0, -20.0, 120.0, 40.0), text_svg=tx.svg_text))
        self.assertIsNotNone(root.find(f".//{{{svg.SVG_NS}}}textPath"))


class TypeToolTest(IllTestCase):
    def type_text(self, text):
        for ch in text:
            self.key(Qt.Key_unknown if not ch.isalpha() else getattr(Qt, f"Key_{ch.upper()}"), text=ch)

    def finish(self):
        self.key(Qt.Key_Escape)
        settle()

    def texts(self):
        return [i for i in self.paths() if isinstance(i, IllTextItem)]

    def test_click_types_point_text_in_one_step(self):
        self.key(Qt.Key_T, text="t")
        self.assertEqual(self.ctl.tool, "type")
        self.click(QPointF(100, 200))
        self.assertIsNotNone(self.ctl.editor)
        self.assertTrue(self.view.editing_text())
        self.type_text("abc")
        self.finish()
        self.assertIsNone(self.ctl.editor)
        texts = self.texts()
        self.assertEqual(len(texts), 1)
        self.assertEqual(texts[0].data["text"], "abc")
        self.assertEqual((texts[0].data["x"], texts[0].data["y"]), (100.0, 200.0))
        self.scene.undo.undo()
        self.assertEqual(self.texts(), [])

    def test_empty_text_leaves_nothing_and_escape_keeps_board(self):
        self.ctl.set_tool("type")
        self.click(QPointF(100, 200))
        self.finish()
        self.assertEqual(self.texts(), [])
        self.assertEqual(self.scene.undo.count(), 0)
        self.assertTrue(self.pane.isVisible())

    def test_drag_creates_area_text_and_double_click_edits(self):
        self.ctl.set_tool("type")
        self.drag(QPointF(100, 100), QPointF(300, 200))
        self.type_text("hello")
        self.click(QPointF(600, 600))                               # clic ailleurs : terminé
        settle()
        item = self.texts()[0]
        self.assertEqual((item.data["mode"], item.data["w"], item.data["h"]), ("area", 200.0, 100.0))
        self.ctl.set_tool("select")
        self.mouse(QEvent.MouseButtonDblClick, QPointF(110, 110))
        self.assertIsNotNone(self.ctl.editor)
        self.key(Qt.Key_End)
        self.type_text("x")
        self.finish()
        self.assertEqual(item.data["text"], "hellox")
        self.scene.undo.undo()
        self.assertEqual(item.data["text"], "hello")

    def test_click_on_open_path_makes_path_text(self):
        self.ctl.set_tool("line")
        self.drag(QPointF(100, 300), QPointF(400, 300))
        line_id = self.paths()[-1].item_id
        self.ctl.set_tool("type")
        self.click(QPointF(250, 300))
        self.type_text("abc")
        self.finish()
        texts = self.texts()
        self.assertEqual(len(texts), 1)
        self.assertEqual(texts[0].data["mode"], "path")
        self.assertIsNone(self.scene.item(line_id))
        self.scene.undo.undo()
        self.assertEqual(self.texts(), [])
        self.assertEqual(len(self.paths()), 1)
        self.assertTrue(self.paths()[0].isVisible())

    def test_attributes_scale_rotation_and_outlines(self):
        item = self.ctl.new_text(QPointF(100, 200), text="Titre", font_size=20.0)
        self.ctl.commit_new(item, "Texte")
        self.ctl.set_text_attr("font_size", 40.0)
        self.assertEqual(item.data["font_size"], 40.0)
        self.ctl.set_text_attr("align", "center")
        self.ctl.rotate_selection(90)
        self.assertAlmostEqual(item.data["rotation"], 90.0)
        rect = self.ctl.selection_rect()
        self.ctl.transform_selection(bz.scale(2, 2, rect.center().x(), rect.center().y()), "Échelle")
        self.assertAlmostEqual(item.data["font_size"], 80.0)
        self.key(Qt.Key_O, Qt.ControlModifier | Qt.ShiftModifier)
        paths = self.paths()
        self.assertEqual(len(paths), 1)
        self.assertNotIsInstance(paths[0], IllTextItem)
        self.assertIsInstance(paths[0], IllPathItem)
        self.assertGreater(len(paths[0].data["subpaths"]), 3)

    def test_pathfinder_ignores_text_and_save_reopen(self):
        a = self.rect(100, 100, 50, 50)
        t = self.ctl.new_text(QPointF(120, 120), text="T")
        self.ctl.commit_new(t, "Texte")
        self.ctl.select([a, t])
        self.assertEqual(self.ctl.pathfinder("unite"), [])         # un seul tracé : rien à combiner
        self.assertTrue(self.pane.save())
        pane = board_ui.BoardPane(self.host)
        from test_illustrator import _PANES
        _PANES.append(pane)
        self.assertTrue(pane.open(self.path))
        again = pane.scene.item(t.item_id)
        self.assertIsInstance(again, IllTextItem)
        self.assertEqual(again.data["text"], "T")

    def test_board_normalizes_text(self):
        item = model.normalize_item({"id": "t", "type": "ill_text", "mode": "rond", "font_size": -3,
                                     "align": "milieu", "text": "a"})
        self.assertEqual((item["mode"], item["align"], item["font_size"]), ("point", "left", 0.5))


if __name__ == "__main__":
    unittest.main()
