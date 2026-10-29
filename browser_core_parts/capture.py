"""Capture d’écran, instantanés et fantôme de déplacement. Carte : docs/agents/colonnes.md."""

from PySide6.QtCore import QObject, QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QPainter, QPen, QPixmap, QRegion
from PySide6.QtWidgets import QApplication, QLabel, QWidget
from app_style import C, font
from settings_widgets import DRAG_GHOST_OPACITY

def _translucent_grab(widget: QWidget, opacity: float = DRAG_GHOST_OPACITY) -> QPixmap:
    """Capture de `widget` (voir Column.eventFilter, group_kind) rendue
    semi-transparente, utilisee comme image suivant le curseur pendant le
    glisser-deposer d'une colonne du groupe IN/OVER/OUT/LOGICIELS — voir la
    remarque de l'utilisateur, "possible lors du glisser d'avoir la colonne
    en curseur avec de la transparence ?". Repeint dans un PIXMAP A PART
    (fond transparent + opacite du QPainter) plutot qu'un simple
    setWindowOpacity sur le widget source : celui-ci reste affiche a l'ecran
    pendant le glisser, une capture directe serait donc a pleine opacite
    quoi que ce reglage change."""
    source = widget.grab()
    result = QPixmap(source.size())
    result.fill(Qt.transparent)
    painter = QPainter(result)
    painter.setOpacity(opacity)
    painter.drawPixmap(0, 0, source)
    painter.end()
    return result

