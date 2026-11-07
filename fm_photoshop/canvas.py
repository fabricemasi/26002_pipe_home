"""Établi d'édition (Qt) : le document en plein cadre, zoom / déplacement de la vue, outils à la souris et au stylet.

L'état de travail (outil, brosse, couleurs, zoom, centre) est dans la SESSION : le Board et le mode Standard le
partagent. Fluidité : aucune recomposition complète à un point de brosse — le trait écrit dans les pixels du calque
(tuiles de 64), la zone touchée invalide ce qu'il faut dans le cache de tuiles, et la peinture ne recompose que cette
partie (`render.TileCache`). Tuiles jamais calculées : en tranches de temps (le reste au tour suivant)."""
from __future__ import annotations

import math
import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QApplication, QWidget

from . import compose as C
from . import look, ops, render
from . import selection as SEL
from .actions import Actions
from .brush import Stroke
from .planes import rect_intersect, rect_union
from .stroke_feed import StrokeFeed

TOOLS = ("brush", "eraser", "eyedropper", "move", "hand", "rect_select", "ellipse_select", "lasso", "poly_lasso",
         "wand", "text", "shape_rect", "shape_ellipse", "shape_line", "clone", "heal", "blur", "sharpen", "smudge",
         "dodge", "burn")
RETOUCH_TOOLS = ("clone", "heal", "blur", "sharpen", "smudge", "dodge", "burn")      # outil = mode de la brosse
SHAPE_TOOLS = {"shape_rect": "rect", "shape_ellipse": "ellipse", "shape_line": "line"}
SELECT_TOOLS = ("rect_select", "ellipse_select", "lasso", "poly_lasso", "wand")
FEED_FIRST_MS = 4.0          # moteur de trait dans le gestionnaire de souris lui-même (charge légère : tout passe ici)
FEED_TICK_MS = 9.0           # moteur de trait à chaque tour de boucle suivant : le cercle est repeint entre deux tranches (voir stroke_feed.py)
FEED_CATCH_MS = 13.0         # tranche plus longue quand le trait a pris du retard sur le curseur (> FEED_LAG_SOFT_MS)
FEED_LAG_SOFT_MS = 150.0
FEED_LAG_HARD_MS = 350.0     # retard maximal du trait sur le curseur : au-delà, le moteur rattrape sans rendre la main


