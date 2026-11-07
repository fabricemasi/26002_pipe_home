"""Reticule du module CAD en NEGATIF sur les zones de sa couleur (`fm_cad/cad_negative.py`, 2026-11-05)."""
import os as _os, sys as _sys  # jamais les vrais reglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import unittest

import numpy as np
from PySide6.QtGui import QColor, QImage

from fm_cad import cad_negative
from test_cad import CadBoardCase


def backdrop(width=100, height=60):
    """Fond sombre, bande blanche verticale de x = 40 a 59."""
    image = QImage(width, height, QImage.Format_RGB32)
    image.fill(QColor("#202020"))
    for x in range(40, 60):
        for y in range(height):
            image.setPixelColor(x, y, QColor("#f4f4f4"))
    return image


class SplitTest(unittest.TestCase):
    def test_only_the_near_zone_is_negative(self):
        array = cad_negative.backdrop_array(backdrop())
        pieces = cad_negative.split([(0, 30, 100, 1), (50, 0, 1, 60)], "#e8eaec", 48, array, 0, 0)
        neg = cad_negative.negative_of("#e8eaec")
        spans = [(x, w, c == neg) for x, y, w, h, c in pieces if y == 30 and h == 1]
        self.assertEqual(spans, [(0, 40, False), (40, 20, True), (60, 40, False)])   # negatif sur la bande seulement
        vertical = [p for p in pieces if p[0] == 50 and p[2] == 1 and p[3] > 1]
        self.assertTrue(vertical and all(p[4] == neg for p in vertical))           # bras vertical dans la bande
        self.assertEqual(cad_negative.split([(0, 30, 100, 1)], "#e8eaec", 0, array, 0, 0)[0][4], QColor("#e8eaec"))

    def test_system_cursor_changes_only_over_its_colour(self):
        array = cad_negative.backdrop_array(backdrop())
        args = (20, 0, "#e8eaec", 1.0, None, 48)
        self.assertIsNone(cad_negative.adapted_cursor(args, array, (10, 30)))       # fond sombre : curseur ordinaire
        over = cad_negative.adapted_cursor(args, array, (50, 30))
        self.assertIsNotNone(over)
        self.assertIs(cad_negative.adapted_cursor(args, array, (50, 30)), over)     # meme motif : meme curseur
        image = over.pixmap().toImage()
        self.assertEqual(image.pixelColor(20, 20).rgb(), cad_negative.negative_of("#e8eaec").rgb())   # centre
        self.assertEqual(image.pixelColor(0, 20).rgb(), QColor("#e8eaec").rgb())   # bout gauche, hors bande


class SettingsTest(CadBoardCase):
    def test_setting_feeds_the_look(self):
        self.assertEqual(self.ctl.look["negative"], 48)
        self.ctl.apply_settings(dict(self.ctl.settings, board_cad_crosshair_negative=False))
        self.assertEqual(self.ctl.look["negative"], 0)


class GpuPointTest(CadBoardCase):
    def test_gpu_layer_reads_under_the_pointer(self):
        """Rendu OpenGL : la couche est la SOEUR du viewport ; le point lu est celui du pointeur, board DECALE dans sa
        fenetre compris (signale : « juste en mode classique mais pas en opengl », mapFrom remontait jusqu'a l'ecran)."""
        from PySide6.QtCore import QPointF, Signal
        from PySide6.QtWidgets import QWidget

        class FakeLayer(QWidget):
            crossReady = Signal()
            asked = None

            def read_cross(self, point, reach):
                self.asked = QPointF(point)
                return None

        view = self.pane.view
        self.pane.move(37, 23)                                  # board decale dans sa fenetre
        layer = FakeLayer(view)
        layer.setGeometry(view.viewport().geometry())
        self.addCleanup(setattr, view, "gpu", getattr(view, "gpu", None))
        view.gpu = layer
        self.ctl.overlay.backdrop = None
        self.ctl.cursor_view = QPointF(123.5, 77.25)
        self.ctl._native_args = (20, 0, "#e8eaec", 1.0, None, 48)
        native = object()
        self.assertIs(self.ctl._negative_cursor(native), native)    # rien de copie : curseur ordinaire
        self.assertEqual(layer.asked, QPointF(123.5, 77.25))


if __name__ == "__main__":
    unittest.main()
