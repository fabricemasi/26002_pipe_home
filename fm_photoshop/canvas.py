"""Établi d'édition (Qt) : le document en plein cadre, zoom / déplacement de la vue, outils à la souris et au stylet.

L'état de travail (outil, brosse, couleurs, zoom, centre) est dans la SESSION : le Board et le mode Standard le
partagent. Fluidité : aucune recomposition complète à un point de brosse — le trait écrit dans les pixels du calque
(tuiles de 64), la zone touchée invalide ce qu'il faut dans le cache de tuiles, et la peinture ne recompose que cette
partie (`render.TileCache`). Tuiles jamais calculées : en tranches de temps (le reste au tour suivant)."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QApplication, QWidget

from . import compose as C
from . import look, ops, render
from . import selection as SEL
from .actions import Actions
from .brush import Stroke
from .planes import rect_intersect, rect_union

TOOLS = ("brush", "eraser", "eyedropper", "move", "hand", "rect_select", "ellipse_select", "lasso", "poly_lasso",
         "wand", "text", "shape_rect", "shape_ellipse", "shape_line", "clone", "heal", "blur", "sharpen", "smudge",
         "dodge", "burn")
RETOUCH_TOOLS = ("clone", "heal", "blur", "sharpen", "smudge", "dodge", "burn")      # outil = mode de la brosse
SHAPE_TOOLS = {"shape_rect": "rect", "shape_ellipse": "ellipse", "shape_line": "line"}
SELECT_TOOLS = ("rect_select", "ellipse_select", "lasso", "poly_lasso", "wand")


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
        self.actions = Actions(session)
        self._gesture = None                # sélection en cours : {"tool", "mode", "points": [...]}
        self._outline = None                # contour des « fourmis » : QPainterPath (doc), refait si la sélection change
        self._zooming = False                       # zoom continu : dessin rapide, puis lissé 150 ms après le dernier cran
        self._zoom_done = QTimer(self)
        self._zoom_done.setSingleShot(True)
        self._zoom_done.setInterval(150)
        self._zoom_done.timeout.connect(self._zoom_settled)
        self._prefetch = QTimer(self)               # tuiles voisines de la vue, calculées pendant les temps morts
        self._prefetch.setSingleShot(True)
        self._prefetch.timeout.connect(self._prefetch_tiles)
        self._ants = QTimer(self)
        self._ants.setInterval(160)
        self._ants.timeout.connect(self._tick_ants)
        self._phase = 0
        session.listeners.append(self._on_session)

    def detach(self):
        if self._on_session in self.session.listeners:
            self.session.listeners.remove(self._on_session)

    # -- session --
    def _on_session(self, kind, rect):
        if kind in ("edit", "paint") and rect is not None:
            self.update_rect(rect)
        elif kind in ("structure", "reload", "view"):
            self.update()
        elif kind == "selection":
            self._outline = None
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
            painter.setRenderHint(QPainter.SmoothPixmapTransform, z < 1.0 and not self._zooming)
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
            preview = self._move["preview"] if self._move else None
            for key in keys:
                if preview is not None and key in preview.touched:      # déplacement en cours : aperçu (movepreview.py)
                    image = preview.base_image(key)
                else:
                    image = self.cache.tiles[key][1] if key in self.cache.tiles else None
                if image is not None:
                    painter.drawImage(key[0] * render.TILE, key[1] * render.TILE, image)
            if preview is not None:
                painter.setClipRect(QRectF(0, 0, doc.width, doc.height))
                preview.paint_layer(painter)
            painter.restore()
            self._prefetch.start(40)
            painter.setPen(QPen(QColor(look.LOOK["frame_color"]), 1))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(area.adjusted(-0.5, -0.5, 0.5, 0.5))
        self._paint_selection(painter)
        self._paint_clone_source(painter)
        self._paint_cursor(painter)
        painter.end()

    def _prefetch_tiles(self):
        """Une couronne de tuiles autour de la vue, par tranches de 8 ms : déplacer la vue n'attend plus leur calcul."""
        if not self.isVisible() or self._stroke is not None or self._move is not None:
            return
        v = self.visible_doc_rect()
        ring = rect_intersect((v[0] - render.TILE, v[1] - render.TILE, v[2] + render.TILE, v[3] + render.TILE),
                              self.session.doc.rect())
        keys = [k for k in self.cache.keys_for(ring) if not self.cache.is_ready(k)] if ring else []
        if keys and not self.cache.pump(keys, 8.0):
            self._prefetch.start(5)

    def _rect_of(self, widget_rect, margin=0):
        x0, y0 = self.to_doc(QPointF(widget_rect.left(), widget_rect.top()))
        x1, y1 = self.to_doc(QPointF(widget_rect.right() + 1, widget_rect.bottom() + 1))
        return (math.floor(x0) - margin, math.floor(y0) - margin, math.ceil(x1) + margin, math.ceil(y1) + margin)

    def brush_diameter(self) -> float:
        return self.session.brush.size * self.zoom()

    def _paint_cursor(self, painter):
        if self._hover is None or self.session.tool not in ("brush", "eraser") + RETOUCH_TOOLS \
                or not look.LOOK["cursor_outline"] \
                or self._pan is not None or self._move is not None:
            return
        radius = max(1.0, self.brush_diameter() / 2.0)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor(0, 0, 0, 200), 3))
        painter.drawEllipse(self._hover, radius, radius)
        painter.setPen(QPen(QColor(255, 255, 255, 230), 1))
        painter.drawEllipse(self._hover, radius, radius)

    def _paint_clone_source(self, painter):
        clone = self.session.clone
        if self.session.tool not in ("clone", "heal") or clone["source"] is None:
            return
        spot = QPointF(*clone["source"])
        if clone["offset"] is not None and self._hover is not None:
            x, y = self.to_doc(self._hover)
            spot = QPointF(x + clone["offset"][0], y + clone["offset"][1])
        p = self.to_widget(spot.x(), spot.y())
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        for pen in (QPen(QColor(0, 0, 0, 220), 3), QPen(QColor(255, 255, 255, 240), 1)):
            painter.setPen(pen)
            painter.drawLine(QPointF(p.x() - 8, p.y()), QPointF(p.x() + 8, p.y()))
            painter.drawLine(QPointF(p.x(), p.y() - 8), QPointF(p.x(), p.y() + 8))
        painter.restore()

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
        elif (tool in ("brush", "eraser") or tool in RETOUCH_TOOLS) and look.LOOK["cursor_outline"]:
            self.setCursor(Qt.BlankCursor)
        elif tool == "eyedropper" or tool in SELECT_TOOLS or tool in SHAPE_TOOLS or tool == "text":
            self.setCursor(Qt.CrossCursor)
        else:
            self.setCursor(Qt.ArrowCursor)

    def current_brush(self):
        s = self.session
        mode = s.tool if s.tool in RETOUCH_TOOLS else "paint"
        return s.brush.copy(color=tuple(s.fg), eraser=(s.tool == "eraser"), mode=mode)

    def set_clone_source(self, x, y):
        self.session.clone = {"source": (float(x), float(y)), "offset": None}
        self.message.emit("Source du tampon / correcteur choisie.")
        self.update()

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
        if tool in ("clone", "heal") and mods & Qt.AltModifier:
            self.set_clone_source(x, y)                          # source choisie EXPLICITEMENT (Alt + clic)
        elif tool == "eyedropper" or (tool in ("brush", "eraser") and mods & Qt.AltModifier):
            self.pick_color(x, y, background=bool(mods & Qt.ShiftModifier) if tool == "eyedropper" else False)
        elif tool in ("brush", "eraser") or tool in RETOUCH_TOOLS:
            self.begin_stroke(x, y, self._pressure)
        elif tool in SELECT_TOOLS:
            self.begin_select(tool, x, y, mods)
        elif tool == "text":
            self.text_at(x, y)
        elif tool in SHAPE_TOOLS:
            self._gesture = {"tool": tool, "mode": "replace", "points": [(x, y), (x, y)], "moved": False}
        elif tool == "move":
            self.begin_move(x, y, bool(QApplication.keyboardModifiers() & Qt.ControlModifier))

    def mouseMoveEvent(self, event):
        pos = event.position()
        if self._hover is not None:
            self.update(self._cursor_rect())
        self._hover = pos
        if self.session.tool in ("clone", "heal") and self.session.clone["source"] is not None:
            self.update()                                          # la croix de la source suit le pointeur
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
        elif self._gesture is not None:
            x, y = self.to_doc(pos)
            self.extend_select(x, y)
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
        elif self._gesture is not None:
            x, y = self.to_doc(event.position())
            self.end_select(x, y)

    def contextMenuEvent(self, event):
        """Clic droit : le menu Édition (copier, coller, remplir, effacer…) ou, sur une sélection, le menu Sélection."""
        factory = getattr(self, "context_menu_factory", None)
        if factory is None or self._stroke is not None or self._move is not None:
            return
        menu = factory("selection" if self.session.selection is not None else "edit")
        self._context_menu = menu
        menu.popup(event.globalPos())

    def mouseDoubleClickEvent(self, event):
        if self._gesture is not None and self._gesture["tool"] == "poly_lasso":
            self.close_polygon()
            return
        super().mouseDoubleClickEvent(event)

    def leaveEvent(self, event):
        if self._hover is not None:
            self.update(self._cursor_rect())
        self._hover = None
        super().leaveEvent(event)

    def wheelEvent(self, event):
        steps = event.angleDelta().y() / 120.0
        if steps:
            self._zooming = True                    # approximation TEMPORAIRE (rapide) remplacée par le lissage exact
            self._zoom_done.start()
            self.set_zoom(self.zoom() * (look.LOOK["zoom_step"] ** steps), event.position())
        event.accept()

    def _zoom_settled(self):
        self._zooming = False
        self.update()

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
        elif ctrl and key == Qt.Key_A:
            self.actions.select_all()
        elif ctrl and key == Qt.Key_D:
            self.actions.deselect()
        elif ctrl and mods & Qt.ShiftModifier and key == Qt.Key_I:
            self.actions.invert_selection()
        elif ctrl and key == Qt.Key_C:
            self.actions.copy()
        elif ctrl and key == Qt.Key_X:
            self.actions.cut()
        elif ctrl and key == Qt.Key_V:
            self.actions.paste()
        elif ctrl and key == Qt.Key_J:
            (self.actions.layer_via_cut if mods & Qt.ShiftModifier else self.actions.layer_via_copy)()
        elif key in (Qt.Key_Delete, Qt.Key_Backspace) and not ctrl and not mods & Qt.AltModifier:
            self.actions.delete()
        elif key == Qt.Key_Backspace and mods & Qt.AltModifier:
            self.actions.fill_foreground()
        elif key == Qt.Key_Backspace and ctrl:
            self.actions.fill_background()
        elif key in (Qt.Key_Return, Qt.Key_Enter) and self._gesture is not None:
            self.close_polygon()
        elif key == Qt.Key_Escape and self._gesture is not None:
            self._gesture = None
            self.update()
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
        elif key == Qt.Key_M:
            self.set_tool("ellipse_select" if s.tool == "rect_select" else "rect_select")
        elif key == Qt.Key_L:
            self.set_tool("poly_lasso" if s.tool == "lasso" else "lasso")
        elif key == Qt.Key_W:
            self.set_tool("wand")
        elif key == Qt.Key_T:
            self.set_tool("text")
        elif key == Qt.Key_S:
            self.set_tool("clone")
        elif key == Qt.Key_J:
            self.set_tool("heal")
        elif key == Qt.Key_R:
            self.set_tool("blur")
        elif key == Qt.Key_O:
            self.set_tool("dodge")
        elif key == Qt.Key_U:
            self.set_tool({"shape_rect": "shape_ellipse", "shape_ellipse": "shape_line"}.get(s.tool, "shape_rect"))
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
        retouch = None
        if s.tool in ("clone", "heal"):
            clone = s.clone
            if clone["source"] is not None:
                if clone["offset"] is None or not clone["aligned"]:
                    clone["offset"] = (clone["source"][0] - x, clone["source"][1] - y)     # fixé au 1er coup de trait
                retouch = {"offset": (round(clone["offset"][0]), round(clone["offset"][1]))}
        try:
            self._stroke = Stroke(layer, s.target, self.current_brush(), s.doc.rect(), s.selection, retouch)
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
        from .brush import MODE_LABELS
        label = "Gomme" if stroke.brush.eraser else MODE_LABELS.get(stroke.mode, "Pinceau").split(" (")[0]
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
        from .movepreview import MovePreview
        # Les pixels du modèle ne bougent PAS pendant le geste (aperçu : voir movepreview.py) ; décalage à la fin.
        preview = MovePreview(s.doc, layer)
        preview.warm(self.visible_doc_rect())
        self._move = {"layer": layer, "start": (x, y), "applied": (0, 0), "rect": rect, "preview": preview}

    def extend_move(self, x, y):
        m = self._move
        if m is None:
            return
        dx, dy = round(x - m["start"][0]), round(y - m["start"][1])
        if (dx, dy) == m["applied"]:
            return
        m["applied"] = (dx, dy)
        dirty = m["preview"].set_offset(dx, dy)
        if dirty is not None:
            m["rect"] = rect_union(m["rect"], dirty)
            self.update_rect(dirty)

    def end_move(self):
        m, self._move = self._move, None
        if m is None or m["applied"] == (0, 0):
            self.update()
            return None
        dx, dy = m["applied"]
        ops.shift_layer(m["layer"], dx, dy)                         # le modèle est décalé UNE fois, à la fin
        command = ops.translation_done(m["layer"], dx, dy, m["rect"])
        self.session.notify("edit", m["rect"])                      # le cache recompose le résultat exact
        self.session.do(command, notified=True)
        self.update()
        return command

    # -- texte et formes --
    def text_at(self, x, y):
        """Outil Texte : un clic sur un calque de texte le modifie, ailleurs il en crée un (fenêtre de texte)."""
        from .dialogs import TextDialog
        layer = self.session.layer()
        source = layer.source if layer.source and layer.source.get("kind") == "text" else None
        dialog = TextDialog(self.session, self.actions, layer if source else None, (x, y), self.window())
        self._dialog = dialog
        dialog.exec()
        return dialog

    def create_shape(self, shape, start, end):
        s = self.session
        if shape == "line":
            if (abs(end[0] - start[0]) + abs(end[1] - start[1])) < 2:
                return None
            source = {"shape": "line", "x": start[0], "y": start[1], "x1": end[0], "y1": end[1], "fill": None,
                      "stroke": list(s.fg) + [255], "stroke_width": s.shape_options["stroke_width"]}
        else:
            x0, y0, x1, y1 = min(start[0], end[0]), min(start[1], end[1]), max(start[0], end[0]), max(start[1], end[1])
            if x1 - x0 < 2 or y1 - y0 < 2:
                return None
            o = s.shape_options
            source = {"shape": shape, "x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0,
                      "fill": list(s.fg) + [255] if o["fill"] else None,
                      "stroke": list(s.bg) + [255] if o["stroke"] else None, "stroke_width": o["stroke_width"],
                      "radius": o["radius"]}
        return self.actions.add_shape(source)

    # -- sélections : outils, contour animé --
    @staticmethod
    def _mode_of(mods) -> str:
        shift, alt = bool(mods & Qt.ShiftModifier), bool(mods & Qt.AltModifier)
        return "intersect" if shift and alt else "add" if shift else "subtract" if alt else "replace"

    def begin_select(self, tool, x, y, mods):
        mode = self._mode_of(mods)
        if tool == "wand":
            o = self.session.options
            self.actions.wand_at(x, y, o["tolerance"], o["contiguous"], mode, o["sample"])
            return
        if tool == "poly_lasso" and self._gesture is not None:
            points = self._gesture["points"]
            first = self.to_widget(*points[0])
            if (self.to_widget(x, y) - first).manhattanLength() < 8 and len(points) >= 3:
                self.close_polygon()
            else:
                points.append((x, y))
                self.update()
            return
        self._gesture = {"tool": tool, "mode": mode, "points": [(x, y)], "moved": False}

    def extend_select(self, x, y):
        g = self._gesture
        if g["tool"] == "poly_lasso":
            g["cursor"] = (x, y)
        elif g["tool"] == "lasso":
            if (x, y) != g["points"][-1]:
                g["points"].append((x, y))
        else:
            g["points"] = [g["points"][0], (x, y)]
        g["moved"] = True
        self.update()

    def end_select(self, x, y):
        g = self._gesture
        if g["tool"] == "poly_lasso":
            return                                          # le polygone se poursuit : clics, double-clic ou Entrée
        self._gesture = None
        rect = self.session.doc.rect()
        if g["tool"] in SHAPE_TOOLS:
            self.create_shape(SHAPE_TOOLS[g["tool"]], g["points"][0], (x, y))
            self.update()
            return
        if g["tool"] in ("rect_select", "ellipse_select"):
            (x0, y0), (x1, y1) = g["points"][0], (x, y)
            box = (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
            if box[2] - box[0] < 1.5 and box[3] - box[1] < 1.5:
                if g["mode"] == "replace":
                    self.actions.deselect()                 # simple clic : désélectionne (comme Photoshop)
                self.update()
                return
            new = SEL.rectangle(rect, box) if g["tool"] == "rect_select" else SEL.ellipse(rect, box)
            self.actions.combine_selection(new, g["mode"], "Rectangle de sélection" if g["tool"] == "rect_select"
                                           else "Ellipse de sélection")
        elif len(g["points"]) >= 3:
            self.actions.combine_selection(SEL.polygon(rect, g["points"]), g["mode"], "Lasso")
        self.update()

    def close_polygon(self):
        g, self._gesture = self._gesture, None
        if g is not None and len(g["points"]) >= 3:
            self.actions.combine_selection(SEL.polygon(self.session.doc.rect(), g["points"]), g["mode"],
                                           "Lasso polygonal")
        self.update()

    def _selection_path(self):
        sel = self.session.selection
        if sel is None or sel.is_empty():
            return None
        if self._outline is None:
            segments = SEL.outline_segments(self.session.doc.rect(), sel)
            path = QPainterPath()
            if segments is None:
                b = sel.bounds()
                path.addRect(b[0], b[1], b[2] - b[0], b[3] - b[1])
            else:
                for x0, y0, x1, y1 in segments:
                    path.moveTo(x0, y0)
                    path.lineTo(x1, y1)
            self._outline = path
        return self._outline

    def _tick_ants(self):
        self._phase = (self._phase + 1) % 8
        sel = self.session.selection
        if sel is None or sel.is_empty() or not self.isVisible():
            self._ants.stop()
            return
        bounds = sel.bounds()
        if bounds:
            self.update_rect(bounds)

    def _paint_selection(self, painter):
        path = self._selection_path()
        sel = self.session.selection
        if path is not None:
            z = self.zoom()
            painter.save()
            painter.translate(self.to_widget(0, 0))
            painter.scale(z, z)
            painter.setRenderHint(QPainter.Antialiasing, False)
            black = QPen(QColor(0, 0, 0), 1)
            black.setCosmetic(True)
            painter.setPen(black)
            painter.drawPath(path)
            white = QPen(QColor(look.LOOK["selection_color"]), 1, Qt.CustomDashLine)
            white.setCosmetic(True)
            white.setDashPattern([4, 4])
            white.setDashOffset(self._phase)
            painter.setPen(white)
            painter.drawPath(path)
            painter.restore()
            if not self._ants.isActive():
                self._ants.start()
        elif sel is None and self._ants.isActive():
            self._ants.stop()
        g = self._gesture
        if g is not None:
            painter.save()
            painter.setPen(QPen(QColor(look.LOOK["selection_color"]), 1, Qt.DashLine))
            if g["tool"] in ("rect_select", "ellipse_select", "shape_rect", "shape_ellipse") and len(g["points"]) == 2:
                a, b = self.to_widget(*g["points"][0]), self.to_widget(*g["points"][1])
                box = QRectF(a, b).normalized()
                (painter.drawRect if g["tool"] in ("rect_select", "shape_rect") else painter.drawEllipse)(box)
            elif g["tool"] == "shape_line" and len(g["points"]) == 2:
                painter.drawLine(self.to_widget(*g["points"][0]), self.to_widget(*g["points"][1]))
            elif g["tool"] in ("lasso", "poly_lasso"):
                pts = [self.to_widget(*p) for p in g["points"]]
                if g["tool"] == "poly_lasso" and g.get("cursor"):
                    pts.append(self.to_widget(*g["cursor"]))
                painter.drawPolyline(pts)
            painter.restore()
