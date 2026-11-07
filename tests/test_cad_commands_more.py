"""Commandes des phases 2 et 3 du module CAD (fm_cad/cad_commands_more.py, geometrie fm_cad/cad_draw.py, points
fm_cad/cad_point.py ; demande de l'utilisateur, 2026-11-04 : « continue a enchainer tous les modules autocad
manquants ») : POINT, DIVISER, MESURER, ELLIPSE, POLYGONE, PROLONGER, ETIRER, COUPURE, JOINDRE, RESEAU."""
import os as _os, sys as _sys  # jamais les vrais reglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import math
import unittest

from fm_cad import cad_commands, cad_draw, cad_point, cad_shapes
from fm_cad import cad_geometry as geo
from fm_cad.cad_commands_more import break_pieces, stretched
from test_cad import CadBoardCase, settle


class PureGeometryTest(unittest.TestCase):
    def test_every_planned_command_is_now_available(self):
        for name in ("ELLIPSE", "POLYGON", "EXTEND", "STRETCH", "BREAK", "JOIN", "ARRAY", "POINT", "DIVIDE",
                     "MEASURE", "BREAKATPOINT"):
            entry = cad_commands.lookup(name)
            self.assertTrue(entry is not None and entry.available, name)
        self.assertFalse([e.name for e in cad_commands.REGISTRY if e.planned])

    def test_ellipse_polyline_stays_on_the_ellipse(self):
        center, major, ratio = (10.0, 5.0), (40.0, 30.0), 0.4                # demi grand axe 50, tourne
        vertices, closed = cad_draw.ellipse_vertices(center, major, ratio)
        self.assertTrue(closed)
        self.assertEqual(len(vertices), cad_draw.ELLIPSE_ARCS)
        primitives = cad_shapes.prims("cad_pline", {"vertices": vertices, "closed": True})
        a = math.hypot(*major)
        for p in cad_shapes.tessellate(primitives, 0.01)[0]:                 # tout point du trace est sur l'ellipse
            ux, uy = major[0] / a, major[1] / a
            dx, dy = p[0] - center[0], p[1] - center[1]
            x, y = dx * ux + dy * uy, -dx * uy + dy * ux
            self.assertAlmostEqual((x / a) ** 2 + (y / (a * ratio)) ** 2, 1.0, delta=2e-3)
        quadrants = [cad_draw.ellipse_point(center, major, ratio, t) for t in (0, math.pi / 2, math.pi)]
        for q in quadrants:                                                  # sommets aux quadrants
            self.assertTrue(any(geo.distance(q, v[:2]) < 1e-9 for v in vertices))

    def test_polygons(self):
        verts = cad_draw.polygon_vertices((0.0, 0.0), 6, (10.0, 0.0), inscribed=True)
        self.assertEqual(len(verts), 6)
        self.assertTrue(all(abs(math.hypot(v[0], v[1]) - 10.0) < 1e-9 for v in verts))
        out = cad_draw.polygon_vertices((0.0, 0.0), 4, (0.0, 10.0), inscribed=False)
        mids = [geo.midpoint(out[i][:2], out[(i + 1) % 4][:2]) for i in range(4)]
        self.assertTrue(any(geo.distance(m, (0.0, 10.0)) < 1e-9 for m in mids))   # milieu d'un cote au point
        edge = cad_draw.polygon_from_edge((0.0, 0.0), (10.0, 0.0), 3)
        self.assertAlmostEqual(edge[2][0], 5.0)
        self.assertAlmostEqual(edge[2][1], 10.0 * math.sqrt(3) / 2)                 # a gauche du cote

    def test_arrays(self):
        self.assertEqual(len(cad_draw.rect_offsets(3, 2, 10.0, 5.0)), 5)
        self.assertEqual(cad_draw.polar_steps(4, 360.0), [90.0, 180.0, 270.0])
        self.assertEqual(cad_draw.polar_steps(3, 180.0), [90.0, 180.0])
        line = [("segment", (0.0, 0.0), (100.0, 0.0))]
        stations = cad_draw.path_stations(line, 5)
        self.assertEqual([round(p[0]) for p, _a in stations], [0, 25, 50, 75, 100])

    def test_break_pieces(self):
        line = {"p1": [0.0, 0.0], "p2": [100.0, 0.0]}
        pieces = break_pieces("cad_line", line, (30.0, 0.0), (60.0, 0.0))
        self.assertEqual([round(cad_shapes.total_length(p)) for p in pieces], [30, 40])
        pieces = break_pieces("cad_line", line, (40.0, 0.0), (40.0, 0.0))             # coupure au point
        self.assertEqual([round(cad_shapes.total_length(p)) for p in pieces], [40, 60])
        circle = {"center": [0.0, 0.0], "radius": 10.0}
        (kept,) = break_pieces("cad_circle", circle, (10.0, 0.0), (0.0, 10.0))       # retire le quart 0 -> 90
        self.assertAlmostEqual(cad_shapes.total_length(kept), 2 * math.pi * 10 * 0.75, places=6)
        self.assertIsInstance(break_pieces("cad_line", line, (0.0, 0.0), (0.0, 0.0)), str)

    def test_stretch_moves_only_the_points_in_the_crossing(self):
        line = {"p1": [0.0, 0.0], "p2": [10.0, 0.0]}
        rect = (8.0, -1.0, 12.0, 1.0)
        self.assertEqual(stretched("cad_line", line, rect, (5.0, 0.0)), {"p1": [0.0, 0.0], "p2": [15.0, 0.0]})
        pline = {"vertices": [[0.0, 0.0, 0.0], [10.0, 0.0, 0.0], [10.0, 10.0, 0.0]], "closed": False}
        out = stretched("cad_pline", pline, (9.0, -1.0, 11.0, 11.0), (0.0, 3.0))
        self.assertEqual([v[:2] for v in out["vertices"]], [[0.0, 0.0], [10.0, 3.0], [10.0, 13.0]])
        whole = stretched("cad_line", line, (-1.0, -1.0, 11.0, 1.0), (1.0, 1.0))      # tout dedans : deplacee
        self.assertEqual(whole, {"p1": [1.0, 1.0], "p2": [11.0, 1.0]})
        self.assertIsNone(stretched("cad_line", line, (20.0, 20.0, 30.0, 30.0), (1.0, 0.0)))

    def test_join_chains_lines_arcs_and_polylines(self):
        pieces = [([("segment", (0.0, 0.0), (10.0, 0.0))], "a"), ([("segment", (20.0, 0.0), (10.0, 0.0))], "b")]
        (found,) = cad_draw.chain(pieces, 1e-6)
        self.assertEqual(cad_draw.joined(found, 1e-6), ("cad_line", {"p1": [0.0, 0.0], "p2": [20.0, 0.0]}))
        arcs = [([("arc", (0.0, 0.0), 5.0, 0.0, 90.0)], 1), ([("arc", (0.0, 0.0), 5.0, 90.0, 90.0)], 2)]
        kind, data = cad_draw.joined(cad_draw.chain(arcs, 1e-6)[0], 1e-6)
        self.assertEqual(kind, "cad_arc")
        self.assertEqual((round(data["start"]), round(data["end"])), (0, 180))
        mixed = [([("segment", (0.0, 0.0), (10.0, 0.0))], 1), ([("segment", (10.0, 0.0), (10.0, 10.0))], 2)]
        kind, data = cad_draw.joined(cad_draw.chain(mixed, 1e-6)[0], 1e-6)
        self.assertEqual((kind, len(data["vertices"])), ("cad_pline", 3))

    def test_point_figures(self):
        dot = cad_point.prims({"pos": [1.0, 2.0], "pdmode": 0, "pdsize": 10.0})
        self.assertEqual(dot, [("segment", (1.0, 2.0), (1.0, 2.0))])
        circle_cross = cad_point.prims({"pos": [0.0, 0.0], "pdmode": 34, "pdsize": 10.0})
        self.assertEqual(sorted(p[0] for p in circle_cross), ["arc", "segment", "segment"])
        self.assertEqual(cad_point.clean_mode(5), 0)
        self.assertEqual(cad_point.clean_mode(99), 99)
        self.assertEqual(cad_shapes.rotated("cad_point", {"pos": [10.0, 0.0]}, (0.0, 0.0), 90.0)["pos"][1], 10.0)


