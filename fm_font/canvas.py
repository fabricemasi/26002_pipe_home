"""Canvas d'édition d'un glyphe (Qt, peint) : zoom, pan, règles, grille, lignes de métriques, rempli / contour /
comparaison avec un autre master, nœuds et poignées, sélection, ancres, composants, repères. Les gestes sont
délégués à l'outil actif (`tools.py`).

FLUIDITÉ : un mouvement de souris ne fait que (1) déplacer des points du modèle, (2) invalider le chemin du SEUL
glyphe édité (`PathCache.invalidate`), (3) `update()`. Aucune compilation, aucun accès disque, aucune notification
du projet pendant le geste : l'étape d'annulation et la notification viennent au relâché."""
from __future__ import annotations

import math

from PySide6.QtCore import QLineF, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen, QPixmap, QTransform
from PySide6.QtWidgets import QWidget

from . import contours as C
from .render import color_brush, color_layers
from .settings_defaults import TYPO_DEFAULTS

RULER = 18                                            # épaisseur des règles (px)


class GlyphCanvas(QWidget):
    selectionChanged = Signal()
    glyphEdited = Signal()                            # après un geste (panneaux : coordonnées, approches…)
    viewChanged = Signal()
    toolChanged = Signal(str)
    statusMessage = Signal(str)
    contextRequested = Signal(QPointF, QPointF)       # position globale, position dans le canvas

    def __init__(self, project, cache, settings: dict | None = None, parent=None):
        super().__init__(parent)
        from . import tools
        self.project = project
        self.cache = cache
        self.settings = dict(TYPO_DEFAULTS)
        self.master = 0
        self.name: str | None = None
        self.scale = 0.5
        self.origin = QPointF(100, 500)                # position écran de (0, 0) en unités
        self.selection: set[tuple[int, int]] = set()   # (contour, point)
        self.selected_components: set[int] = set()
        self.selected_anchors: set[int] = set()
        self.compare_master: int | None = None
        self.hover: tuple | None = None
        self.space_down = False
        self._pan_from: QPointF | None = None
        self.pressure = 1.0
        self.interacting = False                       # geste en cours : remplissage sans anticrénelage
        self._settle = QTimer(self)
        self._settle.setSingleShot(True)
        self._settle.setInterval(160)
        self._settle.timeout.connect(self.end_interaction)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self.setAttribute(Qt.WA_TabletTracking, True)
        self.tools = {ident: cls(self) for ident, cls in tools.TOOLS.items()}
        self.tool = self.tools["select"]
        self.apply_settings(settings or {})

    # -- réglages / état --

    def apply_settings(self, settings: dict) -> None:
        for key in TYPO_DEFAULTS:
            if key in settings:
                self.settings[key] = settings[key]
        s = self.settings
        self._colors = {k: QColor(s[f"typo_{k}"]) for k in (
            "canvas_bg", "fill", "outline", "node", "node_smooth", "handle", "selection", "metrics", "grid",
            "component", "anchor", "compare")}
        self.update()

    @property
    def font(self):
        return self.project.masters[self.master].font

    @property
    def glyph(self):
        if self.name is None or self.name not in self.font:
            return None
        return self.font[self.name]

    def set_glyph(self, name: str | None, fit: bool = True) -> None:
        if name != self.name:
            self.tool.cancel()
            self.clear_selection()
        self.name = name
        if fit:
            self.fit()
        self.update()

    def set_master(self, index: int) -> None:
        self.tool.cancel()
        self.master = max(0, min(index, len(self.project.masters) - 1))
        self.clear_selection()
        self.update()

    def set_tool(self, key: str) -> None:
        if key not in self.tools or self.tool is self.tools[key]:
            return
        self.tool.cancel()
        self.tool = self.tools[key]
        self.setCursor(self.tool.cursor)
        self.toolChanged.emit(key)
        self.update()

    def clear_selection(self) -> None:
        if self.selection or self.selected_components or self.selected_anchors:
            self.selection.clear()
            self.selected_components.clear()
            self.selected_anchors.clear()
            self.selectionChanged.emit()

    def set_selection(self, points, components=(), anchors=()) -> None:
        self.selection = set(points)
        self.selected_components = set(components)
        self.selected_anchors = set(anchors)
        self.selectionChanged.emit()
        self.update()

    def selected_contours(self) -> list[int]:
        return sorted({c for c, _i in self.selection})

    def changed_live(self) -> None:
        """Pendant un geste : chemin du glyphe à refaire, repeindre (rien d'autre)."""
        self.interacting = True
        self.cache.invalidate(self.master, self.name)
        self.update()

    def end_interaction(self) -> None:
        """Fin d'un geste : une dernière peinture anticrénelée."""
        if self.interacting:
            self.interacting = False
            self.update()

    def _interact_briefly(self) -> None:
        """Zoom / pan à la molette : rendu rapide pendant la rafale, net 160 ms après le dernier cran."""
        self.interacting = True
        self._settle.start()

    # -- vue --

    def to_font(self, pos: QPointF) -> tuple[float, float]:
        return ((pos.x() - self.origin.x()) / self.scale, (self.origin.y() - pos.y()) / self.scale)

    def to_widget(self, x: float, y: float) -> QPointF:
        return QPointF(self.origin.x() + x * self.scale, self.origin.y() - y * self.scale)

    def fit(self) -> None:
        """Le cadratin entier (descendante -> ascendante, chasse) au centre du canvas."""
        info = self.font.info
        glyph = self.glyph
        top = max(info.ascender or 800, info.capHeight or 0)
        bottom = min(info.descender or -200, 0)
        width = glyph.width if glyph is not None and glyph.width else (info.unitsPerEm or 1000) * 0.6
        w, h = max(self.width() - RULER - 40, 50), max(self.height() - RULER - 40, 50)
        self.scale = min(w / max(width, 1), h / max(top - bottom, 1))
        self.origin = QPointF(RULER + 20 + (w - width * self.scale) / 2, RULER + 20 + top * self.scale +
                              (h - (top - bottom) * self.scale) / 2)
        self.viewChanged.emit()
        self.update()

    def zoom_at(self, factor: float, pos: QPointF) -> None:
        new = min(max(self.scale * factor, 0.01), 200.0)
        factor = new / self.scale
        self.origin = QPointF(pos.x() - (pos.x() - self.origin.x()) * factor,
                              pos.y() - (pos.y() - self.origin.y()) * factor)
        self.scale = new
        self._interact_briefly()
        self.viewChanged.emit()
        self.update()

    def pan(self, dx: float, dy: float) -> None:
        self.origin = QPointF(self.origin.x() + dx, self.origin.y() + dy)
        self._interact_briefly()
        self.update()

    # -- repérage --

    def hit_point(self, pos: QPointF, radius: float | None = None):
        """(contour, indice) du point sous `pos` (nœuds avant poignées), None sinon."""
        glyph = self.glyph
        if glyph is None:
            return None
        radius = radius or max(self.settings["typo_node_size"], 5) + 1
        best, best_d, best_on = None, radius, False
        for c, contour in enumerate(glyph.contours):
            for i, p in enumerate(contour):
                q = self.to_widget(p.x, p.y)
                d = math.hypot(q.x() - pos.x(), q.y() - pos.y())
                on = p.type is not None
                if d <= radius and (d < best_d or (on and not best_on and d <= best_d + 2)):
                    best, best_d, best_on = (c, i), d, on
        return best

    def hit_anchor(self, pos: QPointF):
        glyph = self.glyph
        if glyph is None:
            return None
        for k, a in enumerate(glyph.anchors):
            q = self.to_widget(a.x, a.y)
            if abs(q.x() - pos.x()) <= 6 and abs(q.y() - pos.y()) <= 6:
                return k
        return None

    def hit_segment(self, pos: QPointF):
        """(contour, segment, t, distance en px) du segment le plus proche à moins de 6 px."""
        glyph = self.glyph
        if glyph is None:
            return None
        fx, fy = self.to_font(pos)
        limit = 6 / self.scale
        best = None
        for c, contour in enumerate(glyph.contours):
            for seg in C.segments(contour):
                pts = C.segment_points(contour, seg)
                xs = [p[0] for p in pts]
                ys = [p[1] for p in pts]
                if not (min(xs) - limit <= fx <= max(xs) + limit and min(ys) - limit <= fy <= max(ys) + limit):
                    continue
                d, t, _p = C.nearest_on_segment(contour, seg, (fx, fy))
                if d <= limit and (best is None or d < best[3]):
                    best = (c, seg, t, d)
        return best

    def hit_component(self, pos: QPointF):
        glyph = self.glyph
        if glyph is None:
            return None
        fx, fy = self.to_font(pos)
        for k in reversed(range(len(glyph.components))):
            comp = glyph.components[k]
            if comp.baseGlyph not in self.font:
                continue
            base = self.cache.path(self.master, comp.baseGlyph)
            t = comp.transformation
            mapped = QTransform(t[0], t[1], t[2], t[3], t[4], t[5]).map(base)
            if mapped.contains(QPointF(fx, fy)):
                return k
        return None

    def hit_guideline(self, pos: QPointF):
        glyph = self.glyph
        if glyph is None:
            return None
        for k, g in enumerate(glyph.guidelines):
            if g.x is None and g.y is not None:                   # horizontal
                if abs(self.to_widget(0, g.y).y() - pos.y()) <= 4:
                    return k
            elif g.y is None and g.x is not None:                 # vertical
                if abs(self.to_widget(g.x, 0).x() - pos.x()) <= 4:
                    return k
        return None

    def hit_metric_line(self, pos: QPointF):
        """« right » : ligne de chasse ; « left » : ligne d'origine (x = 0), à 4 px ; None sinon. Tirer la ligne de
        chasse change la chasse ; tirer l'origine fait glisser le dessin (approche gauche) en gardant la droite."""
        glyph = self.glyph
        if glyph is None:
            return None
        if abs(self.to_widget(glyph.width, 0).x() - pos.x()) <= 4:
            return "right"
        if abs(self.to_widget(0, 0).x() - pos.x()) <= 4:
            return "left"
        return None

    def snap(self, x: float, y: float, exclude=()) -> tuple[float, float]:
        """Magnétisme : lignes de métriques, autres nœuds (à `typo_snap_distance` px), puis unité entière."""
        limit = self.settings["typo_snap_distance"] / self.scale
        info = self.font.info
        glyph = self.glyph
        ys = [0, info.ascender, info.descender, info.capHeight, info.xHeight]
        xs = [0, glyph.width if glyph is not None else 0]
        if glyph is not None and limit > 0:
            for c, contour in enumerate(glyph.contours):
                for i, p in enumerate(contour):
                    if p.type is not None and (c, i) not in exclude:
                        xs.append(p.x)
                        ys.append(p.y)
        bx = min((v for v in xs if v is not None), key=lambda v: abs(v - x), default=None)
        by = min((v for v in ys if v is not None), key=lambda v: abs(v - y), default=None)
        if bx is not None and abs(bx - x) <= limit:
            x = bx
        if by is not None and abs(by - y) <= limit:
            y = by
        if self.settings["typo_snap_integer"]:
            x, y = round(x), round(y)
        return x, y

    # -- dessin --

    def view_transform(self) -> QTransform:
        return QTransform(self.scale, 0, 0, -self.scale, self.origin.x(), self.origin.y())

    def _stroke(self, p: QPainter, path: QPainterPath, transform: QTransform) -> None:
        """Trait d'un chemin APLATI en polylignes dans l'espace de l'écran : ~15 fois plus rapide que le trait
        anticrénelé de courbes par Qt (37 ms -> 2 ms pour 25 anneaux plein écran)."""
        for poly in transform.map(path).toSubpathPolygons():
            p.drawPolyline(poly)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.fillRect(self.rect(), self._colors["canvas_bg"])
        glyph = self.glyph
        if glyph is None:
            p.setPen(self._colors["handle"])
            p.drawText(self.rect(), Qt.AlignCenter, "Choisissez un glyphe dans la grille (double-clic).")
            p.end()
            return
        p.drawPixmap(0, 0, self._background(glyph))
        p.setRenderHint(QPainter.Antialiasing, True)
        view = self.view_transform()
        if self.compare_master is not None and self.compare_master != self.master                 and self.name in self.project.masters[self.compare_master].font:
            p.setPen(QPen(self._colors["compare"], 1))
            p.setBrush(Qt.NoBrush)
            self._stroke(p, self.cache.path(self.compare_master, self.name), view)
        layers = color_layers(self.font, self.name)
        if layers:                                          # glyphe couleur : ses calques en fond, atténués
            from .color import PALETTES_KEY
            palette = self.font.lib[PALETTES_KEY][0]
            p.save()
            p.setRenderHint(QPainter.Antialiasing, not self.interacting)
            p.setTransform(view, True)
            p.setPen(Qt.NoPen)
            for layer, paint in layers:
                if layer in self.font:
                    path = self.cache.path(self.master, layer)
                    p.setBrush(color_brush(palette, paint, path, self._colors["fill"], alpha=110))
                    p.drawPath(path)
            p.restore()
        display = self.settings["typo_display"]
        if display in ("fill", "both"):
            # Remplissage anticrénelé : coût proportionnel à la surface (28 ms plein écran) ; PENDANT un geste
            # (glisser, zoom, pan) sans anticrénelage (3 ms), anticrénelé dès la fin du geste.
            p.setRenderHint(QPainter.Antialiasing, not self.interacting)
            p.setPen(Qt.NoPen)
            fill = QColor(self._colors["fill"])
            if display == "both":
                fill.setAlpha(60)
            p.setBrush(fill)
            p.drawPath(view.map(self.cache.path(self.master, self.name)))
            p.setRenderHint(QPainter.Antialiasing, True)
        p.setBrush(Qt.NoBrush)
        if display != "fill":
            p.setPen(QPen(self._colors["outline"], 1))         # 1 px entier : le chemin rapide du raster
            self._stroke(p, self.cache.path(self.master, self.name, "contours"), view)
        if glyph.components:
            p.setPen(QPen(self._colors["component"], 1.2))
            color = QColor(self._colors["component"])
            color.setAlpha(70 if display != "fill" else 0)
            for k, comp in enumerate(glyph.components):
                if comp.baseGlyph not in self.font:
                    continue
                t = comp.transformation
                local = QTransform(t[0], t[1], t[2], t[3], t[4], t[5]) * view
                base = self.cache.path(self.master, comp.baseGlyph)
                if k in self.selected_components:
                    p.setPen(Qt.NoPen)
                    p.setBrush(color)
                    p.drawPath(local.map(base))
                    p.setBrush(Qt.NoBrush)
                    p.setPen(QPen(self._colors["component"], 1.2))
                self._stroke(p, base, local)
        if display != "fill":
            self._paint_points(p, glyph)
        self._paint_anchors(p, glyph)
        self.tool.paint(p)
        if self.settings["typo_show_rulers"]:
            p.setRenderHint(QPainter.Antialiasing, False)
            self._paint_rulers(p)
        p.end()

    def _background(self, glyph) -> QPixmap:
        """Fond, grille, lignes de métriques et repères en IMAGE gardée tant que la vue, la chasse, les métriques
        et les repères ne changent pas : pendant un glisser de points, 0,3 ms au lieu de ~5 ms."""
        info = self.font.info
        key = (self.width(), self.height(), self.scale, self.origin.x(), self.origin.y(), glyph.width,
               info.ascender, info.descender, info.capHeight, info.xHeight, info.italicAngle,
               tuple((g.x, g.y) for g in glyph.guidelines), self.settings["typo_show_grid"],
               self.settings["typo_grid_step"], tuple(c.rgba() for c in self._colors.values()), self.devicePixelRatioF())
        if getattr(self, "_bg_key", None) != key:
            dpr = self.devicePixelRatioF()
            pixmap = QPixmap(max(1, int(self.width() * dpr)), max(1, int(self.height() * dpr)))
            pixmap.setDevicePixelRatio(dpr)
            pixmap.fill(self._colors["canvas_bg"])
            bp = QPainter(pixmap)
            if self.settings["typo_show_grid"]:
                self._paint_grid(bp)                           # lignes droites : sans anticrénelage (nettes)
            self._paint_metrics(bp, glyph)
            bp.end()
            self._bg_key, self._bg = key, pixmap
        return self._bg

    def _paint_grid(self, p: QPainter) -> None:
        step = self.settings["typo_grid_step"]
        if step <= 0 or step * self.scale < 6:
            return
        pen = QPen(self._colors["grid"], 1)
        p.setPen(pen)
        x0, y1 = self.to_font(QPointF(0, 0))
        x1, y0 = self.to_font(QPointF(self.width(), self.height()))
        lines = []
        x = math.floor(x0 / step) * step
        while x <= x1:
            q = self.to_widget(x, 0).x()
            lines.append((q, 0.0, q, float(self.height())))
            x += step
        y = math.floor(y0 / step) * step
        while y <= y1:
            q = self.to_widget(0, y).y()
            lines.append((0.0, q, float(self.width()), q))
            y += step
        p.drawLines([QLineF(*line) for line in lines])

    def _paint_metrics(self, p: QPainter, glyph) -> None:
        info = self.font.info
        pen = QPen(self._colors["metrics"], 1)
        p.setPen(pen)
        p.setFont(QFont(p.font().family(), 8))
        w = self.width()
        for value, label in ((0, "ligne de base"), (info.xHeight, "x"), (info.capHeight, "capitale"),
                             (info.ascender, "ascendante"), (info.descender, "descendante")):
            if value is None:
                continue
            y = self.to_widget(0, value).y()
            p.drawLine(QPointF(0, y), QPointF(w, y))
            p.drawText(QPointF(RULER + 4, y - 3), f"{label} {value:g}")
        top, bottom = self.to_widget(0, info.ascender or 800).y(), self.to_widget(0, info.descender or -200).y()
        for x in (0, glyph.width):
            q = self.to_widget(x, 0).x()
            p.drawLine(QPointF(q, top - 30), QPointF(q, bottom + 30))
        angle = info.italicAngle or 0
        if angle:
            slope = math.tan(math.radians(-angle))
            a, b = self.to_widget(slope * (info.descender or -200), info.descender or -200), \
                self.to_widget(slope * (info.ascender or 800), info.ascender or 800)
            p.drawLine(a, b)
        for g in glyph.guidelines:
            guide = QPen(self._colors["selection"], 1, Qt.DashLine)
            p.setPen(guide)
            if g.y is None and g.x is not None:
                q = self.to_widget(g.x, 0).x()
                p.drawLine(QPointF(q, 0), QPointF(q, self.height()))
            elif g.y is not None:
                q = self.to_widget(0, g.y).y()
                p.drawLine(QPointF(0, q), QPointF(w, q))

    def _paint_points(self, p: QPainter, glyph) -> None:
        """Nœuds et poignées, regroupés par aspect (un réglage de stylo / brosse par groupe, tiges en un seul
        drawLines) : ~1 200 points en ~4 ms."""
        size = self.settings["typo_node_size"]
        half = size / 2
        sel = self._colors["selection"]
        stems, handles, handles_sel = [], [], []
        corners, smooths, starts, nodes_sel, nodes_sel_smooth = [], [], [], [], []
        arrows = []
        to_widget = self.to_widget
        selection = self.selection
        for c, contour in enumerate(glyph.contours):
            n = len(contour)
            closed = C.is_closed(contour)
            pts = [to_widget(pt.x, pt.y) for pt in contour]
            for i, pt in enumerate(contour):
                q = pts[i]
                if pt.type is None:
                    for j in (i - 1, i + 1):
                        if (closed or 0 <= j < n) and contour[j % n].type is not None:
                            stems.append(QLineF(q, pts[j % n]))
                    (handles_sel if (c, i) in selection else handles).append(q)
                    continue
                if (c, i) in selection:
                    (nodes_sel_smooth if pt.smooth else nodes_sel).append(q)
                elif i == 0 or pt.type == "move":
                    starts.append(QRectF(q.x() - half - 1, q.y() - half - 1, size + 2, size + 2))
                elif pt.smooth:
                    smooths.append(q)
                else:
                    corners.append(QRectF(q.x() - half, q.y() - half, size, size))
            if n > 1 and closed:                                   # sens du contour : petit trait au départ
                a, b = pts[0], pts[1]
                d = math.hypot(b.x() - a.x(), b.y() - a.y())
                if d > 2 * size:
                    ux, uy = (b.x() - a.x()) / d, (b.y() - a.y()) / d
                    arrows.append(QLineF(QPointF(a.x() + ux * size, a.y() + uy * size),
                                         QPointF(a.x() + ux * size * 2.2, a.y() + uy * size * 2.2)))
        p.setPen(QPen(self._colors["handle"], 1))
        p.setBrush(Qt.NoBrush)
        if stems:
            p.drawLines(stems)
        for q in handles:
            p.drawEllipse(q, half * 0.8, half * 0.8)
        p.setPen(QPen(sel, 1))
        p.setBrush(QBrush(sel))
        for q in handles_sel:
            p.drawEllipse(q, half * 0.8, half * 0.8)
        for q in nodes_sel_smooth:
            p.drawEllipse(q, half, half)
        if nodes_sel:
            p.drawRects(nodes_sel and [QRectF(q.x() - half, q.y() - half, size, size) for q in nodes_sel])
        bg = QBrush(self._colors["canvas_bg"])
        p.setBrush(bg)
        p.setPen(QPen(self._colors["node"], 1))
        if corners:
            p.drawRects(corners)
        if starts:
            p.drawRects(starts)
        if arrows:
            p.drawLines(arrows)
        p.setPen(QPen(self._colors["node_smooth"], 1))
        for q in smooths:
            p.drawEllipse(q, half, half)
        if self.hover and self.hover[0] == "point":
            _k, c, i = self.hover
            if c < len(glyph.contours) and i < len(glyph.contours[c]):
                pt = glyph.contours[c][i]
                p.setBrush(Qt.NoBrush)
                p.setPen(QPen(sel, 1.5))
                p.drawEllipse(to_widget(pt.x, pt.y), half + 3, half + 3)

    def _paint_anchors(self, p: QPainter, glyph) -> None:
        if not glyph.anchors:
            return
        color = self._colors["anchor"]
        p.setFont(QFont(p.font().family(), 8))
        for k, a in enumerate(glyph.anchors):
            q = self.to_widget(a.x, a.y)
            selected = k in self.selected_anchors
            p.setPen(QPen(self._colors["selection"] if selected else color, 1.5))
            p.setBrush(QBrush(self._colors["selection"] if selected else self._colors["canvas_bg"]))
            path = QPainterPath()
            path.moveTo(q.x(), q.y() - 5)
            path.lineTo(q.x() + 5, q.y())
            path.lineTo(q.x(), q.y() + 5)
            path.lineTo(q.x() - 5, q.y())
            path.closeSubpath()
            p.drawPath(path)
            p.drawText(QPointF(q.x() + 7, q.y() - 6), a.name or "")

    def _paint_rulers(self, p: QPainter) -> None:
        bg = QColor(self._colors["canvas_bg"]).darker(108)
        p.setPen(Qt.NoPen)
        p.fillRect(QRectF(0, 0, self.width(), RULER), bg)
        p.fillRect(QRectF(0, 0, RULER, self.height()), bg)
        p.setPen(QPen(self._colors["handle"], 1))
        p.setFont(QFont(p.font().family(), 7))
        target = 60 / self.scale
        step = 10 ** math.floor(math.log10(max(target, 1e-6)))
        for m in (1, 2, 5, 10):
            if step * m >= target:
                step *= m
                break
        x0, y1 = self.to_font(QPointF(RULER, RULER))
        x1, y0 = self.to_font(QPointF(self.width(), self.height()))
        x = math.floor(x0 / step) * step
        while x <= x1:
            q = self.to_widget(x, 0).x()
            p.drawLine(QPointF(q, RULER - 6), QPointF(q, RULER))
            p.drawText(QPointF(q + 2, RULER - 7), f"{x:g}")
            x += step
        y = math.floor(y0 / step) * step
        while y <= y1:
            q = self.to_widget(0, y).y()
            p.drawLine(QPointF(RULER - 6, q), QPointF(RULER, q))
            p.save()
            p.translate(RULER - 8, q - 2)
            p.rotate(-90)
            p.drawText(QPointF(0, 0), f"{y:g}")
            p.restore()
            y += step

    # -- événements --

    def _event_pos(self, event) -> QPointF:
        return event.position() if hasattr(event, "position") else QPointF(event.pos())

    def mousePressEvent(self, event):
        pos = self._event_pos(event)
        if event.button() == Qt.MiddleButton or (event.button() == Qt.LeftButton and self.space_down):
            self._pan_from = pos
            self.setCursor(Qt.ClosedHandCursor)
            return
        if self.settings["typo_show_rulers"] and event.button() == Qt.LeftButton and (pos.x() < RULER or pos.y() < RULER):
            self._ruler_guide(pos)
            return
        if event.button() == Qt.RightButton:
            return
        if self.glyph is None:
            return
        self.pressure = 1.0
        self.tool.press(pos, event.modifiers())

    def mouseMoveEvent(self, event):
        pos = self._event_pos(event)
        if self._pan_from is not None:
            self.pan(pos.x() - self._pan_from.x(), pos.y() - self._pan_from.y())
            self._pan_from = pos
            return
        if self.glyph is None:
            return
        if event.buttons() & Qt.LeftButton:
            self.tool.move(pos, event.modifiers())
        else:
            self.tool.hover(pos, event.modifiers())

    def mouseReleaseEvent(self, event):
        pos = self._event_pos(event)
        if self._pan_from is not None:
            self._pan_from = None
            self.setCursor(self.tool.cursor)
            self.viewChanged.emit()
            return
        if self.glyph is not None and event.button() == Qt.LeftButton:
            self.tool.release(pos, event.modifiers())
        self.end_interaction()

    def contextMenuEvent(self, event):
        self.contextRequested.emit(QPointF(event.globalPos()), QPointF(event.pos()))

    def mouseDoubleClickEvent(self, event):
        if self.glyph is not None and event.button() == Qt.LeftButton:
            self.tool.double_click(self._event_pos(event), event.modifiers())

    def tabletEvent(self, event):
        """Tablette : la pression accompagne le geste (outils crayon / calligraphie) ; Qt envoie ensuite le même
        geste en événements souris, que l'outil traite avec cette pression."""
        self.pressure = max(0.05, min(event.pressure(), 1.0)) if event.pressure() > 0 else self.pressure
        event.ignore()

    def wheelEvent(self, event):
        delta = event.angleDelta().y() or event.angleDelta().x()
        zoom = self.settings["typo_wheel_zoom"] != bool(event.modifiers() & Qt.ControlModifier)
        if zoom and delta:
            self.zoom_at(1.0015 ** delta, self._event_pos(event))
        else:
            self.pan(event.angleDelta().x() / 2, event.angleDelta().y() / 2)
            self.viewChanged.emit()

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key_Space and not event.isAutoRepeat():
            self.space_down = True
            self.setCursor(Qt.OpenHandCursor)
            return
        if self.tool.key(event):
            return
        from .tools import TOOL_KEYS
        if key in TOOL_KEYS and not event.modifiers() & (Qt.ControlModifier | Qt.AltModifier):
            self.set_tool(TOOL_KEYS[key])
            return
        if key in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down) and self.selection:
            step = 10 if event.modifiers() & Qt.ShiftModifier else 1
            dx = {Qt.Key_Left: -step, Qt.Key_Right: step}.get(key, 0)
            dy = {Qt.Key_Down: -step, Qt.Key_Up: step}.get(key, 0)
            from . import geometry
            self.edit("Déplacer", lambda g: geometry.move_points(g, self.selection, dx, dy))
            return
        if key in (Qt.Key_Delete, Qt.Key_Backspace) and (self.selection or self.selected_components
                                                           or self.selected_anchors):
            self.delete_selection()
            return
        if key == Qt.Key_Escape:
            self.clear_selection()
            self.update()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key_Space and not event.isAutoRepeat():
            self.space_down = False
            self.setCursor(self.tool.cursor)
            return
        super().keyReleaseEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if event.oldSize().width() <= 0:
            self.fit()

    # -- éditions ponctuelles (un pas d'annulation) --

    def edit(self, label: str, fn) -> bool:
        if self.glyph is None:
            return False
        done = self.project.edit_glyph(self.name, label, fn, master=self.master)
        if done:
            self.glyphEdited.emit()
        self.update()
        return done

    def delete_selection(self) -> None:
        points = sorted(self.selection)
        comps = sorted(self.selected_components, reverse=True)
        anchors = sorted(self.selected_anchors, reverse=True)

        def fn(glyph):
            by_contour: dict[int, list[int]] = {}
            for c, i in points:
                by_contour.setdefault(c, []).append(i)
            for c in sorted(by_contour, reverse=True):
                contour = glyph.contours[c]
                C.delete_points(contour, by_contour[c])
                if len([p for p in contour if p.type]) < 2:
                    del glyph.contours[c]
            for k in comps:
                del glyph.components[k]
            for k in anchors:
                del glyph.anchors[k]
        self.edit("Supprimer", fn)
        self.clear_selection()

    def _ruler_guide(self, pos: QPointF) -> None:
        """Clic sur une règle : un repère du glyphe à cette position (vertical depuis la règle du haut, qui mesure
        les x ; horizontal depuis celle de gauche)."""
        from ufoLib2.objects import Guideline
        x, y = self.to_font(pos)
        guide = Guideline(x=round(x)) if pos.y() < RULER else Guideline(y=round(y))
        self.edit("Repère", lambda g: g.guidelines.append(guide))
