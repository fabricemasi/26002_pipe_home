"""Panneau Propriétés du module CAD : rayon d'un cercle (ou d'un arc) modifiable (2026-11-05)."""
import os as _os, sys as _sys  # jamais les vrais reglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import unittest

from test_cad import CadBoardCase


class RadiusTest(CadBoardCase):
    def test_circle_radius_is_editable(self):
        circle = self.ctl.create_entity("cad_circle", {"center": [0.0, 0.0], "radius": 50.0})
        self.ctl.scene.clearSelection()
        circle.setSelected(True)
        from fm_cad.cad_ui import PropertyRows
        handler = PropertyRows(self.ctl.ui)
        row = next(spec for spec in handler.specs() if spec[0] == "radius")
        self.assertEqual(row[2], "text")                                       # champ, plus une simple valeur
        handler._set_radius(str(80 / self.ctl.unit()))
        self.assertAlmostEqual(circle.data["radius"], 80.0)
        self.assertAlmostEqual(circle.geometry()["radius"], 80.0)
        handler._set_radius("-3")                                              # refuse
        self.assertAlmostEqual(circle.data["radius"], 80.0)
        self.ctl.undo()                                                        # une etape
        self.assertAlmostEqual(circle.data["radius"], 50.0)

    def test_gpu_end_segments_are_long_enough_for_a_border_radius(self):
        """GPU : plus aucun sommet a moins d'une demi-epaisseur d'un bout « border radius » (sinon le disque du joint
        voisin deborde et le bout parait rond, signale 2026-11-05)."""
        import math
        from fm_cad import cad_gpu
        end = {"style": "radius", "radius": 50.0}
        arc = self.ctl.create_entity("cad_arc", {"center": [0.0, 0.0], "radius": 113.4, "start": 12.0, "end": 348.0,
                                                 "lineweight": 22.68, "end1": end, "end2": end})
        rows = cad_gpu.item_instances(arc, False, 0.03)
        for row in (rows[0], rows[-1]):
            self.assertGreaterEqual(math.hypot(row[2] - row[0], row[3] - row[1]), 11.34 - 1e-6)
        self.assertGreater(len(rows), 20)                                       # le reste reste finement decoupe


class ArcEndTest(unittest.TestCase):
    def test_arc_path_starts_on_the_arc(self):
        """Signale 2026-11-05 : bout d'un cercle coupe avec une encoche (segment minuscule ajoute par arcTo)."""
        from fm_cad.cad_items import scene_path
        path = scene_path([("arc", (-110.92193792321358, -23.57718573873391), 113.4, 12.0, 336.0)])
        first, second = path.elementAt(0), path.elementAt(1)
        self.assertTrue(first.isMoveTo())
        self.assertFalse(second.isLineTo())                                    # directement la courbe, pas de segment
        self.assertAlmostEqual(first.x, 0.0, delta=0.1)                         # approximation des arcs de Qt
        self.assertAlmostEqual(first.y, 0.0, delta=0.1)


class ThickCircleTest(unittest.TestCase):
    def test_thick_circle_and_arc_are_round_inside_and_out(self):
        """Signale 2026-11-05 : trou « carre » d'un cercle tres epais (decalage approche des Bezier par Qt)."""
        import math
        from PySide6.QtCore import QPointF, Qt
        from PySide6.QtGui import QPainterPath
        from fm_cad.cad_items import stroke_outline
        r, half = 20.0, 14.0
        ring = stroke_outline([("arc", (0.0, 0.0), r, 0.0, 360.0)], half, None, None, True)
        merged = QPainterPath()
        merged.setFillRule(Qt.WindingFill)                                    # comme les lots (ThickPaths)
        merged.addPath(ring)
        for path in (ring, merged):
            for k in range(72):
                a = math.radians(k * 5 + 2.5)
                at = lambda rho: QPointF(rho * math.cos(a), rho * math.sin(a))
                self.assertTrue(path.contains(at(r + half - 0.05)))
                self.assertFalse(path.contains(at(r + half + 0.05)))
                self.assertTrue(path.contains(at(r - half + 0.05)))
                self.assertFalse(path.contains(at(r - half - 0.05)))               # le trou est rond, et vide
        arc = stroke_outline([("arc", (0.0, 0.0), r, 30.0, 120.0)], half, {"style": "round"}, {"style": "flat"}, False)
        mid = math.radians(90.0)
        self.assertTrue(arc.contains(QPointF((r - half + 0.05) * math.cos(mid), -(r - half + 0.05) * math.sin(mid))))
        self.assertFalse(arc.contains(QPointF((r - half - 0.05) * math.cos(mid), -(r - half - 0.05) * math.sin(mid))))
        start = (r * math.cos(math.radians(30)), -r * math.sin(math.radians(30)))
        self.assertTrue(arc.contains(QPointF(start[0] + 0.0, start[1] + half - 0.1)))   # disque au bout « arrondi »


class RadiusEndTest(unittest.TestCase):
    def test_border_radius_end_of_a_thick_arc(self):
        """Signale 2026-11-05 : bout « border radius » d'un cercle coupe rendu franc (classique) ou rond (GPU)."""
        import math
        from PySide6.QtCore import QPointF
        from fm_cad import cad_gpu
        from fm_cad.cad_items import stroke_outline
        r, half = 100.0, 10.0
        end = {"style": "radius", "radius": 50.0}                              # coins de 5
        path = stroke_outline([("arc", (0.0, 0.0), r, 0.0, 90.0)], half, end, end, False)
        # bout de depart : rayon radial y = 0 (scene), le trace part vers le haut (y scene negatif)
        self.assertFalse(path.contains(QPointF(r + half - 0.3, -0.3)))         # coin exterieur arrondi
        self.assertFalse(path.contains(QPointF(r - half + 0.3, -0.3)))         # coin interieur arrondi
        self.assertTrue(path.contains(QPointF(r, -0.3)))                       # milieu du bout : franc
        self.assertTrue(path.contains(QPointF(r + half - 0.3, -6.0)))          # au-dela du coin : plein


if __name__ == "__main__":
    unittest.main()
