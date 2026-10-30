"""Mode PRÉSENTATION (comme « Présenter » de Canva, local) : les pages en plein écran, une à la fois.
Flèches / Espace / PageDown / clic = page suivante, flèche gauche / PageUp / clic droit = précédente, Origine / Fin,
N = notes du présentateur de la page (bandeau en bas, `notes` de la page), Échap = quitter. Chaque page est rendue UNE fois à la taille de l'écran (`render.render_image`), la suivante est
préparée pendant qu'on regarde la courante : le passage d'une page à l'autre est immédiat.

Animations (« Animer » de Canva, réglées par page : `transition`, `animation`) : la page arrive (fondu, glissement,
zoom) puis ses éléments (fondu, montée, apparition, entrée latérale, ou « un par un » dans l'ordre d'empilement,
un groupe à la fois). Rien n'est repeint pendant l'animation : les images préparées (page entière ; pour une page
animée, fond seul + éléments seuls, `render.render_layers`, ou une petite image par élément, `render.render_units`)
sont seulement posées avec une opacité, un décalage ou une échelle. Une touche pendant l'animation passe
à la page suivante sans attendre."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, QVariantAnimation
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import QWidget

from . import render

TRANSITION_MS = 450
ANIMATION_MS = 600
UNIT_MS = 450                  # « un par un » : arrivée d'un élément ; les suivants partent tous les `cascade_step`


def cascade_step(count: int) -> float:
    """Écart (ms) entre deux éléments « un par un » : 160 ms, resserré pour que tout soit là en ~1,4 s."""
    return min(160.0, 1400.0 / max(1, count))


def _ease(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 1.0 - (1.0 - t) ** 3


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
        self._layers: dict[int, tuple[QPixmap, QPixmap]] = {}
        self._units: dict[int, tuple[QPixmap, list]] = {}
        self._plans: dict[int, tuple[list, float] | None] = {}
        self._size = None
        self._prepare = QTimer(self)
        self._prepare.setSingleShot(True)
        self._prepare.setInterval(30)
        self._prepare.timeout.connect(self._prepare_next)
        self._previous: int | None = None          # page qui s'en va pendant la transition
        self.show_notes = False
        self._direction = 1
        self.anim = QVariantAnimation(self)
        self.anim.setStartValue(0.0)
        self.anim.setEndValue(1.0)
        self.anim.valueChanged.connect(lambda _v: self.update())
        self.anim.finished.connect(self.update)

    def start(self):
        self.showFullScreen()
        self.activateWindow()
        self.setFocus()
        self._play(None)

    # ---------------------------------------------------------------- images préparées
    def _check_size(self):
        size = (self.width(), self.height(), self.devicePixelRatioF())
        if size != self._size:
            self._images.clear()
            self._layers.clear()
            self._units.clear()
            self._size = size

    def _scale(self, page) -> float:
        w, h = page.size()
        return min(self.width() / w, self.height() / h) * (self.devicePixelRatioF() or 1.0)

    def _pixmap(self, image) -> QPixmap:
        pixmap = QPixmap.fromImage(image)
        pixmap.setDevicePixelRatio(self.devicePixelRatioF() or 1.0)
        return pixmap

    def _image(self, index: int) -> QPixmap | None:
        if not (0 <= index < len(self.pages)):
            return None
        self._check_size()
        if index not in self._images:
            page = self.pages[index]
            self._images[index] = self._pixmap(render.render_image(page, self._scale(page)))
        return self._images[index]

    def _layer_pair(self, index: int) -> tuple[QPixmap, QPixmap] | None:
        """Fond seul et éléments seuls d'une page dont les éléments s'animent (sinon None)."""
        if (not (0 <= index < len(self.pages)) or self.pages[index].data.get("animation", "none") in ("none",
                                                                                                     "cascade")
                or self.plan(index) is not None):
            return None
        self._check_size()
        if index not in self._layers:
            page = self.pages[index]
            back, front = render.render_layers(page, self._scale(page))
            self._layers[index] = (self._pixmap(back), self._pixmap(front))
        return self._layers[index]

    def plan(self, index: int) -> tuple[list, float] | None:
        """Animation élément par élément (page « un par un », ou un élément qui a SA propre animation) :
        ([(sorte, début ms, durée ms)] par unité, fin ms) depuis le début de l'animation ; None = page entière."""
        if index in self._plans:
            return self._plans[index]
        page = self.pages[index]
        page_kind = page.data.get("animation", "none")
        units = render.animation_units(page)
        if page_kind != "cascade" and not any(u[0].data.get("animation") for u in units):
            self._plans[index] = None
            return None
        kinds = [u[0].data.get("animation") or page_kind for u in units]     # un groupe : celle du 1er
        step = cascade_step(kinds.count("cascade"))
        out, done, end = [], 0, 0.0
        for kind in kinds:
            if kind == "cascade":
                start, length = done * step, UNIT_MS
                done += 1
            elif kind == "none":
                start, length = 0.0, 0.0
            else:
                start, length = 0.0, ANIMATION_MS
            out.append((kind, start, length))
            end = max(end, start + length)
        self._plans[index] = (out, end)
        return self._plans[index]

    def _cascade(self, index: int) -> tuple[QPixmap, list] | None:
        """Fond seul et une image par élément (ou groupe) d'une page animée élément par élément (sinon None)."""
        if not (0 <= index < len(self.pages)) or self.plan(index) is None:
            return None
        self._check_size()
        if index not in self._units:
            page = self.pages[index]
            scale = self._scale(page)
            back = render.render_image(page, scale, exclude=set(page.elements()))
            units = [(rect, QPixmap.fromImage(image) if image is not None else None)
                     for rect, image in render.render_units(page, scale, render.animation_units(page))]
            self._units[index] = (self._pixmap(back), units)
        return self._units[index]

    def _prepare_next(self):
        if self.anim.state() == QVariantAnimation.Running:
            self._prepare.start()                      # pas de rendu pendant une animation
            return
        for index in (self.index + 1, self.index - 1):
            try:
                self._image(index)
                self._layer_pair(index)
                self._cascade(index)
            except RuntimeError:                       # page retirée du board entre-temps
                pass

    # ---------------------------------------------------------------- navigation
    def durations(self, index: int) -> tuple[int, int, int]:
        """(durée de la transition, début de l'animation des éléments, durée totale) en ms pour arriver sur `index`."""
        page = self.pages[index]
        data = page.data
        transition = TRANSITION_MS if data.get("transition", "none") != "none" else 0
        plan = self.plan(index)
        if plan is not None:
            delay = transition // 2
            return transition, delay, max(transition, delay + round(plan[1]))
        if data.get("animation", "none") == "none":
            return transition, transition, transition
        delay = transition // 2
        return transition, delay, delay + ANIMATION_MS

    def _play(self, previous: int | None):
        self.anim.stop()
        self._previous = previous
        total = self.durations(self.index)[2] if self.pages else 0
        if total > 0:
            self.anim.setDuration(total)
            self.anim.start()
        self.update()

    def go(self, index: int):
        index = max(0, min(len(self.pages) - 1, index))
        if index != self.index:
            previous, self.index = self.index, index
            self._direction = 1 if index > previous else -1
            self._play(previous)
        self._prepare.start()

    # ---------------------------------------------------------------- peinture
    def _draw(self, painter, pixmap, opacity=1.0, dx=0.0, dy=0.0, scale=1.0):
        if pixmap is None or opacity <= 0.0:
            return
        ratio = pixmap.devicePixelRatio() or 1.0
        target = QRectF(0, 0, pixmap.width() / ratio * scale, pixmap.height() / ratio * scale)
        target.moveCenter(QRectF(self.rect()).center() + QPointF(dx, dy))
        painter.setOpacity(opacity)
        painter.drawPixmap(target, pixmap, QRectF(pixmap.rect()))
        painter.setOpacity(1.0)

    def _paint_page(self, painter, ms: float | None):
        """Page courante ; `ms` = temps écoulé de son arrivée (None = arrivée terminée)."""
        page = self.pages[self.index]
        transition, delay, _total = self.durations(self.index)
        kind = page.data.get("transition", "none")
        t = 1.0 if ms is None or transition == 0 else _ease(ms / transition)
        if t < 1.0 and self._previous is not None:
            old = self._image(self._previous)
            if kind == "slide":
                self._draw(painter, old, dx=-self._direction * self.width() * t)
            else:
                self._draw(painter, old)
        opacity, dx, scale = 1.0, 0.0, 1.0
        if t < 1.0:
            if kind == "slide":
                dx = self._direction * self.width() * (1.0 - t)
            else:
                opacity = t
                scale = 0.85 + 0.15 * t if kind == "zoom" else 1.0
        animation = page.data.get("animation", "none")
        if ms is not None and ms < _total and self.plan(self.index) is not None:
            self._paint_units(painter, page, ms - delay, opacity, dx, scale)
            return
        a = 1.0 if ms is None or animation in ("none", "cascade") else _ease((ms - delay) / ANIMATION_MS)
        layers = self._layer_pair(self.index) if a < 1.0 else None
        if layers is None:
            self._draw(painter, self._image(self.index), opacity, dx, 0.0, scale)
            return
        back, front = layers
        self._draw(painter, back, opacity, dx, 0.0, scale)
        e_opacity, e_dx, e_dy, e_scale = opacity * a, dx, 0.0, scale
        if animation == "rise":
            e_dy = (1.0 - a) * self.height() * 0.06
        elif animation == "pop":
            e_scale = scale * (0.8 + 0.2 * a)
        elif animation == "slide":
            e_dx = dx - (1.0 - a) * self.width() * 0.08
        self._draw(painter, front, e_opacity, e_dx, e_dy, e_scale)

    def _paint_units(self, painter, page, ms, opacity, dx, scale):
        """Élément par élément : fond, puis chaque élément (ou groupe) avec SON animation (« un par un » : montée en
        fondu l'un après l'autre ; fondu, montée, apparition, entrée latérale ; aucune = là tout de suite)."""
        prepared = self._cascade(self.index)
        plan = self.plan(self.index)
        if prepared is None or plan is None:
            return
        back, units = prepared
        self._draw(painter, back, opacity, dx, 0.0, scale)
        w, h = page.size()
        k = min(self.width() / w, self.height() / h) * scale
        center = QRectF(self.rect()).center()
        left, top = center.x() + dx - w * k / 2, center.y() - h * k / 2
        for (rect, pixmap), (kind, start, length) in zip(units, plan[0]):
            if rect is None:
                continue
            u = 1.0 if length <= 0 else _ease((ms - start) / length)
            if u <= 0.0:
                continue
            target = QRectF(left + rect.x() * k, top + rect.y() * k, rect.width() * k, rect.height() * k)
            if kind in ("cascade", "rise"):
                target.translate(0.0, (1.0 - u) * 24.0)
            elif kind == "slide":
                target.translate(-(1.0 - u) * 60.0, 0.0)
            elif kind == "pop":
                c = target.center()
                target = QRectF(0, 0, target.width() * (0.8 + 0.2 * u), target.height() * (0.8 + 0.2 * u))
                target.moveCenter(c)
            painter.setOpacity(opacity * u)
            painter.drawPixmap(target, pixmap, QRectF(pixmap.rect()))
        painter.setOpacity(1.0)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#000000"))
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        running = self.anim.state() == QVariantAnimation.Running
        try:
            if self.pages:
                self._paint_page(painter, float(self.anim.currentTime()) if running else None)
        except RuntimeError:                           # page retirée du board entre-temps
            pass
        if self.show_notes and self.pages:
            self._paint_notes(painter)
        painter.setPen(QColor(255, 255, 255, 90))
        font = QFont()
        font.setPointSize(9)
        painter.setFont(font)
        painter.drawText(QRectF(self.rect()).adjusted(0, 0, -14, -8), Qt.AlignRight | Qt.AlignBottom,
                         f"{self.index + 1} / {len(self.pages)}")
        painter.end()
        if not running:
            self._prepare.start()

    def _paint_notes(self, painter):
        """Bandeau des notes en bas de l'écran (texte blanc sur fond sombre), « Aucune note » si vide."""
        try:
            text = str(self.pages[self.index].data.get("notes", "")).strip()
        except RuntimeError:
            return
        font = QFont()
        font.setPointSize(13)
        painter.setFont(font)
        margin = 24
        width = self.width() - 2 * margin
        flags = Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap
        shown = text or "Aucune note pour cette page."
        needed = painter.boundingRect(QRectF(0, 0, width - 32, self.height() / 2), flags, shown)
        band = QRectF(margin, self.height() - margin - needed.height() - 28, width, needed.height() + 24)
        painter.setOpacity(1.0)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0, 200))
        painter.drawRoundedRect(band, 8, 8)
        painter.setPen(QColor(255, 255, 255, 235 if text else 140))
        painter.drawText(band.adjusted(16, 12, -16, -12), flags, shown)

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key_Escape:
            self.close()
        elif key == Qt.Key_N:
            self.show_notes = not self.show_notes
            self.update()
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
