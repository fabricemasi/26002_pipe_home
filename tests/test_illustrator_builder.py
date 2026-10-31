"""Module Illustrator, tranche 9 : Shape Builder (Maj+M) : zones de la sélection, glisser = réunir, Alt = supprimer,
une étape d'annulation, survol hachuré."""
import os as _os, sys as _sys  # jamais les vrais réglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import unittest

from PySide6.QtCore import QEvent, QPointF, Qt

from test_illustrator import IllTestCase


class ShapeBuilderTest(IllTestCase):
    def two_squares(self):
        a = self.rect(100, 100, 100, 100)
        b = self.rect(150, 100, 100, 100)
        self.ctl.select([a, b])
        self.key(Qt.Key_M, Qt.ShiftModifier, "M")
        self.assertEqual(self.ctl.tool, "shape_builder")
        return a, b

    def test_drag_merges_crossed_regions(self):
        self.two_squares()
        self.mouse(QEvent.MouseMove, QPointF(120, 150), buttons=Qt.NoButton)
        self.assertEqual(self.ctl.preview[0], "regions")
        self.drag(QPointF(120, 150), QPointF(175, 150))           # zone de gauche + zone commune
        paths = self.paths()
        self.assertEqual(len(paths), 2)
        widths = sorted(round(p.geometry_rect().width()) for p in paths)
        self.assertEqual(widths, [50, 100])
        self.scene.undo.undo()
        self.assertEqual(len(self.paths()), 2)
        self.assertEqual(sorted(round(p.geometry_rect().x()) for p in self.paths()), [100, 150])

    def test_alt_deletes_a_region(self):
        self.two_squares()
        self.drag(QPointF(175, 150), QPointF(176, 150), mods=Qt.AltModifier)    # zone commune supprimée
        paths = self.paths()
        self.assertEqual(len(paths), 2)
        self.assertEqual(sorted(round(p.geometry_rect().width()) for p in paths), [50, 50])


if __name__ == "__main__":
    unittest.main()
