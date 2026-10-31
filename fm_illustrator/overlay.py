"""Dessin temporaire du module Illustrator : noms et choix des plans de travail, survol, sélection (contours, points
d'ancrage, boîte englobante et poignées), poignées de Bézier de la Sélection directe, cadre de sélection, ligne
élastique de la plume, trait du crayon, bulle (taille / angle). Un seul `QGraphicsItem` hors du fichier et de
l'annulation, sans souris ; tailles constantes à l'écran.

Fluidité : seule la zone qui change est repeinte (ancienne + nouvelle zone dynamique, la vue est en
`MinimalViewportUpdate` quand le module est actif) ; au-delà de `MAX_ANCHORS` points choisis, les points ne sont plus
dessinés (contours et boîte seulement)."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QGraphicsItem

from . import bezier as bz, model
from .tools import HANDLE_PX, box_handles, visible_handles

OVERLAY_Z = 1e8
ANCHOR_SIDE = 5.0               # côté d'un point d'ancrage (pixels)
MAX_ANCHORS = 6000


class IllOverlay(QGraphicsItem):
    def __init__(self, controller):
        super().__init__()
        self.ctl = controller
        self.setZValue(OVERLAY_Z)
        self.setAcceptedMouseButtons(Qt.NoButton)
        self.setAcceptHoverEvents(False)
        self._bounds = QRectF()
        self._dirty: list[QRectF] = []
        self._key = None

    # -- zone --
    def _zoom(self) -> float:
        scene = self.scene()
        return max(1e-4, float(getattr(scene, "zoom", 1.0))) if scene is not None else 1.0

    def boundingRect(self) -> QRectF:
        return self._bounds

    def refresh(self):
        scene = self.scene()
        if scene is None:
            return
        bounds = scene.sceneRect()
        if bounds != self._bounds:
            self.prepareGeometryChange()
            self._bounds = QRectF(bounds)
            self.update()
        new = self.dynamic_rects()
        key = self._state_key()
        if key != self._key:                            # ce qui est peint a changé : anciennes et nouvelles zones
            self._key = key
            changed = self._dirty + new
        else:                                           # seulement les zones qui ont bougé (ligne élastique…)
            old = {_rect_key(r) for r in self._dirty}
            now = {_rect_key(r) for r in new}
            changed = [r for r in self._dirty if _rect_key(r) not in now] +                       [r for r in new if _rect_key(r) not in old]
        for rect in changed:
            self.update(rect)
        self._dirty = new

    def _state_key(self):
        """Ce qui change le dessin sans changer les zones : outil, sélection, points choisis, plan choisi, zoom."""
        ctl = self.ctl
        return (ctl.active, ctl.tool, ctl.artboard_id, round(self._zoom(), 6),
                tuple(i.item_id for i in ctl.selection()),
                tuple(sorted((k, tuple(sorted(v))) for k, v in ctl.anchors.items() if v)),
                id(ctl.hover), repr(ctl.tip), tuple(b.data.get("name") for b in ctl.artboards()))

    def dynamic_rects(self) -> list[QRectF]:
        """Zones peintes (scène) : à repeindre à chaque changement."""
        ctl = self.ctl
        if not ctl.active:
            return []
        z = self._zoom()
        pad = (HANDLE_PX + 12) / z
        out = []
        items = ctl.selection()
        rect = ctl.selection_rect(items)
        if rect is not None:
            if len(items) <= 40:                        # au-delà : une seule zone (moins d'appels à update)
                for item in items:
                    out.append(item.sceneBoundingRect().united(_control_rect(item)).adjusted(-pad, -pad, pad, pad))
            else:
                whole = rect
                for item in items:
                    whole = whole.united(item.sceneBoundingRect())
                out.append(whole.adjusted(-pad, -pad, pad, pad))
            out.append(rect.adjusted(-pad - 20 / z, -pad - 20 / z, pad + 20 / z, pad + 20 / z))
        if ctl.hover is not None and ctl.hover.scene() is not None:
            out.append(ctl.hover.sceneBoundingRect().adjusted(-pad, -pad, pad, pad))
        if ctl.marquee is not None:
            out.append(ctl.marquee.adjusted(-pad, -pad, pad, pad))
        if ctl.preview is not None:
            out.append(_preview_rect(ctl.preview).adjusted(-pad, -pad, pad, pad))
        for board in ctl.artboards():
            r = board.scene_rect()
            out.append(QRectF(r.left() - pad, r.top() - 24 / z, r.width() + 2 * pad, 24 / z + pad))
            if board.item_id == ctl.artboard_id:
                out.append(r.adjusted(-pad, -pad, pad, pad))
        if ctl.tip is not None:
            p = ctl.tip[0]
            out.append(QRectF(p.x() - 10 / z, p.y() - 10 / z, 200 / z, 50 / z))
        return out

    # -- peinture --
    def paint(self, painter: QPainter, option, widget=None):
        ctl = self.ctl
        if not ctl.active:
            return
        painter.setRenderHint(QPainter.Antialiasing, True)
        z = self._zoom()
        accent = QColor(model.ACCENT)
        self._paint_artboards(painter, z, accent)
        if ctl.hover is not None and ctl.hover.scene() is not None and not ctl.hover.isSelected():
            painter.setPen(QPen(accent, 1.5 / z))
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(ctl.hover.path.translated(ctl.hover.pos()))
        items = ctl.selection()
        if items:
            self._paint_selection(painter, z, accent, items)
        if ctl.marquee is not None:
            pen = QPen(QColor("#444444"), 0, Qt.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(ctl.marquee)
        if ctl.preview is not None:
            self._paint_preview(painter, z, accent)
        if ctl.tip is not None:
            self._paint_tip(painter, z)

    def _paint_artboards(self, painter, z, accent):
        ctl = self.ctl
        font = QFont()
        font.setPointSizeF(max(0.1, 9.0 / z))
        painter.setFont(font)
        for board in ctl.artboards():
            if not board.isVisible():
                continue
            r = board.scene_rect()
            chosen = board.item_id == ctl.artboard_id
            painter.setPen(QColor(model.ACCENT) if chosen else QColor("#6a6a6a"))
            painter.drawText(QPointF(r.left(), r.top() - 6 / z), str(board.data.get("name", "")))
            if chosen:
                painter.setPen(QPen(accent, 1.5 / z))
                painter.setBrush(Qt.NoBrush)
                painter.drawRect(r)
                self._paint_box_handles(painter, z, r, accent)

    def _paint_box_handles(self, painter, z, rect, accent):
        s = HANDLE_PX / z
        painter.setPen(QPen(accent, 1.0 / z))
        painter.setBrush(QColor("#ffffff"))
        for p in box_handles(rect).values():
            painter.drawRect(QRectF(p.x() - s, p.y() - s, 2 * s, 2 * s))

    def _paint_selection(self, painter, z, accent, items):
        ctl = self.ctl
        painter.setPen(QPen(accent, 1.0 / z))
        painter.setBrush(Qt.NoBrush)
        for item in items:
            painter.drawPath(item.path.translated(item.pos()))
        total = sum(len(s["nodes"]) for i in items for s in i.data["subpaths"])
        direct = ctl.tool in ("direct", "convert", "pen", "add_anchor", "delete_anchor")
        if total <= MAX_ANCHORS:
            a = ANCHOR_SIDE / 2 / z
            for item in items:
                ox, oy = item.data["x"], item.data["y"]
                chosen = ctl.anchors.get(item.item_id, set())
                for si, sub in enumerate(item.data["subpaths"]):
                    for ni, n in enumerate(sub["nodes"]):
                        filled = (si, ni) in chosen or not direct
                        painter.setBrush(accent if filled else QColor("#ffffff"))
                        painter.drawRect(QRectF(n[0] + ox - a, n[1] + oy - a, 2 * a, 2 * a))
        if direct:
            r = 3.0 / z
            for item, si, ni, which in visible_handles(ctl):
                n = item.data["subpaths"][si]["nodes"][ni]
                ox, oy = item.data["x"], item.data["y"]
                k = 2 if which == "in" else 4
                anchor = QPointF(n[0] + ox, n[1] + oy)
                handle = QPointF(n[k] + ox, n[k + 1] + oy)
                painter.setPen(QPen(accent, 1.0 / z))
                painter.drawLine(anchor, handle)
                painter.setBrush(accent)
                painter.drawEllipse(handle, r, r)
        elif ctl.tool == "select":
            rect = ctl.selection_rect()
            if rect is not None:
                painter.setPen(QPen(accent, 1.0 / z))
                painter.setBrush(Qt.NoBrush)
                painter.drawRect(rect)
                self._paint_box_handles(painter, z, rect, accent)

    def _paint_preview(self, painter, z, accent):
        kind = self.ctl.preview[0]
        painter.setPen(QPen(accent, 1.0 / z))
        painter.setBrush(Qt.NoBrush)
        if kind == "rubber":
            _kind, p0, c1, p3 = self.ctl.preview
            path = QPainterPath(QPointF(*p0))
            path.cubicTo(QPointF(*c1), QPointF(*p3), QPointF(*p3))
            painter.drawPath(path)
        elif kind == "polyline":
            pts = self.ctl.preview[1]
            if len(pts) > 1:
                path = QPainterPath(QPointF(*pts[0]))
                for p in pts[1:]:
                    path.lineTo(QPointF(*p))
                painter.setPen(QPen(QColor(self.ctl.style.get("stroke") or model.DEFAULT_STROKE),
                                    max(1.0 / z, float(self.ctl.style.get("stroke_width", 1.0)))))
                painter.drawPath(path)

    def _paint_tip(self, painter, z):
        pos, text = self.ctl.tip
        font = QFont()
        font.setPointSizeF(max(0.1, 8.5 / z))
        painter.setFont(font)
        box = QRectF(pos.x() + 14 / z, pos.y() + 14 / z, 150 / z, 20 / z)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(40, 40, 40, 220))
        painter.drawRoundedRect(box, 3 / z, 3 / z)
        painter.setPen(QColor("#ffffff"))
        painter.drawText(box, Qt.AlignCenter, text)


def _rect_key(r: QRectF) -> tuple:
    return round(r.x(), 4), round(r.y(), 4), round(r.width(), 4), round(r.height(), 4)


def _control_rect(item) -> QRectF:
    box = bz.control_bounds(item.data["subpaths"])
    if box is None:
        return item.sceneBoundingRect()
    ox, oy = item.data["x"], item.data["y"]
    return QRectF(box[0] + ox, box[1] + oy, box[2] - box[0], box[3] - box[1])


def _preview_rect(preview) -> QRectF:
    if preview[0] == "rubber":
        pts = preview[1:]
    else:
        pts = preview[1]
    xs = [p[0] for p in pts] or [0.0]
    ys = [p[1] for p in pts] or [0.0]
    return QRectF(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))
