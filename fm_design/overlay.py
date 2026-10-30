"""Dessin temporaire du module Design, par-dessus la page : titres des pages, survol, sélection et poignées,
guides du magnétisme, cadre de sélection, recadrage, bulle (taille / angle). Un seul `QGraphicsItem` de la scène,
hors du fichier et de l'annulation (pas un `BoardItem`), sans souris ; tailles constantes à l'écran."""
from __future__ import annotations

import math

from PySide6.QtCore import QLineF, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QGraphicsItem

from . import design_model as dm

HANDLE_PX = 9.0
SIDE_PX = (16.0, 6.0)          # poignée de côté : pastille allongée
ROTATE_PX = 26.0               # poignée de rotation : sous la sélection
HIT_PX = 9.0
OVERLAY_Z = 1e8


class DesignOverlay(QGraphicsItem):
    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.setZValue(OVERLAY_Z)
        self.setAcceptedMouseButtons(Qt.NoButton)
        self.setAcceptHoverEvents(False)
        self.setFlag(QGraphicsItem.ItemHasNoContents, False)
        self._bounds = QRectF()

    # -- zone : tout le contenu Design (titres compris) ; refaite à chaque changement --
    def refresh(self):
        scene = self.scene()
        if scene is None:
            return
        rect = QRectF()
        for page in self.controller.pages():
            rect = rect.united(page.sceneBoundingRect())
        sel = self.controller.selection_polygon()
        if sel is not None:
            rect = rect.united(sel.boundingRect())
        if self.controller.marquee is not None:
            rect = rect.united(self.controller.marquee)
        zoom = self._zoom()
        pad = (ROTATE_PX + 60) / zoom
        rect = rect.adjusted(-pad, -pad - 40 / zoom, pad, pad)
        if rect != self._bounds:
            self.prepareGeometryChange()
            self._bounds = rect
        self.update()

    def boundingRect(self) -> QRectF:
        return self._bounds

    def _zoom(self) -> float:
        scene = self.scene()
        return max(0.01, float(getattr(scene, "zoom", 1.0))) if scene is not None else 1.0

    # -- peinture --
    def paint(self, painter: QPainter, option, widget=None):
        scene = self.scene()
        if scene is None or getattr(scene, "exporting", False):
            return
        c = self.controller
        zoom = self._zoom()
        painter.setRenderHint(QPainter.Antialiasing, True)
        accent = QColor(dm.ACCENT)
        self._paint_titles(painter, zoom)
        if not c.active:
            return
        hover = c.hover
        if hover is not None and hover.scene() is scene and not hover.isSelected():
            painter.setPen(QPen(accent, 1.5 / zoom))
            painter.setBrush(Qt.NoBrush)
            painter.drawPolygon(c.item_polygon(hover))
        selected = c.selection()
        if len(selected) > 1:
            painter.setPen(QPen(QColor(dm.ACCENT).lighter(130), 1.0 / zoom, Qt.DashLine))
            for item in selected:
                painter.drawPolygon(c.item_polygon(item))
        if c.crop_item is not None and c.crop_item.scene() is scene:
            self._paint_crop(painter, zoom)
        poly = c.selection_polygon()
        if poly is not None and not c.text_editing():
            painter.setPen(QPen(accent, 1.6 / zoom))
            painter.setBrush(Qt.NoBrush)
            painter.drawPolygon(poly)
            if c.gesture_kind() not in ("move",):
                self._paint_handles(painter, zoom)
        for line in c.guides:
            pen = QPen(QColor("#ff2fd0"), 1.0 / zoom)
            painter.setPen(pen)
            painter.drawLine(line)
        if c.marquee is not None:
            fill = QColor(accent)
            fill.setAlpha(28)
            painter.setPen(QPen(accent, 1.0 / zoom))
            painter.setBrush(fill)
            painter.drawRect(c.marquee)
        if c.tip is not None:
            self._paint_tip(painter, zoom, *c.tip)

    def _paint_titles(self, painter, zoom):
        font = QFont()
        font.setPointSizeF(max(0.5, 9.5 / zoom))
        painter.setFont(font)
        current = self.controller.current_page()
        for number, page in enumerate(self.controller.pages(), 1):
            if not page.isVisible():
                continue
            r = page.mapRectToScene(page.content_rect())
            label = dm.page_label(page.data, number)
            painter.setPen(QColor(dm.ACCENT) if page is current and self.controller.active else QColor(90, 90, 90))
            box = QRectF(r.left(), r.top() - 22 / zoom, r.width(), 18 / zoom)
            painter.drawText(box, Qt.AlignLeft | Qt.AlignVCenter, label)
            self._paint_page_guides(painter, page, r, zoom)
            if page is current and self.controller.active:
                painter.setPen(QPen(QColor(dm.ACCENT), 1.0 / zoom))
                painter.setBrush(Qt.NoBrush)
                painter.drawRect(r.adjusted(-1 / zoom, -1 / zoom, 1 / zoom, 1 / zoom))

    def _paint_page_guides(self, painter, page, r, zoom):
        """Repères (traits cyan sur toute la page) et marges (cadre en tirets), seulement en mode Design."""
        if not self.controller.active:
            return
        guides = page.data.get("guides") or []
        if guides:
            painter.setPen(QPen(QColor(0, 190, 255, 200), 1.0 / zoom))
            for guide in guides:
                pos = float(guide["pos"])
                if guide["axis"] == "v":
                    painter.drawLine(page.mapToScene(QPointF(pos, 0)), page.mapToScene(QPointF(pos, page.size()[1])))
                else:
                    painter.drawLine(page.mapToScene(QPointF(0, pos)), page.mapToScene(QPointF(page.size()[0], pos)))
        if page.data.get("margins"):
            m = dm.margin_size(*page.size())
            painter.setPen(QPen(QColor(0, 190, 255, 160), 1.0 / zoom, Qt.DashLine))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(r.adjusted(m, m, -m, -m))

    def _paint_handles(self, painter, zoom):
        for name, point, angle in self.controller.handles():
            if name == "rot":
                painter.setPen(QPen(QColor(0, 0, 0, 60), 1.0 / zoom))
                painter.setBrush(QColor("#ffffff"))
                r = 9.0 / zoom
                painter.drawEllipse(point, r, r)
                pen = QPen(QColor("#1a1a1a"), 1.3 / zoom)
                painter.setPen(pen)
                a = 4.6 / zoom
                painter.drawArc(QRectF(point.x() - a, point.y() - a, 2 * a, 2 * a), 40 * 16, 280 * 16)
                continue
            painter.save()
            painter.translate(point)
            painter.rotate(angle)
            painter.setPen(QPen(QColor(0, 0, 0, 70), 1.0 / zoom))
            painter.setBrush(QColor("#ffffff"))
            if name in ("l", "r", "t", "b"):
                w, h = SIDE_PX
                if name in ("l", "r"):
                    w, h = h, w
                rect = QRectF(-w / 2 / zoom, -h / 2 / zoom, w / zoom, h / zoom)
                painter.drawRoundedRect(rect, min(w, h) / 2 / zoom, min(w, h) / 2 / zoom)
            else:
                r = HANDLE_PX / 2 / zoom
                painter.drawEllipse(QPointF(0, 0), r, r)
            painter.restore()

    def _paint_crop(self, painter, zoom):
        item = self.controller.crop_item
        full = self.controller.crop_full_polygon()
        if full is None:
            return
        from .items import adjusted_image
        data = dict(item.data)
        data["crop"] = [0.0, 0.0, 1.0, 1.0]
        pixmap = adjusted_image(getattr(self.scene(), "board_path", None), data)
        if pixmap is not None:
            painter.save()
            painter.setTransform(self.controller.crop_full_transform(), True)
            painter.setOpacity(0.35)
            painter.drawPixmap(QRectF(0, 0, 1, 1), pixmap, QRectF(pixmap.rect()))
            painter.restore()
        painter.setPen(QPen(QColor(255, 255, 255, 200), 1.0 / zoom, Qt.DashLine))
        painter.setBrush(Qt.NoBrush)
        painter.drawPolygon(full)

    def _paint_tip(self, painter, zoom, point: QPointF, text: str):
        font = QFont()
        font.setPointSizeF(max(0.5, 9 / zoom))
        painter.setFont(font)
        metrics_w = (len(text) * 7 + 14) / zoom
        box = QRectF(point.x() + 14 / zoom, point.y() + 14 / zoom, metrics_w, 20 / zoom)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(20, 20, 20, 220))
        painter.drawRoundedRect(box, 4 / zoom, 4 / zoom)
        painter.setPen(QColor("#ffffff"))
        painter.drawText(box, Qt.AlignCenter, text)


def polygon_of(points) -> QPolygonF:
    return QPolygonF(list(points))


def angle_of(a: QPointF, b: QPointF) -> float:
    """Angle (degrés) du segment a -> b, pour orienter une poignée."""
    return math.degrees(math.atan2(b.y() - a.y(), b.x() - a.x()))


def mid(a: QPointF, b: QPointF) -> QPointF:
    return QPointF((a.x() + b.x()) / 2, (a.y() + b.y()) / 2)


def length(a: QPointF, b: QPointF) -> float:
    return QLineF(a, b).length()
