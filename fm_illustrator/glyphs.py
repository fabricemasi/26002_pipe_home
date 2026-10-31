"""Glyphes des boutons du module Illustrator (traits, comme les autres glyphes du board) ; appelé par
`fm_board.ui.paint_glyph` pour « illustrator » et les genres « ill_… »."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPolygonF


def _arrow(s: float, c: QPointF) -> QPolygonF:
    pts = [(-0.45, -0.85), (0.55, 0.15), (0.05, 0.2), (0.35, 0.8), (0.12, 0.9), (-0.18, 0.3), (-0.45, 0.6)]
    return QPolygonF([QPointF(c.x() + x * s, c.y() + y * s) for x, y in pts])


def _nib(painter: QPainter, c: QPointF, s: float):
    """Plume (outil Plume, bouton du module)."""
    path = QPainterPath()
    path.moveTo(c.x(), c.y() - s * 0.95)
    path.lineTo(c.x() + s * 0.55, c.y() + s * 0.1)
    path.lineTo(c.x() + s * 0.3, c.y() + s * 0.55)
    path.lineTo(c.x() - s * 0.3, c.y() + s * 0.55)
    path.lineTo(c.x() - s * 0.55, c.y() + s * 0.1)
    path.closeSubpath()
    painter.drawPath(path)
    painter.drawLine(QPointF(c.x(), c.y() - s * 0.95), QPointF(c.x(), c.y() - s * 0.05))
    painter.drawEllipse(QPointF(c.x(), c.y() - s * 0.02), s * 0.09, s * 0.09)
    painter.drawRect(QRectF(c.x() - s * 0.35, c.y() + s * 0.62, s * 0.7, s * 0.28))


def paint_ill_glyph(painter: QPainter, kind: str, rect: QRectF, color: QColor):
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, True)
    pen = QPen(color, 1.4)
    pen.setJoinStyle(Qt.RoundJoin)
    pen.setCapStyle(Qt.RoundCap)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    c = rect.center()
    s = min(rect.width(), rect.height()) * 0.36
    if kind in ("illustrator", "ill_pen", "ill_add_anchor", "ill_delete_anchor"):
        _nib(painter, QPointF(c.x() - (s * 0.15 if kind != "illustrator" and kind != "ill_pen" else 0), c.y()), s)
        if kind != "illustrator" and kind != "ill_pen":
            x, y = c.x() + s * 0.75, c.y() - s * 0.65
            painter.drawLine(QPointF(x - s * 0.25, y), QPointF(x + s * 0.25, y))
            if kind == "ill_add_anchor":
                painter.drawLine(QPointF(x, y - s * 0.25), QPointF(x, y + s * 0.25))
    elif kind == "ill_select":
        painter.setBrush(color)
        painter.drawPolygon(_arrow(s, c))
    elif kind == "ill_direct":
        painter.drawPolygon(_arrow(s, c))
    elif kind == "ill_convert":
        painter.drawLine(QPointF(c.x() - s * 0.9, c.y() + s * 0.6), QPointF(c.x(), c.y() - s * 0.6))
        painter.drawLine(QPointF(c.x(), c.y() - s * 0.6), QPointF(c.x() + s * 0.9, c.y() + s * 0.6))
        painter.drawRect(QRectF(c.x() - s * 0.14, c.y() - s * 0.74, s * 0.28, s * 0.28))
    elif kind == "ill_rect":
        painter.drawRect(QRectF(c.x() - s * 0.85, c.y() - s * 0.6, s * 1.7, s * 1.2))
    elif kind == "ill_ellipse":
        painter.drawEllipse(c, s * 0.85, s * 0.65)
    elif kind in ("ill_polygon", "ill_star"):
        n = 6 if kind == "ill_polygon" else 10
        pts = []
        for i in range(n):
            r = s * 0.9 if kind == "ill_polygon" or i % 2 == 0 else s * 0.4
            a = math.radians(-90 + 360 * i / n)
            pts.append(QPointF(c.x() + r * math.cos(a), c.y() + r * math.sin(a)))
        painter.drawPolygon(QPolygonF(pts))
    elif kind == "ill_line":
        painter.drawLine(QPointF(c.x() - s * 0.8, c.y() + s * 0.8), QPointF(c.x() + s * 0.8, c.y() - s * 0.8))
    elif kind == "ill_pencil":
        painter.drawLine(QPointF(c.x() - s * 0.75, c.y() + s * 0.75), QPointF(c.x() + s * 0.55, c.y() - s * 0.55))
        painter.drawLine(QPointF(c.x() - s * 0.45, c.y() + s * 0.95), QPointF(c.x() + s * 0.85, c.y() - s * 0.35))
        painter.drawLine(QPointF(c.x() + s * 0.55, c.y() - s * 0.55), QPointF(c.x() + s * 0.85, c.y() - s * 0.35))
        painter.drawLine(QPointF(c.x() - s * 0.75, c.y() + s * 0.75), QPointF(c.x() - s * 0.95, c.y() + s * 0.95))
    elif kind in ("ill_artboard", "ill_new_artboard"):
        painter.drawRect(QRectF(c.x() - s * 0.55, c.y() - s * 0.55, s * 1.1, s * 1.1))
        for x, y, dx, dy in ((-0.55, -0.55, -1, 0), (-0.55, -0.55, 0, -1), (0.55, 0.55, 1, 0), (0.55, 0.55, 0, 1)):
            painter.drawLine(QPointF(c.x() + x * s, c.y() + y * s),
                             QPointF(c.x() + (x + dx * 0.4) * s, c.y() + (y + dy * 0.4) * s))
        if kind == "ill_new_artboard":
            painter.drawLine(QPointF(c.x() - s * 0.3, c.y()), QPointF(c.x() + s * 0.3, c.y()))
            painter.drawLine(QPointF(c.x(), c.y() - s * 0.3), QPointF(c.x(), c.y() + s * 0.3))
    elif kind == "ill_hand":
        painter.drawRoundedRect(QRectF(c.x() - s * 0.55, c.y() - s * 0.2, s * 1.1, s * 1.0), s * 0.3, s * 0.3)
        for i in range(4):
            x = c.x() - s * 0.42 + i * s * 0.28
            painter.drawLine(QPointF(x, c.y() - s * 0.2), QPointF(x, c.y() - s * (0.8 if i in (1, 2) else 0.6)))
    elif kind == "ill_zoom":
        painter.drawEllipse(QPointF(c.x() - s * 0.2, c.y() - s * 0.2), s * 0.55, s * 0.55)
        painter.drawLine(QPointF(c.x() + s * 0.2, c.y() + s * 0.2), QPointF(c.x() + s * 0.85, c.y() + s * 0.85))
    elif kind == "ill_eyedropper":
        painter.drawLine(QPointF(c.x() - s * 0.8, c.y() + s * 0.8), QPointF(c.x() + s * 0.3, c.y() - s * 0.3))
        painter.drawEllipse(QPointF(c.x() + s * 0.5, c.y() - s * 0.5), s * 0.3, s * 0.3)
    elif kind == "ill_export":
        painter.drawLine(QPointF(c.x(), c.y() + s * 0.3), QPointF(c.x(), c.y() - s * 0.9))
        painter.drawLine(QPointF(c.x() - s * 0.4, c.y() - s * 0.5), QPointF(c.x(), c.y() - s * 0.9))
        painter.drawLine(QPointF(c.x() + s * 0.4, c.y() - s * 0.5), QPointF(c.x(), c.y() - s * 0.9))
        painter.drawPolyline(QPolygonF([QPointF(c.x() - s * 0.8, c.y()), QPointF(c.x() - s * 0.8, c.y() + s * 0.8),
                                        QPointF(c.x() + s * 0.8, c.y() + s * 0.8), QPointF(c.x() + s * 0.8, c.y())]))
    elif kind == "ill_swap":
        painter.drawArc(QRectF(c.x() - s * 0.7, c.y() - s * 0.7, s * 1.4, s * 1.4), 0, 90 * 16)
        painter.drawLine(QPointF(c.x() + s * 0.7, c.y()), QPointF(c.x() + s * 0.45, c.y() - s * 0.25))
        painter.drawLine(QPointF(c.x(), c.y() - s * 0.7), QPointF(c.x() - s * 0.25, c.y() - s * 0.45))
    else:                                                       # genre inconnu : un point
        painter.setBrush(color)
        painter.drawEllipse(c, s * 0.2, s * 0.2)
    painter.restore()
