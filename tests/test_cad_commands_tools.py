"""ALIGNER, SUPPRIMER LES DOUBLONS (OVERKILL) et SPLINE du module CAD (fm_cad/cad_commands_tools.py ; 2026-11-04)."""
import os as _os, sys as _sys  # jamais les vrais reglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import unittest

from fm_cad import cad_shapes
from fm_cad import cad_geometry as geo
from fm_cad.cad_commands_tools import overkill, spline_points, spline_vertices
from test_cad import CadBoardCase


class PureTest(unittest.TestCase):
    def test_overkill_removes_duplicates_and_merges_collinear_lines(self):
        entries = [("a", "cad_line", {"p1": [0.0, 0.0], "p2": [10.0, 0.0]}),
                   ("b", "cad_line", {"p1": [10.0, 0.0], "p2": [0.0, 0.0]}),          # doublon (sens inverse)
                   ("c", "cad_line", {"p1": [5.0, 0.0], "p2": [20.0, 0.0]}),          # chevauche a
                   ("d", "cad_line", {"p1": [0.0, 5.0], "p2": [10.0, 5.0]}),          # parallele : gardee
                   ("e", "cad_circle", {"center": [0.0, 0.0], "radius": 3.0}),
                   ("f", "cad_circle", {"center": [0.0, 0.0], "radius": 3.0})]
        gone, changed = overkill(entries, 1e-6)
        self.assertEqual(sorted(gone), ["b", "c", "f"])
        self.assertIn(("a", {"p1": [0.0, 0.0], "p2": [20.0, 0.0]}), changed)

    def test_spline_passes_through_its_points(self):
        pts = [(0.0, 0.0), (10.0, 10.0), (20.0, 0.0), (30.0, 10.0)]
        curve = spline_points(pts)
        for p in pts:
            self.assertTrue(any(geo.distance(p, q) < 1e-9 for q in curve))
        verts = spline_vertices(pts)
        primitives = cad_shapes.prims("cad_pline", {"vertices": verts, "closed": False})
        self.assertAlmostEqual(cad_shapes.prim_start(primitives[0])[0], 0.0)
        self.assertAlmostEqual(cad_shapes.prim_end(primitives[-1])[0], 30.0)
        self.assertTrue(any(p[0] == "arc" for p in primitives))


class ToolsOnTheBoardTest(CadBoardCase):
    def kinds(self, kind):
        return [i for i in self.ctl.cad_items() if i.kind == kind]

    def select(self, *items):
        self.pane.scene.clearSelection()
        for item in items:
            item.setSelected(True)

    def test_align_moves_turns_and_scales(self):
        line = self.line((0, 0), (10, 0))
        self.select(line)
        self.type("AL", "0,0", "100,100", "10,0", "100,120", "O")
        a, b = line.points()
        self.assertEqual(tuple(round(v, 6) for v in a), (100.0, 100.0))
        self.assertEqual(tuple(round(v, 6) for v in b), (100.0, 120.0))                # tournee + echelle x2
        self.ctl.undo()
        self.select(line)
        self.type("AL", "0,0", "5,5", "")                                             # une paire : deplacer
        self.assertEqual(line.points(), ((5.0, 5.0), (15.0, 5.0)))

    def test_overkill_and_spline(self):
        self.line((0, 0), (10, 0))
        self.type("L", "10,0", "0,0", "")
        self.type("OVERKILL", "TOUT", "")
        self.assertEqual(len(self.kinds("cad_line")), 1)
        self.type("SPL", "0,50", "20,70", "40,50", "")
        (spline,) = self.kinds("cad_pline")
        self.assertFalse(spline.closed())
        self.type("SPL", "0,100", "20,120", "40,100", "C")
        self.assertTrue(self.kinds("cad_pline")[-1].closed())


if __name__ == "__main__":
    unittest.main()
