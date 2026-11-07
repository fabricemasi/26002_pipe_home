"""Outils de transformation à POINT D'ORIGINE (Rotation R, Mise à l'échelle S, Symétrie O), saisies numériques,
repères commentés (magnétisme pendant un déplacement).

Outils (comme Illustrator) : l'origine est le centre de la sélection ; un clic la déplace ; glisser depuis un point
transforme autour de l'origine (Maj : pas de 45° / échelle uniforme / axe à 45°) ; Alt + clic = valeur saisie
autour du point cliqué. Une étape par geste ; la transformation devient la « dernière » (Transformer de nouveau,
Ctrl+D). Géométrie, pas un déplacement d'élément : sans Ctrl (règle de l'appli).

Repères commentés (Ctrl+U, actifs par défaut) : pendant Ctrl + glisser, les bords et centres de la sélection
s'aimantent à ceux des objets VISIBLES à l'écran et des plans de travail, à 6 px d'écran près ; lignes montrées par
l'overlay, chacune avec sa SORTE (`fm_board.snap_guides` : plan de travail = « bords des documents », objet =
« objets internes » ; Réglages > Module MRO > Magnétisme). Candidats calculés une fois au début du geste,
recherche par dichotomie (`bisect`)."""
from __future__ import annotations

import math
from bisect import bisect_left

from PySide6.QtCore import QLineF, QPointF, QRectF, Qt
from PySide6.QtWidgets import QInputDialog

from fm_board.snap_guides import DOCUMENTS, INNER, GuideLine

from . import bezier as bz
from .tools import Tool, TransformGesture

SNAP_PX = 6.0


# ---------------------------------------------------------------- repères commentés
class Snapper:
    """Repères : bords et centres des objets visibles et des plans de travail, en simples nombres (des milliers de
    `QRectF` réveillaient le ramasse-miettes : relevé 11 à 54 ms selon le moment)."""

    def __init__(self, ctl, exclude=()):
        self.ctl = ctl
        self.boxes: list[tuple[float, float, float, float]] = []      # (gauche, haut, droite, bas)
        self.xs: list[tuple[float, int]] = []
        self.ys: list[tuple[float, int]] = []
        self._xv: list[float] = []
        self._yv: list[float] = []
        self.objects = 0                                                # boîtes d'objets ; les suivantes : plans de travail
        if not ctl.smart_guides:
            return
        from .items import IllPathItem
        skip = set(exclude)
        visible = ctl.view.mapToScene(ctl.view.viewport().rect()).boundingRect()
        rects = [i.geometry_rect() for i in ctl.scene.items(visible, Qt.IntersectsItemBoundingRect)
                 if isinstance(i, IllPathItem) and i not in skip and i.isVisible()]     # index : visibles seulement
        self.objects = len(rects)
        rects += [b.scene_rect() for b in ctl.artboards() if b.isVisible() and b.scene_rect().intersects(visible)]
        boxes = self.boxes
        xs, ys = self.xs, self.ys
        for r in rects:
            left, top, right, bottom = r.getCoords()
            n = len(boxes)
            boxes.append((left, top, right, bottom))
            xs += ((left, n), ((left + right) / 2, n), (right, n))
            ys += ((top, n), ((top + bottom) / 2, n), (bottom, n))
        xs.sort()
        ys.sort()
        self._xv = [v for v, _n in xs]
        self._yv = [v for v, _n in ys]

    @staticmethod
    def _nearest(values, mine, tol):
        best = None
        for value in mine:
            i = bisect_left(values, value)
            for j in (i - 1, i):
                if 0 <= j < len(values):
                    d = values[j] - value
                    if abs(d) <= tol and (best is None or abs(d) < abs(best[0])):
                        best = (d, j)
        return best

    def snap_rect(self, rect: QRectF) -> tuple[float, float, list[QLineF]]:
        """(dx, dy, lignes) : décalage qui aligne un bord / centre de `rect` sur le plus proche candidat."""
        if not self.xs and not self.ys:
            return 0.0, 0.0, []
        tol = self.ctl.tolerance(SNAP_PX)
        bx = self._nearest(self._xv, (rect.left(), rect.center().x(), rect.right()), tol)
        by = self._nearest(self._yv, (rect.top(), rect.center().y(), rect.bottom()), tol)
        dx = bx[0] if bx else 0.0
        dy = by[0] if by else 0.0
        moved = rect.translated(dx, dy).getCoords()
        lines = []
        if bx:
            x, (_l, top, _r, bottom), kind = self._closest(self.xs, self._xv, bx[1], moved, vertical=True)
            lines.append(GuideLine(x, min(moved[1], top), x, max(moved[3], bottom), kind=kind))
        if by:
            y, (left, _t, right, _b), kind = self._closest(self.ys, self._yv, by[1], moved, vertical=False)
            lines.append(GuideLine(min(moved[0], left), y, max(moved[2], right), y, kind=kind))
        return dx, dy, lines

    def _closest(self, entries, values, j, moved, vertical: bool):
        """Parmi les objets alignés sur la même valeur, le plus PROCHE : ligne courte (une ligne vers un objet
        lointain d'une grille faisait repeindre une longue bande à chaque mouvement : +8 ms). Rend aussi la sorte du
        guide : « bords des documents » si un plan de travail est aligné sur cette valeur (il l'emporte), sinon
        « objets internes »."""
        value = values[j]
        lo = bisect_left(values, value - 1e-6)
        best, best_d = self.boxes[entries[j][1]], float("inf")
        kind = INNER
        k = lo
        while k < len(values) and values[k] <= value + 1e-6 and k < lo + 400:
            if entries[k][1] >= self.objects:
                kind = DOCUMENTS
            box = self.boxes[entries[k][1]]
            if vertical:
                d = max(box[1] - moved[3], moved[1] - box[3], 0.0)
            else:
                d = max(box[0] - moved[2], moved[0] - box[2], 0.0)
            if d < best_d:
                best, best_d = box, d
            k += 1
        return value, best, kind

    def snap_point(self, p: QPointF) -> tuple[QPointF, list[QLineF]]:
        dx, dy, lines = self.snap_rect(QRectF(p, p))
        return QPointF(p.x() + dx, p.y() + dy), lines


