"""Commandes courantes d'AutoCAD ajoutees le 2026-11-04 (fm_cad/cad_commands_extra.py, geometrie fm_cad/cad_draw.py) :
ID, DIST, AIRE, LISTE, COTATION CONTINUE / DE LIGNE DE BASE, REPERE, ALLONGER, PEDIT, ANNEAU, NUAGE DE REVISION,
ORDRE DE TRACE, ZOOM."""
import os as _os, sys as _sys  # jamais les vrais reglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import math
import unittest

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from fm_cad import cad_draw, cad_shapes
from test_cad import CadBoardCase


class PureTest(unittest.TestCase):
    def test_areas(self):
        square = [("segment", (0.0, 0.0), (10.0, 0.0)), ("segment", (10.0, 0.0), (10.0, 10.0)),
                  ("segment", (10.0, 10.0), (0.0, 10.0)), ("segment", (0.0, 10.0), (0.0, 0.0))]
        self.assertAlmostEqual(cad_draw.prims_area(square), 100.0)
        circle = [("arc", (3.0, 4.0), 5.0, 0.0, 360.0)]
        self.assertAlmostEqual(cad_draw.prims_area(circle), math.pi * 25.0)
        half = cad_shapes.prims("cad_pline", {"vertices": [[0.0, 0.0, 1.0], [10.0, 0.0, 0.0]], "closed": True})
        self.assertAlmostEqual(abs(cad_draw.prims_area(half)), math.pi * 25.0 / 2.0)   # demi-disque

    def test_lengthen(self):
        line = {"p1": [0.0, 0.0], "p2": [10.0, 0.0]}
        self.assertEqual(cad_draw.lengthened("cad_line", line, (9.0, 0.0), "delta", 5.0)["p2"], [15.0, 0.0])
        self.assertEqual(cad_draw.lengthened("cad_line", line, (1.0, 0.0), "total", 4.0)["p1"], [6.0, 0.0])
        self.assertEqual(cad_draw.lengthened("cad_line", line, (9.0, 0.0), "percent", 50.0)["p2"], [5.0, 0.0])
        self.assertIsInstance(cad_draw.lengthened("cad_line", line, (9.0, 0.0), "delta", -20.0), str)
        arc = {"center": [0.0, 0.0], "radius": 10.0, "start": 0.0, "end": 90.0}
        out = cad_draw.lengthened("cad_arc", arc, (0.0, 10.0), "total", math.pi * 10.0)      # demi-tour
        self.assertAlmostEqual(out["end"], 180.0)

    def test_revcloud_bulges_outwards(self):
        verts = cad_draw.revcloud_vertices([(0, 0), (100, 0), (100, 50), (0, 50)], 25.0)
        self.assertEqual(len(verts), 4 + 2 + 4 + 2)
        primitives = cad_shapes.prims("cad_pline", {"vertices": verts, "closed": True})
        box = cad_shapes.bounds(primitives)
        self.assertLess(box[1], -1.0)                                     # les arcs du bas sortent du rectangle


