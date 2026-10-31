"""Module Illustrator, tranches 6-8 : dégradés (modèle, rendu, outil Dégradé, SVG aller-retour), nuancier du
document, calques (création avec le 1er objet, masquer / verrouiller, ordre, déplacer la sélection, suppression),
disposition dans le calque, Pathfinder (modes de forme, division, découpe, fusion, recadrage, vectoriser le contour)."""
import os as _os, sys as _sys  # jamais les vrais réglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import unittest
import xml.etree.ElementTree as ET

from PySide6.QtCore import QPointF, Qt

from test_illustrator import IllTestCase, settle
from fm_board import model
from fm_illustrator import bezier as bz, layers as lay, paint, pathfinder as pf, svg


class PaintModelTest(unittest.TestCase):
    def test_gradient_validation_and_geometry(self):
        self.assertIsNone(paint.valid_gradient({"type": "linear", "stops": [[0, "#fff"]]}))
        g = paint.valid_gradient({"type": "radial", "stops": [[1.5, "#000000"], [0, "#ffffff"]], "r": -3})
        self.assertEqual(g["stops"], [[0.0, "#ffffff"], [1.0, "#000000"]])
        self.assertGreater(g["r"], 0)
        lin = paint.new_gradient("linear")
        a = paint.absolute(lin, (10, 20, 110, 70))
        self.assertEqual((a["x1"], a["y1"], a["x2"], a["y2"]), (10, 45, 110, 45))
        moved = paint.set_from_drag(lin, (0, 0, 100, 100), (0, 0), (100, 100))
        self.assertEqual((moved["x1"], moved["y2"]), (0.0, 1.0))
        self.assertEqual(paint.interpolate(lin, 0.5), "#808080")

    def test_board_normalizes_gradients_and_layers(self):
        item = model.normalize_item({"id": "p", "type": "ill_path", "fill_gradient": {"type": "nope"},
                                     "stroke_gradient": {"type": "linear", "stops": [[0, "#ff0000"], [1, "#00ff00"]]}})
        self.assertIsNone(item["fill_gradient"])
        self.assertEqual(item["stroke_gradient"]["stops"][1][1], "#00ff00")
        layer = model.normalize_item({"id": "l", "type": "ill_layer", "color": "vert"})
        self.assertEqual(layer["color"], "#2f7cf6")

    def test_svg_gradient_round_trip(self):
        g = paint.new_gradient("linear", "#ff0000", "#0000ff")
        data = {"type": "ill_path", "subpaths": bz.rect(0, 0, 100, 50), "fill": "#ff0000", "fill_gradient": g,
                "stroke": "", "x": 10.0, "y": 10.0}
        text = svg.export_svg([data], (0.0, 0.0, 200.0, 100.0))
        root = ET.fromstring(text)
        self.assertIsNotNone(root.find(f"{{{svg.SVG_NS}}}defs/{{{svg.SVG_NS}}}linearGradient"))
        back = svg.import_svg(text)[0]
        self.assertEqual(back["fill_gradient"]["stops"], g["stops"])
        self.assertAlmostEqual(back["fill_gradient"]["x2"], 1.0, places=3)
        self.assertAlmostEqual(back["fill_gradient"]["y1"], 0.5, places=3)

    def test_svg_object_bounding_box_gradient(self):
        text = ('<svg xmlns="http://www.w3.org/2000/svg"><defs><radialGradient id="r"><stop offset="0" '
                'stop-color="#fff"/><stop offset="100%" stop-color="#000" stop-opacity="0.5"/></radialGradient>'
                '</defs><circle cx="50" cy="50" r="40" fill="url(#r)"/></svg>')
        e = svg.import_svg(text)[0]
        self.assertEqual(e["fill_gradient"]["type"], "radial")
        self.assertEqual(e["fill_gradient"]["stops"][1][1], "#80000000")


class PathfinderModelTest(unittest.TestCase):
    def test_modes(self):
        a, b = bz.rect(0, 0, 100, 100), bz.rect(50, 0, 100, 100)
        shapes = [(a, "nonzero"), (b, "nonzero")]
        self.assertEqual([round(v) for v in bz.bounds(pf.combine(shapes, "unite"))], [0, 0, 150, 100])
        self.assertEqual([round(v) for v in bz.bounds(pf.combine(shapes, "minus_front"))], [0, 0, 50, 100])
        self.assertEqual([round(v) for v in bz.bounds(pf.combine(shapes, "intersect"))], [50, 0, 100, 100])
        self.assertEqual(len(pf.divide(shapes)), 3)
        self.assertEqual([o for o, _s in pf.divide(shapes)].count(1), 2)
        line = pf.outline_stroke(bz.line(0, 0, 100, 0), 4, "round")
        self.assertEqual([round(v) for v in bz.bounds(line)], [-2, -2, 102, 2])


