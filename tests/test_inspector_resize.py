"""Le curseur et le clic partagent toute la zone de redimensionnement."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt, QEvent, QPointF, QPoint
from PySide6.QtGui import QMouseEvent

APP = QApplication.instance() or QApplication([])
import pipeline_browser as p
import detail_panel as dp
import browser_core as bc
import app_style


class InspectorResizeTest(unittest.TestCase):
    def test_handle_is_accessible_in_real_browser_layout(self):
        with tempfile.TemporaryDirectory(prefix="inspector_handle_") as work:
            window = p.PipelineBrowser(Path(work))
            window._idle_preview_scheduler.timer.stop()
            window.setGeometry(10, 10, 780, 560)
            window.show()
            APP.processEvents()
            try:
                panel = window.detail
                handle = panel._resize_handle
                for y in (5, panel.height() // 2, panel.height() - 5):
                    point = QPoint(handle.width() - 1, y)
                    self.assertIs(QApplication.widgetAt(panel.mapToGlobal(point)), handle)
                width = panel.width()
                point = QPoint(handle.width() - 1, panel.height() // 2)
                origin = panel.mapToGlobal(point)
                with patch.object(dp, "_persist_detail_panel_width"):
                    QApplication.sendEvent(handle, QMouseEvent(QEvent.MouseButtonPress, QPointF(point),
                        QPointF(origin), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
                    QApplication.sendEvent(panel, QMouseEvent(QEvent.MouseMove, QPointF(point + QPoint(20, 0)),
                        QPointF(origin + QPoint(20, 0)), Qt.NoButton, Qt.LeftButton, Qt.NoModifier))
                    self.assertEqual(panel.width(), max(bc.DETAIL_PANEL_MIN_WIDTH, width - 20))
                    QApplication.sendEvent(panel, QMouseEvent(QEvent.MouseButtonRelease, QPointF(point),
                        QPointF(origin + QPoint(20, 0)), Qt.LeftButton, Qt.NoButton, Qt.NoModifier))
                    self.assertFalse(panel._resizing)
            finally:
                window.hide()
                window.deleteLater()
                APP.processEvents()

    def test_entire_handle_starts_resize_and_tracks_drag(self):
        panel = dp.DetailPanel()
        panel.resize(panel.width(), 700)
        panel.show()
        APP.processEvents()
        try:
            handle = panel._resize_handle
            self.assertEqual(handle.width(), app_style.scaled(16))
            self.assertEqual(handle.height(), panel.height())
            for y in (5, panel.height() // 2, panel.height() - 5):
                for x in (0, handle.width() // 2, handle.width() - 1):
                    self.assertTrue(panel._in_resize_zone(x))
                    # Verifie la cible REELLE du clic, pas uniquement le filtre.
                    self.assertIs(panel.childAt(QPoint(x, y)), handle)
                    self.assertIs(QApplication.widgetAt(panel.mapToGlobal(QPoint(x, y))), handle)
                    origin = handle.mapToGlobal(handle.rect().topLeft())
                    def event(kind, local_x, global_x, button, buttons):
                        return QMouseEvent(kind, QPointF(local_x, y), QPointF(global_x, origin.y() + y),
                                           button, buttons, Qt.NoModifier)
                    QApplication.sendEvent(handle, event(QEvent.MouseMove, x, origin.x() + x,
                                                          Qt.NoButton, Qt.NoButton))
                    self.assertEqual(handle.cursor().shape(), Qt.SizeHorCursor)
                    width = panel.width()
                    with patch.object(dp, "_persist_detail_panel_width"), \
                            patch.object(panel, "grabMouse") as grab, patch.object(panel, "releaseMouse") as release:
                        QApplication.sendEvent(handle, event(QEvent.MouseButtonPress, x, origin.x() + x,
                                                              Qt.LeftButton, Qt.LeftButton))
                        self.assertTrue(panel._resizing)
                        grab.assert_called_once()
                        QApplication.sendEvent(panel, event(QEvent.MouseMove, x - 10, origin.x() + x - 10,
                                                             Qt.NoButton, Qt.LeftButton))
                        self.assertEqual(panel.width(), width + 10)
                        QApplication.sendEvent(panel, event(QEvent.MouseButtonRelease, x - 10,
                                                             origin.x() + x - 10, Qt.LeftButton, Qt.NoButton))
                        self.assertFalse(panel._resizing)
                        release.assert_called_once()
                    panel.setFixedWidth(width)
            self.assertFalse(panel._in_resize_zone(handle.width()))
        finally:
            panel.close()
            panel.deleteLater()
            APP.processEvents()


if __name__ == "__main__":
    unittest.main()
