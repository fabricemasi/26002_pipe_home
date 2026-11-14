"""Module Illustrator : « Convertir en tracés CAD » (menu Objet) : sous-tracés -> polylignes du module CAD
(courbes -> arcs, Y retourné), objets remplacés en une étape d'annulation ; et l'inverse, « Convertir en tracés
Illustrator » (clic droit du CAD) : traits -> contours, hachures -> remplissages."""
import os as _os, sys as _sys  # jamais les vrais réglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import math
import unittest

from PySide6.QtCore import QPointF

from test_illustrator import IllTestCase
from fm_cad import cad_shapes
from fm_illustrator import bezier as bz, from_cad, to_cad


def _max_error(geometry, center, radius, tol=0.01):
    """Écart maximal au cercle (centre, rayon) des points de la polyligne CAD."""
    prims = cad_shapes.prims("cad_pline", geometry)
    return max(abs(math.dist(a, center) - radius) for a, _b in cad_shapes.display_segments(prims, tol))


class ToCadGeometryTest(unittest.TestCase):
    def test_circle_becomes_closed_arcs_on_the_circle(self):
        geometry = to_cad.subpath_to_pline(bz.ellipse(100, 50, 40, 40)[0], 0.01)
        self.assertTrue(geometry["closed"])
        self.assertTrue(all(abs(v[2]) > 1e-6 for v in geometry["vertices"]))       # que des arcs
        self.assertLess(_max_error(geometry, (100, -50), 40), 0.05)                  # Y retourné

    def test_square_stays_straight_and_open_path_keeps_its_end(self):
        square = to_cad.subpath_to_pline(bz.rect(0, 0, 10, 20)[0])
        self.assertEqual(len(square["vertices"]), 4)
        self.assertTrue(all(v[2] == 0.0 for v in square["vertices"]))
        self.assertIn([10.0, -20.0, 0.0], square["vertices"])
        line = to_cad.subpath_to_pline(bz.line(0, 0, 30, 0)[0])
        self.assertEqual((line["closed"], line["vertices"]), (False, [[0.0, 0.0, 0.0], [30.0, 0.0, 0.0]]))

    def test_colour(self):
        self.assertEqual(to_cad.cad_color({"fill": "#FF0000", "stroke": "#00ff00"}), "#ff0000")
        self.assertEqual(to_cad.cad_color({"fill": "", "stroke": "#00ff00"}), "#00ff00")
        self.assertIsNone(to_cad.cad_color({"fill": "", "stroke": ""}))