class LayersTest(IllTestCase):
    def rect_at(self, x):
        return self.rect(x, 100, 50, 50)

    def test_first_object_creates_layer_in_same_step(self):
        a = self.rect_at(100)
        layers = lay.layers(self.scene)
        self.assertEqual(len(layers), 1)
        self.assertEqual(a.data["layer"], layers[0].item_id)
        self.scene.undo.undo()
        self.assertEqual(lay.layers(self.scene), [])
        self.assertEqual(self.paths(), [])

    def test_hide_lock_and_order(self):
        a = self.rect_at(100)
        bottom = lay.layers(self.scene)[0]
        top = self.ctl.new_layer()
        b = self.rect_at(130)
        self.assertEqual(b.data["layer"], top.item_id)
        self.assertGreater(b.zValue(), a.zValue())
        self.ctl.set_layer_flag(top, "hidden")
        self.assertFalse(b.isVisible())
        self.ctl.set_layer_flag(top, "hidden")
        self.ctl.set_layer_flag(top, "content_locked")
        self.assertIs(self.ctl.object_at(QPointF(140, 120)), a)        # b verrouillé : on clique à travers
        self.ctl.set_layer_flag(top, "content_locked")
        self.ctl.move_layer(top, 1)                                      # le calque du haut passe en bas
        self.assertLess(b.zValue(), a.zValue())
        self.scene.undo.undo()
        self.assertGreater(b.zValue(), a.zValue())
        self.ctl.select([a])
        self.ctl.move_to_layer(top)
        self.assertEqual(a.data["layer"], top.item_id)
        self.assertGreater(a.zValue(), b.zValue())
        self.ctl.delete_layer(bottom)
        self.assertEqual(len(lay.layers(self.scene)), 1)

    def test_arrange_stays_in_layer(self):
        a = self.rect_at(100)
        b = self.rect_at(120)
        top = self.ctl.new_layer()
        c = self.rect_at(140)
        self.ctl.select([a])
        self.key(Qt.Key_BracketRight, Qt.ControlModifier | Qt.ShiftModifier)
        self.assertGreater(a.zValue(), b.zValue())
        self.assertLess(a.zValue(), c.zValue())
        self.assertIsNotNone(top)

    def test_layers_panel_toggles(self):
        self.rect_at(100)
        self.ctl.ui.toggle_layers()
        settle()
        self.assertTrue(self.ctl.ui.layers.isVisible())
        self.assertEqual(len(self.ctl.ui.layer_list.rows), 1)


class GradientAndPathfinderTest(IllTestCase):
    def test_gradient_tool_and_fill_menu_values(self):
        a = self.rect(100, 100, 100, 100)
        self.ctl.set_tool("gradient")
        self.drag(QPointF(100, 150), QPointF(200, 150))
        g = a.data["fill_gradient"]
        self.assertEqual(g["type"], "linear")
        self.assertAlmostEqual(g["x1"], 0.0)
        self.assertAlmostEqual(g["x2"], 1.0)
        self.scene.undo.undo()
        self.assertIsNone(a.data["fill_gradient"])
        self.ctl.select([a])
        self.ctl.set_style("fill_gradient", paint.new_gradient("radial", "#ff0000", "#00ff00"))
        self.assertEqual(a.data["fill"], "#ff0000")
        self.ctl.set_style("fill", "#123456")
        self.assertIsNone(a.data["fill_gradient"])
        self.assertIn("#123456", self.ctl.document_colors())

    def test_pathfinder_unite_divide_and_undo(self):
        a = self.rect(100, 100, 100, 100)
        b = self.rect(150, 100, 100, 100)
        self.ctl.select([a, b])
        new = self.ctl.pathfinder("unite")
        self.assertEqual(len(new), 1)
        r = new[0].geometry_rect()
        self.assertEqual((round(r.x()), round(r.width())), (100, 150))
        self.scene.undo.undo()
        self.assertEqual(len(self.paths()), 2)
        self.ctl.select(self.paths())
        pieces = self.ctl.pathfinder("divide")
        self.assertEqual(len(pieces), 3)
        self.assertTrue(pieces[0].data["group"])
        self.assertEqual(len({p.data["group"] for p in pieces}), 1)

    def test_trim_removes_strokes_and_outline_stroke(self):
        a = self.rect(100, 100, 100, 100)
        b = self.rect(150, 100, 100, 100)
        self.ctl.select([a, b])
        pieces = self.ctl.pathfinder("trim")
        self.assertTrue(all(p.data["stroke"] == "" for p in pieces))
        self.ctl.set_tool("line")
        self.drag(QPointF(100, 400), QPointF(300, 400))
        line = self.paths()[-1]
        stroke = line.data["stroke"]
        self.ctl.select([line])
        out = self.ctl.outline_stroke()
        self.assertEqual(len(out), 1)                                   # trait sans fond : remplacé par sa surface
        self.assertEqual((out[0].data["fill"], out[0].data["stroke"]), (stroke, ""))


if __name__ == "__main__":
    unittest.main()