class CanvasView(QWidget):
    zoomChanged = Signal(float)         # zoom affiché (1.0 = 100 %), émis à la peinture quand il change
    message = Signal(str)               # texte d'état (calque verrouillé, outil refusé…)
    toolChanged = Signal(str)
    colorsChanged = Signal()

    def __init__(self, session, parent=None):
        super().__init__(parent)
        self.session = session
        self.cache = render.cache_for(session)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WA_TabletTracking, True)
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
        self._zoom_shown = -1
        self._pen_active = False                  # des évènements tablette ont accompagné le geste en cours
        self.pen_log = None                       # `pen_log.PenLog` quand le journal du stylet est activé (panneau Brosse)
        self._last_row = None
        self.debug_trace = False                  # diagnostic : points bruts / filtrés / centres des empreintes du dernier trait
        self._last_trace = None
        self._bicubic_key = None                  # affichage bicubique mis en cache (voir `_draw_bicubic`)
        self._bicubic_image = None
        self._tablet_t = None                     # horodatage (ms) du dernier évènement tablette : il tient alors le curseur
        self._checker = None
        self._checker_key = None
        self._pump = QTimer(self)
        self._pump.setSingleShot(True)
        self._pump.timeout.connect(self.update)
        self._catch_up = QTimer(self)               # rattrapage du lissage pendant une pause (Stroke Catch-up)
        self._catch_up.setInterval(16)
        self._catch_up.timeout.connect(self._catch_up_tick)
        self._air_timer = QTimer(self)              # aérographe : dépose le TEMPS écoulé, même stylet immobile (voir Stroke.air_tick)
        self._air_timer.setInterval(16)
        self._air_timer.setTimerType(Qt.PreciseTimer)
        self._air_timer.timeout.connect(self._air_tick)
        self._feed = StrokeFeed()                   # points du curseur pas encore donnés au moteur (tranches de temps, voir stroke_feed.py)
        self._feed_timer = QTimer(self)
        self._feed_timer.setSingleShot(True)
        self._feed_timer.setTimerType(Qt.PreciseTimer)
        self._feed_timer.timeout.connect(self._feed_tick)
        self.actions = Actions(session)
        self._xf = None                     # transformation libre en cours (freetransform.FreeTransform)
        self._xf_dragging = False
        self._xf_timer = QTimer(self)       # aperçu regroupé : un seul rendu par tour, quel que soit le nombre d'évènements
        self._xf_timer.setSingleShot(True)
        self._xf_timer.timeout.connect(self._xf_render)
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
        elif kind in ("structure", "reload", "view", "props"):
            self.update()
        elif kind == "selection":
            self._outline = None
            self.update()
        if self._xf is not None and kind in ("structure", "view") and self.session.layer() is not self._xf.job.layer:
            self.commit_free_transform()                     # un autre calque est choisi : la transformation est validée

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
        if round(z * 100) != self._zoom_shown:
            self._zoom_shown = round(z * 100)
            self.zoomChanged.emit(z)
        doc = self.session.doc
        origin = self.to_widget(0, 0)
        area = QRectF(origin, self.to_widget(doc.width, doc.height))
        shown = area.intersected(QRectF(event.rect()))
        if not shown.isEmpty():
            painter.setBrush(Qt.NoBrush)
            painter.fillRect(shown, self._checker_brush())
            bicubic = self._draw_bicubic(painter, shown)           # affichage bicubique (diagnostic) : remplace les tuiles
            painter.save()
            painter.translate(origin)
            painter.scale(z, z)
            smooth = z < 1.0 or self.session.display_filter in ("bilinear", "bicubic")      # (jamais en cours de zoom continu)
            painter.setRenderHint(QPainter.SmoothPixmapTransform, smooth and not self._zooming)
            rect = rect_intersect(self._rect_of(event.rect(), 2), doc.rect())
            keys = self.cache.keys_for(rect) if rect and not bicubic else []
            for key in keys:                                  # zones modifiées (peu de pixels) : toujours à jour
                if key in self.cache.tiles and key not in self.cache.pending_props:
                    self.cache.tile(key)
            # jamais calculées, ou réglage de calque en direct : en tranches de temps (la version précédente de la
            # tuile reste affichée un instant : approximation TEMPORAIRE remplacée par le résultat exact)
            late = [k for k in keys if k not in self.cache.tiles or k in self.cache.pending_props]
            if late:
                self.cache.pump(late, 12.0)
                if not all(self.cache.is_ready(k) for k in late):
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
        self._paint_free_transform(painter)
        self._paint_clone_source(painter)
        self._paint_trace(painter)
        self._paint_cursor(painter)
        painter.end()

    def _draw_bicubic(self, painter, shown) -> bool:
        """Mode d'affichage « bicubique » à fort zoom (présentation seulement, mise en cache tant que ni le document ni la
        vue ne changent). Repli sur le bilinéaire pendant un trait, un déplacement, un zoom continu ou une zone énorme."""
        z = self.zoom()
        if self.session.display_filter != "bicubic" or z <= 1.0 or self._stroke is not None or self._move is not None                 or self._zooming:
            return False
        x0, y0 = int(math.floor(shown.left())), int(math.floor(shown.top()))
        x1, y1 = int(math.ceil(shown.right())), int(math.ceil(shown.bottom()))
        if x1 <= x0 or y1 <= y0 or (x1 - x0) * (y1 - y0) > 1_500_000:
            return False
        key = (self.cache.version, x0, y0, x1, y1, round(z, 6), tuple(round(v, 4) for v in self.center()))
        if key != self._bicubic_key:
            from . import display
            first = self.to_doc(QPointF(x0 + 0.5, y0 + 0.5))
            pixels = display.bicubic_view(self.session.doc, first, 1.0 / z, (x1 - x0, y1 - y0))
            image = QImage(pixels.data, x1 - x0, y1 - y0, (x1 - x0) * 4, QImage.Format.Format_RGBA8888_Premultiplied).copy()
            self._bicubic_key, self._bicubic_image = key, image
        painter.drawImage(x0, y0, self._bicubic_image)
        return True

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

    def _paint_trace(self, painter):
        """Diagnostic : points BRUTS (rouge), trajectoire FILTRÉE (vert), centres des EMPREINTES (bleu) du dernier trait."""
        trace = self._last_trace
        if not self.debug_trace or not trace:
            return
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setBrush(Qt.NoBrush)
        for key, color, radius in (("dabs", QColor(40, 120, 255, 200), 1.5), ("used", QColor(0, 200, 90, 230), 2.5),
                                   ("raw", QColor(255, 40, 40, 230), 2.5)):
            painter.setPen(QPen(color, 1))
            for point in trace[key][-4000:]:
                p = self.to_widget(point[0], point[1])
                painter.drawEllipse(p, radius, radius)
        painter.restore()

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
        if self._xf is not None:
            self._xf_press(x, y)
            return
        if tool in ("clone", "heal") and mods & Qt.AltModifier:
            self.set_clone_source(x, y)                          # source choisie EXPLICITEMENT (Alt + clic)
        elif tool == "eyedropper" or (tool in ("brush", "eraser") and mods & Qt.AltModifier):
            self.pick_color(x, y, background=bool(mods & Qt.ShiftModifier) if tool == "eyedropper" else False)
        elif tool in ("brush", "eraser") or tool in RETOUCH_TOOLS:
            pressure = self._pressure_of(event)
            self._log_input("press", self._mouse_source(event), event, pressure)
            self.begin_stroke(x, y, pressure)
            self._log_engine((x, y))
            if self._pen_active or event.source() != Qt.MouseEventNotSynthesized:   # diagnostic du stylet
                self.message.emit(f"Stylet : pression {pressure:.2f} au premier contact"
                                  + ("" if self._pen_active else " (aucun évènement tablette reçu : Windows Ink ?)"))
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
        if not self._tablet_owns_hover(event):
            self._set_hover(pos)
        self._log_hover(event, self._mouse_source(event), self._pressure_of(event) if self._stroke is not None else 1.0)
        if self.session.tool in ("clone", "heal") and self.session.clone["source"] is not None:
            self.update()                                          # la croix de la source suit le pointeur
        if self._pan is not None:
            start, (cx, cy) = self._pan
            z = self.zoom()
            self.session.center = (cx - (pos.x() - start.x()) / z, cy - (pos.y() - start.y()) / z)
            self.update()
            return
        if self._xf_dragging:
            x, y = self.to_doc(pos)
            self._xf.drag(x, y, bool(event.modifiers() & Qt.ShiftModifier))
            self._xf_timer.start(0)
            self.update()
            return
        if self._stroke is not None:
            x, y = self.to_doc(pos)
            pressure = self._pressure_of(event)
            self._log_input("move", self._mouse_source(event), event, pressure)
            if self._feed_direct():
                self.extend_stroke(x, y, pressure, event.timestamp() / 1000.0)
                self._log_engine((x, y))
            else:
                self._feed.push(x, y, pressure, event.timestamp() / 1000.0)      # le cercle d'abord, le moteur par tranches
                if not self._feed_timer.isActive() or self._feed.lag_ms() > FEED_LAG_HARD_MS:
                    self._feed_run(FEED_FIRST_MS)       # (ou le retard maximal est atteint : rattrapage tout de suite)
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
        if self._xf_dragging:
            self._xf_dragging = False
            self._xf.end()
            self._xf_render()
            return
        if self._stroke is not None:
            x, y = self.to_doc(event.position())
            pressure = self._pressure_of(event)
            self._log_input("release", self._mouse_source(event), event, pressure)
            self.end_stroke(x, y, pressure)
            self._pressure = 1.0
            self._pen_active = False                                 # (réinitialisée APRÈS le trait : pas de bout gonflé)
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

    def _pressure_of(self, event) -> float:
        """Pression du geste : celle des évènements tablette, sinon (stylet livré seulement en souris synthétisée par
        Qt / le système) celle que porte le point de l'évènement ; la vraie souris donne 1."""
        if self._pen_active:
            return self._pressure                    # (aucun plancher : le diamètre minimum se règle dans la brosse)
        if event.source() == Qt.MouseEventNotSynthesized:
            return 1.0                               # vraie souris : pression constante explicite
        points = event.points()
        value = points[0].pressure() if points else 1.0
        if 0.0 < value < 1.0 and not self.session.pen_seen:
            self.session.pen_seen = True
            self.session.brush.pressure_size = True
            self.colorsChanged.emit()
        return max(0.0, min(1.0, value)) if value > 0.0 else self._pressure

    def _log_input(self, kind, source, event, pressure=None, **extra):
        """Journal du stylet (désactivé par défaut) : l'évènement REÇU, brut, avec son horodatage et sa position flottante."""
        log = self.pen_log
        if log is None:
            return None
        pos = event.position()
        self._last_row = log.add(kind, source, event.timestamp() / 1000.0, pos.x(), pos.y(), p_raw=pressure, **extra)
        return self._last_row

    @staticmethod
    def _mouse_source(event) -> str:
        return "mouse" if event.source() == Qt.MouseEventNotSynthesized else "mouse_synth"

    def _log_engine(self, doc_xy):
        """Complète la dernière ligne du journal avec ce que le moteur en a fait (valeurs filtrées et résultantes)."""
        row, stroke = self._last_row, self._stroke
        if self.pen_log is None or row is None:
            return
        row["doc"] = [doc_xy[0], doc_xy[1]]
        info = stroke.info if stroke is not None else None
        if info:
            row.update(p_filtered=round(info["p_filtered"], 5), size=round(info["size"], 4),
                       opacity=round(info["opacity"], 5), flow=round(info["flow"], 5),
                       used=[round(v, 4) for v in info["used"]], proc_ms=round(info["seconds"] * 1000.0, 4))

    # -- curseur de brosse : chemin PROPRE, indépendant du moteur de trait (aucun filtre, aucun arrondi) --
    def _set_hover(self, pos):
        """Position FLOTTANTE du curseur (coordonnées du widget). Ni lissage, ni pression, ni alignement sur la grille."""
        if self._hover is not None:
            self.update(self._cursor_rect())
        self._hover = QPointF(pos)
        self.update(self._cursor_rect())

    def _tablet_owns_hover(self, event) -> bool:
        """Une souris SYNTHÉTISÉE juste après un évènement tablette porte la même position : la tablette tient déjà le
        curseur (une seule source de coordonnées ; deux sources qui alternent le feraient trembler)."""
        return (event.source() != Qt.MouseEventNotSynthesized and self._tablet_t is not None
                and 0 <= event.timestamp() - self._tablet_t <= 100)

    def _log_hover(self, event, source, pressure):
        """Journal du survol : position locale / globale / document / curseur affiché, périphérique, boutons, zoom, DPR."""
        log = self.pen_log
        if log is None:
            return
        pos, glob = event.position(), event.globalPosition()
        device = event.pointingDevice()
        doc = self.to_doc(pos)
        hover = self._hover
        log.add("hover", source, event.timestamp() / 1000.0, pos.x(), pos.y(), p_raw=pressure, gx=glob.x(), gy=glob.y(),
                doc=[doc[0], doc[1]], cursor=None if hover is None else [hover.x(), hover.y()], buttons=int(event.buttons().value),
                zoom=self.zoom(), dpr=self.devicePixelRatioF(), device=device.name() if device is not None else "",
                device_type=str(device.type()) if device is not None else "",
                device_id=int(device.uniqueId().numericId()) if device is not None else 0,
                device_system_id=int(device.systemId()) if device is not None else 0)

    def tabletEvent(self, event):
        if event.type() in (event.type().TabletMove, event.type().TabletPress, event.type().TabletRelease):
            self._tablet_t = event.timestamp()
            self._set_hover(event.position())
            self._log_hover(event, "tablet", event.pressure())
        if self.pen_log is not None:
            kind = {event.type().TabletPress: "press", event.type().TabletRelease: "release"}.get(event.type(), "move")
            device = event.pointingDevice()
            self._log_input(kind, "tablet", event, event.pressure(), tilt_x=event.xTilt(), tilt_y=event.yTilt(),
                            rotation=event.rotation(), tangential=event.tangentialPressure(),
                            device=device.name() if device is not None else "", pointer=str(event.pointerType()))
        pen = event.pointerType() != event.pointerType().Unknown
        self._pressure = max(0.0, min(1.0, event.pressure())) if pen else 1.0
        self._pen_active = pen and event.type() != event.type().TabletLeaveProximity   # (hors de portée : retour à la souris)
        if not self._pen_active:
            self._pressure = 1.0
        if pen and not self.session.pen_seen:
            # premier contact d'un stylet : la pression pilote la taille (sinon « non prise en compte » : case décochée)
            self.session.pen_seen = True
            self.session.brush.pressure_size = True
            self.colorsChanged.emit()
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
        elif self._xf is not None and key in (Qt.Key_Return, Qt.Key_Enter):
            self.commit_free_transform()
        elif self._xf is not None and key == Qt.Key_Escape:
            self.cancel_free_transform()
        elif ctrl and key == Qt.Key_T:
            self.start_free_transform()
        elif ctrl and key == Qt.Key_G:
            self.actions.group_selected()
        elif ctrl and key == Qt.Key_A:
            self.actions.select_all()
        elif ctrl and key == Qt.Key_D:
            self.actions.deselect()
        elif ctrl and mods & Qt.ShiftModifier and key == Qt.Key_I:
            self.actions.invert_selection()
        elif ctrl and key == Qt.Key_C:
            (self.actions.copy_merged if mods & Qt.ShiftModifier else self.actions.copy)()     # Ctrl+Maj+C : image finale (tous les calques)
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
        if self._stroke is not None or self._xf is not None:
            return
        command = self.session.undo()
        self.message.emit(f"Annulé : {command.label}" if command else "Rien à annuler")

    def redo(self):
        if self._stroke is not None or self._xf is not None:
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
        self._stroke.zoom = self.zoom()
        if self.debug_trace:
            self._last_trace = self._stroke.trace = {"raw": [], "used": [], "dabs": []}
        dirty = self._stroke.begin(x, y, pressure, air_now=time.monotonic())
        self._feed.start(x, y, pressure)
        self._notify_dirty(dirty)
        if self._stroke._air:
            self._air_timer.start()
        from .brush import TUNING
        if TUNING.catch_up_pause and self._stroke.brush.smoothing > 0:
            self._catch_up.start()
        return self._stroke

    def _catch_up_tick(self):
        if self._stroke is None:
            self._catch_up.stop()
            return
        if self._feed.pending():
            return                                  # le moteur a encore des points du curseur à poser
        self._notify_dirty(self._stroke.idle())

    def _air_tick(self):
        if self._stroke is None or not self._stroke._air:
            self._air_timer.stop()                  # (jamais de minuterie orpheline : elle ne vit que pendant un trait d'aérographe)
            return
        self._notify_dirty(self._stroke.air_tick(time.monotonic()))

    def extend_stroke(self, x, y, pressure=1.0, t=None):
        """Point suivant du geste, donné tout de suite au moteur (synchrone : tests, aérographe, journal du stylet)."""
        if self._stroke is not None:
            self._notify_dirty(self._stroke.move(x, y, pressure, t, air_now=time.monotonic()))
            self._feed.note(x, y, pressure, t)

    def _feed_direct(self) -> bool:
        """Mesure exacte plutôt que file : aérographe (horloge réelle), journal du stylet, tracé de diagnostic."""
        return self._stroke._air or self.pen_log is not None or self.debug_trace

    def _feed_point(self, x, y, pressure, t):
        stroke = self._stroke
        if stroke is not None:
            self._notify_dirty(stroke.move(x, y, pressure, t, air_now=time.monotonic()))

    def _feed_run(self, budget_ms):
        if self._stroke is None:
            self._feed.clear()
            return
        lag = self._feed.lag_ms()
        if lag > FEED_LAG_HARD_MS:
            budget_ms += lag - FEED_LAG_HARD_MS               # retard borné : l'excédent est rattrapé tout de suite (le relâchement ne bloque pas)
        elif lag > FEED_LAG_SOFT_MS:
            budget_ms = max(budget_ms, FEED_CATCH_MS)
        self._feed.run(self._feed_point, budget_ms)
        if self._feed.pending():
            self._feed_timer.start(1)                # la main revient à la boucle : évènements et peinture passent avant la suite

    def _feed_tick(self):
        self._feed_run(FEED_TICK_MS)

    def end_stroke(self, x, y, pressure=1.0):
        self._feed_timer.stop()
        if self._stroke is not None and self._feed.pending():
            self._feed.run(self._feed_point, None)  # relâchement : tous les points du curseur sont posés avant la fin du trait
        stroke, self._stroke = self._stroke, None
        self._catch_up.stop()
        self._air_timer.stop()                      # relâchement : le dépôt temporel s'arrête immédiatement
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
        layers = s.selected_layers()
        layer = layers[0]
        if any(l.locked for l in layers):
            self.message.emit("Un calque sélectionné est verrouillé.")
            return
        rect = None
        for l in layers:
            rect = rect_union(rect, ops.layer_rect(l))
        if rect is None:
            return
        from .movepreview import MovePreview
        # Les pixels du modèle ne bougent PAS pendant le geste (aperçu : voir movepreview.py) ; décalage à la fin.
        preview = MovePreview(s.doc, layers)
        preview.warm(self.visible_doc_rect())
        self._move = {"layer": layer, "layers": layers, "start": (x, y), "applied": (0, 0), "rect": rect,
                      "preview": preview}

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
        commands = []
        for layer in m["layers"]:                                   # le modèle est décalé UNE fois, à la fin
            ops.shift_layer(layer, dx, dy)
            commands.append(ops.translation_done(layer, dx, dy, m["rect"]))
        from .history import Compound
        command = commands[0] if len(commands) == 1 else Compound("Déplacer les calques", commands)
        self.session.notify("edit", m["rect"])                      # le cache recompose le résultat exact
        self.session.do(command, notified=True)
        self.update()
        return command

    # -- transformation libre (Ctrl+T) : poignées sans Ctrl, déplacer le corps avec Ctrl --
    def start_free_transform(self):
        from .freetransform import FreeTransform
        s = self.session
        layer = s.layer()
        if self._xf is not None:
            return self._xf
        if layer.locked or layer.is_group() or layer.pix is None:
            self.message.emit("Choisissez un calque de pixels non verrouillé.")
            return None
        if layer.source:
            self.message.emit(self.actions.REFUSED)
            return None
        try:
            self._xf = FreeTransform(layer)
        except ValueError as exc:
            self.message.emit(str(exc))
            return None
        self.message.emit("Transformation libre : poignées = échelle (Maj : proportions), cercle = rotation, "
                          "Ctrl + glisser = déplacer ; Entrée valide, Échap annule.")
        self.update()
        return self._xf

    def _xf_press(self, x, y):
        name = self._xf.hit(x, y, self.zoom())
        if name == "body" and not QApplication.keyboardModifiers() & Qt.ControlModifier:
            self.message.emit("Déplacer : Ctrl + glisser")
            return
        if name:
            self._xf.begin(name, x, y)
            self._xf_dragging = True

    def _xf_render(self):
        if self._xf is None:
            return
        dirty = self._xf.preview()
        if dirty is not None:
            self.session.notify("paint", dirty)

    def commit_free_transform(self):
        xf, self._xf, self._xf_dragging = self._xf, None, False
        if xf is None:
            return None
        self._xf_timer.stop()
        if xf.is_identity():
            self.session.notify("paint", xf.cancel())
            self.update()
            return None
        command = xf.command("bicubic")
        self.session.do(command)
        self.update()
        return command

    def cancel_free_transform(self):
        xf, self._xf, self._xf_dragging = self._xf, None, False
        if xf is not None:
            self._xf_timer.stop()
            rect = xf.cancel()
            self.session.notify("paint", rect)
            self.session.notify("structure", None)
        self.update()

    def _paint_free_transform(self, painter):
        xf = self._xf
        if xf is None:
            return
        from PySide6.QtGui import QPolygonF
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        corners = [self.to_widget(*p) for p in xf.corners()]
        painter.setBrush(Qt.NoBrush)
        for pen in (QPen(QColor(0, 0, 0, 200), 3), QPen(QColor(255, 255, 255), 1)):
            painter.setPen(pen)
            painter.drawPolygon(QPolygonF(corners))
        points = xf.handle_points(self.zoom())
        top, rot = self.to_widget(*points["n"]), self.to_widget(*points["rot"])
        painter.setPen(QPen(QColor(255, 255, 255), 1))
        painter.drawLine(top, rot)
        painter.setBrush(QColor(255, 255, 255))
        painter.setPen(QPen(QColor(0, 0, 0), 1))
        for name, p in points.items():
            w = self.to_widget(*p)
            if name == "rot":
                painter.drawEllipse(w, 5, 5)
            else:
                painter.drawRect(QRectF(w.x() - 4, w.y() - 4, 8, 8))
        painter.restore()

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
