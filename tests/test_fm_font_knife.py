"""fm_font, COUTEAU : coupe exacte de contours fermés (rectangle, « o » avec contre-forme, courbes), contours
ouverts, trait qui ne traverse rien ; outil dans le canvas (geste simulé, un pas d'annulation)."""
import os as _os, sys as _sys  # jamais les vrais réglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import unittest

import ufoLib2
from fontTools.pens.areaPen import AreaPen
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication

from _window_cleanup import WindowTestCase, track  # noqa: E402
from fm_font import contours as C  # noqa: E402
from fm_font import knife, shapes  # noqa: E402
from fm_font.contours import new_contour  # noqa: E402

app = QApplication.instance() or QApplication([])


def area(item) -> float:
    pen = AreaPen()
    item.draw(pen)
    return pen.value


def ring(glyph):
    glyph.contours.append(shapes.ellipse(0, 0, 500, 600))
    inner = shapes.ellipse(100, 100, 400, 500)
    C.reverse(inner)
    glyph.contours.append(inner)


class KnifeModelTest(unittest.TestCase):
    def setUp(self):
        self.font = ufoLib2.Font()

    def test_rectangle_cut_in_two_exact(self):
        g = self.font.newGlyph("r")
        g.contours.append(shapes.rectangle(0, 0, 100, 100))
        self.assertEqual(knife.cut(g, (50, -10), (50, 110)), 1)
        self.assertEqual(len(g.contours), 2)
        self.assertEqual(sorted(round(area(c)) for c in g.contours), [5000, 5000])
        self.assertEqual({(p.x, p.y) for c in g.contours for p in c if p.x == 50}, {(50, 0), (50, 100)})

    def test_ring_cut_across_gives_two_c_shapes(self):
        g = self.font.newGlyph("o")
        ring(g)
        total = area(g)
        self.assertEqual(knife.cut(g, (-50, 300), (550, 300)), 2)      # relie contour et contre-forme, puis coupe
        self.assertEqual(len(g.contours), 2)
        self.assertAlmostEqual(sum(area(c) for c in g.contours), total, places=3)
        for c in g.contours:                                             # chaque moitié : au-dessus OU au-dessous
            ys = [p.y for p in c if p.type]
            self.assertTrue(max(ys) <= 300 + 1e-6 or min(ys) >= 300 - 1e-6)
            self.assertAlmostEqual(area(c), total / 2, places=3)
        self.assertEqual(C.wrong_directions(g), [])

    def test_curves_split_exactly_and_shape_unchanged(self):
        g = self.font.newGlyph("e")
        g.contours.append(shapes.ellipse(0, 0, 400, 400))
        before = area(g)
        knife.cut(g, (-10, 50), (410, 350))                              # diagonale
        self.assertEqual(len(g.contours), 2)
        self.assertAlmostEqual(area(g), before, places=3)
        cuts = [p for c in g.contours for p in c if p.type == "line"]   # nœuds de coupe : sur le trait
        self.assertEqual(len(cuts), 2)                                  # un nœud « ligne » par moitié
        for p in cuts:
            self.assertAlmostEqual(((p.x + 10) * 300 - (p.y - 50) * 420) / 516.14, 0, places=3)   # distance au trait

    def test_open_contour_and_miss(self):
        g = self.font.newGlyph("s")
        g.contours.append(new_contour([(0, 0, "move"), (100, 0, "line"), (200, 0, "line")]))
        self.assertEqual(knife.cut(g, (50, -10), (50, 10)), 1)
        self.assertEqual([[(p.x, p.y) for p in c] for c in g.contours], [[(0, 0), (50, 0)], [(50, 0), (100, 0), (200, 0)]])
        self.assertEqual(g.contours[1][0].type, "move")
        r = self.font.newGlyph("r")
        r.contours.append(shapes.rectangle(0, 0, 100, 100))
        self.assertEqual(knife.cut(r, (50, 50), (50, 200)), 0)            # part de l'intérieur : rien à couper
        self.assertEqual(len(r.contours[0]), 4)                           # aucun nœud laissé
        self.assertEqual(knife.cut(r, (200, 0), (300, 100)), 0)


class KnifeToolTest(WindowTestCase):
    def test_drag_cuts_with_one_undo_step(self):
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtTest import QTest
        from fm_font.canvas import GlyphCanvas
        from fm_font.document import FontProject
        from fm_font.render import PathCache
        project = FontProject.new("Couteau")
        project.add_glyph("A")
        project.font["A"].contours.append(shapes.rectangle(0, 0, 400, 400))
        cv = track(GlyphCanvas(project, PathCache(project), {"typo_snap_distance": 0, "typo_show_rulers": False}))
        cv.resize(800, 600)
        cv.show()
        cv.set_glyph("A")
        cv.scale, cv.origin = 0.5, QPointF(100, 500)
        messages = []
        cv.statusMessage.connect(messages.append)
        cv.set_tool("knife")

        def at(x, y):
            q = cv.to_widget(x, y)
            return QPoint(round(q.x()), round(q.y()))
        QTest.mousePress(cv, Qt.LeftButton, Qt.NoModifier, at(200, -40))
        QTest.mouseMove(cv, at(200, 200))
        self.assertTrue(cv.tools["knife"].hits)                           # aperçu des points de coupe
        cv.grab()
        QTest.mouseMove(cv, at(200, 440))
        QTest.mouseRelease(cv, Qt.LeftButton, Qt.NoModifier, at(200, 440))
        self.assertEqual(len(project.font["A"].contours), 2)
        self.assertIn("1 coupe", messages[-1])
        self.assertEqual(project.undo.undo_label(), "Couteau")
        project.undo.undo()
        self.assertEqual(len(project.font["A"].contours), 1)


if __name__ == "__main__":
    unittest.main()
