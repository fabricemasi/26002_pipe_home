"""Outils du canvas : sélection / édition des points, plume Bézier, crayon, rectangle, ellipse, polygone,
calligraphie (plume à angle, brosse), mesure, main.

Règle de l'appli (Ctrl + glisser pour DÉPLACER un élément) : les composants et les repères se déplacent avec
Ctrl + glisser ; les nœuds, poignées et ancres sont des gestes d'ÉDITION du tracé (comme les poignées du CAD) et se
tirent sans Ctrl. Un geste = une étape d'annulation (instantané au clic, étape au relâché)."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainterPath, QPen, QPolygonF
from ufoLib2.objects import Contour, Point

from . import calligraphy, geometry, knife, shapes
from . import contours as C

DRAG_THRESHOLD = 3


class Tool:
    ident = ""
    label = ""
    tip = ""
    cursor = Qt.ArrowCursor

    def __init__(self, canvas):
        self.canvas = canvas

    def press(self, pos, mods):
        pass

    def move(self, pos, mods):
        pass

    def release(self, pos, mods):
        pass

    def hover(self, pos, mods):
        pass

    def double_click(self, pos, mods):
        pass

    def key(self, event) -> bool:
        return False

    def paint(self, painter):
        pass

    def cancel(self):
        pass

    def font_pos(self, pos, snap: bool = True, exclude=()):
        x, y = self.canvas.to_font(pos)
        return self.canvas.snap(x, y, exclude) if snap else (x, y)


class SelectTool(Tool):
    ident, label, tip = "select", "Sélection", "Sélection et édition des points (V)"

    def __init__(self, canvas):
        super().__init__(canvas)
        self.drag = None              # ("points", poignée tirée | None) / ("anchor", k) / ("component", k) / ("guide", k)
        self.token = None
        self.start = None
        self.band: QRectF | None = None
        self.moved = False
        self.last = None

    def press(self, pos, mods):
        cv = self.canvas
        shift = bool(mods & Qt.ShiftModifier)
        ctrl = bool(mods & Qt.ControlModifier)
        self.start, self.moved, self.band = pos, False, None
        anchor = cv.hit_anchor(pos)
        if anchor is not None:
            anchors = (cv.selected_anchors ^ {anchor}) if shift else {anchor}
            cv.set_selection(cv.selection if shift else (), cv.selected_components if shift else (), anchors)
            self._begin(("anchor", anchor))
            return
        hit = cv.hit_point(pos)
        if hit is not None:
            if shift:
                cv.set_selection(cv.selection ^ {hit}, cv.selected_components, cv.selected_anchors)
            elif hit not in cv.selection:
                cv.set_selection({hit})
            if hit in cv.selection:
                glyph = cv.glyph
                self._begin(("points", hit if glyph.contours[hit[0]][hit[1]].type is None else None))
            return
        guide = cv.hit_guideline(pos)
        if guide is not None and ctrl:
            self._begin(("guide", guide))
            return
        seg = cv.hit_segment(pos)
        if seg is not None:
            c, (start, _offs, end, _kind), _t, _d = seg
            points = {(c, start), (c, end)}
            cv.set_selection((cv.selection | points) if shift else points)
            self._begin(("points", None))
            return
        comp = cv.hit_component(pos)
        if comp is not None:
            comps = (cv.selected_components ^ {comp}) if shift else {comp}
            cv.set_selection(cv.selection if shift else (), comps)
            if ctrl:
                self._begin(("component", comp))
            else:
                cv.statusMessage.emit("Ctrl + glisser pour déplacer le composant.")
            return
        side = cv.hit_metric_line(pos)
        if side is not None:                                # ligne de chasse / d'origine : métriques DANS la vue
            self._begin(("metric", side))
            self.metric_start = (cv.glyph.width, cv.to_font(pos)[0])
            self.metric_moved = 0
            return
        if not shift:
            cv.clear_selection()
        self.band = QRectF(pos, pos)
        cv.update()

    def _begin(self, drag):
        cv = self.canvas
        self.drag = drag
        self.token = cv.project.begin_edit(cv.name, cv.master)
        self.last = None

    def move(self, pos, mods):
        cv = self.canvas
        if self.band is not None:
            self.band = QRectF(self.start, pos).normalized()
            cv.update()
            return
        if self.drag is None:
            return
        if not self.moved and math.hypot(pos.x() - self.start.x(), pos.y() - self.start.y()) < DRAG_THRESHOLD:
            return
        self.moved = True
        glyph = cv.glyph
        kind, ref = self.drag
        if mods & Qt.ShiftModifier:                         # contrainte horizontale / verticale
            if abs(pos.x() - self.start.x()) > abs(pos.y() - self.start.y()):
                pos = QPointF(pos.x(), self.start.y())
            else:
                pos = QPointF(self.start.x(), pos.y())
        if kind == "points":
            anchor_point = ref if ref is not None else self._reference_node()
            p = glyph.contours[anchor_point[0]][anchor_point[1]]
            if self.last is None:                           # décalage clic / point gardé pendant le geste
                fx, fy = cv.to_font(self.start)
                self.offset = (p.x - fx, p.y - fy)
            ox, oy = self.offset
            fx, fy = cv.to_font(pos)
            x, y = cv.snap(fx + ox, fy + oy, exclude=geometry.with_handles(glyph, cv.selection))
            dx, dy = x - p.x, y - p.y
            self.last = (x, y)
            if ref is not None and len(cv.selection) == 1:  # une poignée : la seule tirée, l'autre suit si lisse
                p.x, p.y = x, y
                contour = glyph.contours[ref[0]]
                for j in C.neighbours(contour, ref[1]):
                    if j is not None and contour[j].type is not None and contour[j].smooth:
                        C.align_handles(contour, j, keep=ref[1])
            else:
                geometry.move_points(glyph, cv.selection, dx, dy)
        elif kind == "anchor":
            a = glyph.anchors[ref]
            a.x, a.y = self.font_pos(pos)
        elif kind == "component":
            comp = glyph.components[ref]
            fx, fy = cv.to_font(pos)
            sx, sy = cv.to_font(self.start)
            if self.last is None:
                t = comp.transformation
                self.base_t = tuple(t)
            t = self.base_t
            dx, dy = fx - sx, fy - sy
            if cv.settings["typo_snap_integer"]:
                dx, dy = round(dx), round(dy)
            comp.transformation = type(comp.transformation)(t[0], t[1], t[2], t[3], t[4] + dx, t[5] + dy)
            self.last = (dx, dy)
        elif kind == "metric":
            width0, x0 = self.metric_start
            dx = cv.to_font(pos)[0] - x0
            if cv.settings["typo_snap_integer"]:
                dx = round(dx)
            if ref == "right":                              # chasse : le dessin ne bouge pas
                glyph.width = max(0, width0 + dx)
            else:                                           # origine : le dessin glisse, l'approche droite reste
                from .metrics import _shift
                moved = getattr(self, "metric_moved", 0)
                _shift(glyph, -dx - moved)
                self.metric_moved = -dx
                glyph.width = max(0, width0 - dx)
        elif kind == "guide":
            g = glyph.guidelines[ref]
            x, y = self.font_pos(pos)
            if g.x is not None and g.y is None:
                g.x = x
            elif g.y is not None and g.x is None:
                g.y = y
        cv.changed_live()

    def _reference_node(self):
        cv = self.canvas
        glyph = cv.glyph
        nodes = sorted(ci for ci in cv.selection if glyph.contours[ci[0]][ci[1]].type is not None)
        if not nodes:
            return min(cv.selection)
        fx, fy = cv.to_font(self.start)
        return min(nodes, key=lambda ci: math.hypot(glyph.contours[ci[0]][ci[1]].x - fx,
                                                     glyph.contours[ci[0]][ci[1]].y - fy))

    def release(self, pos, mods):
        cv = self.canvas
        if self.band is not None:
            band = self.band
            self.band = None
            glyph = cv.glyph
            found = set()
            for c, contour in enumerate(glyph.contours):
                for i, p in enumerate(contour):
                    if band.contains(cv.to_widget(p.x, p.y)):
                        found.add((c, i))
            anchors = {k for k, a in enumerate(glyph.anchors) if band.contains(cv.to_widget(a.x, a.y))}
            if mods & Qt.ShiftModifier:
                found |= cv.selection
                anchors |= cv.selected_anchors
            cv.set_selection(found, cv.selected_components, anchors)
            return
        if self.token is not None:
            label = {"points": "Déplacer les points", "anchor": "Déplacer l'ancre", "component": "Déplacer le composant",
                     "guide": "Déplacer le repère", "metric": "Métriques"}[self.drag[0]]
            self.metric_moved = 0
            if cv.project.end_edit(self.token, label):
                cv.glyphEdited.emit()
        self.token, self.drag = None, None
        cv.update()

    def cancel(self):
        if self.token is not None:
            from .undo import glyph_restore
            master, name, snap = self.token
            glyph_restore(self.canvas.project.masters[master].font[name], snap)
            self.canvas.changed_live()
        self.token, self.drag, self.band = None, None, None

    def hover(self, pos, mods):
        cv = self.canvas
        hit = cv.hit_point(pos)
        state = ("point", *hit) if hit is not None else None
        if state != cv.hover:
            cv.hover = state
            cv.update()

    def double_click(self, pos, mods):
        cv = self.canvas
        hit = cv.hit_point(pos)
        glyph = cv.glyph
        if hit is not None and glyph.contours[hit[0]][hit[1]].type is not None:
            c, i = hit
            smooth = not glyph.contours[c][i].smooth
            cv.edit("Lisse / coin", lambda g: C.set_smooth(g.contours[c], i, smooth))
            return
        seg = cv.hit_segment(pos)
        if seg is not None:
            c = seg[0]
            cv.set_selection({(c, i) for i in range(len(glyph.contours[c]))})

    def paint(self, painter):
        if self.band is not None:
            color = QColor(self.canvas._colors["selection"])
            painter.setPen(QPen(color, 1, Qt.DashLine))
            color.setAlpha(30)
            painter.setBrush(color)
            painter.drawRect(self.band)


class PenTool(Tool):
    ident, label, tip = "pen", "Plume", "Plume Bézier : clic = coin, glisser = nœud lisse, clic sur le départ = fermer (P)"
    cursor = Qt.CrossCursor

    def __init__(self, canvas):
        super().__init__(canvas)
        self.contour = None           # contour en cours (objet)
        self.pending_out = None       # poignée sortante du dernier nœud (x, y)
        self.token = None
        self.press_pos = None
        self.node = None              # nœud créé par le clic en cours
        self.closing = False
        self.cursor_pos = None

    def press(self, pos, mods):
        cv = self.canvas
        glyph = cv.glyph
        self.token = cv.project.begin_edit(cv.name, cv.master)
        self.press_pos = pos
        x, y = self.font_pos(pos)
        if self.contour is not None and self.contour not in glyph.contours:
            self.contour = None                                   # annulé entre-temps
        if self.contour is None:
            self.node = Point(x, y, "move")
            self.contour = Contour([self.node])
            glyph.contours.append(self.contour)
            self.pending_out = None
            self.closing = False
        else:
            first = self.contour[0]
            q = cv.to_widget(first.x, first.y)
            self.closing = len(self.contour) > 1 and math.hypot(q.x() - pos.x(), q.y() - pos.y()) <= 8
            if self.closing:
                if self.pending_out is not None:
                    self.contour.points += [Point(*self.pending_out), Point(first.x, first.y)]
                    first.type = "curve"
                else:
                    first.type = "line"
                self.node = first
            else:
                if self.pending_out is not None:
                    self.contour.points += [Point(*self.pending_out), Point(x, y)]
                    self.node = Point(x, y, "curve")
                else:
                    self.node = Point(x, y, "line")
                self.contour.points.append(self.node)
        cv.changed_live()

    def move(self, pos, mods):
        cv = self.canvas
        if self.node is None or math.hypot(pos.x() - self.press_pos.x(), pos.y() - self.press_pos.y()) < DRAG_THRESHOLD:
            return
        hx, hy = self.font_pos(pos, snap=False)
        node = self.node
        out = (hx, hy)
        mirror = (2 * node.x - hx, 2 * node.y - hy)
        pts = self.contour.points
        if node is not pts[0] or self.closing:
            k = len(pts) - 1 if not self.closing else len(pts)     # le nœud (ou la fin, à la fermeture)
            if node.type == "line":                               # ligne -> courbe : poignées ajoutées
                prev = pts[k - 1]
                node.type = "curve"
                pts[k:k] = [Point(prev.x, prev.y), Point(*mirror)]
            elif node.type == "curve":
                pts[k - 1].x, pts[k - 1].y = mirror
        node.smooth = True
        self.pending_out = None if self.closing else out
        if self.closing and len(pts) > 2 and pts[1].type is None:
            pts[1].x, pts[1].y = out                               # poignée sortante du départ
        self._dragged_out = out
        cv.changed_live()

    def release(self, pos, mods):
        cv = self.canvas
        moved = self.press_pos is not None and math.hypot(pos.x() - self.press_pos.x(),
                                                          pos.y() - self.press_pos.y()) >= DRAG_THRESHOLD
        if not moved:
            self.pending_out = None
        if cv.project.end_edit(self.token, "Plume"):
            cv.glyphEdited.emit()
        self.token = None
        if self.closing:
            self.finish()
        cv.update()

    def hover(self, pos, mods):
        self.cursor_pos = pos
        if self.contour is not None:
            self.canvas.update()

    def key(self, event) -> bool:
        if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Escape) and self.contour is not None:
            self.finish()
            return True
        return False

    def finish(self):
        self.contour, self.pending_out, self.node, self.closing = None, None, None, False
        self.canvas.update()

    def cancel(self):
        self.finish()

    def paint(self, painter):
        if self.contour is None or self.cursor_pos is None or not len(self.contour):
            return
        last = next((p for p in reversed(self.contour.points) if p.type), None)
        if last is None:
            return
        cv = self.canvas
        painter.setPen(QPen(cv._colors["selection"], 1, Qt.DashLine))
        a = cv.to_widget(last.x, last.y)
        if self.pending_out is not None:
            h = cv.to_widget(*self.pending_out)
            path = QPainterPath(a)
            path.quadTo(h, self.cursor_pos)
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(path)
        else:
            painter.drawLine(a, self.cursor_pos)


class PencilTool(Tool):
    ident, label, tip = "pencil", "Crayon", "Crayon : tracé libre lissé puis ajusté en courbes (B)"
    cursor = Qt.CrossCursor

    def __init__(self, canvas):
        super().__init__(canvas)
        self.points: list[tuple[float, float]] = []
        self.screen: list[QPointF] = []

    def press(self, pos, mods):
        self.points = [self.canvas.to_font(pos)]
        self.screen = [pos]

    def move(self, pos, mods):
        if not self.points:
            return
        self.points.append(self.canvas.to_font(pos))
        self.screen.append(pos)
        self.canvas.update()

    def release(self, pos, mods):
        cv = self.canvas
        pts, screen = self.points, self.screen
        self.points, self.screen = [], []
        if len(pts) < 3:
            cv.update()
            return
        closed = math.hypot(screen[0].x() - screen[-1].x(), screen[0].y() - screen[-1].y()) <= 10
        error = cv.settings["typo_pencil_error"] / 10 / cv.scale
        contour = shapes.pencil_contour(pts, error=error, smoothing=int(cv.settings["typo_pencil_smoothing"]),
                                        closed=closed)
        if len(contour):
            cv.edit("Crayon", lambda g: g.contours.append(contour))

    def cancel(self):
        self.points, self.screen = [], []

    def paint(self, painter):
        if len(self.screen) > 1:
            painter.setPen(QPen(self.canvas._colors["selection"], 1.5))
            painter.drawPolyline(QPolygonF(self.screen))


class ShapeTool(Tool):
    cursor = Qt.CrossCursor
    shape = "rect"

    def __init__(self, canvas):
        super().__init__(canvas)
        self.a = self.b = None

    def press(self, pos, mods):
        self.a = self.b = self.font_pos(pos)

    def move(self, pos, mods):
        if self.a is None:
            return
        x, y = self.font_pos(pos)
        if mods & Qt.ShiftModifier:                            # carré / cercle
            side = max(abs(x - self.a[0]), abs(y - self.a[1]))
            x = self.a[0] + math.copysign(side, x - self.a[0])
            y = self.a[1] + math.copysign(side, y - self.a[1])
        self.b = (x, y)
        self.canvas.update()

    def make(self, mods) -> Contour | None:
        (x0, y0), (x1, y1) = self.a, self.b
        if abs(x1 - x0) < 1 or abs(y1 - y0) < 1:
            return None
        if self.shape == "rect":
            return shapes.rectangle(x0, y0, x1, y1)
        if self.shape == "ellipse":
            return shapes.ellipse(x0, y0, x1, y1)
        radius = max(abs(x1 - x0), abs(y1 - y0)) / 2
        star = 0.5 if mods & Qt.AltModifier else 0.0
        return shapes.polygon((x0 + x1) / 2, (y0 + y1) / 2, radius, 6 if not star else 5, star)

    def release(self, pos, mods):
        if self.a is None:
            return
        contour = self.make(mods)
        self.a = self.b = None
        if contour is not None:
            self.canvas.edit(self.label, lambda g: g.contours.append(contour))
        self.canvas.update()

    def cancel(self):
        self.a = self.b = None

    def paint(self, painter):
        if self.a is None or self.b is None:
            return
        cv = self.canvas
        contour = self.make(Qt.NoModifier)
        if contour is None:
            return
        from .render import QPathPen
        path = QPainterPath()
        contour.draw(QPathPen(None, path))
        painter.save()
        painter.translate(cv.origin)
        painter.scale(cv.scale, -cv.scale)
        pen = QPen(cv._colors["selection"], 1)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)
        painter.restore()


class RectTool(ShapeTool):
    ident, label, tip, shape = "rect", "Rectangle", "Rectangle (R ; Maj = carré)", "rect"


class EllipseTool(ShapeTool):
    ident, label, tip, shape = "ellipse", "Ellipse", "Ellipse (E ; Maj = cercle)", "ellipse"


class PolygonTool(ShapeTool):
    ident, label, tip, shape = "polygon", "Polygone", "Polygone (Y ; Alt = étoile)", "polygon"


class CalligraphyTool(Tool):
    ident, label, tip = "nib", "Plume calligraphique", "Plume à bec plat (angle et largeur : réglages ; pression) (C)"
    cursor = Qt.CrossCursor
    kind = "nib"

    def __init__(self, canvas):
        super().__init__(canvas)
        self.samples: list[tuple[float, float, float]] = []
        self.preview: list[QPolygonF] = []

    def _width(self):
        s = self.canvas.settings
        return float(s["typo_nib_width"] if self.kind == "nib" else s["typo_brush_width"])

    def press(self, pos, mods):
        x, y = self.canvas.to_font(pos)
        self.samples = [(x, y, self.canvas.pressure)]
        self.preview = []

    def move(self, pos, mods):
        if not self.samples:
            return
        cv = self.canvas
        x, y = cv.to_font(pos)
        self.samples.append((x, y, cv.pressure))
        s = cv.settings
        pressure = bool(s["typo_use_pressure"])
        pair = self.samples[-2:]
        if self.kind == "nib":
            polys = calligraphy.nib_polygons(pair, self._width(), float(s["typo_nib_angle"]), pressure)
        else:
            polys = calligraphy.brush_polygons(pair, self._width(), pressure, round_caps=False)
        for poly in polys:                                     # aperçu incrémental : un quadrilatère par pas
            self.preview.append(QPolygonF([cv.to_widget(px, py) for px, py in poly]))
        cv.update()

    def release(self, pos, mods):
        cv = self.canvas
        samples, self.samples, self.preview = self.samples, [], []
        if len(samples) < 2:
            cv.update()
            return
        s = cv.settings
        contours = calligraphy.outline(samples, self.kind, self._width(), float(s["typo_nib_angle"]),
                                       bool(s["typo_use_pressure"]), int(s["typo_pencil_smoothing"]),
                                       error=max(0.5, 1.5 / cv.scale))

        def add(glyph):
            for contour in contours:
                glyph.contours.append(contour)
        if contours:
            cv.edit(self.label, add)
        cv.update()

    def cancel(self):
        self.samples, self.preview = [], []

    def paint(self, painter):
        if not self.preview:
            return
        color = QColor(self.canvas._colors["fill"])
        color.setAlpha(140)
        painter.setPen(Qt.NoPen)
        painter.setBrush(color)
        for poly in self.preview:
            painter.drawPolygon(poly)


class BrushTool(CalligraphyTool):
    ident, label, tip, kind = "brush", "Brosse", "Brosse à largeur variable (pression de la tablette) (W)", "brush"


class MeasureTool(Tool):
    ident, label, tip = "measure", "Mesure", "Mesure : distance, angle, épaisseurs traversées (M)"
    cursor = Qt.CrossCursor

    def __init__(self, canvas):
        super().__init__(canvas)
        self.a = self.b = None
        self.hits = []

    def press(self, pos, mods):
        self.a = self.b = self.canvas.to_font(pos)
        self.hits = []
        self.polys = geometry.flattened(self.canvas.glyph) if self.canvas.glyph is not None else []

    def move(self, pos, mods):
        if self.a is None:
            return
        self.b = self.canvas.to_font(pos)
        self.hits = geometry.intersections_with_line(None, self.a, self.b, polys=self.polys)
        self.canvas.update()

    def release(self, pos, mods):
        if self.a is not None:
            m = geometry.measure(self.a, self.b)
            self.canvas.statusMessage.emit(f"Distance {m['distance']:.1f} u, angle {m['angle']:.1f}°, "
                                           f"Δx {m['dx']:.1f}, Δy {m['dy']:.1f}")

    def cancel(self):
        self.a = self.b = None

    def paint(self, painter):
        if self.a is None or self.b is None:
            return
        cv = self.canvas
        a, b = cv.to_widget(*self.a), cv.to_widget(*self.b)
        painter.setPen(QPen(cv._colors["selection"], 1))
        painter.drawLine(a, b)
        m = geometry.measure(self.a, self.b)
        painter.drawText(QPointF(b.x() + 8, b.y() - 8), f"{m['distance']:.1f} u  {m['angle']:.1f}°")
        for p, q in zip(self.hits, self.hits[1:]):
            mid = cv.to_widget((p[0] + q[0]) / 2, (p[1] + q[1]) / 2)
            painter.drawText(QPointF(mid.x() + 4, mid.y() + 12), f"{math.dist(p, q):.0f}")
        for h in self.hits:
            painter.drawEllipse(cv.to_widget(*h), 3, 3)


class KnifeTool(Tool):
    ident, label, tip = "knife", "Couteau", "Couteau : glisser à travers une forme pour la couper (Maj : 45°) (K)"
    cursor = Qt.CrossCursor

    def __init__(self, canvas):
        super().__init__(canvas)
        self.a = self.b = None
        self.hits = []

    def press(self, pos, mods):
        self.a = self.b = self.canvas.to_font(pos)
        self.hits = []
        self.polys = geometry.flattened(self.canvas.glyph) if self.canvas.glyph is not None else []

    def move(self, pos, mods):
        if self.a is None:
            return
        x, y = self.canvas.to_font(pos)
        if mods & Qt.ShiftModifier:                         # contrainte à 45°
            dx, dy = x - self.a[0], y - self.a[1]
            angle = round(math.atan2(dy, dx) / (math.pi / 4)) * (math.pi / 4)
            length = math.hypot(dx, dy)
            x, y = self.a[0] + length * math.cos(angle), self.a[1] + length * math.sin(angle)
        self.b = (x, y)
        self.hits = geometry.intersections_with_line(None, self.a, self.b, polys=self.polys)   # aperçu
        self.canvas.update()

    def release(self, pos, mods):
        cv = self.canvas
        a, b, self.a, self.b, self.hits = self.a, self.b, None, None, []
        if a is None or b is None or math.dist(a, b) * cv.scale < 3:
            cv.update()
            return
        result = []
        cv.edit(self.label, lambda glyph: result.append(knife.cut(glyph, a, b)))
        cv.statusMessage.emit(f"Couteau : {result[0]} coupe(s)." if result and result[0] else
                              "Couteau : le trait ne traverse aucune forme.")
        cv.update()

    def cancel(self):
        self.a = self.b = None
        self.hits = []

    def paint(self, painter):
        if self.a is None or self.b is None:
            return
        cv = self.canvas
        painter.setPen(QPen(cv._colors["selection"], 1, Qt.DashLine))
        painter.drawLine(cv.to_widget(*self.a), cv.to_widget(*self.b))
        for h in self.hits:
            painter.drawEllipse(cv.to_widget(*h), 3, 3)


class HandTool(Tool):
    ident, label, tip = "hand", "Main", "Déplacer la vue (H ; Espace tenu ou bouton du milieu partout)"
    cursor = Qt.OpenHandCursor

    def press(self, pos, mods):
        self.last = pos

    def move(self, pos, mods):
        self.canvas.pan(pos.x() - self.last.x(), pos.y() - self.last.y())
        self.last = pos


TOOLS = {cls.ident: cls for cls in (SelectTool, PenTool, PencilTool, RectTool, EllipseTool, PolygonTool,
                                  CalligraphyTool, BrushTool, MeasureTool, KnifeTool, HandTool)}
TOOL_KEYS = {Qt.Key_V: "select", Qt.Key_P: "pen", Qt.Key_B: "pencil", Qt.Key_R: "rect", Qt.Key_E: "ellipse",
             Qt.Key_Y: "polygon", Qt.Key_C: "nib", Qt.Key_W: "brush", Qt.Key_M: "measure", Qt.Key_K: "knife",
             Qt.Key_H: "hand"}
