"""Règles graduées du module Design (Maj+R, comme « Afficher les règles » de Canva) : en haut et à gauche de la vue,
en unités de la PAGE COURANTE (origine = son coin haut gauche). Tirer depuis une règle vers la page crée un repère
(création, pas un déplacement : sans Ctrl ; le déplacer ensuite = Ctrl + glisser).

Fluidité : widgets OPAQUES (Qt ne les repeint pas quand le board se repeint dessous) redessinés seulement quand le zoom
ou le défilement change ; graduations calculées à la peinture (quelques dizaines de traits)."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

from . import design_model as dm, document as doc

THICKNESS = 20


def tick_step(zoom: float, min_px: float = 60.0) -> float:
    """Pas des graduations principales (1, 2, 5 × 10^n unités) : au moins `min_px` pixels à l'écran."""
    raw = min_px / max(1e-6, zoom)
    power = 10 ** math.floor(math.log10(raw))
    for k in (1, 2, 5, 10):
        if k * power >= raw:
            return k * power
    return 10 * power


class Ruler(QWidget):
    def __init__(self, ctl, vertical: bool, parent):
        super().__init__(parent)
        self.ctl = ctl
        self.vertical = vertical
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self.setCursor(Qt.SplitHCursor if vertical else Qt.SplitVCursor)
        self.setToolTip("Tirer vers la page : nouveau repère")
        self._drag = None
        self.hide()

    def _page(self):
        return self.ctl.current_page()

    def paintEvent(self, _event):
        from settings_store import M
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(M["panel_bg"]))
        p.setPen(QColor(M["panel_border"]))
        if self.vertical:
            p.drawLine(self.width() - 1, 0, self.width() - 1, self.height())
        else:
            p.drawLine(0, self.height() - 1, self.width(), self.height() - 1)
        page = self._page()
        view = self.ctl.view
        if page is None:
            p.end()
            return
        zoom = view.zoom()
        step = tick_step(zoom)
        from app_style import C
        ink = QColor(C["text"])
        font = QFont()
        font.setPixelSize(9)
        p.setFont(font)
        origin = view.mapFromScene(page.mapToScene(QPointF(0, 0)))
        offset = self.mapFrom(self.ctl.pane, view.viewport().mapTo(self.ctl.pane, origin))
        length = self.height() if self.vertical else self.width()
        start = (0 - (offset.y() if self.vertical else offset.x())) / zoom
        first = math.floor(start / step) * step
        value = first
        while True:
            px = (offset.y() if self.vertical else offset.x()) + value * zoom
            if px > length:
                break
            for sub in range(1, 5):                        # petites graduations
                spx = px + sub * step * zoom / 5
                p.setPen(QPen(QColor(ink.red(), ink.green(), ink.blue(), 70), 1))
                if self.vertical:
                    p.drawLine(QPointF(THICKNESS - 5, spx), QPointF(THICKNESS, spx))
                else:
                    p.drawLine(QPointF(spx, THICKNESS - 5), QPointF(spx, THICKNESS))
            p.setPen(QPen(QColor(ink.red(), ink.green(), ink.blue(), 160), 1))
            label = f"{value:g}"
            if self.vertical:
                p.drawLine(QPointF(THICKNESS - 10, px), QPointF(THICKNESS, px))
                p.save()
                p.translate(9, px + 2)
                p.rotate(-90)
                p.drawText(QPointF(0, 0), label)
                p.restore()
            else:
                p.drawLine(QPointF(px, THICKNESS - 10), QPointF(px, THICKNESS))
                p.drawText(QPointF(px + 2, 10), label)
            value += step
        p.end()

    # -- tirer un repère --
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self._page() is not None:
            self._drag = True
        event.accept()

    def mouseMoveEvent(self, event):
        if self._drag:
            self.ctl.preview_guide = self._guide_at(event)
            self.ctl.refresh()
        event.accept()

    def mouseReleaseEvent(self, event):
        if self._drag:
            self._drag = None
            guide = self._guide_at(event)
            self.ctl.preview_guide = None
            page = self._page()
            if guide is not None and page is not None:
                axis, pos = guide
                w, h = page.size()
                if 0 <= pos <= (w if axis == "v" else h):
                    doc.change(self.ctl.scene, [page], lambda i: i.data.update(
                        guides=list(i.data.get("guides") or []) + [{"axis": axis, "pos": round(pos, 2)}]),
                        "Ajouter un repère")
            self.ctl.refresh()
        event.accept()

    def _guide_at(self, event):
        """(axe, position dans la page) sous le pointeur ; règle verticale (à gauche) = repère vertical."""
        page = self._page()
        if page is None:
            return None
        view = self.ctl.view
        local = view.viewport().mapFrom(self.ctl.pane, self.mapTo(self.ctl.pane, event.position().toPoint()))
        point = page.mapFromScene(view.mapToScene(local))
        return ("v", point.x()) if self.vertical else ("h", point.y())


class Rulers:
    """Les deux règles, placées le long du haut et de la gauche de la vue."""

    def __init__(self, ctl):
        self.ctl = ctl
        self.top = Ruler(ctl, False, ctl.pane)
        self.left = Ruler(ctl, True, ctl.pane)
        self.visible = bool(dm.LOOK["rulers"])         # Réglages > Design > Sélection et repères
        view = ctl.view
        view.zoomChanged.connect(lambda _z: self.update())
        view.horizontalScrollBar().valueChanged.connect(lambda _v: self.update())
        view.verticalScrollBar().valueChanged.connect(lambda _v: self.update())

    def set_visible(self, on: bool):
        self.visible = on
        self.place()

    def update(self):
        if self.visible and self.ctl.active:
            self.top.update()
            self.left.update()

    def place(self):
        on = self.visible and self.ctl.active
        for ruler in (self.top, self.left):
            ruler.setVisible(on)
        if not on:
            return
        view = self.ctl.view
        rect = view.viewport().rect()
        origin = view.viewport().mapTo(self.ctl.pane, rect.topLeft())
        self.top.setGeometry(origin.x() + THICKNESS, origin.y(), rect.width() - THICKNESS, THICKNESS)
        self.left.setGeometry(origin.x(), origin.y() + THICKNESS, THICKNESS, rect.height() - THICKNESS)
        self.top.raise_()
        self.left.raise_()
        self.update()

