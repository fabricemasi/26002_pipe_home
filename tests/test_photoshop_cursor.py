"""Module Photoshop : curseur de brosse en SURVOL. Position flottante exacte à tous les zooms (aucune quantification en
coordonnées document), chemin indépendant du moteur de trait, une seule source de coordonnées (tablette OU souris
synthétisée), journal du survol."""
import os as _os, sys as _sys  # jamais les vrais réglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QInputDevice, QMouseEvent, QPointingDevice, QTabletEvent

from _photoshop_case import PsCase

PEN = QPointingDevice("Stylet de test", 7, QInputDevice.DeviceType.Stylus, QPointingDevice.PointerType.Pen,
                      QPointingDevice.Capability.Position | QPointingDevice.Capability.Pressure, 1, 2)


class FakePainter:
    def __init__(self):
        self.ellipses = []

    def setRenderHint(self, *args):
        pass

    def setBrush(self, *args):
        pass

    def setPen(self, *args):
        pass

    def drawEllipse(self, center, rx, ry):
        self.ellipses.append((QPointF(center), rx, ry))


def mouse_move(x, y, ts=0, synthesized=False):
    if synthesized:
        event = QMouseEvent(QEvent.MouseMove, QPointF(x, y), QPointF(x, y), QPointF(x + 100, y + 100), Qt.NoButton,
                            Qt.NoButton, Qt.NoModifier, Qt.MouseEventSynthesizedByQt, PEN)
    else:
        event = QMouseEvent(QEvent.MouseMove, QPointF(x, y), QPointF(x + 100, y + 100), Qt.NoButton, Qt.NoButton,
                            Qt.NoModifier)
    event.setTimestamp(ts)
    return event


def tablet_move(x, y, ts=0, pressure=0.0):
    event = QTabletEvent(QEvent.TabletMove, PEN, QPointF(x, y), QPointF(x + 100, y + 100), 0.0, 0.0, pressure, 0.0, 0.0, 0.0,
                         Qt.NoModifier, Qt.NoButton, Qt.NoButton)
    event.setTimestamp(ts)
    return event