# ---------------------------------------------------------------- outils à origine
class OriginGesture(TransformGesture):
    def __init__(self, tool, items, start: QPointF):
        super().__init__(tool.ctl, items, tool.ctl.selection_rect(items), "origin", start)
        self.tool = tool
        self.label = tool.label.split(" (")[0]

    def matrix(self, pos: QPointF, mods):
        return self.tool.matrix(self.start, pos, mods)


class OriginTool(Tool):
    def __init__(self, ctl):
        super().__init__(ctl)
        self.origin: QPointF | None = None          # None = centre de la sélection
        self.gesture = None
        self.press_at = None

    def origin_point(self) -> QPointF | None:
        if self.origin is not None:
            return self.origin
        rect = self.ctl.selection_rect()
        return rect.center() if rect is not None else None

    def press(self, pos, mods):
        self.press_at = pos
        if not self.ctl.selection():
            item = self.ctl.object_at(pos)
            if item is not None:
                self.ctl.select(self.ctl.group_of(item))
                self.origin = None

    def drag(self, pos, mods):
        ctl = self.ctl
        if self.press_at is None or not ctl.selection():
            return
        if self.gesture is None:
            if math.dist((pos.x(), pos.y()), (self.press_at.x(), self.press_at.y())) <= ctl.tolerance(3):
                return
            self.gesture = OriginGesture(self, ctl.selection(), self.press_at)
        self.gesture.update(pos, mods)

    def release(self, pos, mods):
        ctl = self.ctl
        press, self.press_at = self.press_at, None
        if self.gesture is not None:
            gesture, self.gesture = self.gesture, None
            gesture.finish()
            ctl.remember_transform(gesture.current)
            return
        if press is None or not ctl.selection():
            return
        self.origin = QPointF(pos)                   # clic : nouvelle origine
        if mods & Qt.AltModifier:                    # Alt + clic : valeur saisie autour de ce point
            self.dialog(pos)

    def cancel(self):
        if self.gesture is not None:
            self.gesture.cancel()
            self.gesture = None
        self.press_at = None

    def busy(self) -> bool:
        return self.gesture is not None

    def cursor(self):
        return Qt.CrossCursor

    def matrix(self, start, pos, mods):
        raise NotImplementedError

    def dialog(self, origin: QPointF):
        raise NotImplementedError


