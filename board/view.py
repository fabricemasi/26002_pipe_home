"""Vue d'un board : canvas infini, zoom 10-400 % AUTOUR DU CURSEUR, deplacement, et les outils.

Souris : molette = zoom (Maj + molette = deplacement horizontal, pave tactile : geste de pincement) ; bouton du
milieu, Espace tenu ou outil Main = deplacer le canvas ; outil Selection = clic / cadre de selection / deplacer
(aimante) / poignees ; tirer un point de connexion bleu = une fleche ; Ctrl + clic sur un element qui a un lien
= l'ouvrir.
Outils (touche, comme Miro quand elle existe) : Selection (V), Main (H), Post-it (N), Texte (T), Forme (S ; R =
rectangle, O = ellipse), Connecteur (L), Stylo (P), Surligneur, Dessin intelligent, Gomme (E), Gomme de
precision, Lasso, Commentaire (C), Cadre (F). Un element pose = retour a la Selection (sauf les outils de
dessin).
Clavier : Suppr / Retour arriere = supprimer, Ctrl+Z / Ctrl+Y (Ctrl+Maj+Z) = annuler / retablir, Ctrl+C / X / V,
Ctrl+D = dupliquer, Ctrl+A = tout, Ctrl+Maj+L = verrouiller, Ctrl+0 = 100 %, Maj+1 = tout voir, + / - = zoom,
fleches = deplacer (Maj = 1 unite), Echap = annuler / deselectionner / Selection. Glisser des images (ou les
coller) = elles sont copiees dans le dossier du board."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QEvent, QIODevice, QLineF, QMimeData, QPointF, QRectF, Qt, QUrl, Signal
from PySide6.QtGui import (QColor, QDesktopServices, QImage, QImageReader, QKeySequence, QPainter, QPainterPath, QPen,
                           QPolygonF, QTransform)
from PySide6.QtWidgets import (QApplication, QFrame, QGraphicsItem, QGraphicsLineItem, QGraphicsPathItem,
                               QGraphicsView)

from . import model, serialization, smart
from .items import BoardItem, CommentItem, ConnectorItem, InkItem, ink_path, ink_pen, shape_path
from .scene import CLIPBOARD_MIME, BoardScene

CACHE_MAX_ZOOM = 4.0          # au-dela, les images gardees des elements seraient enormes : peints directement
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tif", ".tiff"}
TOOL_KEYS = {Qt.Key_V: "select", Qt.Key_H: "hand", Qt.Key_N: "sticky", Qt.Key_T: "text", Qt.Key_S: "shape",
             Qt.Key_L: "connector", Qt.Key_P: "pen", Qt.Key_E: "eraser", Qt.Key_C: "comment", Qt.Key_F: "frame"}
DRAW_TOOLS = ("pen", "highlighter", "smart", "eraser", "precision_eraser", "lasso")
ERASER_SIZES = {"S": 8, "M": 18, "L": 36}          # gomme de precision : diametre en pixels d'ecran


class BoardView(QGraphicsView):
    zoomChanged = Signal(float)
    toolChanged = Signal(str)
    commentOpened = Signal(object, bool)       # CommentItem, nouveau (pas encore dans l'annulation)

    def __init__(self, scene: BoardScene, parent=None, opengl: bool = False):
        super().__init__(scene, parent)
        if opengl:
            try:
                from PySide6.QtOpenGLWidgets import QOpenGLWidget
                self.setViewport(QOpenGLWidget())
            except Exception:
                pass
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform | QPainter.TextAntialiasing)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setTransformationAnchor(QGraphicsView.NoAnchor)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        self.setOptimizationFlags(QGraphicsView.DontSavePainterState)
        self.setDragMode(QGraphicsView.RubberBandDrag)
        self.setRubberBandSelectionMode(Qt.IntersectsItemShape)
        self.setAcceptDrops(True)
        self.setMouseTracking(True)
        self.viewport().grabGesture(Qt.PinchGesture)
        self.tool = "select"
        self.shape_kind = "rect"
        # Outils de dessin : style du preset choisi (barre de dessin, `ui`) ; taille de la gomme de precision.
        self.ink_styles = {"pen": {"color": model.MIRO_INK, "width": 2.0},
                           "highlighter": {"color": "#fac710", "width": 16.0, "opacity": 0.45},
                           "smart": {"color": model.MIRO_INK, "width": 2.0}}
        self.eraser_size = "M"
        # Format des cadres a creer (barre d'outils > Cadre) : voir model.FRAME_FORMATS.
        self.frame_format = {"format": "free", "orientation": "landscape", "ratio": [16.0, 9.0],
                             "ratio_locked": False}
        self._zoom = 1.0
        self._pan = None
        self._space = False
        self._draft = None
        self._press = None

    @property
    def board(self) -> BoardScene:
        return self.scene()

    # -- zoom / deplacement --
    def zoom(self) -> float:
        return self._zoom

    def limits(self) -> tuple[float, float]:
        """Zoom minimal / maximal de la PAGE (reglages du .mro ; 10 % - 400 % par defaut)."""
        return model.zoom_limits(self.board.page)

    def set_zoom(self, zoom: float, anchor=None):
        low, high = self.limits()
        zoom = max(low, min(high, float(zoom)))
        if anchor is None:
            anchor = QPointF(self.viewport().rect().center())
        anchor = QPointF(anchor)
        # Point fixe calcule en flottants (mapToScene arrondit au pixel : a 0,1 % un pixel = 1 000 unites).
        fixed = self.viewportTransform().inverted()[0].map(anchor)
        was_cached = self._zoom <= CACHE_MAX_ZOOM
        self._zoom = zoom
        self._fit_scroll_area()
        self.setTransform(QTransform.fromScale(zoom, zoom))
        self.board.set_zoom(zoom)
        moved = self.viewportTransform().map(fixed) - anchor
        self._scroll_by(moved.x(), moved.y())
        if was_cached != (zoom <= CACHE_MAX_ZOOM) and not getattr(self, "_zoom_timer", None):
            self._set_item_cache(True)
        self._note_visible()
        self.zoomChanged.emit(zoom)

    def _fit_scroll_area(self):
        """Zone de defilement de la VUE (pas de la scene : son index ne bouge pas) : assez grande pour
        circuler a 0,1 %, assez petite pour que les barres (entiers) ne debordent pas a 2 000 %."""
        size = max(self.viewport().width(), self.viewport().height(), 1000)
        half = min(1e9 / self._zoom, max(5e5, 4 * size / self._zoom))
        rect = QRectF(-half, -half, 2 * half, 2 * half)
        if self.sceneRect() != rect:
            self.setSceneRect(rect)

    def enforce_limits(self):
        """Limites de la page changees : zoom ramene dans la plage, autour du centre de la vue."""
        low, high = self.limits()
        if not (low <= self._zoom <= high):
            self.set_zoom(self._zoom)

    def zoom_by(self, factor: float, anchor=None):
        self._zoom_gesture()
        self.set_zoom(self._zoom * factor, anchor)

    def _zoom_gesture(self):
        """Pendant un zoom continu (molette, pincement) les elements sont peints directement : leur image a
        l'ecran (cache) serait refaite a CHAQUE cran, plus cher qu'une simple peinture (mesure, 500 elements :
        ~80 -> voir AGENTS.md). Le cache revient 250 ms apres le dernier cran (deplacements fluides)."""
        from PySide6.QtCore import QTimer
        timer = getattr(self, "_zoom_timer", None)
        if timer is None:
            timer = self._zoom_timer = QTimer(self)
            timer.setSingleShot(True)
            timer.setInterval(250)
            timer.timeout.connect(lambda: self._set_item_cache(True))
        if not timer.isActive():
            self._set_item_cache(False)
        timer.start()

    def _set_item_cache(self, on: bool):
        on = on and self._zoom <= CACHE_MAX_ZOOM
        mode = QGraphicsItem.DeviceCoordinateCache if on else QGraphicsItem.NoCache
        for item in self.board.board_items():
            if isinstance(item, CommentItem):
                continue
            item.setCacheMode(mode)
            if item.text_item is not None and not item.text_item.editing():
                item.text_item.setCacheMode(mode)

    def _scroll_by(self, dx: float, dy: float):
        """Defilement en pixels ; les barres ne prennent que des entiers : le reste est GARDE pour le pas
        suivant (sinon le zoom autour du curseur derivait d'un demi-pixel par cran)."""
        rx, ry = getattr(self, "_scroll_rest", (0.0, 0.0))
        dx, dy = dx + rx, dy + ry
        ix, iy = round(dx), round(dy)
        self._scroll_rest = (dx - ix, dy - iy)
        h, v = self.horizontalScrollBar(), self.verticalScrollBar()
        h.setValue(h.value() + ix)
        v.setValue(v.value() + iy)
        self._note_visible()

    def center_on(self, point: QPointF):
        self.centerOn(point)
        self._note_visible()

    def view_center(self) -> QPointF:
        return self.mapToScene(self.viewport().rect().center())

    def fit_all(self):
        rect = self.board.content_rect()
        if not rect.isValid() or rect.isNull():
            self.set_zoom(1.0)
            self.center_on(QPointF(0, 0))
            return
        rect = rect.adjusted(-60, -60, 60, 60)
        area = self.viewport().rect()
        zoom = min(area.width() / max(1.0, rect.width()), area.height() / max(1.0, rect.height()))
        self.set_zoom(min(1.0, zoom))                       # borne aux limites de la page par set_zoom
        self.center_on(rect.center())

    def _note_visible(self):
        self.board.visible_rect = self.mapToScene(self.viewport().rect()).boundingRect()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._note_visible()

    def wheelEvent(self, event):
        if event.modifiers() & Qt.ShiftModifier:
            delta = event.angleDelta()
            self._scroll_by(-(delta.y() or delta.x()), 0)
            event.accept()
            return
        pixel = event.pixelDelta()
        if not (event.modifiers() & Qt.ControlModifier) and not pixel.isNull() and event.angleDelta().y() == 0:
            self._scroll_by(-pixel.x(), -pixel.y())          # pave tactile, deux doigts en travers
            event.accept()
            return
        steps = event.angleDelta().y() / 120.0
        if steps:
            self.zoom_by(1.15 ** steps, event.position())
        event.accept()

    def viewportEvent(self, event):
        if event.type() == QEvent.NativeGesture and event.gestureType() == Qt.ZoomNativeGesture:
            self.zoom_by(1.0 + event.value(), event.position())
            return True
        if event.type() == QEvent.Gesture:
            pinch = event.gesture(Qt.PinchGesture)
            if pinch is not None:
                self.zoom_by(pinch.scaleFactor(), self.viewport().mapFromGlobal(pinch.centerPoint().toPoint()))
                return True
        return super().viewportEvent(event)

    # -- outils --
    def set_tool(self, tool: str):
        if tool == self.tool:
            return
        self._cancel_draft()
        self.tool = tool
        self.setDragMode(QGraphicsView.RubberBandDrag if tool == "select" else QGraphicsView.NoDrag)
        self._sync_cursor()
        self.toolChanged.emit(tool)

    def _sync_cursor(self):
        if self._pan is not None:
            self.viewport().setCursor(Qt.ClosedHandCursor)
        elif self._space or self.tool == "hand":
            self.viewport().setCursor(Qt.OpenHandCursor)
        elif self.tool == "select":
            self.viewport().unsetCursor()
        else:
            self.viewport().setCursor(Qt.CrossCursor)

    def _item_at(self, view_pos) -> BoardItem | None:
        for item in self.items(view_pos.toPoint() if hasattr(view_pos, "toPoint") else view_pos):
            while item is not None and not isinstance(item, BoardItem):
                item = item.parentItem()
            if isinstance(item, BoardItem):
                return item
        return None

    def finish_text_edit(self, exclude=None):
        """Un clic ailleurs que sur le texte en cours d'edition le termine (une etape d'annulation) : la scene,
        elle, laissait le focus au texte et l'edition continuait (bug signale)."""
        focus = self.board.focusItem()
        if focus is not None and hasattr(focus, "editing") and focus.editing() and focus.owner is not exclude:
            focus.clearFocus()

    def editing_text(self) -> bool:
        focus = self.board.focusItem()
        return focus is not None and hasattr(focus, "editing") and focus.editing()

    def _preview(self, item, pen):
        item.setPen(pen)
        item.setZValue(1e9)
        self.board.addItem(item)
        return item

    def mousePressEvent(self, event):
        pos = event.position()
        scene_pos = self.mapToScene(pos.toPoint())
        self.board.commit_live()
        if event.button() == Qt.MiddleButton or (event.button() == Qt.LeftButton
                                                 and (self._space or self.tool == "hand")):
            self._pan = pos
            self._sync_cursor()
            event.accept()
            return
        if event.button() == Qt.LeftButton and self.tool == "select":
            self.finish_text_edit(exclude=self._item_at(pos))
            selected = [i for i in self.board.selectedItems() if isinstance(i, BoardItem)]
            if len(selected) == 1 and selected[0].connection_dot_at(scene_pos):
                pen = QPen(QColor(self.board.accent), 2)
                pen.setCosmetic(True)
                preview = self._preview(QGraphicsLineItem(QLineF(scene_pos, scene_pos)), pen)
                self._draft = {"kind": "connector", "src": selected[0], "start": scene_pos, "preview": preview,
                               "back_to": "select"}
                event.accept()
                return
            target = self._item_at(pos)
            if event.modifiers() & Qt.ControlModifier and target is not None and target.data.get("link"):
                self.open_link(target.data["link"])
                event.accept()
                return
            self._press = (pos, target)
            super().mousePressEvent(event)
            return
        if event.button() != Qt.LeftButton:
            super().mousePressEvent(event)
            return
        if self.editing_text():
            self.board.focusItem().clearFocus()
        tool = self.tool
        if tool in ("sticky", "text"):
            data = model.new_item(tool)
            data["x"] = scene_pos.x() - (data["w"] / 2 if tool == "sticky" else 0)
            data["y"] = scene_pos.y() - (data["h"] / 2)
            item = self.board.add_new(data, "Ajouter un post-it" if tool == "sticky" else "Ajouter un texte")
            self.set_tool("select")
            item.start_edit()
        elif tool in ("shape", "frame"):
            pen = QPen(QColor(self.board.accent), 1.5)
            pen.setCosmetic(True)
            preview = self._preview(QGraphicsPathItem(), pen)
            self._draft = {"kind": tool, "start": scene_pos, "preview": preview}
            self._update_shape_draft(scene_pos)
        elif tool in ("pen", "highlighter", "smart"):
            style = self._ink_data(tool)
            preview = self._preview(QGraphicsPathItem(), ink_pen(style))
            self._draft = {"kind": "ink", "tool": tool, "points": [scene_pos], "preview": preview}
        elif tool == "eraser":
            self._draft = {"kind": "eraser", "hit": [], "last": pos}
            self._erase_at(pos)
        elif tool == "precision_eraser":
            self._draft = {"kind": "precision", "before": {}, "created": set(), "last": pos}
            self._precision_at(scene_pos)
        elif tool == "lasso":
            pen = QPen(QColor(self.board.accent), 1.2, Qt.DashLine)
            pen.setCosmetic(True)
            preview = self._preview(QGraphicsPathItem(), pen)
            self._draft = {"kind": "lasso", "points": [scene_pos], "preview": preview}
        elif tool == "connector":
            pen = QPen(QColor(self.board.accent), 2)
            pen.setCosmetic(True)
            preview = self._preview(QGraphicsLineItem(QLineF(scene_pos, scene_pos)), pen)
            source = self._item_at(pos)
            if isinstance(source, (ConnectorItem, CommentItem)):
                source = None
            self._draft = {"kind": "connector", "src": source, "start": scene_pos, "preview": preview}
        elif tool == "comment":
            target = self._item_at(pos)
            if isinstance(target, (ConnectorItem, CommentItem)):
                target = None
            data = model.new_item("comment", x=scene_pos.x(), y=scene_pos.y())
            if target is not None:
                r = target.scene_rect()
                data.update(target=target.item_id, dx=scene_pos.x() - r.left(), dy=scene_pos.y() - r.top())
            comment = self.board._add(data)                 # entre dans l'annulation a son 1er message
            self.set_tool("select")
            self.commentOpened.emit(comment, True)
        event.accept()

    def _ink_data(self, tool: str) -> dict:
        style = dict(self.ink_styles.get(tool) or self.ink_styles["pen"])
        data = {"tool": "highlighter" if tool == "highlighter" else "pen", "color": style.get("color", model.MIRO_INK),
                "width": float(style.get("width", 2.0)), "opacity": float(style.get("opacity", 1.0))}
        return data

    def mouseMoveEvent(self, event):
        pos = event.position()
        if self._pan is not None:
            delta = pos - self._pan
            self._pan = pos
            self._scroll_by(-delta.x(), -delta.y())
            event.accept()
            return
        draft = self._draft
        if draft is None:
            super().mouseMoveEvent(event)
            return
        scene_pos = self.mapToScene(pos.toPoint())
        kind = draft["kind"]
        if kind in ("shape", "frame"):
            self._update_shape_draft(scene_pos)
        elif kind in ("ink", "lasso"):
            points = draft["points"]
            if QLineF(points[-1], scene_pos).length() * self._zoom >= 2:
                points.append(scene_pos)
                if kind == "ink":
                    draft["preview"].setPath(ink_path([(p.x(), p.y()) for p in points]))
                else:
                    path = QPainterPath()
                    path.addPolygon(QPolygonF(points))
                    draft["preview"].setPath(path)
        elif kind in ("eraser", "precision"):
            # Toute la trajectoire depuis l'evenement precedent (un geste rapide ne saute aucun trait).
            last = draft.get("last", pos)
            steps = max(1, int(QLineF(last, pos).length() / 4))
            for n in range(1, steps + 1):
                point = last + (pos - last) * (n / steps)
                if kind == "eraser":
                    self._erase_at(point)
                else:
                    self._precision_at(self.mapToScene(point.toPoint()))
            draft["last"] = pos
        elif kind == "connector":
            draft["preview"].setLine(QLineF(draft["start"], scene_pos))
        event.accept()

    def mouseReleaseEvent(self, event):
        if self._pan is not None and event.button() in (Qt.MiddleButton, Qt.LeftButton):
            self._pan = None
            self._sync_cursor()
            event.accept()
            return
        draft, self._draft = self._draft, None
        if draft is None:
            press, self._press = self._press, None
            super().mouseReleaseEvent(event)
            if (press is not None and isinstance(press[1], CommentItem)
                    and QLineF(press[0], event.position()).length() < 4):
                self.commentOpened.emit(press[1], False)
            return
        scene_pos = self.mapToScene(event.position().toPoint())
        kind = draft["kind"]
        preview = draft.get("preview")
        if preview is not None:
            self.board.removeItem(preview)
        if kind in ("shape", "frame"):
            self._finish_shape(draft, scene_pos)
        elif kind == "ink":
            self._finish_ink(draft)
        elif kind == "eraser":
            hit = [i for i in draft["hit"] if i.scene() is self.board]
            for item in hit:
                item.setOpacity(1.0)
            self.board.delete_items(hit)
        elif kind == "precision":
            self._finish_precision(draft)
        elif kind == "lasso":
            self._finish_lasso(draft)
        elif kind == "connector":
            self._finish_connector(draft, event.position(), scene_pos)
        event.accept()

    def _frame_rect(self, start: QPointF, end: QPointF) -> QRectF:
        """Cadre tire : proportions du format choisi (hauteur tiree de la largeur)."""
        rect = QRectF(start, end).normalized()
        ratio = model.frame_ratio(self.frame_format)
        if ratio is None or rect.width() <= 0:
            return rect
        h = rect.width() / ratio
        top = start.y() if end.y() >= start.y() else start.y() - h
        return QRectF(rect.left(), top, rect.width(), h)

    def _finish_shape(self, draft, scene_pos):
        kind = draft["kind"]
        rect = (self._frame_rect(draft["start"], scene_pos) if kind == "frame"
                else QRectF(draft["start"], scene_pos).normalized())
        data = model.new_item("frame" if kind == "frame" else "shape")
        if kind == "frame":
            data.update(self.frame_format, ratio=list(self.frame_format.get("ratio", [16.0, 9.0])))
        if rect.width() * self._zoom < 8 and rect.height() * self._zoom < 8:   # simple clic : taille d'origine
            w, h = data["w"], data["h"]
            if kind == "frame":
                real = model.paper_size(data)
                ratio = model.frame_ratio(data)
                if real is not None:
                    w, h = real                                   # format papier : taille « reelle » (96 ppp)
                elif ratio is not None:
                    h = w / ratio
            rect = QRectF(0, 0, w, h)
            rect.moveCenter(draft["start"])
        data.update(x=rect.x(), y=rect.y(), w=max(24.0, rect.width()), h=max(24.0, rect.height()))
        if kind == "frame":
            frames = [i for i in self.board.board_items() if i.kind == "frame"]
            data["title"] = f"Cadre {len(frames) + 1}"
        else:
            data["shape"] = self.shape_kind
            if self.shape_kind == "round":
                data["radius"] = round(min(data["w"], data["h"]) * 0.18, 2)
        self.board.add_new(data, "Ajouter un cadre" if kind == "frame" else "Ajouter une forme")
        self.set_tool("select")

    def _finish_ink(self, draft):
        points = draft["points"]
        style = self._ink_data(draft["tool"])
        if draft["tool"] == "smart":
            found = smart.recognize(points)
            if found is not None:
                self._add_recognized(found, style)
                return
        base = smart.bounds(points).topLeft()
        data = model.new_item("ink", **style,
                              points=[[round(p.x() - base.x(), 2), round(p.y() - base.y(), 2)] for p in points],
                              x=base.x(), y=base.y())
        if style["tool"] == "highlighter":
            data["z"] = 0
        self.board.add_new(data, "Surligner" if style["tool"] == "highlighter" else "Dessiner", select=False)

    def _add_recognized(self, found, style):
        if found[0] == "line":
            _kind, a, b = found
            data = model.new_item("connector", src={"x": a.x(), "y": a.y()}, dst={"x": b.x(), "y": b.y()},
                                  arrow_end=False, end_cap="none", color=style["color"], width=style["width"])
            self.board.add_new(data, "Dessin intelligent : ligne", select=False)
            return
        kind, rect = found
        data = model.new_item("shape", shape=kind, x=rect.x(), y=rect.y(), w=max(24.0, rect.width()),
                              h=max(24.0, rect.height()), stroke=style["color"], stroke_width=style["width"])
        self.board.add_new(data, "Dessin intelligent : forme", select=False)

    def _finish_lasso(self, draft):
        points = draft["points"]
        if len(points) < 3:
            return
        path = QPainterPath()
        path.addPolygon(QPolygonF(points))
        path.closeSubpath()
        self.board.clearSelection()
        for item in self.board.board_items():
            if item.isVisible() and path.contains(item.scene_rect().center()):
                item.setSelected(True)

    def _finish_connector(self, draft, view_pos, scene_pos):
        target = self._item_at(view_pos)
        if isinstance(target, (ConnectorItem, CommentItem)):
            target = None
        source = draft["src"]
        if QLineF(draft["start"], scene_pos).length() * self._zoom >= 6 and not (
                source is not None and target is source):
            data = model.new_item(
                "connector",
                src={"item": source.item_id} if source else {"x": draft["start"].x(), "y": draft["start"].y()},
                dst={"item": target.item_id} if target else {"x": scene_pos.x(), "y": scene_pos.y()})
            self.board.add_new(data, "Ajouter un connecteur")
            self.set_tool("select")

    def _update_shape_draft(self, scene_pos):
        draft = self._draft
        rect = QRectF(draft["start"], scene_pos).normalized()
        path = QPainterPath()
        if draft["kind"] == "frame":
            path.addRect(self._frame_rect(draft["start"], scene_pos))
        else:
            path = shape_path(self.shape_kind, rect, min(rect.width(), rect.height()) * 0.18
                              if self.shape_kind == "round" else 0.0)
        draft["preview"].setPath(path)

    def _erase_at(self, view_pos):
        """Gomme : un trait (stylo, surligneur) touche disparait en entier (au relachement, une etape)."""
        radius = 6
        rect = QRectF(view_pos.x() - radius, view_pos.y() - radius, 2 * radius, 2 * radius).toRect()
        for item in self.items(rect):
            if isinstance(item, InkItem) and not item.locked() and item not in self._draft["hit"]:
                self._draft["hit"].append(item)
                item.setOpacity(0.25)

    def _precision_at(self, scene_pos):
        """Gomme de precision : coupe les traits sous le cercle (diametre `ERASER_SIZES`, pixels d'ecran)."""
        draft = self._draft
        radius = ERASER_SIZES.get(self.eraser_size, 18) / 2 / self._zoom
        area = QRectF(scene_pos.x() - radius, scene_pos.y() - radius, 2 * radius, 2 * radius)
        for item in self.board.items(area):
            if not isinstance(item, InkItem) or item.locked():
                continue
            origin = item.pos()
            points = [QPointF(origin.x() + float(x), origin.y() + float(y)) for x, y in item.data.get("points", [])]
            pieces = smart.cut(points, scene_pos, radius, max(1.0, float(item.data.get("width", 2.0)) / 2))
            if pieces is None:
                continue
            if item.item_id not in draft["created"]:
                draft["before"][item.item_id] = item.to_dict()
            draft["created"].discard(item.item_id)
            base = item.to_dict()
            self.board._remove(item.item_id)
            for piece in pieces:
                rect = smart.bounds(piece)
                data = dict(base, id=model.new_id(), x=rect.x(), y=rect.y(),
                            points=[[round(p.x() - rect.x(), 2), round(p.y() - rect.y(), 2)] for p in piece])
                self.board._add(data)
                draft["created"].add(data["id"])

    def _finish_precision(self, draft):
        if not draft["before"]:
            return
        before = dict(draft["before"])
        before.update({i: None for i in draft["created"]})
        after = {i: None for i in draft["before"]}
        after.update(self.board.snapshot([i for i in draft["created"] if self.board.item(i) is not None]))
        self.board.push(before, after, "Gomme de précision")

    def _cancel_draft(self):
        draft, self._draft = self._draft, None
        if draft is None:
            return
        if draft.get("preview") is not None:
            self.board.removeItem(draft["preview"])
        for item in draft.get("hit", []):
            item.setOpacity(1.0)
        if draft.get("kind") == "precision":
            self._finish_precision(draft)

    @staticmethod
    def open_link(link: str):
        url = QUrl.fromUserInput(link, "", QUrl.AssumeLocalFile)
        QDesktopServices.openUrl(url)

    # -- clavier --
    def _refresh_gesture(self, event):
        """Maj enfoncee / relachee pendant un redimensionnement : le geste est rejoue aussitot."""
        grabber = self.board.mouseGrabberItem()
        if event.key() == Qt.Key_Shift and isinstance(grabber, BoardItem):
            grabber.refresh_gesture(event.modifiers())

    def keyPressEvent(self, event):
        self._refresh_gesture(event)
        if self.editing_text():
            super().keyPressEvent(event)
            return
        key, mods = event.key(), event.modifiers()
        board = self.board
        selected = [i for i in board.selectedItems() if isinstance(i, BoardItem)]
        if key == Qt.Key_Space and not event.isAutoRepeat():
            self._space = True
            self._sync_cursor()
        elif key in (Qt.Key_Delete, Qt.Key_Backspace):
            board.delete_items(selected)
        elif event.matches(QKeySequence.Undo):
            board.undo.undo()
        elif event.matches(QKeySequence.Redo) or (mods & Qt.ControlModifier and key == Qt.Key_Y):
            board.undo.redo()
        elif event.matches(QKeySequence.Copy):
            self.copy_selection()
        elif event.matches(QKeySequence.Cut):
            self.copy_selection()
            board.delete_items(selected)
        elif event.matches(QKeySequence.Paste):
            self.paste()
        elif event.matches(QKeySequence.SelectAll):
            for item in board.board_items():
                if item.isVisible():
                    item.setSelected(True)
        elif mods & Qt.ControlModifier and mods & Qt.ShiftModifier and key == Qt.Key_L:
            self.toggle_lock(selected)
        elif mods & Qt.ControlModifier and key == Qt.Key_D:
            self.duplicate(selected)
        elif mods & Qt.ControlModifier and key == Qt.Key_0:
            self.set_zoom(1.0)
        elif key == Qt.Key_Exclam or (mods & Qt.ShiftModifier and key == Qt.Key_1):
            self.fit_all()
        elif key in (Qt.Key_Plus, Qt.Key_Equal):
            self.zoom_by(1.25)
        elif key in (Qt.Key_Minus, Qt.Key_Underscore):
            self.zoom_by(1 / 1.25)
        elif key in (Qt.Key_Return, Qt.Key_Enter) and len(selected) == 1 and selected[0].text_item is not None:
            selected[0].start_edit()
        elif key == Qt.Key_Escape:
            if self._draft is not None:
                self._cancel_draft()
            elif selected:
                board.clearSelection()
            elif self.tool != "select":
                self.set_tool("select")
            else:
                event.ignore()                              # le panneau ferme le board
                return
        elif not mods and key in (Qt.Key_R, Qt.Key_O):
            self.shape_kind = "rect" if key == Qt.Key_R else "ellipse"
            self.set_tool("select")
            self.set_tool("shape")
        elif not mods and key in TOOL_KEYS:
            self.set_tool(TOOL_KEYS[key])
        elif (not mods & (Qt.ControlModifier | Qt.AltModifier) and selected
              and key in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down)):
            step = 1 if mods & Qt.ShiftModifier else 10
            dx = {Qt.Key_Left: -step, Qt.Key_Right: step}.get(key, 0)
            dy = {Qt.Key_Up: -step, Qt.Key_Down: step}.get(key, 0)
            movable = [i for i in selected if i.flags() & QGraphicsItem.ItemIsMovable]
            before = board.snapshot([i.item_id for i in movable])
            for item in movable:
                item.moveBy(dx, dy)
            board.push(before, board.snapshot(list(before)), "Deplacer")
        else:
            super().keyPressEvent(event)
            return
        event.accept()

    def keyReleaseEvent(self, event):
        self._refresh_gesture(event)
        if event.key() == Qt.Key_Space and not event.isAutoRepeat() and self._space:
            self._space = False
            self._sync_cursor()
        super().keyReleaseEvent(event)

    # -- commandes de la selection --
    def duplicate(self, items):
        items = [i for i in items if isinstance(i, BoardItem)]
        if items:
            self.board.paste(self.board.serialize(items), QPointF(30, 30), "Dupliquer")

    def toggle_lock(self, items):
        items = [i for i in items if isinstance(i, BoardItem)]
        if not items:
            return
        lock = not all(i.locked() for i in items)
        self.board.change_items(items, lambda i: i.data.update(locked=lock),
                                "Verrouiller" if lock else "Déverrouiller", include_locked=True)

    # -- presse-papiers / depot --
    def copy_selection(self):
        """Copie : format interne (entre boards, objets complets) + texte brut et tableau HTML (une cellule
        par objet a texte) pour les autres logiciels — Miro en fait des post-it modifiables (voir clipboard)."""
        from . import clipboard
        items = [i for i in self.board.selectedItems() if isinstance(i, BoardItem)]
        if not items:
            return
        mime = QMimeData()
        mime.setData(CLIPBOARD_MIME, QByteArray(self.board.clipboard_payload(self.board.serialize(items))))
        texts = clipboard.items_text(items)
        if texts:
            mime.setText("\n".join(t.replace("\n", " ") for t in texts))
            mime.setHtml(clipboard.table_html(texts))
        QApplication.clipboard().setMimeData(mime)

    def copy_selection_image(self):
        """Copier en image (PNG) : un RENDU APLATI de la selection (non modifiable ailleurs)."""
        from . import export
        items = [i for i in self.board.selectedItems() if isinstance(i, BoardItem)]
        if items:
            QApplication.clipboard().setImage(export.render_items(self.board, items))

    def _paste_point(self) -> QPointF:
        local = self.viewport().mapFromGlobal(self.cursor().pos())
        if self.viewport().rect().contains(local):
            return self.mapToScene(local)
        return self.view_center()

    def paste(self):
        mime = QApplication.clipboard().mimeData()
        at = self._paste_point()
        if mime.hasFormat(CLIPBOARD_MIME):
            dicts, source = self.board.read_payload(mime.data(CLIPBOARD_MIME).data())
            if dicts:
                origin = QRectF()
                for d in dicts:
                    if d.get("type") != "connector":
                        origin = origin.united(QRectF(d.get("x", 0.0), d.get("y", 0.0),
                                                      d.get("w", 1.0) or 1.0, d.get("h", 1.0) or 1.0))
                self.board.paste(dicts, at - origin.center() if origin.isValid() else QPointF(30, 30),
                                 source_board=Path(source) if source else None)
            return
        if mime.hasHtml() and self._paste_html(mime.html(), at):
            return
        if mime.hasUrls() and self.add_image_files([Path(u.toLocalFile()) for u in mime.urls()], at):
            return
        if mime.hasImage():
            image = QImage(mime.imageData())
            if not image.isNull():
                buffer = QBuffer()
                buffer.open(QIODevice.WriteOnly)
                image.save(buffer, "PNG")
                self._add_image(serialization.import_image_bytes(self.board.board_path, bytes(buffer.data())),
                                image.width(), image.height(), at)
                return
        if mime.hasText() and mime.text().strip():
            data = model.new_item("text", text=mime.text().strip(), x=at.x(), y=at.y())
            self.board.add_new(data, "Coller du texte")

    def _paste_html(self, markup: str, at: QPointF) -> bool:
        """Tableau (Excel, Miro...) ou objets copies dans Miro : un post-it par cellule / objet (le texte seul :
        le format interne de Miro n'est pas documente). Autre HTML : False (texte brut ou image ensuite)."""
        from . import clipboard
        kind, texts = clipboard.html_texts(markup)
        if kind not in ("table", "miro") or not texts:
            return False
        columns = max(1, min(6, round(len(texts) ** 0.5)))
        dicts = []
        for n, text in enumerate(texts[:500]):
            data = model.new_item("sticky", text=text)
            data["x"] = (n % columns) * (data["w"] + 20)
            data["y"] = (n // columns) * (data["h"] + 20)
            dicts.append(data)
        rows = (len(dicts) + columns - 1) // columns
        width, height = columns * 220 - 20, rows * 220 - 20
        self.board.paste(dicts, at - QPointF(width / 2, height / 2),
                         "Coller depuis Miro" if kind == "miro" else "Coller un tableau")
        return True

    def add_image_files(self, paths, at: QPointF) -> bool:
        added = False
        for i, path in enumerate(p for p in paths if p.suffix.lower() in IMAGE_SUFFIXES and p.is_file()):
            size = QImageReader(str(path)).size()
            if not size.isValid():
                continue
            name = serialization.import_asset(self.board.board_path, path)
            self._add_image(name, size.width(), size.height(), at + QPointF(40 * i, 40 * i))
            added = True
        return added

    def _add_image(self, name: str, width: int, height: int, at: QPointF):
        side = 600.0
        scale = min(1.0, side / max(1, width, height))
        w, h = max(24.0, width * scale), max(24.0, height * scale)
        data = model.new_item("image", asset=name, w=w, h=h, x=at.x() - w / 2, y=at.y() - h / 2)
        self.board.add_new(data, "Ajouter une image")

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() or event.mimeData().hasImage():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls() or event.mimeData().hasImage():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        mime = event.mimeData()
        at = self.mapToScene(event.position().toPoint())
        if mime.hasUrls() and self.add_image_files([Path(u.toLocalFile()) for u in mime.urls()], at):
            event.acceptProposedAction()
            return
        super().dropEvent(event)
