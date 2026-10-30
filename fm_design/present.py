"""Mode PRÉSENTATION (comme « Présenter » de Canva, local) : les pages en plein écran, une à la fois.
Flèches / Espace / PageDown / clic = page suivante, flèche gauche / PageUp / clic droit = précédente, Origine / Fin,
Échap = quitter. Chaque page est rendue UNE fois à la taille de l'écran (`render.render_image`), la suivante est
préparée pendant qu'on regarde la courante : le passage d'une page à l'autre est immédiat."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import QWidget

from . import render


class PresentationWindow(QWidget):
    def __init__(self, pages, start: int = 0, parent=None):
        super().__init__(parent, Qt.Window | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self.setCursor(Qt.BlankCursor)
        self.setWindowTitle("Présentation")
        self.pages = list(pages)
        self.index = max(0, min(len(self.pages) - 1, start))
        self._images: dict[int, QPixmap] = {}
        self._size = None
        self._prepare = QTimer(self)
        self._prepare.setSingleShot(True)
        self._prepare.setInterval(30)
        self._prepare.timeout.connect(self._prepare_next)

    def start(self):
        self.showFullScreen()
        self.activateWindow()
        self.setFocus()

    def _image(self, index: int) -> QPixmap | None:
        if not (0 <= index < len(self.pages)):
            return None
        size = (self.width(), self.height(), self.devicePixelRatioF())
        if size != self._size:
            self._images.clear()
            self._size = size
        if index not in self._images:
            page = self.pages[index]
            w, h = page.size()
            ratio = self.devicePixelRatioF() or 1.0
            scale = min(self.width() / w, self.height() / h) * ratio
            pixmap = QPixmap.fromImage(render.render_image(page, scale))
            pixmap.setDevicePixelRatio(ratio)
            self._images[index] = pixmap
        return self._images[index]

    def _prepare_next(self):
        for index in (self.index + 1, self.index - 1):
            try:
                self._image(index)
            except RuntimeError:                       # page retirée du board entre-temps
                pass

    def go(self, index: int):
        index = max(0, min(len(self.pages) - 1, index))
        if index != self.index:
            self.index = index
            self.update()
        self._prepare.start()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#000000"))
        try:
            pixmap = self._image(self.index)
        except RuntimeError:
            pixmap = None
        if pixmap is not None:
            ratio = pixmap.devicePixelRatio() or 1.0
            target = QRectF(0, 0, pixmap.width() / ratio, pixmap.height() / ratio)
            target.moveCenter(QRectF(self.rect()).center())
            painter.drawPixmap(target, pixmap, QRectF(pixmap.rect()))
        painter.setPen(QColor(255, 255, 255, 90))
        font = QFont()
        font.setPointSize(9)
        painter.setFont(font)
        painter.drawText(QRectF(self.rect()).adjusted(0, 0, -14, -8), Qt.AlignRight | Qt.AlignBottom,
                         f"{self.index + 1} / {len(self.pages)}")
        painter.end()
        self._prepare.start()

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key_Escape:
            self.close()
        elif key in (Qt.Key_Right, Qt.Key_Down, Qt.Key_Space, Qt.Key_PageDown, Qt.Key_Return, Qt.Key_Enter):
            self.go(self.index + 1)
        elif key in (Qt.Key_Left, Qt.Key_Up, Qt.Key_PageUp, Qt.Key_Backspace):
            self.go(self.index - 1)
        elif key == Qt.Key_Home:
            self.go(0)
        elif key == Qt.Key_End:
            self.go(len(self.pages) - 1)
        else:
            super().keyPressEvent(event)

    def mousePressEvent(self, event):
        self.go(self.index + (-1 if event.button() == Qt.RightButton else 1))
