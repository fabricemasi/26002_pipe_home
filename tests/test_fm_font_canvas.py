"""fm_font, CANVAS et OUTILS (Qt offscreen, gestes souris simulés) : rectangle, ellipse, polygone, plume Bézier,
crayon, calligraphie, sélection / déplacement de points et de poignées (une étape d'annulation par geste),
composants (Ctrl + glisser), cache des chemins invalidé finement, zoom / pan, magnétisme, saisie clavier."""
import os as _os, sys as _sys  # jamais les vrais réglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import unittest

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from _window_cleanup import WindowTestCase, track  # noqa: E402
from fm_font import components, shapes  # noqa: E402
from fm_font.canvas import GlyphCanvas  # noqa: E402
from fm_font.document import FontProject  # noqa: E402
from fm_font.render import PathCache  # noqa: E402

app = QApplication.instance() or QApplication([])


def drag(widget, points, mods=Qt.NoModifier):
    a = QPoint(*points[0])
    QTest.mousePress(widget, Qt.LeftButton, mods, a)
    for p in points[1:]:
        QTest.mouseMove(widget, QPoint(*p))
    QTest.mouseRelease(widget, Qt.LeftButton, mods, QPoint(*points[-1]))


class CanvasTest(WindowTestCase):
    def setUp(self):
        self.project = FontProject.new("Essai")
        self.project.add_glyph("A")
        self.cache = PathCache(self.project)
        self.cv = track(GlyphCanvas(self.project, self.cache, {"typo_snap_distance": 0, "typo_show_rulers": False}))
        self.cv.resize(800, 600)
        self.cv.show()
        self.cv.set_glyph("A")
        # vue fixe : 1 unité = 0,5 px, origine à (100, 500)
        self.cv.scale = 0.5
        self.cv.origin = QPointF(100, 500)

    def w(self, x, y):
        q = self.cv.to_widget(x, y)
        return round(q.x()), round(q.y())

    def glyph(self):
        return self.project.font["A"]

    def test_rectangle_then_move_node_one_undo_step(self):
        self.cv.set_tool("rect")
        drag(self.cv, [self.w(100, 0), self.w(300, 200), self.w(500, 700)])
        contour = self.glyph().contours[0]
        self.assertEqual([(p.x, p.y) for p in contour], [(100, 0), (500, 0), (500, 700), (100, 700)])
        self.cv.set_tool("select")
        drag(self.cv, [self.w(500, 700), self.w(520, 710), self.w(540, 720)])
        self.assertEqual((contour[2].x, contour[2].y), (540, 720))
        self.assertEqual(self.project.undo.undo_label(), "Déplacer les points")
        self.project.undo.undo()
        self.assertEqual((self.glyph().contours[0][2].x, self.glyph().contours[0][2].y), (500, 700))
        self.project.undo.undo()
        self.assertEqual(len(self.glyph().contours), 0)

    def test_rubber_band_and_arrows(self):
        self.glyph().contours.append(shapes.rectangle(100, 0, 500, 700))
        drag(self.cv, [self.w(50, -50), self.w(300, 300), self.w(550, 300)])
        self.assertEqual(self.cv.selection, {(0, 0), (0, 1)})
        QTest.keyClick(self.cv, Qt.Key_Up, Qt.ShiftModifier)
        self.assertEqual((self.glyph().contours[0][0].y, self.glyph().contours[0][1].y), (10, 10))
        QTest.keyClick(self.cv, Qt.Key_Delete)
        self.assertEqual(len(self.glyph().contours[0]), 2)

    def test_pen_tool_line_curve_and_close(self):
        self.cv.set_tool("pen")
        QTest.mouseClick(self.cv, Qt.LeftButton, Qt.NoModifier, QPoint(*self.w(100, 0)))
        drag(self.cv, [self.w(400, 0), self.w(450, 100), self.w(500, 200)])      # nœud lisse
        QTest.mouseClick(self.cv, Qt.LeftButton, Qt.NoModifier, QPoint(*self.w(300, 600)))
        QTest.mouseClick(self.cv, Qt.LeftButton, Qt.NoModifier, QPoint(*self.w(100, 0)))  # fermer
        contour = self.glyph().contours[0]
        kinds = [p.type for p in contour]
        self.assertNotIn("move", kinds)                                   # fermé
        self.assertIn("curve", kinds)
        node = next(p for p in contour if p.smooth)
        self.assertEqual((node.x, node.y), (400, 0))
        self.assertEqual(self.project.undo.undo_label(), "Plume")
        self.assertIsNone(self.cv.tool.contour)

    def test_smooth_handle_drag_keeps_opposite_aligned(self):
        self.glyph().contours.append(shapes.ellipse(0, 0, 400, 400))
        contour = self.glyph().contours[0]
        handle = contour[1]                                               # poignée sortante du nœud 0 (lisse)
        drag(self.cv, [self.w(handle.x, handle.y), self.w(handle.x + 20, handle.y + 30),
                       self.w(handle.x + 40, handle.y + 60)])
        node, a, b = contour[0], contour[-1], contour[1]
        cross = (a.x - node.x) * (b.y - node.y) - (a.y - node.y) * (b.x - node.x)
        self.assertAlmostEqual(cross, 0, delta=1e-6)

    def test_pencil_ellipse_polygon_calligraphy(self):
        self.cv.set_tool("pencil")
        drag(self.cv, [self.w(100 + 10 * k, 300 + (k % 7) * 3) for k in range(40)])
        self.cv.set_tool("ellipse")
        drag(self.cv, [self.w(0, 0), self.w(200, 200)])
        self.cv.set_tool("polygon")
        drag(self.cv, [self.w(300, 0), self.w(500, 200)])
        self.cv.set_tool("nib")
        drag(self.cv, [self.w(100 + 8 * k, 400 + 4 * k) for k in range(30)])
        kinds = len(self.glyph().contours)
        self.assertGreaterEqual(kinds, 4)
        self.assertEqual(len(self.glyph().contours[2]), 6)               # hexagone
        self.assertEqual(self.project.undo.undo_label(), "Plume calligraphique")

    def test_component_moves_only_with_ctrl_and_cache_follows_base(self):
        font = self.project.font
        self.project.add_glyph("B")
        font["B"].contours.append(shapes.rectangle(0, 0, 200, 200))
        components.add_component(font, self.glyph(), "B")
        drag(self.cv, [self.w(100, 100), self.w(200, 100), self.w(300, 100)])
        self.assertEqual(tuple(self.glyph().components[0].transformation)[4:], (0, 0))
        drag(self.cv, [self.w(100, 100), self.w(200, 100), self.w(300, 100)], Qt.ControlModifier)
        self.assertEqual(tuple(self.glyph().components[0].transformation)[4:], (200, 0))
        before = self.cache.path(0, "A").boundingRect()
        self.project.edit_glyph("B", "x", lambda g: g.contours[0][2].__setattr__("y", 400))
        after = self.cache.path(0, "A").boundingRect()
        self.assertEqual((before.height(), after.height()), (200, 400))      # composé invalidé avec sa base

    def test_zoom_pan_fit_and_tool_keys(self):
        self.cv.zoom_at(2.0, QPointF(400, 300))
        self.assertAlmostEqual(self.cv.scale, 1.0)
        x, y = self.cv.to_font(QPointF(400, 300))
        self.assertAlmostEqual((x, y)[0], 600)
        self.cv.fit()
        self.assertGreater(self.cv.scale, 0.1)
        QTest.keyClick(self.cv, Qt.Key_P)
        self.assertIs(self.cv.tool, self.cv.tools["pen"])
        QTest.keyClick(self.cv, Qt.Key_V)
        self.assertIs(self.cv.tool, self.cv.tools["select"])

    def test_double_click_toggles_smooth(self):
        self.glyph().contours.append(shapes.rectangle(100, 0, 500, 700))
        QTest.mouseDClick(self.cv, Qt.LeftButton, Qt.NoModifier, QPoint(*self.w(500, 0)))
        self.assertTrue(self.glyph().contours[0][1].smooth)

    def test_paint_does_not_crash_with_everything(self):
        g = self.glyph()
        g.contours.append(shapes.ellipse(0, 0, 400, 400))
        components.set_anchor(g, "top", 200, 500)
        from ufoLib2.objects import Guideline
        g.guidelines.append(Guideline(y=300))
        self.project.font.info.italicAngle = -10
        self.cv.compare_master = 0
        for mode in ("fill", "outline", "both"):
            self.cv.settings["typo_display"] = mode
            self.cv.settings["typo_show_rulers"] = True
            self.cv.grab()


if __name__ == "__main__":
    unittest.main()
