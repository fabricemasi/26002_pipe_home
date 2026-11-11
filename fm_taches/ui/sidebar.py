"""Panneau latéral des tâches, PEINT : vues intelligentes (Aujourd'hui, Planifiées, Marquées, Toutes, Terminées)
avec leur nombre, puis « Mes listes » (pastille de couleur, nom, tâches à faire) et « + » pour en créer une.
Clic = ouvrir ; double-clic sur une liste = renommer ; clic droit = menu de la liste."""
from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QSizePolicy, QWidget

from fm_agenda.ui.widgets import draw_icon, elide
from . import theme as th

SMART = (("today", "Aujourd'hui", "sun"), ("planned", "Planifiées", "bell"), ("flagged", "Marquées", "flag"),
         ("all", "Toutes", "list"), ("done", "Terminées", "check"))
SMART_COLORS = {"today": "bleu", "planned": "rouge", "flagged": "orange", "all": "gris", "done": "vert"}
HEAD_H = 34


class Sidebar(QWidget):
    picked = Signal(str, str)                    # ("smart" | "list", clé)
    addList = Signal()
    renameList = Signal(str)
    contextRequested = Signal(str, QPoint)

    def __init__(self, holder, parent=None):
        super().__init__(parent)
        self.holder = holder
        self.lists: list = []
        self.counts: dict = {}
        self.smart_counts: dict = {}
        self.current = ("smart", "today")
        self._hover = None
        self.setMouseTracking(True)
        self.setObjectName("TachesSidebar")
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.setAccessibleName("Vues et listes de tâches")

    def set_data(self, lists, counts: dict, smart_counts: dict, current: tuple) -> None:
        self.lists, self.counts, self.smart_counts, self.current = list(lists), counts, smart_counts, current
        h = 10 + len(SMART) * th.SIDE_ROW_H + 14 + HEAD_H + len(self.lists) * th.SIDE_ROW_H + 20
        if self.height() != h:
            self.setFixedHeight(h)
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(240, self.height())

    # -- géométrie --

    def _items(self):
        """[(genre, clé, rect)] : vues, en-tête « Mes listes » (bouton +), listes."""
        out = []
        y = 10
        for key, _label, _icon in SMART:
            out.append(("smart", key, QRectF(8, y, self.width() - 16, th.SIDE_ROW_H)))
            y += th.SIDE_ROW_H
        y += 14
        out.append(("add", "", QRectF(self.width() - 38, y + 4, 26, 26)))
        self._head_y = y
        y += HEAD_H
        for lst in self.lists:
            out.append(("list", lst.id, QRectF(8, y, self.width() - 16, th.SIDE_ROW_H)))
            y += th.SIDE_ROW_H
        return out

    def _hit(self, pos):
        for kind, key, rect in self._items():
            if rect.contains(pos):
                return kind, key
        return None

    # -- peinture --

    def paintEvent(self, event):
        t = self.holder.t
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.fillRect(self.rect(), t.c("side"))
        names = {lst.id: lst for lst in self.lists}
        for kind, key, rect in self._items():
            if kind == "add":
                hover = self._hover == ("add", "")
                if hover:
                    p.setPen(Qt.NoPen)
                    p.setBrush(t.c("btn"))
                    p.drawRoundedRect(rect, 6, 6)
                draw_icon(p, "plus", rect.adjusted(6, 6, -6, -6), t.c("strong") if hover else t.c("muted"))
                p.setFont(th.font(11, 600))
                p.setPen(t.c("section"))
                p.drawText(QRectF(16, self._head_y, 200, HEAD_H), Qt.AlignVCenter | Qt.AlignLeft, "MES LISTES")
                continue
            on = self.current == (kind, key)
            if on:
                p.setPen(Qt.NoPen)
                p.setBrush(th.with_alpha(t.c("accent"), 0.22))
                p.drawRoundedRect(rect, 6, 6)
            elif self._hover == (kind, key):
                p.setPen(Qt.NoPen)
                p.setBrush(t.c("hover"))
                p.drawRoundedRect(rect, 6, 6)
            cy = rect.center().y()
            if kind == "smart":
                label, icon = next((lb, ic) for k, lb, ic in SMART if k == key)
                bar = t.event(SMART_COLORS[key])[1]
                badge = QRectF(rect.x() + 8, cy - 10, 20, 20)
                p.setPen(Qt.NoPen)
                p.setBrush(bar)
                p.drawEllipse(badge)
                if icon == "flag":
                    _flag(p, badge.center(), QColor("#ffffff"))
                else:
                    draw_icon(p, icon, badge.adjusted(4, 4, -4, -4), QColor("#ffffff"), 1.8)
                count = self.smart_counts.get(key)
            else:
                lst = names[key]
                label = lst.name
                p.setPen(Qt.NoPen)
                p.setBrush(t.event(lst.color)[1])
                p.drawEllipse(QPointF(rect.x() + 18, cy), 5, 5)
                count = self.counts.get(key, 0)
            p.setFont(th.font(13, 600 if on else 400))
            p.setPen(t.c("strong") if on else t.c("text"))
            text_x = rect.x() + 36
            count_w = 34
            p.drawText(QRectF(text_x, rect.y(), rect.right() - text_x - count_w, rect.height()),
                       Qt.AlignVCenter | Qt.AlignLeft, elide(label, 13, 600 if on else 400,
                                                             rect.right() - text_x - count_w))
            if count:
                p.setFont(th.font(12))
                p.setPen(t.c("muted"))
                p.drawText(QRectF(rect.right() - count_w - 6, rect.y(), count_w, rect.height()),
                           Qt.AlignVCenter | Qt.AlignRight, str(count))
            if kind == "list" and names[key].synced:      # liste Google Tasks : petit « G » avant le nombre
                p.setFont(th.font(10, 700))
                p.setPen(t.c("dim"))
                p.drawText(QRectF(rect.right() - count_w - 22, rect.y(), 14, rect.height()),
                           Qt.AlignVCenter | Qt.AlignHCenter, "G")

    # -- souris --

    def mouseMoveEvent(self, event):
        hit = self._hit(event.position())
        if hit != self._hover:
            self._hover = hit
            self.setCursor(Qt.PointingHandCursor if hit else Qt.ArrowCursor)
            self.update()

    def leaveEvent(self, event):
        self._hover = None
        self.update()

    def mousePressEvent(self, event):
        hit = self._hit(event.position())
        if hit is None:
            return
        kind, key = hit
        if event.button() == Qt.RightButton:
            if kind == "list":
                self.contextRequested.emit(key, event.globalPosition().toPoint())
            return
        if event.button() != Qt.LeftButton:
            return
        if kind == "add":
            self.addList.emit()
        else:
            self.picked.emit(kind, key)

    def mouseDoubleClickEvent(self, event):
        hit = self._hit(event.position())
        if hit is not None and hit[0] == "list":
            self.renameList.emit(hit[1])


def _flag(p: QPainter, c: QPointF, color: QColor) -> None:
    from PySide6.QtGui import QPainterPath, QPen, QPolygonF
    p.save()
    p.setPen(QPen(color, 1.5, Qt.SolidLine, Qt.RoundCap))
    p.drawLine(QPointF(c.x() - 3, c.y() - 5), QPointF(c.x() - 3, c.y() + 5))
    path = QPainterPath()
    path.addPolygon(QPolygonF([QPointF(c.x() - 3, c.y() - 5), QPointF(c.x() + 4, c.y() - 3),
                               QPointF(c.x() - 3, c.y() - 0.5)]))
    p.fillPath(path, color)
    p.restore()
