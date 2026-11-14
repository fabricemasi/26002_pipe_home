"""Grisage sans effet imbriqué (`fm_theme.widgets._set_dimmed` / `_set_faded`, 2026-11-12) : signalé, éléments grisés
qui disparaissent et artefacts dans les réglages (toggles H, B, D de « lier les 4 » dans une ligne grisée puis
réactivée). Qt ne dessine plus un enfant à effet d'opacité dans un parent à effet laissé à 100 %."""
import os as _os, sys as _sys  # jamais les vrais reglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtGui import QColor, QPalette  # noqa: E402
from PySide6.QtWidgets import QApplication, QGraphicsOpacityEffect, QWidget  # noqa: E402

from fm_theme.widgets import _set_dimmed, _set_faded  # noqa: E402

APP = QApplication.instance() or QApplication([])


def _box(parent, rect, color):
    w = QWidget(parent)
    w.setGeometry(*rect)
    w.setAutoFillBackground(True)
    pal = w.palette()
    pal.setColor(QPalette.Window, QColor(color))
    w.setPalette(pal)
    return w


def _has_effect(w) -> bool:
    return isinstance(w.graphicsEffect(), QGraphicsOpacityEffect)


class DimNestingTest(unittest.TestCase):
    def setUp(self):
        self.top = _box(None, (0, 0, 200, 100), "black")
        self.row = QWidget(self.top)                    # le champ de la ligne (grisé par le toggle « activer »)
        self.row.setGeometry(50, 20, 140, 70)
        self.child = _box(self.row, (60, 10, 40, 40), "white")   # toggle H grisé par « lier les 4 »
        self.top.show()

    def tearDown(self):
        self.top.deleteLater()

    def _child_pixel(self) -> int:
        APP.processEvents()
        return QColor(self.top.grab().toImage().pixel(130, 50)).red()

    def test_no_effect_inside_an_effect(self):
        _set_dimmed(self.child, True)
        _set_dimmed(self.row, True)
        self.assertTrue(_has_effect(self.row))
        self.assertFalse(_has_effect(self.child))      # marque gardée, effet retiré
        self.assertFalse(self.child.isEnabled())

    def test_child_still_drawn_after_row_reactivated(self):
        _set_dimmed(self.child, True)
        _set_dimmed(self.row, True)
        _set_dimmed(self.row, False)
        self.assertFalse(_has_effect(self.row))         # retiré, jamais laissé à 100 %
        self.assertTrue(_has_effect(self.child))        # le toggle H retrouve son grisage
        self.assertGreater(self._child_pixel(), 20)     # et se dessine (noir = disparu)
        self.assertFalse(self.child.isEnabled())

    def test_child_dimmed_while_row_dimmed(self):
        _set_dimmed(self.row, True)
        _set_dimmed(self.child, True)
        self.assertFalse(_has_effect(self.child))
        _set_faded(self.row, False)
        self.assertTrue(_has_effect(self.child))
        _set_dimmed(self.child, False)
        self.assertFalse(_has_effect(self.child))
        self.assertGreater(self._child_pixel(), 240)


if __name__ == "__main__":
    unittest.main()