def _make_group_drag_ghost(column: QWidget) -> QWidget:
    """Petite fenetre top-level SANS decoration, qui affiche la capture
    semi-transparente de `column` (voir _translucent_grab) et suit le
    curseur pendant le glisser d'un en-tete du groupe IN/OVER/OUT/LOGICIELS
    — voir Column.eventFilter (group_kind), qui la deplace a chaque
    MouseMove et la ferme au relachement. Qt.ToolTip (pas de barre de
    titre/entree dans la barre des taches, ne prend jamais le focus) +
    WA_TransparentForMouseEvents (ne doit jamais intercepter le clic —
    la cible du depot est determinee a la main par _find_group_drop_target,
    pas par ce que Qt voit sous le curseur)."""
    ghost = QLabel(None)
    ghost.setWindowFlags(Qt.ToolTip | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
    ghost.setAttribute(Qt.WA_TranslucentBackground, True)
    ghost.setAttribute(Qt.WA_TransparentForMouseEvents, True)
    ghost.setAttribute(Qt.WA_ShowWithoutActivating, True)
    pixmap = _translucent_grab(column)
    ghost.setPixmap(pixmap)
    ghost.resize(pixmap.size())
    ghost.show()
    return ghost

class SquareCaptureOverlay(QWidget):
    """Fenetre plein ecran translucide sur UN SEUL moniteur, permettant de
    choisir une zone carree a capturer (deplacable et redimensionnable a la
    souris). Reste volontairement limitee a un seul ecran : une fenetre qui
    chevauche deux moniteurs d'echelles differentes se fait etirer (bitmap
    stretch) par Windows lui-meme des que le process n'est pas reconnu
    "Per-Monitor DPI Aware" par le systeme (ce qui echappe totalement au
    controle de l'appli) — d'ou le flou/pixelisation observe en tentant de
    couvrir plusieurs ecrans dans une seule fenetre. Pour capturer sur
    plusieurs moniteurs, voir MultiScreenCapture qui ouvre une instance de
    cette classe par ecran. Emet `captured` (QPixmap deja carree) a la
    validation, ou `cancelled` si l'utilisateur abandonne (Echap / fermeture)."""

    captured = Signal(QPixmap)
    cancelled = Signal()

    HANDLE_SIZE = 16
    MIN_SIZE = 24

    def __init__(self, screen):
        super().__init__(None)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setCursor(Qt.CrossCursor)
        self.setMouseTracking(True)

        self.background = screen.grabWindow(0)
        self.setGeometry(screen.geometry())

        w, h = self.width(), self.height()
        size = max(self.MIN_SIZE, min(320, w, h))
        self.sel = QRect((w - size) // 2, (h - size) // 2, size, size)

        self._mode = None       # None | "move" | "resize" | "new"
        self._anchor = QPoint()
        self._drag_offset = QPoint()
        self._done = False

        self.font_hint = font(12, 500)

    def _handle_rect(self) -> QRect:
        s = self.HANDLE_SIZE
        return QRect(self.sel.right() - s + 1, self.sel.bottom() - s + 1, s, s)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.drawPixmap(0, 0, self.background)

        painter.setClipRegion(self._dim_region())
        painter.fillRect(self.rect(), QColor(0, 0, 0, 150))
        painter.setClipping(False)

        painter.setPen(QPen(QColor(C["accent"]), 2))
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(self.sel)

        handle = self._handle_rect()
        painter.fillRect(handle, QColor(C["accent"]))

        painter.setFont(self.font_sub_size())
        painter.setPen(QColor("#ffffff"))
        label = f"{self.sel.width()} x {self.sel.height()}"
        painter.drawText(self.sel.x(), max(16, self.sel.y() - 8), label)

        painter.setFont(self.font_hint)
        painter.setPen(QColor("#ffffff"))
        hint = (
            "Glisser l'interieur pour deplacer  •  coin bas-droit pour redimensionner  •  "
            "Entree pour valider  •  Echap pour annuler"
        )
        painter.drawText(20, self.height() - 24, hint)

    def font_sub_size(self):
        return font(11, 400, mono=True)

    def _dim_region(self):
        return QRegion(self.rect()).subtracted(QRegion(self.sel))

    def mousePressEvent(self, event):
        pos = event.position().toPoint()
        if self._handle_rect().contains(pos):
            self._mode = "resize"
            self._anchor = self.sel.topLeft()
        elif self.sel.contains(pos):
            self._mode = "move"
            self._drag_offset = pos - self.sel.topLeft()
        else:
            self._mode = "new"
            self._anchor = pos
            self.sel = QRect(pos, QSize(1, 1))
        self.update()

    def mouseMoveEvent(self, event):
        pos = event.position().toPoint()
        if self._mode == "move":
            top_left = pos - self._drag_offset
            top_left.setX(max(0, min(top_left.x(), self.width() - self.sel.width())))
            top_left.setY(max(0, min(top_left.y(), self.height() - self.sel.height())))
            self.sel.moveTopLeft(top_left)
            self.update()
        elif self._mode == "resize":
            size = max(self.MIN_SIZE, min(pos.x() - self._anchor.x(), pos.y() - self._anchor.y()))
            size = min(size, self.width() - self._anchor.x(), self.height() - self._anchor.y())
            self.sel = QRect(self._anchor, QSize(size, size))
            self.update()
        elif self._mode == "new":
            dx, dy = pos.x() - self._anchor.x(), pos.y() - self._anchor.y()
            size = max(abs(dx), abs(dy), 1)
            x = self._anchor.x() if dx >= 0 else self._anchor.x() - size
            y = self._anchor.y() if dy >= 0 else self._anchor.y() - size
            x = max(0, min(x, self.width() - size))
            y = max(0, min(y, self.height() - size))
            size = min(size, self.width() - x, self.height() - y)
            self.sel = QRect(x, y, size, size)
            self.update()
        else:
            if self._handle_rect().contains(pos):
                self.setCursor(Qt.SizeFDiagCursor)
            elif self.sel.contains(pos):
                self.setCursor(Qt.SizeAllCursor)
            else:
                self.setCursor(Qt.CrossCursor)

    def mouseReleaseEvent(self, event):
        self._mode = None

    def mouseDoubleClickEvent(self, event):
        self._finish()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self._finish()
        elif event.key() == Qt.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)

    def _finish(self):
        if self.sel.width() < self.MIN_SIZE or self.sel.height() < self.MIN_SIZE:
            return
        dpr = self.background.devicePixelRatio()
        crop = QRect(
            round(self.sel.x() * dpr), round(self.sel.y() * dpr),
            round(self.sel.width() * dpr), round(self.sel.height() * dpr),
        )
        cropped = self.background.copy(crop)
        cropped.setDevicePixelRatio(1.0)
        self._done = True
        self.captured.emit(cropped)
        self.close()

    def closeEvent(self, event):
        if not self._done:
            self.cancelled.emit()
        super().closeEvent(event)

class MultiScreenCapture(QObject):
    """Ouvre un SquareCaptureOverlay par ecran physique connecte, pour
    permettre de capturer sur n'importe lequel sans jamais faire chevaucher
    une seule fenetre sur deux ecrans d'echelles differentes (voir
    SquareCaptureOverlay). Valider la selection dans l'un d'eux ferme
    automatiquement tous les autres ; Echap dans n'importe lequel annule
    l'ensemble. `captured`/`cancelled` ne sont emis qu'une seule fois."""

    captured = Signal(QPixmap)
    cancelled = Signal()

    def __init__(self, initial_screen=None, parent=None):
        super().__init__(parent)
        self._done = False
        screens = QApplication.screens()
        focus_screen = initial_screen or QApplication.screenAt(QCursor.pos()) or screens[0]

        self._overlays = [SquareCaptureOverlay(screen) for screen in screens]
        for overlay in self._overlays:
            overlay.captured.connect(self._on_captured)
            overlay.cancelled.connect(self._on_cancelled)
            overlay.show()
        for overlay, screen in zip(self._overlays, screens):
            if screen is focus_screen:
                overlay.activateWindow()
                overlay.setFocus()

    def _on_captured(self, pix: QPixmap):
        if self._done:
            return
        self._done = True
        self._close_all()
        self.captured.emit(pix)

    def _on_cancelled(self):
        if self._done:
            return
        self._done = True
        self._close_all()
        self.cancelled.emit()

    def _close_all(self):
        for overlay in self._overlays:
            if overlay.isVisible():
                overlay._done = True  # evite un cancelled/capture en double
                overlay.close()
