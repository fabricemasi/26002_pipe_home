"""Etat « focus » : se concentrer sur UN objet precis (aujourd'hui l'apercu image/
turntable de l'inspecteur ; plus tard texte, informations...). Ce module recevra
tout ce qui releve de cet etat ; il vient apres browser_core dans l'ordre de
dependance."""
from PySide6.QtCore import QElapsedTimer, QRect, QRectF, Qt, QTimer
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import QWidget

from browser_core import _fine_timer


class FocusOverlay(QWidget):
    """Objet en FOCUS (image ou image de turntable) qui voyage entre sa place
    dans l'inspecteur (`source`) et le centre de la zone des colonnes
    (`target`), position ET echelle interpolees ensemble. Progression p : 0 =
    a la place de l'inspecteur, 1 = centre. Meme horloge/lissage que
    _FadeOverlay ; `retarget` repart de la valeur courante (clic pendant
    l'animation). Couvre toute la zone, transparent a la souris : seuls les
    pixels de l'objet sont peints. Premier maillon du concept « focus » : le
    contenu est un pixmap pour l'instant, d'autres types (texte...) viendront."""

    def __init__(self, parent, pixmap: QPixmap, source: QRectF, target: QRectF, start: float, end: float,
                 duration_ms: int = 420, on_finished=None, on_done=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setGeometry(parent.rect())
        self._source = source
        self._target = target
        self._base = pixmap
        self._cache_key = None
        self._cache = None
        self._value = start
        self._from = start
        self._end = end
        self._duration = max(1, duration_ms)
        self._on_finished = on_finished
        self._on_done = on_done
        self.running = True
        self.hold = True    # le proprietaire le retire (voir PipelineBrowser._show_columns_now)
        self._clock = QElapsedTimer()
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.setInterval(8)
        self._timer.timeout.connect(self._tick)
        self._clock.start()
        _fine_timer(True)
        self._timer.start()

    @staticmethod
    def target_rect(pixmap: QPixmap, area: QRect, margin: int = 40) -> QRectF:
        """Taille reelle si elle tient dans `area` (moins une marge), sinon reduite ;
        centre sur `area`."""
        dpr = pixmap.devicePixelRatio() or 1.0
        w, h = pixmap.width() / dpr, pixmap.height() / dpr
        scale = min(1.0, max(1, area.width() - 2 * margin) / max(1.0, w),
                    max(1, area.height() - 2 * margin) / max(1.0, h))
        w, h = max(1.0, w * scale), max(1.0, h * scale)
        return QRectF(area.x() + (area.width() - w) / 2, area.y() + (area.height() - h) / 2, w, h)

    def set_geometry_target(self, area: QRect, source: QRectF = None):
        """Redimensionnement de la fenetre : recentre (et suit l'inspecteur si connu)."""
        self.setGeometry(self.parentWidget().rect())
        self._target = self.target_rect(self._base, area)
        if source is not None:
            self._source = source
        self.update()

    def retarget(self, end: float, on_finished=None):
        self._from = self._value
        self._end = end
        self._on_finished = on_finished
        self.running = True
        self._clock.restart()
        if not self._timer.isActive():
            _fine_timer(True)
            self._timer.start()

    def current_rect(self) -> QRectF:
        t = self._value
        s, e = self._source, self._target
        return QRectF(s.x() + (e.x() - s.x()) * t, s.y() + (e.y() - s.y()) * t,
                      s.width() + (e.width() - s.width()) * t, s.height() + (e.height() - s.height()) * t)

    def paintEvent(self, event):
        rect = self.current_rect()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        # Pre-reduit a la plus grande des deux tailles extremes : dessiner une
        # grande image reduite a chaque image de l'animation serait trop lent.
        big_w = max(self._source.width(), self._target.width())
        dpr = self._base.devicePixelRatio() or 1.0
        if self._base.width() / dpr > big_w * 1.01:
            key = round(big_w)
            if self._cache_key != key:
                self._cache = self._base.scaledToWidth(max(1, round(big_w * dpr)), Qt.SmoothTransformation)
                self._cache_key = key
            pixmap = self._cache
        else:
            pixmap = self._base
        painter.drawPixmap(rect, pixmap, QRectF(pixmap.rect()))

    def _tick(self):
        distance = abs(self._end - self._from)
        t = min(1.0, self._clock.elapsed() / (self._duration * max(distance, 0.05)))
        eased = t * t * t * (t * (t * 6.0 - 15.0) + 10.0)
        self._value = self._from + (self._end - self._from) * eased
        self.update()
        if t >= 1.0:
            self._finish()

    def finish_now(self):
        if self.running:
            self._finish()

    def _finish(self):
        self._timer.stop()
        _fine_timer(False)
        self.running = False
        self._value = self._end
        self.update()
        if self._on_finished is not None:
            self._on_finished()
        if self._on_done is not None:
            self._on_done()

    def dispose(self):
        if self.running:
            self._timer.stop()
            _fine_timer(False)
            self.running = False
        self.hide()
        self.deleteLater()
