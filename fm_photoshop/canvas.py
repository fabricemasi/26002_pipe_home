"""Établi d'édition (Qt) : le document en plein cadre, zoom / déplacement de la vue, outils à la souris et au stylet.

L'état de travail (outil, brosse, couleurs, zoom, centre) est dans la SESSION : le Board et le mode Standard le
partagent. Fluidité : aucune recomposition complète à un point de brosse — le trait écrit dans les pixels du calque
(tuiles de 64), la zone touchée invalide ce qu'il faut dans le cache de tuiles, et la peinture ne recompose que cette
partie (`render.TileCache`). Tuiles jamais calculées : en tranches de temps (le reste au tour suivant)."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QApplication, QWidget

from . import compose as C
from . import look, ops, render
from .brush import Stroke
from .planes import rect_intersect, rect_union

TOOLS = ("brush", "eraser", "eyedropper", "move", "hand")


class CanvasView(QWidget):
    message = Signal(str)               # texte d'état (calque verrouillé, outil refusé…)
    toolChanged = Signal(str)
    colorsChanged = Signal()

    def __init__(self, session, parent=None):
        super().__init__(parent)
        self.session = session
        self.cache = render.cache_for(session)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self.setMinimumSize(160, 120)
        self._stroke = None
        self._stroke_pressure = 1.0
        self._pan = None
        self._move = None
        self._space = False
        self._hover = None                  # dernière position de la souris (widget) : curseur de brosse
        self._pressure = 1.0
        self._checker = None
        self._checker_key = None
        self._pump = QTimer(self)
        self._pump.setSingleShot(True)
        self._pump.timeout.connect(self.update)
        session.listeners.append(self._on_session)

    def detach(self):
        if self._on_session in self.session.listeners:
            self.session.listeners.remove(self._on_session)

    # -- session --
    def _on_session(self, kind, rect):
        if kind in ("edit", "paint") and rect is not None:
            self.update_rect(rect)
        elif kind in ("structure", "reload"):
            self.update()
        elif kind == "view":
            self.update()

    # -- repère --
    def zoom(self) -> float:
        z = self.session.zoom
        return z if z else self.fit_zoom()

    def fit_zoom(self) -> float:
        doc = self.session.doc
        return max(0.01, min((self.width() - 40) / max(1, doc.width), (self.height() - 40) / max(1, doc.height), 1.0))

    def center(self):
        c = self.session.center
        return c if c else (self.session.doc.width / 2.0, self.session.doc.height / 2.0)

    def to_doc(self, point) -> tuple:
        z, (cx, cy) = self.zoom(), self.center()
        return (point.x() - self.width() / 2.0) / z + cx, (point.y() - self.height() / 2.0) / z + cy

    def to_widget(self, x: float, y: float) -> QPointF:
        z, (cx, cy) = self.zoom(), self.center()
        return QPointF((x - cx) * z + self.width() / 2.0, (y - cy) * z + self.height() / 2.0)

    def visible_doc_rect(self):
        x0, y0 = self.to_doc(QPointF(0, 0))
        x1, y1 = self.to_doc(QPointF(self.width(), self.height()))
        return (math.floor(x0) - 1, math.floor(y0) - 1, math.ceil(x1) + 1, math.ceil(y1) + 1)

    def update_rect(self, rect):
        a, b = self.to_widget(rect[0], rect[1]), self.to_widget(rect[2], rect[3])
        self.update(QRectF(a, b).normalized().adjusted(-2, -2, 2, 2).toAlignedRect())

    def fit(self):
        self.session.zoom = None
        self.session.center = None
        self.update()

    def set_zoom(self, zoom: float, anchor: QPointF | None = None):
        zoom = max(0.02, min(look.LOOK["max_zoom"], zoom))
        if anchor is None:
            anchor = QPointF(self.width() / 2.0, self.height() / 2.0)
        before = self.to_doc(anchor)
        self.session.zoom = zoom
        cx = before[0] - (anchor.x() - self.width() / 2.0) / zoom
        cy = before[1] - (anchor.y() - self.height() / 2.0) / zoom
        self.session.center = (cx, cy)
        self.update()

    # -- peinture --
    def _checker_brush(self):
        key = (look.LOOK["checker_a"], look.LOOK["checker_b"], look.LOOK["checker_size"])
        if self._checker_key != key:
            self._checker, self._checker_key = render.checker_brush(*key), key
        return self._checker

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(event.rect(), QColor(look.LOOK["bench_color"]))
        z = self.zoom()
        doc = self.session.doc
        origin = self.to_widget(0, 0)
        area = QRectF(origin, self.to_widget(doc.width, doc.height))
        shown = area.intersected(QRectF(event.rect()))
        if not shown.isEmpty():
            painter.setBrush(Qt.NoBrush)
            painter.fillRect(shown, self._checker_brush())
            painter.save()
            painter.translate(origin)
            painter.scale(z, z)
            painter.setRenderHint(QPainter.SmoothPixmapTransform, z < 1.0)
            rect = rect_intersect(self._rect_of(event.rect(), 2), doc.rect())
            keys = self.cache.keys_for(rect) if rect else []
            for key in keys:                                  # zones modifiées (peu de pixels) : toujours à jour
                if key in self.cache.tiles:
                    self.cache.tile(key)
            missing = [k for k in keys if k not in self.cache.tiles]
            if missing:                                       # jamais calculées : en tranches de temps
                self.cache.pump(missing, 25.0)
                if not all(k in self.cache.tiles for k in missing):
                    self._pump.start(1)
            for key in keys:
                image = self.cache.tiles[key][1] if key in self.cache.tiles else None
                if image is not None:
                    painter.drawImage(key[0] * render.TILE, key[1] * render.TILE, image)
            painter.restore()
            painter.setPen(QPen(QColor(look.LOOK["frame_color"]), 1))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(area.adjusted(-0.5, -0.5, 0.5, 0.5))
        self._paint_cursor(painter)
        painter.end()

    def _rect_of(self, widget_rect, margin=0):
        x0, y0 = self.to_doc(QPointF(widget_rect.left(), widget_rect.top()))
        x1, y1 = self.to_doc(QPointF(widget_rect.right() + 1, widget_rect.bottom() + 1))
        return (math.floor(x0) - margin, math.floor(y0) - margin, math.ceil(x1) + margin, math.ceil(y1) + margin)

    def brush_diameter(self) -> float:
        return self.session.brush.size * self.zoom()

    def _paint_cursor(self, painter):
        if self._hover is None or self.session.tool not in ("brush", "eraser") or not look.LOOK["cursor_outline"] \
                or self._pan is not None or self._move is not None:
            return
        radius = max(1.0, self.brush_diameter() / 2.0)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor(0, 0, 0, 200), 3))
        painter.drawEllipse(self._hover, radius, radius)
        painter.setPen(QPen(QColor(255, 255, 255, 230), 1))
        painter.drawEllipse(self._hover, radius, radius)

    def _cursor_rect(self):
        r = self.brush_diameter() / 2.0 + 4
        return QRectF(self._hover.x() - r, self._hover.y() - r, 2 * r, 2 * r).toAlignedRect()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update()

    # -- outils --
    def set_tool(self, tool: str):
        if tool in TOOLS and tool != self.session.tool:
            self.session.tool = tool
            self.toolChanged.emit(tool)
        self._refresh_cursor()
        self.update()

    def _refresh_cursor(self):
        tool = self.session.tool
        if self._pan is not None or self._space or tool == "hand":
            self.setCursor(Qt.ClosedHandCursor if self._pan else Qt.OpenHandCursor)
        elif tool in ("brush", "eraser") and look.LOOK["cursor_outline"]:
            self.setCursor(Qt.BlankCursor)
        elif tool == "eyedropper":
            self.setCursor(Qt.CrossCursor)
        else:
            self.setCursor(Qt.ArrowCursor)

    def current_brush(self):
        s = self.session
        brush = s.brush.copy(color=tuple(s.fg), eraser=(s.tool == "eraser"))
        return brush

    # -- souris --
    def mousePressEvent(self, event):
        self.setFocus()
        pos = event.position()
        if event.button() == Qt.MiddleButton or (event.button() == Qt.LeftButton and (self._space or
                                                                                      self.session.tool == "hand")):
            self._pan = (pos, self.center())
            self._refresh_cursor()
            return
        if event.button() != Qt.LeftButton:
            return
        tool = self.session.tool
        x, y = self.to_doc(pos)
        mods = event.modifiers()
        if tool == "eyedropper" or (tool in ("brush", "eraser") and mods & Qt.AltModifier):
            self.pick_color(x, y, background=bool(mods & Qt.ShiftModifier) if tool == "eyedropper" else False)
        elif tool in ("brush", "eraser"):
            self.begin_stroke(x, y, self._pressure)
        elif tool == "move":
            self.begin_move(x, y, bool(QApplication.keyboardModifiers() & Qt.ControlModifier))

    def mouseMoveEvent(self, event):
        pos = event.position()
        if self._hover is not None:
            self.update(self._cursor_rect())
        self._hover = pos
        if self._pan is not None:
            start, (cx, cy) = self._pan
            z = self.zoom()
            self.session.center = (cx - (pos.x() - start.x()) / z, cy - (pos.y() - start.y()) / z)
            self.update()
            return
        if self._stroke is not None:
            x, y = self.to_doc(pos)
            self.extend_stroke(x, y, self._pressure)
        elif self._move is not None:
            x, y = self.to_doc(pos)
            self.extend_move(x, y)
        if self._hover is not None:
            self.update(self._cursor_rect())

    def mouseReleaseEvent(self, event):
        if self._pan is not None and event.button() in (Qt.MiddleButton, Qt.LeftButton):
            self._pan = None
            self._refresh_cursor()
            return
        if event.button() != Qt.LeftButton:
            return
        if self._stroke is not None:
            x, y = self.to_doc(event.position())
            self.end_stroke(x, y, self._pressure)
        elif self._move is not None:
            self.end_move()

    def leaveEvent(self, event):
        if self._hover is not None:
            self.update(self._cursor_rect())
        self._hover = None
        super().leaveEvent(event)

    def wheelEvent(self, event):
        steps = event.angleDelta().y() / 120.0
        if steps:
            self.set_zoom(self.zoom() * (look.LOOK["zoom_step"] ** steps), event.position())
        event.accept()

    def tabletEvent(self, event):
        self._pressure = max(0.0, min(1.0, event.pressure())) if event.pointerType() != event.pointerType().Unknown \
            else 1.0
        if event.type() == event.type().TabletRelease:
            self._pressure = 1.0
        event.ignore()                                         # Qt rejoue l'évènement en souris : une seule logique

    def keyPressEvent(self, event):
        key, mods = event.key(), event.modifiers()
        ctrl = bool(mods & Qt.ControlModifier)
        s = self.session
        if key == Qt.Key_Space and not event.isAutoRepeat():
            self._space = True
            self._refresh_cursor()
        elif ctrl and key == Qt.Key_Z and not mods & Qt.ShiftModifier:
            self.undo()
        elif ctrl and (key == Qt.Key_Y or (key == Qt.Key_Z and mods & Qt.ShiftModifier)):
            self.redo()
        elif ctrl and key == Qt.Key_0:
            self.fit()
        elif ctrl and key == Qt.Key_1:
            self.set_zoom(1.0)
        elif ctrl and key in (Qt.Key_Plus, Qt.Key_Equal):
            self.set_zoom(self.zoom() * look.LOOK["zoom_step"])
        elif ctrl and key == Qt.Key_Minus:
            self.set_zoom(self.zoom() / look.LOOK["zoom_step"])
        elif ctrl:
            event.ignore()
            return
        elif key == Qt.Key_B:
            self.set_tool("brush")
        elif key == Qt.Key_E:
            self.set_tool("eraser")
        elif key == Qt.Key_I:
            self.set_tool("eyedropper")
        elif key == Qt.Key_V:
            self.set_tool("move")
        elif key == Qt.Key_H:
            self.set_tool("hand")
        elif key == Qt.Key_X:
            s.fg, s.bg = s.bg, s.fg
            self.colorsChanged.emit()
        elif key == Qt.Key_D:
            s.fg, s.bg = (0, 0, 0), (255, 255, 255)
            self.colorsChanged.emit()
        elif key == Qt.Key_BracketLeft:
            self.scale_brush(0.8)
        elif key == Qt.Key_BracketRight:
            self.scale_brush(1.25)
        else:
            event.ignore()
            return
        event.accept()

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key_Space and not event.isAutoRepeat():
            self._space = False
            self._refresh_cursor()
        super().keyReleaseEvent(event)

    def scale_brush(self, factor: float):
        brush = self.session.brush
        brush.size = max(1.0, min(2000.0, round(brush.size * factor)))
        self.colorsChanged.emit()
        self.update()

    # -- actions (appelées par les évènements, les barres et les tests) --
    def undo(self):
        if self._stroke is not None:
            return
        command = self.session.undo()
        self.message.emit(f"Annulé : {command.label}" if command else "Rien à annuler")

    def redo(self):
        if self._stroke is not None:
            return
        command = self.session.redo()
        self.message.emit(f"Rétabli : {command.label}" if command else "Rien à rétablir")

    def pick_color(self, x, y, background=False):
        rect = (int(math.floor(x)), int(math.floor(y)), int(math.floor(x)) + 1, int(math.floor(y)) + 1)
        if rect_intersect(rect, self.session.doc.rect()) is None:
            return
        r, g, b, a = (int(v) for v in C.flatten_u8(self.session.doc, rect)[0, 0])
        if a == 0:
            return
        if background:
            self.session.bg = (r, g, b)
        else:
            self.session.fg = (r, g, b)
        self.colorsChanged.emit()

    def begin_stroke(self, x, y, pressure=1.0):
        s = self.session
        layer = s.layer()
        try:
            self._stroke = Stroke(layer, s.target, self.current_brush(), s.doc.rect(), s.selection)
        except ValueError as exc:
            self.message.emit(str(exc))
            return None
        dirty = self._stroke.begin(x, y, pressure)
        self._notify_dirty(dirty)
        return self._stroke

    def extend_stroke(self, x, y, pressure=1.0):
        if self._stroke is not None:
            self._notify_dirty(self._stroke.move(x, y, pressure))

    def end_stroke(self, x, y, pressure=1.0):
        stroke, self._stroke = self._stroke, None
        if stroke is None:
            return None
        self._notify_dirty(stroke.finish_to(x, y, pressure))
        label = "Gomme" if stroke.brush.eraser else "Pinceau"
        if stroke.target == "mask":
            label += " (masque)"
        command = stroke.end(label)
        self.session.do(command, notified=True)
        return command

    def _notify_dirty(self, rect):
        if rect is not None:
            self.session.notify("paint", rect)

    # -- déplacer un calque : Ctrl + glisser (règle de l'appli) --
    def begin_move(self, x, y, ctrl: bool):
        s = self.session
        if not ctrl:
            self.message.emit("Déplacer un calque : Ctrl + glisser")
            return
        layer = s.layer()
        if layer.locked:
            self.message.emit("Le calque est verrouillé.")
            return
        rect = ops.layer_rect(layer)
        if rect is None:
            return
        self._move = {"layer": layer, "start": (x, y), "applied": (0, 0), "rect": rect}
        self._move_pending = None

    def extend_move(self, x, y):
        m = self._move
        if m is None:
            return
        dx, dy = round(x - m["start"][0]), round(y - m["start"][1])
        ax, ay = m["applied"]
        if (dx, dy) == (ax, ay):
            return
        before = ops.layer_rect(m["layer"])
        ops.shift_layer(m["layer"], dx - ax, dy - ay)
        m["applied"] = (dx, dy)
        after = ops.layer_rect(m["layer"])
        m["rect"] = rect_union(m["rect"], rect_union(before, after))
        self.session.notify("paint", rect_union(before, after))

    def end_move(self):
        m, self._move = self._move, None
        if m is None or m["applied"] == (0, 0):
            return None
        command = ops.translation_done(m["layer"], m["applied"][0], m["applied"][1], m["rect"])
        self.session.do(command, notified=True)
        return command