class CommandsOnTheBoardTest(CadBoardCase):
    def kinds(self, kind):
        return [i for i in self.ctl.cad_items() if i.kind == kind]

    def select(self, *items):
        self.pane.scene.clearSelection()
        for item in items:
            item.setSelected(True)

    def test_point_divide_and_measure(self):
        self.ctl.apply_settings(dict(self.ctl.settings, board_cad_point_mode=3, board_cad_point_size=500))
        self.type("PO", "10,10", "20,20", "")
        points = self.kinds("cad_point")
        self.assertEqual(len(points), 2)
        self.assertEqual((points[0].data["pdmode"], points[0].data["pdsize"]), (3, 5.0))
        self.assertEqual(points[0].snap_primitives(), [("segment", (10.0, 10.0), (10.0, 10.0))])
        self.ctl.undo()
        self.assertEqual(self.kinds("cad_point"), [])                                  # une etape
        line = self.line((0, 0), (100, 0))
        self.ctl.run("DIVIDE")
        self.click((50, 0))
        self.type("4")
        xs = sorted(round(p.data["pos"][0]) for p in self.kinds("cad_point"))
        self.assertEqual(xs, [25, 50, 75])
        self.ctl.run("MEASURE")
        self.click((90, 0))                                                            # depuis le bout de droite
        self.type("30")
        xs = sorted(round(p.data["pos"][0]) for p in self.kinds("cad_point"))
        self.assertEqual(xs, [10, 25, 40, 50, 70, 75])
        self.assertTrue(line.scene() is self.pane.scene)

    def test_ellipse_by_axis_and_by_center_with_an_arc(self):
        self.type("EL", "0,0", "100,0", "20")
        (ellipse,) = self.kinds("cad_pline")
        self.assertTrue(ellipse.closed())
        box = cad_shapes.bounds(ellipse.prims())
        self.assertAlmostEqual(box[0], 0.0, places=3)
        self.assertAlmostEqual(box[2], 100.0, places=3)
        self.assertAlmostEqual(box[3] - box[1], 40.0, delta=0.05)
        self.type("EL", "C", "500,0", "550,0", "10")
        self.assertEqual(len(self.kinds("cad_pline")), 2)
        self.type("EL", "A", "0,300", "100,300", "20", "0", "180")
        arc = self.kinds("cad_pline")[-1]
        self.assertFalse(arc.closed())
        start, end = arc.points()
        self.assertAlmostEqual(start[0], 100.0, places=3)
        self.assertAlmostEqual(end[0], 0.0, places=3)

    def test_polygon_inscribed_circumscribed_and_edge(self):
        self.type("POL", "6", "0,0", "I", "50")
        (hexagon,) = self.kinds("cad_pline")
        self.assertEqual(len(hexagon.data["vertices"]), 6)
        ys = [v[1] for v in hexagon.data["vertices"]]
        self.assertEqual(sum(1 for y in ys if abs(y - min(ys)) < 1e-9), 2)            # un cote du bas horizontal
        self.type("POL", "", "C", "0,0", "100,0")
        self.assertEqual(len(self.kinds("cad_pline")[-1].data["vertices"]), 6)        # nombre de cotes retenu
        self.type("POL", "4", "300,0", "C", "300,50")
        square = self.kinds("cad_pline")[-1]
        box = cad_shapes.bounds(square.prims())
        self.assertAlmostEqual(box[3] - box[1], 100.0, places=6)

    def test_extend_to_the_nearest_boundary_and_shift_trims(self):
        self.line((100, -50), (100, 50))
        target = self.line((0, 0), (60, 0))
        self.ctl.run("EXTEND")
        self.click((55, 0))
        self.assertEqual(target.points(), ((0.0, 0.0), (100.0, 0.0)))
        self.type("")
        self.ctl.undo()
        self.assertEqual(target.points(), ((0.0, 0.0), (60.0, 0.0)))

    def test_stretch_with_a_crossing(self):
        line = self.line((0, 0), (100, 0))
        other = self.line((200, 200), (300, 200))
        self.type("S", "90,-10", "110,10", "0,0", "50,0")
        self.assertEqual(line.points(), ((0.0, 0.0), (150.0, 0.0)))
        self.assertEqual(other.points(), ((200.0, 200.0), (300.0, 200.0)))

    def test_break_and_break_at_point(self):
        line = self.line((0, 0), (100, 0))
        self.ctl.run("BREAK")
        self.click((30, 0))
        self.type("60,0")
        lines = sorted(i.points() for i in self.kinds("cad_line"))
        self.assertEqual(lines, [((0.0, 0.0), (30.0, 0.0)), ((60.0, 0.0), (100.0, 0.0))])
        self.ctl.undo()
        self.assertEqual([i.points() for i in self.kinds("cad_line")], [((0.0, 0.0), (100.0, 0.0))])
        self.ctl.run("BREAKATPOINT")
        self.click((40, 0))
        self.type("40,0")
        self.assertEqual(len(self.kinds("cad_line")), 2)
        self.assertTrue(line.scene() is self.pane.scene)

    def test_join(self):
        a = self.line((0, 0), (50, 0))
        b = self.line((50, 0), (100, 0))
        c = self.line((100, 0), (100, 40))
        self.select(a, b)
        self.type("J")
        self.assertEqual([i.points() for i in self.kinds("cad_line") if i is not c], [((0.0, 0.0), (100.0, 0.0))])
        self.select(*self.kinds("cad_line"))
        self.type("J")
        (pline,) = self.kinds("cad_pline")
        self.assertEqual(len(pline.data["vertices"]), 3)
        self.assertEqual(self.kinds("cad_line"), [])
        self.ctl.undo()
        self.assertEqual(len(self.kinds("cad_line")), 2)

    def test_rect_polar_and_path_arrays(self):
        line = self.line((0, 0), (10, 0))
        self.select(line)
        self.type("AR", "R", "3", "2", "20", "30")
        self.assertEqual(len(self.kinds("cad_line")), 6)
        starts = sorted(i.points()[0] for i in self.kinds("cad_line"))
        self.assertIn((40.0, 30.0), starts)
        self.ctl.undo()
        self.assertEqual(len(self.kinds("cad_line")), 1)
        self.select(line)
        self.type("AR", "PO", "0,-50", "4", "360", "O")
        lines = self.kinds("cad_line")
        self.assertEqual(len(lines), 4)
        ends = {tuple(round(v, 6) + 0.0 for v in i.points()[0]) for i in lines}
        self.assertIn((0.0, -100.0), ends)                                            # 180° autour du centre
        self.ctl.undo()
        path = self.line((0, 100), (100, 100))
        self.select(line)
        self.ctl.run("ARRAY")
        self.type("H")
        self.click((50, 100))
        self.type("", "3", "N")
        self.assertEqual(len(self.kinds("cad_line")), 4)                              # original + 2 copies + chemin
        self.assertTrue(path.scene() is self.pane.scene)


if __name__ == "__main__":
    unittest.main()
