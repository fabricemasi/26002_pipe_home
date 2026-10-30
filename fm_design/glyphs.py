"""Glyphes des boutons du module Design (traits, comme ceux du board) ; appelés par `fm_board.ui.paint_glyph`
pour tout genre « design… ». Une icône perso (Réglages > Module MRO > Icônes) les remplace comme les autres."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QFont, QPainter, QPainterPath, QPen, QPolygonF


def paint_design_glyph(painter: QPainter, kind: str, rect: QRectF, color):
    pen = QPen(color, 1.4)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    c = rect.center()
    s = min(rect.width(), rect.height()) * 0.2
    cx, cy = c.x(), c.y()
    letters = {"design_bold": ("B", True, False, False), "design_italic": ("I", False, True, False),
               "design_underline": ("U", False, False, True), "design_text": ("T", True, False, False),
               "design_upper": ("aA", False, False, False)}
    if kind in letters:
        text, bold, italic, underline = letters[kind]
        font = QFont()
        font.setPixelSize(max(6, int(s * (3.4 if len(text) == 1 else 2.4))))
        font.setBold(bold)
        font.setItalic(italic)
        font.setUnderline(underline)
        painter.setFont(font)
        painter.drawText(rect, Qt.AlignCenter, text)
        return
    if kind.startswith("design_shape:"):       # forme du module (dont cœur, anneau)
        from .items import design_shape_path
        shape = kind.split(":", 1)[1]
        box = QRectF(cx - s * 1.5, cy - s * 1.1, s * 3.0, s * 2.2)
        if shape == "line":
            painter.drawLine(QPointF(box.left(), cy), QPointF(box.right(), cy))
        else:
            painter.drawPath(design_shape_path(shape or "rect", box, s * 0.5))
        return
    if kind == "design":                      # module : palette (pastilles dans un cadre arrondi)
        painter.drawRoundedRect(QRectF(cx - s * 1.5, cy - s * 1.5, s * 3, s * 3), s * 0.7, s * 0.7)
        painter.setBrush(color)
        painter.drawEllipse(QPointF(cx - s * 0.6, cy - s * 0.5), s * 0.42, s * 0.42)
        painter.drawPolygon(QPolygonF([QPointF(cx + s * 0.2, cy + s * 0.9), QPointF(cx + s * 0.75, cy - s * 0.1),
                                       QPointF(cx + s * 1.1, cy + s * 0.9)]))
    elif kind == "design_templates":
        for dx, dy in ((-1, -1), (0.15, -1), (-1, 0.15), (0.15, 0.15)):
            painter.drawRoundedRect(QRectF(cx + dx * s * 1.3, cy + dy * s * 1.3, s * 1.15, s * 1.15), 2, 2)
    elif kind == "design_elements":
        painter.drawEllipse(QPointF(cx - s * 0.75, cy - s * 0.7), s * 0.65, s * 0.65)
        painter.drawRect(QRectF(cx + s * 0.1, cy - s * 1.35, s * 1.3, s * 1.3))
        painter.drawPolygon(QPolygonF([QPointF(cx - s * 0.2, cy + s * 0.3), QPointF(cx + s * 0.6, cy + s * 1.5),
                                       QPointF(cx - s * 1.0, cy + s * 1.5)]))
    elif kind == "design_images":
        painter.drawRoundedRect(QRectF(cx - s * 1.5, cy - s * 1.2, s * 3, s * 2.4), 2, 2)
        painter.drawPolyline(QPolygonF([QPointF(cx - s * 1.3, cy + s * 1.0), QPointF(cx - s * 0.3, cy - s * 0.1),
                                        QPointF(cx + s * 0.3, cy + s * 0.5), QPointF(cx + s * 0.8, cy),
                                        QPointF(cx + s * 1.4, cy + s * 0.8)]))
        painter.drawEllipse(QPointF(cx + s * 0.7, cy - s * 0.6), s * 0.25, s * 0.25)
    elif kind == "design_layers":
        for dy in (-0.7, 0.0, 0.7):
            painter.drawPolygon(QPolygonF([QPointF(cx, cy + (dy - 0.6) * s), QPointF(cx + s * 1.4, cy + dy * s),
                                           QPointF(cx, cy + (dy + 0.6) * s), QPointF(cx - s * 1.4, cy + dy * s)]))
    elif kind == "design_export":
        painter.drawLine(QPointF(cx, cy - s * 1.4), QPointF(cx, cy + s * 0.5))
        painter.drawPolyline(QPolygonF([QPointF(cx - s * 0.7, cy - s * 0.2), QPointF(cx, cy + s * 0.5),
                                        QPointF(cx + s * 0.7, cy - s * 0.2)]))
        painter.drawPolyline(QPolygonF([QPointF(cx - s * 1.4, cy + s * 0.6), QPointF(cx - s * 1.4, cy + s * 1.4),
                                        QPointF(cx + s * 1.4, cy + s * 1.4), QPointF(cx + s * 1.4, cy + s * 0.6)]))
    elif kind == "design_effects":
        font = QFont()
        font.setPixelSize(max(6, int(s * 3.2)))
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(rect.translated(1.2, 1.2), Qt.AlignCenter, "A")
        painter.setPen(QPen(color, 0.8))
        painter.drawText(rect, Qt.AlignCenter, "A")
    elif kind == "design_table":
        painter.drawRect(QRectF(cx - s * 1.5, cy - s * 1.2, s * 3, s * 2.4))
        painter.drawLine(QPointF(cx - s * 1.5, cy - s * 0.4), QPointF(cx + s * 1.5, cy - s * 0.4))
        painter.drawLine(QPointF(cx - s * 1.5, cy + s * 0.4), QPointF(cx + s * 1.5, cy + s * 0.4))
        painter.drawLine(QPointF(cx - s * 0.5, cy - s * 1.2), QPointF(cx - s * 0.5, cy + s * 1.2))
        painter.drawLine(QPointF(cx + s * 0.5, cy - s * 1.2), QPointF(cx + s * 0.5, cy + s * 1.2))
    elif kind == "design_chart_bar":
        painter.setBrush(color)
        for n, h in enumerate((1.2, 2.2, 1.6)):
            painter.drawRect(QRectF(cx - s * 1.3 + n * s * 0.95, cy + s * 1.3 - h * s, s * 0.6, h * s))
    elif kind == "design_chart_line":
        painter.drawPolyline(QPolygonF([QPointF(cx - s * 1.5, cy + s * 0.9), QPointF(cx - s * 0.5, cy - s * 0.2),
                                        QPointF(cx + s * 0.4, cy + s * 0.4), QPointF(cx + s * 1.5, cy - s * 1.1)]))
        painter.drawLine(QPointF(cx - s * 1.5, cy + s * 1.4), QPointF(cx + s * 1.5, cy + s * 1.4))
    elif kind in ("design_chart_pie", "design_chart_donut"):
        box = QRectF(cx - s * 1.4, cy - s * 1.4, s * 2.8, s * 2.8)
        painter.drawEllipse(box)
        painter.setBrush(color)
        painter.drawPie(box, 90 * 16, -110 * 16)
        if kind == "design_chart_donut":
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(box.adjusted(s * 0.8, s * 0.8, -s * 0.8, -s * 0.8))
    elif kind == "design_present":
        painter.drawRoundedRect(QRectF(cx - s * 1.5, cy - s * 1.2, s * 3, s * 2.1), 2, 2)
        painter.drawLine(QPointF(cx, cy + s * 0.9), QPointF(cx, cy + s * 1.5))
        painter.drawLine(QPointF(cx - s * 0.6, cy + s * 1.5), QPointF(cx + s * 0.6, cy + s * 1.5))
        painter.setBrush(color)
        painter.drawPolygon(QPolygonF([QPointF(cx - s * 0.35, cy - s * 0.65), QPointF(cx + s * 0.55, cy - s * 0.15),
                                       QPointF(cx - s * 0.35, cy + s * 0.35)]))
    elif kind == "design_add_page":
        painter.drawRoundedRect(QRectF(cx - s * 1.1, cy - s * 1.5, s * 2.2, s * 3), 2, 2)
        painter.drawLine(QPointF(cx - s * 0.5, cy), QPointF(cx + s * 0.5, cy))
        painter.drawLine(QPointF(cx, cy - s * 0.5), QPointF(cx, cy + s * 0.5))
    elif kind == "design_crop":
        painter.drawPolyline(QPolygonF([QPointF(cx - s * 0.9, cy - s * 1.5), QPointF(cx - s * 0.9, cy + s * 0.9),
                                        QPointF(cx + s * 1.5, cy + s * 0.9)]))
        painter.drawPolyline(QPolygonF([QPointF(cx - s * 1.5, cy - s * 0.9), QPointF(cx + s * 0.9, cy - s * 0.9),
                                        QPointF(cx + s * 0.9, cy + s * 1.5)]))
    elif kind == "design_adjust":
        for n, x in enumerate((-0.9, 0.0, 0.9)):
            painter.drawLine(QPointF(cx + x * s, cy - s * 1.4), QPointF(cx + x * s, cy + s * 1.4))
            y = (-0.5, 0.6, -0.1)[n] * s
            painter.setBrush(color)
            painter.drawEllipse(QPointF(cx + x * s, cy + y), s * 0.32, s * 0.32)
            painter.setBrush(Qt.NoBrush)
    elif kind == "design_opacity":
        painter.drawRect(QRectF(cx - s * 1.3, cy - s * 1.3, s * 2.6, s * 2.6))
        painter.setBrush(color)
        painter.setPen(Qt.NoPen)
        for i in range(3):
            for j in range(3):
                if (i + j) % 2 == 0:
                    painter.drawRect(QRectF(cx - s * 1.3 + i * s * 0.87, cy - s * 1.3 + j * s * 0.87, s * 0.87,
                                            s * 0.87))
    elif kind == "design_shadow":
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(QRectF(cx - s * 1.4, cy - s * 1.4, s * 2.2, s * 2.2), 2, 2)
        painter.setPen(QPen(color, s * 0.45))
        painter.drawPolyline(QPolygonF([QPointF(cx + s * 1.1, cy - s * 0.8), QPointF(cx + s * 1.1, cy + s * 1.1),
                                        QPointF(cx - s * 0.8, cy + s * 1.1)]))
    elif kind == "design_flip":
        painter.drawLine(QPointF(cx, cy - s * 1.5), QPointF(cx, cy + s * 1.5))
        painter.drawPolygon(QPolygonF([QPointF(cx - s * 0.3, cy - s), QPointF(cx - s * 1.4, cy + s),
                                       QPointF(cx - s * 0.3, cy + s)]))
        painter.setBrush(color)
        painter.drawPolygon(QPolygonF([QPointF(cx + s * 0.3, cy - s), QPointF(cx + s * 1.4, cy + s),
                                       QPointF(cx + s * 0.3, cy + s)]))
    elif kind == "design_position":
        painter.drawRect(QRectF(cx - s * 1.4, cy - s * 0.7, s * 1.6, s * 1.6))
        painter.setBrush(color)
        painter.drawRect(QRectF(cx - s * 0.4, cy - s * 1.3, s * 1.7, s * 1.5))
    elif kind in ("design_group", "design_ungroup"):
        dash = QPen(color, 1.2, Qt.DashLine if kind == "design_group" else Qt.SolidLine)
        painter.setPen(dash)
        painter.drawRect(QRectF(cx - s * 1.5, cy - s * 1.5, s * 3, s * 3))
        painter.setPen(pen)
        painter.drawRect(QRectF(cx - s * 1.0, cy - s * 1.0, s * 1.1, s * 1.1))
        painter.drawRect(QRectF(cx - s * 0.1, cy - s * 0.1, s * 1.1, s * 1.1))
    elif kind == "design_duplicate":
        painter.drawRoundedRect(QRectF(cx - s * 1.4, cy - s * 1.4, s * 2.0, s * 2.0), 2, 2)
        painter.drawRoundedRect(QRectF(cx - s * 0.6, cy - s * 0.6, s * 2.0, s * 2.0), 2, 2)
    elif kind == "design_delete":
        painter.drawLine(QPointF(cx - s * 1.3, cy - s * 0.9), QPointF(cx + s * 1.3, cy - s * 0.9))
        painter.drawLine(QPointF(cx - s * 0.4, cy - s * 1.4), QPointF(cx + s * 0.4, cy - s * 1.4))
        path = QPainterPath()
        path.moveTo(cx - s * 1.0, cy - s * 0.9)
        path.lineTo(cx - s * 0.75, cy + s * 1.4)
        path.lineTo(cx + s * 0.75, cy + s * 1.4)
        path.lineTo(cx + s * 1.0, cy - s * 0.9)
        painter.drawPath(path)
    elif kind == "design_spacing":
        painter.drawLine(QPointF(cx - s * 1.5, cy - s * 1.2), QPointF(cx - s * 1.5, cy + s * 1.2))
        painter.drawLine(QPointF(cx + s * 1.5, cy - s * 1.2), QPointF(cx + s * 1.5, cy + s * 1.2))
        painter.drawLine(QPointF(cx - s * 0.9, cy), QPointF(cx + s * 0.9, cy))
        painter.drawPolyline(QPolygonF([QPointF(cx - s * 0.5, cy - s * 0.4), QPointF(cx - s * 0.9, cy),
                                        QPointF(cx - s * 0.5, cy + s * 0.4)]))
        painter.drawPolyline(QPolygonF([QPointF(cx + s * 0.5, cy - s * 0.4), QPointF(cx + s * 0.9, cy),
                                        QPointF(cx + s * 0.5, cy + s * 0.4)]))
    elif kind == "design_resize":
        painter.drawRect(QRectF(cx - s * 1.5, cy - s * 1.0, s * 3.0, s * 2.0))
        painter.drawPolyline(QPolygonF([QPointF(cx + s * 0.4, cy - s * 0.4), QPointF(cx + s * 0.9, cy - s * 0.4),
                                        QPointF(cx + s * 0.9, cy + s * 0.1)]))
        painter.drawLine(QPointF(cx + s * 0.9, cy - s * 0.4), QPointF(cx + s * 0.1, cy + s * 0.4))
    elif kind.startswith("design_align_"):
        mode = kind[len("design_align_"):]
        if mode in ("left", "hcenter", "right"):
            x = {"left": cx - s * 1.4, "hcenter": cx, "right": cx + s * 1.4}[mode]
            painter.drawLine(QPointF(x, cy - s * 1.6), QPointF(x, cy + s * 1.6))
            for y, w in ((-0.8, 2.2), (0.6, 1.4)):
                left = {"left": x, "hcenter": x - w * s / 2, "right": x - w * s}[mode]
                painter.drawRect(QRectF(left, cy + (y - 0.35) * s, w * s, 0.7 * s))
        else:
            y = {"top": cy - s * 1.4, "vcenter": cy, "bottom": cy + s * 1.4}[mode]
            painter.drawLine(QPointF(cx - s * 1.6, y), QPointF(cx + s * 1.6, y))
            for x, h in ((-0.8, 2.2), (0.6, 1.4)):
                top = {"top": y, "vcenter": y - h * s / 2, "bottom": y - h * s}[mode]
                painter.drawRect(QRectF(cx + (x - 0.35) * s, top, 0.7 * s, h * s))
    else:
        painter.drawRect(QRectF(cx - s, cy - s, 2 * s, 2 * s))
