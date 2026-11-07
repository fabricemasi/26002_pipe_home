"""Coins arrondis des cartes de colonnes (`capture_widgets._RoundedCornersEffect`, 2026-11-05) : seuls les coins passent
par le masque antialiase (fluidite), le rendu reste IDENTIQUE au pixel pres a l'ancien (deux pixmaps pleine taille)."""
import _isolate  # noqa: F401
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QPoint, QRect, Qt  # noqa: E402
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from capture_widgets import _RoundedCornersEffect, _rounded_rect_path  # noqa: E402

APP = QApplication.instance() or QApplication([])


class _Old(_RoundedCornersEffect):
    """L'algorithme d'avant (reference)."""

    def draw(self, painter):
        offset = QPoint()
        pixmap = self.sourcePixmap(Qt.LogicalCoordinates, offset)
        if pixmap.isNull():
            return
        dpr = pixmap.devicePixelRatio() or 1.0
        w, h = int(round(pixmap.width() / dpr)), int(round(pixmap.height() / dpr))
        path = _rounded_rect_path(QRect(0, 0, w, h), self._radius)
        mask = QPixmap(pixmap.size())
        mask.setDevicePixelRatio(dpr)
        mask.fill(Qt.transparent)
        mkp = QPainter(mask)
        mkp.setRenderHint(QPainter.Antialiasing, True)
        mkp.setPen(Qt.NoPen)
        mkp.setBrush(Qt.white)
        mkp.drawPath(path)
        mkp.end()
        masked = QPixmap(pixmap.size())
        masked.setDevicePixelRatio(dpr)
        masked.fill(Qt.transparent)
        mp = QPainter(masked)
        mp.setRenderHint(QPainter.Antialiasing, True)
        mp.drawPixmap(0, 0, pixmap)
        mp.setCompositionMode(QPainter.CompositionMode_DestinationIn)
        mp.drawPixmap(0, 0, mask)
        mp.end()
        painter.drawPixmap(offset, masked)


class _Content(QWidget):
    def paintEvent(self, _event):
        p = QPainter(self)
        grad = QLinearGradient(0, 0, self.width(), self.height())
        grad.setColorAt(0, QColor("#ff3366"))
        grad.setColorAt(1, QColor("#33aaff"))
        p.fillRect(self.rect(), grad)


def render(effect_class, radius, size=(160, 300)):
    host = QWidget()
    host.resize(size[0] + 20, size[1] + 20)
    host.setStyleSheet("background: #202020;")
    child = _Content(host)
    child.setGeometry(10, 10, *size)
    effect = effect_class(child)
    effect.setRadius(radius)
    child.setGraphicsEffect(effect)
    image = host.grab().toImage()
    host.deleteLater()
    return image


class RoundedEffectTest(unittest.TestCase):
    def test_same_pixels_as_before(self):
        for radius in ({"top_left": 12, "top_right": 12, "bottom_right": 12, "bottom_left": 12},
                       {"top_left": 0, "top_right": 25, "bottom_right": 3, "bottom_left": 40},
                       {"top_left": 0, "top_right": 0, "bottom_right": 0, "bottom_left": 0},
                       {"top_left": 500, "top_right": 500, "bottom_right": 500, "bottom_left": 500}):
            self.assertEqual(render(_RoundedCornersEffect, radius), render(_Old, radius), radius)


if __name__ == "__main__":
    unittest.main()