class ExtraCommandsTest(CadBoardCase):
    def kinds(self, kind):
        return [i for i in self.ctl.cad_items() if i.kind == kind]

    def select(self, *items):
        self.pane.scene.clearSelection()
        for item in items:
            item.setSelected(True)

    def last(self):
        return self.ctl.history[-1][0]

    def test_id_dist_area_list(self):
        self.type("ID", "12,5")
        self.assertIn("X = 12", self.last())
        self.type("DI", "0,0", "30,40")
        self.assertIn("Distance = 50", self.last())
        self.type("AIRE", "0,0", "10,0", "10,10", "0,10", "")
        self.assertIn("Aire = 100", self.last())
        self.type("C", "0,0", "10")
        self.ctl.run("AREA")
        self.type("O")
        self.click((10, 0))
        self.assertIn(f"Aire = {math.pi * 100:.6g}", self.last())
        line = self.line((0, 0), (3, 4))
        self.select(line)
        self.type("LI")
        self.assertTrue(any("longueur 5" in text for text, _k in self.ctl.history[-3:]))

    def test_dim_continue_and_baseline(self):
        self.type("DLI", "0,0", "100,0", "50,20")
        self.type("DCO", "150,0", "200,0", "")
        dims = self.kinds("cad_dim")
        self.assertEqual(len(dims), 3)
        texts = sorted(d.measured_text() for d in dims)
        self.assertEqual(texts, ["100", "50", "50"])
        self.assertTrue(all(abs(d.geometry()["pos"][1] - 20.0) < 1e-9 for d in dims))   # meme ligne de cote
        self.ctl.undo()
        self.assertEqual(len(self.kinds("cad_dim")), 1)                                  # une etape
        self.type("DBA", "150,0", "")
        base = [d for d in self.kinds("cad_dim") if d.measured_text() == "150"]
        self.assertEqual(len(base), 1)
        self.assertGreater(base[0].geometry()["pos"][1], 20.0)                          # decalee vers l'exterieur

    def test_leader_makes_a_line_an_arrow_and_a_text(self):
        self.type("LE", "0,0", "50,50", "")
        for ch in "Note":
            QTest.keyClick(self.pane.view, ch)
        QTest.keyClick(self.pane.view, Qt.Key_Return, Qt.ControlModifier)
        self.assertEqual([t.text() for t in self.kinds("cad_text")], ["Note"])
        self.assertEqual(len(self.kinds("cad_pline")), 1)
        self.assertEqual(len(self.kinds("cad_hatch")), 1)
        self.ctl.undo()
        self.assertEqual(self.kinds("cad_text") + self.kinds("cad_pline") + self.kinds("cad_hatch"), [])

    def test_lengthen_and_pedit(self):
        line = self.line((0, 0), (100, 0))
        self.ctl.run("LENGTHEN")
        self.type("DE", "20")
        self.click((90, 0))
        self.type("")
        self.assertEqual(line.points(), ((0.0, 0.0), (120.0, 0.0)))
        self.ctl.run("PEDIT")
        self.click((60, 0))
        self.type("O", "Q")                                                              # convertir : Oui
        (pline,) = self.kinds("cad_pline")
        other = self.line((120, 0), (120, 50))
        self.ctl.run("PEDIT")
        self.click((60, 0))
        self.type("J")
        self.click((120, 30))
        self.type("C", "Q")                                    # (Entree a l'invite des options = Quitter)
        (pline,) = self.kinds("cad_pline")
        self.assertEqual(len(pline.data["vertices"]), 3)
        self.assertTrue(pline.data["closed"])
        self.assertTrue(other.scene() is None or other not in self.ctl.cad_items())

    def test_donut_and_revcloud(self):
        self.type("DO", "10", "20", "0,0", "100,0", "")
        rings = self.kinds("cad_pline")
        self.assertEqual(len(rings), 2)
        self.assertAlmostEqual(rings[0].data["lineweight"], 5.0)
        box = cad_shapes.bounds(rings[0].prims())
        self.assertAlmostEqual(box[2] - box[0], 15.0)                                     # rayon moyen 7,5
        self.type("DO", "0", "20", "300,0", "")
        self.assertEqual(len(self.kinds("cad_hatch")), 1)                                  # disque plein
        self.type("REVCLOUD", "0,200", "100,260")
        clouds = [p for p in self.kinds("cad_pline") if p.data["closed"] and len(p.data["vertices"]) > 4]
        self.assertEqual(len(clouds), 1)

    def test_draworder_and_zoom(self):
        a = self.line((0, 0), (100, 0))
        b = self.line((0, 10), (100, 10))
        self.select(a)
        self.type("DR", "P")
        self.assertGreater(a.zValue(), b.zValue())
        self.ctl.undo()
        self.assertLess(a.zValue(), b.zValue())
        view = self.pane.view
        zoom = view.zoom()
        self.type("Z", "2")
        self.assertAlmostEqual(view.zoom(), zoom * 2, places=6)
        self.type("Z", "P")
        self.assertAlmostEqual(view.zoom(), zoom, places=6)
        self.type("Z", "0,0", "200,100")
        self.assertGreater(view.zoom(), 1.0)
        self.type("Z", "E")


if __name__ == "__main__":
    unittest.main()
