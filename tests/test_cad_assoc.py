"""COTATIONS ASSOCIATIVES (phase 5 du module CAD ; fm_cad/cad_assoc.py, liens poses par les commandes de cotation,
suivi par `cad_items.CadLayer._follow_dims`) : la cote suit l'objet cote (deplace, etire, annule), se detache quand on
tire son point a la main, rayon / diametre suivent le cercle."""
import os as _os, sys as _sys  # jamais les vrais reglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import unittest

from fm_cad import cad_assoc, cad_shapes
from test_cad import CadBoardCase, settle


class AssocLogicTest(unittest.TestCase):
    def test_follow_moves_linked_points_and_detaches_hand_moved_ones(self):
        grips = {"L": ([("p1", (10.0, 0.0)), ("p2", (30.0, 5.0))], None)}
        links = {"p1": ["L", "p1", 0.0, 0.0], "p2": ["L", "p2", 20.0, 0.0]}
        moved, new = cad_assoc.follow({"p1": (0.0, 0.0), "p2": (20.0, 0.0)}, links, grips.get)
        self.assertEqual(moved, {"p1": (10.0, 0.0), "p2": (30.0, 5.0)})
        self.assertEqual(new["p2"], ["L", "p2", 30.0, 5.0])
        moved, new = cad_assoc.follow({"p1": (99.0, 99.0), "p2": (30.0, 5.0)}, new, grips.get)   # p1 tire a la main
        self.assertEqual(moved, {})
        self.assertNotIn("p1", new)
        self.assertIn("p2", new)
        moved, new = cad_assoc.follow({"p1": (0.0, 0.0), "p2": (30.0, 5.0)}, new, lambda _i: None)  # objet efface
        self.assertEqual((moved, new), ({}, {}))

    def test_circle_link(self):
        circle = {"C": ([], ((5.0, 5.0), 4.0))}
        links = {"circle": ["C", 0.0, 0.0, 2.0]}
        moved, new = cad_assoc.follow({"p1": (0.0, 0.0), "p2": (2.0, 0.0)}, links, circle.get)
        self.assertEqual(moved, {"p1": (5.0, 5.0), "p2": (9.0, 5.0)})
        self.assertEqual(new["circle"], ["C", 5.0, 5.0, 4.0])

    def test_clean_drops_malformed_links(self):
        self.assertEqual(cad_assoc.clean({"p1": ["a", "p1", 1, 2], "p2": "x", "circle": [1, 2]}),
                         {"p1": ["a", "p1", 1.0, 2.0]})


class AssocOnTheBoardTest(CadBoardCase):
    def dims(self):
        return [i for i in self.ctl.cad_items() if i.kind == "cad_dim"]

    def select(self, *items):
        self.pane.scene.clearSelection()
        for item in items:
            item.setSelected(True)

    def test_dimension_of_a_picked_line_follows_it(self):
        line = self.line((0, 0), (100, 0))
        self.type("DLI", "")                                 # Entree : choisir l'objet
        self.click((50, 0))
        self.type("50,30")
        (dim,) = self.dims()
        self.assertEqual(set(dim.data["assoc"]), {"p1", "p2"})
        self.assertEqual(dim.measured_text(), "100")
        self.select(line)
        self.type("M", "0,0", "0,50")                         # deplacer la ligne seule
        settle(0.05)
        self.assertEqual([round(v, 6) for v in dim.geometry()["p1"]], [0.0, 50.0])
        self.select(line)
        self.ctl.run("STRETCH")
        self.type("90,40", "110,60", "0,0", "20,0")            # etirer le bout droit de la ligne
        settle(0.05)
        self.assertEqual(dim.measured_text(), "120")
        self.ctl.undo()
        settle(0.05)
        self.assertEqual(dim.measured_text(), "100")         # l'annulation aussi
        self.ctl.undo()
        settle(0.05)
        self.assertEqual([round(v, 6) for v in dim.geometry()["p1"]], [0.0, 0.0])

    def test_moving_line_and_dimension_together_keeps_the_link(self):
        line = self.line((0, 0), (100, 0))
        self.type("DLI", "")
        self.click((50, 0))
        self.type("50,30")
        (dim,) = self.dims()
        self.select(line, dim)
        self.type("M", "0,0", "10,10")
        settle(0.05)
        self.assertEqual(set(dim.data["assoc"]), {"p1", "p2"})
        self.select(line)
        self.type("M", "0,0", "5,0")
        settle(0.05)
        self.assertEqual([round(v, 6) for v in dim.geometry()["p1"]], [15.0, 10.0])

    def test_radius_dimension_follows_its_circle(self):
        self.type("C", "0,0", "20")
        (circle,) = [i for i in self.ctl.cad_items() if i.kind == "cad_circle"]
        self.ctl.run("DIMRADIUS")
        self.click((20, 0))
        self.type("40,0")
        (dim,) = self.dims()
        self.assertIn("circle", dim.data["assoc"])
        self.pane.scene.change_items([circle], lambda i: i.data.update(radius=35.0), "rayon")
        settle(0.05)
        self.assertEqual(dim.measured_text(), "R35")
        self.assertAlmostEqual(cad_shapes.prims("cad_circle", circle.geometry())[0][2], 35.0)

    def test_angular_dimension_follows_its_two_lines_and_its_arc(self):
        self.line((0, 0), (100, 0))
        b = self.line((0, 0), (0, 100))
        self.ctl.run("DIMANGULAR")
        self.click((60, 0))
        self.click((0, 60))
        self.type("30,30")
        (dim,) = self.dims()
        self.assertIn("lines", dim.data["assoc"])
        self.assertEqual(dim.measured_text().replace(",", ".").rstrip("°"), "90")
        self.pane.scene.change_items([b], lambda i: i.data.update(p2=[100.0, 100.0]), "tourner")   # 45 degres
        settle(0.05)
        self.assertEqual(dim.measured_text().replace(",", ".").rstrip("°"), "45")
        self.ctl.undo()
        settle(0.05)
        self.assertEqual(dim.measured_text().replace(",", ".").rstrip("°"), "90")

    def test_angular_link_logic(self):
        grips = {"A": ([("center", (0.0, 0.0)), ("start", (10.0, 0.0)), ("end", (0.0, 10.0))], None)}
        moved, new = cad_assoc.follow({"center": (5.0, 5.0), "p1": (15.0, 5.0), "p2": (5.0, 15.0)},
                                      {"arc": ["A", 5.0, 5.0]}, grips.get)
        self.assertEqual(moved, {"center": (0.0, 0.0), "p1": (10.0, 0.0), "p2": (0.0, 10.0)})
        self.assertEqual(new["arc"], ["A", 0.0, 0.0])
        moved, new = cad_assoc.follow({"center": (50.0, 50.0), "p1": (15.0, 5.0), "p2": (5.0, 15.0)},
                                      {"arc": ["A", 5.0, 5.0]}, grips.get)          # sommet tire a la main
        self.assertEqual((moved, new), ({}, {}))
        self.assertEqual(cad_assoc.targets({"lines": ["a", 0.5, "b", 0.5, 0, 0]}), {"a", "b"})


if __name__ == "__main__":
    unittest.main()