class HoverCursorTest(PsCase):
    ZOOMS = (1.0, 2.0, 5.0, 10.0, 14.15)

    def _canvas(self, zoom=1.0):
        _item, std = self.editor(120, 80, zoom=zoom, background="Transparent")
        std.session.tool = "brush"
        return std.canvas, std.session

    def test_hover_follows_the_float_position_exactly_at_every_zoom(self):
        for zoom in self.ZOOMS:
            canvas, _s = self._canvas(zoom)
            for i in range(10):
                x, y = 300.0 + i * 0.1, 200.0 + i * 0.037                       # sub-pixel d'ÉCRAN : jamais arrondi
                canvas.mouseMoveEvent(mouse_move(x, y))
                self.assertEqual((canvas._hover.x(), canvas._hover.y()), (x, y), f"zoom {zoom}")
                painter = FakePainter()
                canvas._paint_cursor(painter)
                centre = painter.ellipses[0][0]
                self.assertEqual((centre.x(), centre.y()), (x, y))               # le cercle est dessiné à la position reçue
                dx, dy = canvas.to_doc(canvas._hover)
                back = canvas.to_widget(dx, dy)
                self.assertAlmostEqual(back.x(), x, places=9)                    # aller-retour écran -> document -> écran
                self.assertAlmostEqual(back.y(), y, places=9)

    def test_displayed_motion_is_not_amplified_by_zoom(self):
        # Un bruit de 0,3 px d'écran ne doit PAS devenir un saut d'un pixel de document (14 px écran à 1 415 %).
        for zoom in self.ZOOMS:
            canvas, _s = self._canvas(zoom)
            worst = 0.0
            for i in range(40):
                x = 400.0 + (0.3 if i % 2 else -0.3)
                y = 250.0 + (0.2 if i % 3 else -0.2)
                canvas.mouseMoveEvent(mouse_move(x, y))
                worst = max(worst, abs(canvas._hover.x() - x), abs(canvas._hover.y() - y))
            self.assertEqual(worst, 0.0, f"zoom {zoom}")

    def test_cursor_path_ignores_stroke_engine_settings(self):
        canvas, s = self._canvas(5.0)
        s.brush.smoothing, s.brush.smoothing_mode, s.brush.pressure_size = 0.9, "stabilizer", True
        canvas._pressure, canvas._pen_active = 0.0, True                         # pression nulle : le diamètre affiché ne change pas
        before = canvas.brush_diameter()
        canvas.mouseMoveEvent(mouse_move(250.25, 180.75))
        self.assertEqual((canvas._hover.x(), canvas._hover.y()), (250.25, 180.75))
        self.assertEqual(canvas.brush_diameter(), before)
        self.assertIsNone(canvas._stroke)                                         # aucun trait créé pendant le survol
        self.assertEqual(len(s.history.done), 0)

    def test_a_single_coordinate_source_holds_the_cursor(self):
        canvas, _s = self._canvas(10.0)
        canvas.tabletEvent(tablet_move(300.4, 200.7, ts=1000))
        self.assertEqual((canvas._hover.x(), canvas._hover.y()), (300.4, 200.7))
        # la souris synthétisée qui suit (positions arrondies) ne doit pas déplacer le curseur
        canvas.mouseMoveEvent(mouse_move(300.0, 201.0, ts=1000, synthesized=True))
        self.assertEqual((canvas._hover.x(), canvas._hover.y()), (300.4, 200.7))
        canvas.tabletEvent(tablet_move(301.2, 201.1, ts=1008))
        canvas.mouseMoveEvent(mouse_move(301.0, 201.0, ts=1008, synthesized=True))
        self.assertEqual((canvas._hover.x(), canvas._hover.y()), (301.2, 201.1))
        # une vraie souris (non synthétisée) reprend le curseur
        canvas.mouseMoveEvent(mouse_move(120.5, 90.5, ts=5000))
        self.assertEqual((canvas._hover.x(), canvas._hover.y()), (120.5, 90.5))

    def test_hover_log_records_every_quantity(self):
        canvas, _s = self._canvas(14.15)
        from fm_photoshop.pen_log import PenLog
        canvas.pen_log = PenLog()
        canvas.tabletEvent(tablet_move(300.4, 200.7, ts=1000))
        canvas.mouseMoveEvent(mouse_move(300.0, 201.0, ts=1000, synthesized=True))
        canvas.tabletEvent(tablet_move(300.9, 200.9, ts=1008))
        canvas.mouseMoveEvent(mouse_move(301.0, 201.0, ts=1008, synthesized=True))
        rows = [e for e in canvas.pen_log.events if e["kind"] == "hover"]
        self.assertEqual([r["source"] for r in rows], ["tablet", "mouse_synth", "tablet", "mouse_synth"])
        first = rows[0]
        for key in ("x", "y", "gx", "gy", "doc", "cursor", "buttons", "zoom", "dpr", "device", "device_type", "device_id", "device_system_id", "t"):
            self.assertIn(key, first)
        self.assertEqual(first["device"], "Stylet de test")
        self.assertAlmostEqual(first["zoom"], 14.15)
        self.assertEqual(first["device_system_id"], 7)
        stats = canvas.pen_log.stats()
        self.assertEqual(stats["survol_sources"], {"tablet": 2, "mouse_synth": 2})
        self.assertLess(stats["survol_ecart_curseur_px_max"], 1.0)                 # le curseur reste sur la position tablette
        self.assertEqual(stats["survol_alternances_de_source"], 2)                 # les deux sources alternent : détecté


class TraceOverlayTest(PsCase):
    def test_debug_trace_shows_raw_filtered_and_dab_points(self):
        _item, std = self.editor(120, 60, zoom=4.0, background="Transparent")
        canvas, s, panel = std.canvas, std.session, std.brush_panel
        s.brush.size, s.brush.hardness = 8.0, 1.0
        s.brush.smoothing, s.brush.smoothing_mode = 0.5, "adaptive"
        panel.trace_toggle.setChecked(True)
        self.drag(canvas, [self.at(canvas, 10, 30), self.at(canvas, 30, 31), self.at(canvas, 50, 30), self.at(canvas, 70, 32)])
        trace = canvas._last_trace
        self.assertTrue(trace and len(trace["raw"]) >= 4)
        self.assertEqual(len(trace["raw"]), len(trace["used"]))
        self.assertGreater(len(trace["dabs"]), len(trace["raw"]))                    # davantage d'empreintes que d'évènements
        self.assertNotEqual(trace["raw"][-1], trace["used"][-1])                      # filtré != brut en mode adaptatif
        canvas.grab()                                                                  # la superposition se dessine sans erreur
        panel.trace_toggle.setChecked(False)
        self.assertIsNone(canvas._last_trace)


if __name__ == "__main__":
    unittest.main()