class RotateTool(OriginTool):
    name, label = "rotate", "Rotation (R ; clic = origine, Alt + clic = angle)"

    def matrix(self, start, pos, mods):
        o = self.origin_point()
        deg = math.degrees(math.atan2(pos.y() - o.y(), pos.x() - o.x()) - math.atan2(start.y() - o.y(),
                                                                                      start.x() - o.x()))
        if mods & Qt.ShiftModifier:
            deg = round(deg / 45.0) * 45.0
        self.ctl.tip = (pos, f"{(deg + 180) % 360 - 180:.1f}°")
        return bz.rotate(deg, o.x(), o.y())

    def dialog(self, origin):
        angle, ok = QInputDialog.getDouble(self.ctl.pane, "Rotation", "Angle (°, sens horaire) :", 90.0, -360.0,
                                           360.0, 2)
        if ok:
            self.ctl.transform_selection(bz.rotate(angle, origin.x(), origin.y()), "Rotation")


class ScaleTool(OriginTool):
    name, label = "scale", "Mise à l'échelle (S ; clic = origine, Alt + clic = valeur)"

    def matrix(self, start, pos, mods):
        o = self.origin_point()
        dx0, dy0 = start.x() - o.x(), start.y() - o.y()
        sx = (pos.x() - o.x()) / dx0 if abs(dx0) > 1e-6 else 1.0
        sy = (pos.y() - o.y()) / dy0 if abs(dy0) > 1e-6 else 1.0
        if mods & Qt.ShiftModifier:                  # uniforme
            k = math.hypot(pos.x() - o.x(), pos.y() - o.y()) / max(1e-6, math.hypot(dx0, dy0))
            sx = sy = k
        sx = sx if abs(sx) > 1e-4 else 1e-4
        sy = sy if abs(sy) > 1e-4 else 1e-4
        self.ctl.tip = (pos, f"{sx * 100:.0f} % × {sy * 100:.0f} %")
        return bz.scale(sx, sy, o.x(), o.y())

    def dialog(self, origin):
        pct, ok = QInputDialog.getDouble(self.ctl.pane, "Mise à l'échelle", "Échelle uniforme (%) :", 100.0, 0.1,
                                         100000.0, 2)
        if ok:
            k = pct / 100.0
            self.ctl.transform_selection(bz.scale(k, k, origin.x(), origin.y()), "Mise à l'échelle")


def reflect_matrix(degrees: float, o: QPointF):
    """Symétrie par rapport à l'axe passant par `o`, d'angle `degrees` (0 = horizontal)."""
    a = math.radians(2 * degrees)
    c, s = math.cos(a), math.sin(a)
    m = (c, s, s, -c, 0.0, 0.0)
    return bz.multiply(bz.multiply(bz.translate(-o.x(), -o.y()), m), bz.translate(o.x(), o.y()))


class ReflectTool(OriginTool):
    name, label = "reflect", "Symétrie (O ; glisser = axe, Alt + clic = angle de l'axe)"

    def matrix(self, start, pos, mods):
        o = self.origin_point()
        deg = math.degrees(math.atan2(pos.y() - o.y(), pos.x() - o.x()))
        if mods & Qt.ShiftModifier:
            deg = round(deg / 45.0) * 45.0
        self.ctl.tip = (pos, f"axe {(-deg + 180) % 360 - 180:.1f}°")
        return reflect_matrix(deg, o)

    def dialog(self, origin):
        angle, ok = QInputDialog.getDouble(self.ctl.pane, "Symétrie", "Angle de l'axe (°, 90 = vertical) :", 90.0,
                                           -360.0, 360.0, 2)
        if ok:
            self.ctl.transform_selection(reflect_matrix(-angle, origin), "Symétrie")