class FromCadGeometryTest(unittest.TestCase):
    PROPS = {"color": "#FF0000", "lineweight": 2.0, "pattern": (3.0, 1.5), "ltscale": 2.0, "end1": {"style": "round"}}

    def test_circle_becomes_closed_stroke(self):
        values = from_cad.entity_to_path("cad_circle", {"center": [100, 50], "radius": 40}, self.PROPS, (10, 0))
        sub = values["subpaths"][0]
        self.assertTrue(sub["closed"])
        self.assertEqual(len(sub["nodes"]), 4)
        self.assertEqual((values["fill"], values["stroke"], values["stroke_width"], values["dash"], values["cap"]),
                         ("", "#ff0000", 2.0, [6.0, 3.0], "round"))
        self.assertEqual((values["x"], values["y"]), (70.0, -90.0))                   # Y retourné, place comprise
        x0, y0, x1, y1 = bz.bounds(values["subpaths"])
        self.assertAlmostEqual(x1 - x0, 80, delta=0.01)

    def test_polyline_with_arc_and_thin_line(self):
        pline = {"vertices": [[0, 0, 0.0], [10, 0, 1.0], [10, 10, 0.0]], "closed": False}    # demi-cercle au milieu
        values = from_cad.entity_to_path("cad_pline", pline, dict(self.PROPS, lineweight=0.0, pattern=()))
        self.assertEqual(len(values["subpaths"]), 1)
        self.assertFalse(values["subpaths"][0]["closed"])
        self.assertEqual((values["stroke_width"], values["dash"]), (from_cad.THIN, []))
        x0, _y0, x1, _y1 = bz.bounds(values["subpaths"])
        self.assertAlmostEqual(x1 - x0, 15, delta=0.01)                                 # renflement de rayon 5

    def test_hatches_become_fills_or_pattern_strokes(self):
        loops = [[[0, 0], [100, 0], [100, 100], [0, 100]], [[25, 25], [75, 25], [75, 75], [25, 75]]]
        solid = from_cad.entity_to_path("cad_hatch", {"loops": loops, "hatch_pattern": "solid", "hatch_alpha": 50},
                                        self.PROPS)
        self.assertEqual((solid["fill"], solid["stroke"], solid["fill_rule"], solid["opacity"]),
                         ("#ff0000", "", "evenodd", 0.5))
        self.assertEqual([s["closed"] for s in solid["subpaths"]], [True, True])
        gradient = from_cad.entity_to_path("cad_hatch", {"loops": loops, "hatch_pattern": "gradient",
                                                         "hatch_color2": "#00ff00"}, self.PROPS)
        self.assertEqual(gradient["fill_gradient"]["stops"], [[0.0, "#ff0000"], [1.0, "#00ff00"]])
        lines = from_cad.entity_to_path("cad_hatch", {"loops": loops, "hatch_pattern": "lines", "hatch_angle": 0,
                                                      "hatch_spacing": 10}, self.PROPS)
        self.assertEqual((lines["fill"], lines["stroke"]), ("", "#ff0000"))
        self.assertGreater(len(lines["subpaths"]), 8)
        self.assertIsNone(from_cad.entity_to_path("cad_text", {}, self.PROPS))


class ToCadCommandTest(IllTestCase):
    def test_convert_selection_replaces_and_undoes(self):
        ring = self.ctl.new_path(bz.ellipse(50, 50, 50, 50) + bz.ellipse(50, 50, 20, 20), QPointF(100, 100),
                                 dict(self.ctl.style, fill="#123456", stroke=""))
        self.ctl.commit_new(ring, "r")
        self.ctl.select([ring])
        count = self.scene.undo.count()
        new = self.ctl.convert_to_cad()
        self.assertEqual([i.kind for i in new], ["cad_pline", "cad_pline"])
        self.assertEqual({i.data["color"] for i in new}, {"#123456"})
        self.assertEqual(self.scene.undo.count(), count + 1)
        kinds = lambda: sorted(i.kind for i in self.scene._items.values() if i.kind in ("ill_path", "cad_pline"))
        self.assertEqual(kinds(), ["cad_pline", "cad_pline"])
        x0, y0, x1, y1 = new[0].doc_bounds()
        self.assertAlmostEqual(x1 - x0, 100, delta=0.2)
        self.assertAlmostEqual((y0 + y1) / 2, -150, delta=0.2)                        # centre (150, 150) scène
        self.scene.undo.undo()
        self.assertEqual(kinds(), ["ill_path"])

    def test_round_trip_back_to_illustrator(self):
        ring = self.ctl.new_path(bz.ellipse(50, 50, 50, 50), QPointF(100, 100),
                                 dict(self.ctl.style, fill="#123456", stroke=""))
        self.ctl.commit_new(ring, "r")
        self.ctl.select([ring])
        plines = self.ctl.convert_to_cad()
        self.pane.set_module("cad")
        for item in plines:
            item.setSelected(True)
        count = self.scene.undo.count()
        back = self.pane.cad.to_illustrator()
        self.assertEqual([i.kind for i in back], ["ill_path"])
        self.assertEqual(self.scene.undo.count(), count + 1)
        self.assertEqual((back[0].data["stroke"], back[0].data["fill"]), ("#123456", ""))
        r = back[0].geometry_rect()
        self.assertAlmostEqual(r.center().x(), 150, delta=0.2)
        self.assertAlmostEqual(r.center().y(), 150, delta=0.2)
        self.assertAlmostEqual(r.width(), 100, delta=0.2)
        self.assertIs(self.pane.illustrator, self.ctl)
        self.assertEqual(self.ctl.selection(), back)


if __name__ == "__main__":
    unittest.main()