XFORM_TOOLS = [RotateTool, ScaleTool, ReflectTool]


# ---------------------------------------------------------------- aligner et répartir
def align(ctl, how: str):
    """Aligner (panneau Alignement) : sur la boîte de la sélection ; un seul objet : sur son plan de travail."""
    items = ctl.selection()
    if not items:
        return
    groups = _units(ctl, items)
    if len(groups) == 1:
        board = ctl.current_artboard()
        if board is None:
            return
        key = board.scene_rect()
    else:
        key = ctl.selection_rect(items)
    moves = {}
    for members, r in groups:
        dx = dy = 0.0
        if how == "left":
            dx = key.left() - r.left()
        elif how == "hcenter":
            dx = key.center().x() - r.center().x()
        elif how == "right":
            dx = key.right() - r.right()
        elif how == "top":
            dy = key.top() - r.top()
        elif how == "vcenter":
            dy = key.center().y() - r.center().y()
        elif how == "bottom":
            dy = key.bottom() - r.bottom()
        for m in members:
            moves[m.item_id] = (dx, dy)
    _move(ctl, items, moves, "Aligner")


def distribute(ctl, axis: str, spacing: bool = False):
    """Répartir les centres (ou, `spacing`, les espaces) : extrêmes fixes, au moins 3 objets / groupes."""
    items = ctl.selection()
    groups = _units(ctl, items)
    if len(groups) < 3:
        return
    horizontal = axis == "h"
    groups.sort(key=lambda g: g[1].center().x() if horizontal else g[1].center().y())
    moves = {}
    if spacing:
        sizes = [g[1].width() if horizontal else g[1].height() for g in groups]
        first, last = groups[0][1], groups[-1][1]
        span = (last.right() - first.left()) if horizontal else (last.bottom() - first.top())
        gap = (span - sum(sizes)) / (len(groups) - 1)
        cursor = first.left() if horizontal else first.top()
        for (members, r), size in zip(groups, sizes):
            delta = cursor - (r.left() if horizontal else r.top())
            for m in members:
                moves[m.item_id] = (delta, 0.0) if horizontal else (0.0, delta)
            cursor += size + gap
    else:
        a = groups[0][1].center()
        b = groups[-1][1].center()
        for n, (members, r) in enumerate(groups):
            t = n / (len(groups) - 1)
            target = (a.x() + (b.x() - a.x()) * t) if horizontal else (a.y() + (b.y() - a.y()) * t)
            delta = target - (r.center().x() if horizontal else r.center().y())
            for m in members:
                moves[m.item_id] = (delta, 0.0) if horizontal else (0.0, delta)
    _move(ctl, items, moves, "Répartir")


def _units(ctl, items) -> list[tuple[list, QRectF]]:
    """Unités alignées : un groupe compte pour un (sa boîte), comme Illustrator."""
    seen, out = set(), []
    for item in items:
        group = item.data.get("group")
        if group:
            if group in seen:
                continue
            seen.add(group)
            members = [i for i in items if i.data.get("group") == group]
        else:
            members = [item]
        out.append((members, ctl.selection_rect(members)))
    return out


def _move(ctl, items, moves: dict, text: str):
    targets = [i for i in items if abs(moves.get(i.item_id, (0, 0))[0]) > 1e-9
               or abs(moves.get(i.item_id, (0, 0))[1]) > 1e-9]
    if targets:
        ctl.change(targets, lambda i: i.data.update(x=round(i.data["x"] + moves[i.item_id][0], 3),
                                                    y=round(i.data["y"] + moves[i.item_id][1], 3)), text)
