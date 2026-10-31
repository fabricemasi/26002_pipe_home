"""Outils du module Illustrator : base commune, gestes partagés (déplacer, transformer, cadre de sélection),
Sélection et Sélection directe ; les outils de dessin sont dans `tools_draw.py` (un objet par outil : press / drag /
release / hover / clés / curseur).

Raccourcis d'Illustrator (sources et degré de vérification : `docs/agents/fm_illustrator.md`) : V Sélection,
A Sélection directe, P Plume, + / - ajout / suppression de point, Maj+C Conversion de point, M Rectangle,
L Ellipse, \\ Segment de droite, N Crayon, Maj+O Plan de travail, H Main, Z Zoom, I Pipette ; Polygone et Étoile
n'ont pas de lettre dans Illustrator (Y y est la Baguette magique : laissée libre).

Règle de l'appli : déplacer des ÉLÉMENTS = Ctrl + glisser ; les gestes de géométrie (poignées, points) sans Ctrl."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt

from PySide6.QtGui import QTransform
from PySide6.QtWidgets import QGraphicsItem

from . import bezier as bz
from .items import IllItem, notify_moved

HANDLE_PX = 4.5                 # demi-côté des poignées de la boîte englobante (pixels d'écran)
ANCHOR_PX = 5.0                 # tolérance des points d'ancrage et poignées de Bézier
ROTATE_PX = 18.0                # zone de rotation : juste à l'extérieur d'un coin
DRAG_PX = 3.0                   # au-delà : c'est un glisser, pas un clic

TOOL_KEYS = {(Qt.Key_V, False): "select", (Qt.Key_A, False): "direct", (Qt.Key_P, False): "pen",
             (Qt.Key_Plus, False): "add_anchor", (Qt.Key_Equal, False): "add_anchor",
             (Qt.Key_Plus, True): "add_anchor", (Qt.Key_Minus, False): "delete_anchor",
             (Qt.Key_C, True): "convert", (Qt.Key_M, False): "rect", (Qt.Key_L, False): "ellipse",
             (Qt.Key_Backslash, False): "line",
             (Qt.Key_N, False): "pencil", (Qt.Key_O, True): "artboard", (Qt.Key_H, False): "hand",
             (Qt.Key_Z, False): "zoom", (Qt.Key_I, False): "eyedropper"}


def _constrain45(origin: QPointF, pos: QPointF) -> QPointF:
    dx, dy = pos.x() - origin.x(), pos.y() - origin.y()
    a = round(math.atan2(dy, dx) / (math.pi / 4)) * (math.pi / 4)
    d = math.hypot(dx, dy)
    return QPointF(origin.x() + d * math.cos(a), origin.y() + d * math.sin(a))


def box_handles(rect: QRectF) -> dict[str, QPointF]:
    c = rect.center()
    return {"tl": rect.topLeft(), "t": QPointF(c.x(), rect.top()), "tr": rect.topRight(),
            "r": QPointF(rect.right(), c.y()), "br": rect.bottomRight(), "b": QPointF(c.x(), rect.bottom()),
            "bl": rect.bottomLeft(), "l": QPointF(rect.left(), c.y())}


OPPOSITE = {"tl": "br", "t": "b", "tr": "bl", "r": "l", "br": "tl", "b": "t", "bl": "tr", "l": "r"}
RESIZE_CURSORS = {"tl": Qt.SizeFDiagCursor, "br": Qt.SizeFDiagCursor, "tr": Qt.SizeBDiagCursor,
                  "bl": Qt.SizeBDiagCursor, "l": Qt.SizeHorCursor, "r": Qt.SizeHorCursor, "t": Qt.SizeVerCursor,
                  "b": Qt.SizeVerCursor}


class Tool:
    name = ""
    label = ""

    def __init__(self, ctl):
        self.ctl = ctl

    def press(self, pos: QPointF, mods): pass

    def drag(self, pos: QPointF, mods): pass

    def release(self, pos: QPointF, mods): pass

    def hover(self, pos: QPointF, mods): pass

    def double_click(self, pos: QPointF, mods) -> bool:
        return False

    def key_press(self, key, mods) -> bool:
        return False

    def key_release(self, key, mods) -> bool:
        return False

    def cancel(self): pass

    def busy(self) -> bool:
        """Un geste ou un tracé est en cours (Échap l'annule ou le termine)."""
        return any(getattr(self, name, None) is not None for name in ("gesture", "item", "mode", "points"))

    def cursor(self):
        return Qt.CrossCursor


# ---------------------------------------------------------------- gestes partagés
class MoveGesture:
    """Ctrl + glisser : déplace les objets choisis (Ctrl + Alt : une copie). Une étape d'annulation."""

    def __init__(self, ctl, items, start: QPointF, copy: bool):
        self.ctl = ctl
        scene = ctl.scene
        if copy:
            dicts = [i.to_dict() for i in items]
            from fm_board import model as board_model
            groups = {}
            for d in dicts:
                d["id"] = board_model.new_id()
                if d.get("group"):
                    d["group"] = groups.setdefault(d["group"], board_model.new_id())
            items = scene.replace_items([], dicts, "Déplacer une copie")
            ctl.select(items)                   # la copie est une étape, le déplacement une autre
        self.items = items
        self.start = start
        self.origins = [QPointF(i.pos()) for i in items]
        scene.begin_change(items)
        self.text = "Déplacer"

    def update(self, pos: QPointF, mods):
        d = pos - self.start
        if mods & Qt.ShiftModifier:                             # Maj : horizontal, vertical ou 45°
            d = _constrain45(QPointF(0, 0), d)
        IllItem.quiet_moves = True
        try:
            for item, origin in zip(self.items, self.origins):
                item.setPos(origin + d)
        finally:
            IllItem.quiet_moves = False
        self.ctl.tip = (pos, f"dX {d.x():.1f}  dY {d.y():.1f}")

    def finish(self):
        for item in self.items:
            item.data["x"], item.data["y"] = round(item.pos().x(), 3), round(item.pos().y(), 3)
        notify_moved(self.ctl.scene, self.items)
        self.ctl.scene.end_change(self.text)
        self.ctl.tip = None

    def cancel(self):
        IllItem.quiet_moves = True
        try:
            for item, origin in zip(self.items, self.origins):
                item.setPos(origin)
        finally:
            IllItem.quiet_moves = False
        self.ctl.scene.end_change(self.text)
        self.ctl.tip = None


class TransformGesture:
    """Poignées de la boîte englobante (mise à l'échelle) ou rotation : la matrice est appliquée aux nœuds gardés au
    départ (aucune dérive). Maj = proportions (échelle) / pas de 45° (rotation) ; Alt = depuis le centre."""

    def __init__(self, ctl, items, rect: QRectF, handle: str, start: QPointF):
        self.ctl = ctl
        self.items = items
        self.rect = QRectF(rect)
        self.handle = handle
        self.start = start
        self.current = bz.IDENTITY
        ctl.scene.begin_change(items)
        # Pendant le geste, chaque élément change de forme à chaque image : son image gardée serait refaite à
        # chaque fois (plus cher que le peindre) ; rendue au relâché.
        for item in items:
            item.setCacheMode(QGraphicsItem.NoCache)

    def matrix(self, pos: QPointF, mods):
        r = self.rect
        if self.handle == "rotate":
            c = r.center()
            a0 = math.atan2(self.start.y() - c.y(), self.start.x() - c.x())
            a1 = math.atan2(pos.y() - c.y(), pos.x() - c.x())
            deg = math.degrees(a1 - a0)
            if mods & Qt.ShiftModifier:
                deg = round(deg / 45.0) * 45.0
            self.ctl.tip = (pos, f"{(deg + 180) % 360 - 180:.1f}°")
            return bz.rotate(deg, c.x(), c.y())
        h = self.handle
        alt = bool(mods & Qt.AltModifier)
        fixed = r.center() if alt else box_handles(r)[OPPOSITE[h]]
        moving = box_handles(r)[h]
        sx = sy = 1.0
        if h in ("l", "r", "tl", "tr", "bl", "br"):
            den = moving.x() - fixed.x()
            sx = (pos.x() - fixed.x()) / den if abs(den) > 1e-9 else 1.0
        if h in ("t", "b", "tl", "tr", "bl", "br"):
            den = moving.y() - fixed.y()
            sy = (pos.y() - fixed.y()) / den if abs(den) > 1e-9 else 1.0
        if mods & Qt.ShiftModifier:                         # proportions gardées
            if h in ("l", "r"):
                sy = abs(sx) * (1 if sy >= 0 else -1)
            elif h in ("t", "b"):
                sx = abs(sy) * (1 if sx >= 0 else -1)
            else:
                k = max(abs(sx), abs(sy))
                sx, sy = math.copysign(k, sx), math.copysign(k, sy)
        sx = sx if abs(sx) > 1e-4 else 1e-4
        sy = sy if abs(sy) > 1e-4 else 1e-4
        self.ctl.tip = (pos, f"L {abs(r.width() * sx):.1f}  H {abs(r.height() * sy):.1f}")
        return bz.scale(sx, sy, fixed.x(), fixed.y())

    @staticmethod
    def local(item, m):
        px, py = item.data["x"], item.data["y"]
        return bz.multiply(bz.multiply(bz.translate(px, py), m), bz.translate(-px, -py))

    def update(self, pos: QPointF, mods):
        """Pendant le geste, la matrice est posée sur chaque élément (`QTransform` : aucun nœud recalculé) ; les
        nœuds ne sont transformés qu'au relâché. (Le contour paraît mis à l'échelle pendant le geste ; à la fin il
        garde son épaisseur, comme Illustrator par défaut.)"""
        self.current = self.matrix(pos, mods)
        IllItem.quiet_moves = True
        try:
            for item in self.items:
                item.setTransform(QTransform(*self.local(item, self.current)))
        finally:
            IllItem.quiet_moves = False

    def finish(self):
        for item in self.items:
            item.resetTransform()
            item.setCacheMode(QGraphicsItem.DeviceCoordinateCache)
            bz.transform(item.data["subpaths"], self.local(item, self.current))
            item.prepareGeometryChange()
            item.sync()
            item.update()
        notify_moved(self.ctl.scene, self.items)
        self.ctl.scene.end_change("Rotation" if self.handle == "rotate" else "Mise à l'échelle")
        self.ctl.tip = None

    def cancel(self):
        for item in self.items:
            item.resetTransform()
            item.setCacheMode(QGraphicsItem.DeviceCoordinateCache)
        self.ctl.scene.end_change("Mise à l'échelle")
        self.ctl.tip = None


def handle_at(ctl, pos: QPointF) -> str | None:
    """Poignée de la boîte englobante sous `pos` : « tl »… ; « rotate » juste à l'extérieur d'un coin."""
    rect = ctl.selection_rect()
    if rect is None or not ctl.selection():
        return None
    t = ctl.tolerance(HANDLE_PX + 2)
    for name, p in box_handles(rect).items():
        if abs(pos.x() - p.x()) <= t and abs(pos.y() - p.y()) <= t:
            return name
    r = ctl.tolerance(ROTATE_PX)
    for name in ("tl", "tr", "bl", "br"):
        p = box_handles(rect)[name]
        if math.hypot(pos.x() - p.x(), pos.y() - p.y()) <= r and not rect.contains(pos):
            return "rotate"
    return None


def marquee_select(ctl, rect: QRectF, mods, anchors: bool = False):
    """Cadre de sélection : les objets qu'il TOUCHE (comme Illustrator) ; `anchors` = les points qu'il contient."""
    found = []
    for item in ctl.scene.items(rect, Qt.IntersectsItemBoundingRect):
        if not ctl.editable(item) or not hasattr(item, "geometry_rect"):
            continue
        local = rect.translated(-item.pos())
        if not item.path.intersects(local) and not item.hit_path(0.5).intersects(local):
            continue
        found.append(item)
    add = bool(mods & Qt.ShiftModifier)
    if anchors:
        if not add:
            ctl.anchors.clear()
        for item in found:
            chosen = ctl.anchors.setdefault(item.item_id, set())
            for si, sub in enumerate(item.data["subpaths"]):
                for ni, n in enumerate(sub["nodes"]):
                    if rect.contains(QPointF(n[0] + item.data["x"], n[1] + item.data["y"])):
                        chosen.add((si, ni))
        ctl.select(found, add=add)
        return
    members = []
    for item in found:
        for m in ctl.group_of(item):
            if m not in members:
                members.append(m)
    ctl.select(members, add=add)


# ---------------------------------------------------------------- Sélection (V)
class SelectTool(Tool):
    name, label = "select", "Sélection (V)"

    def __init__(self, ctl):
        super().__init__(ctl)
        self.gesture = None
        self.press_at = None
        self.pressed_item = None
        self.marquee_from = None
        self._cursor = Qt.ArrowCursor

    def press(self, pos, mods):
        ctl = self.ctl
        self.press_at = pos
        self.pressed_item = None
        self.marquee_from = None
        handle = handle_at(ctl, pos)
        if handle is not None:
            self.gesture = TransformGesture(ctl, ctl.selection(), ctl.selection_rect(), handle, pos)
            return
        item = ctl.object_at(pos)
        ctrl = bool(mods & Qt.ControlModifier)
        if item is not None:
            group = ctl.group_of(item)
            if mods & Qt.ShiftModifier:
                ctl.select(group, toggle=True)
            elif not item.isSelected():
                ctl.select(group)
            if ctrl and item.isSelected():
                self.pressed_item = item
            elif not ctrl:
                self.marquee_from = pos                 # glisser sans Ctrl depuis un objet : cadre de sélection
            return
        rect = ctl.selection_rect()
        if ctrl and rect is not None and rect.contains(pos):
            self.pressed_item = ctl.selection()[0]
            return
        if not (mods & Qt.ShiftModifier):
            ctl.clear_selection()
        self.marquee_from = pos

    def drag(self, pos, mods):
        ctl = self.ctl
        if self.gesture is not None:
            self.gesture.update(pos, mods)
            return
        if self.press_at is None:
            return
        far = math.dist((pos.x(), pos.y()), (self.press_at.x(), self.press_at.y())) > ctl.tolerance(DRAG_PX)
        if self.pressed_item is not None and far:
            copy = bool(mods & Qt.AltModifier)
            self.gesture = MoveGesture(ctl, ctl.selection(), self.press_at, copy)
            self.gesture.update(pos, mods)
            return
        if self.marquee_from is not None and far:
            ctl.marquee = QRectF(self.marquee_from, pos).normalized()

    def release(self, pos, mods):
        ctl = self.ctl
        if self.gesture is not None:
            self.gesture.finish()
            self.gesture = None
        elif ctl.marquee is not None:
            marquee_select(ctl, ctl.marquee, mods)
        ctl.marquee = None
        self.press_at = None
        self.pressed_item = None
        self.marquee_from = None

    def hover(self, pos, mods):
        ctl = self.ctl
        handle = handle_at(ctl, pos)
        item = ctl.object_at(pos)
        ctl.hover = item
        if handle == "rotate":
            cursor = Qt.CrossCursor
        elif handle is not None:
            cursor = RESIZE_CURSORS[handle]
        elif item is not None and mods & Qt.ControlModifier:
            cursor = Qt.SizeAllCursor
        else:
            cursor = Qt.ArrowCursor
        if cursor != self._cursor:
            self._cursor = cursor
            ctl.sync_cursor()

    def double_click(self, pos, mods) -> bool:
        """Double-clic sur un objet : Sélection directe de ses points (comme entrer dans le tracé)."""
        item = self.ctl.object_at(pos)
        if item is None:
            return False
        self.ctl.set_tool("direct")
        self.ctl.select([item])
        return True

    def key_press(self, key, mods) -> bool:
        if key == Qt.Key_Escape and self.gesture is not None:
            self.gesture.cancel()
            self.gesture = None
            return True
        return False

    def cancel(self):
        if self.gesture is not None:
            self.gesture.cancel()
            self.gesture = None
        self.ctl.marquee = None

    def cursor(self):
        return self._cursor


# ---------------------------------------------------------------- Sélection directe (A)
def anchor_at(ctl, pos: QPointF, items=None) -> tuple | None:
    """(objet, sous-tracé, nœud) du point d'ancrage sous `pos`."""
    t = ctl.tolerance(ANCHOR_PX)
    candidates = items if items is not None else _near_objects(ctl, pos)
    for item in reversed(candidates):
        ox, oy = item.data["x"], item.data["y"]
        for si, sub in enumerate(item.data["subpaths"]):
            for ni, n in enumerate(sub["nodes"]):
                if abs(n[0] + ox - pos.x()) <= t and abs(n[1] + oy - pos.y()) <= t:
                    return item, si, ni
    return None


def bezier_handle_at(ctl, pos: QPointF) -> tuple | None:
    """(objet, sous-tracé, nœud, « in » / « out ») d'une poignée visible (points choisis et leurs voisins)."""
    t = ctl.tolerance(ANCHOR_PX)
    for item, si, ni, which in visible_handles(ctl):
        n = item.data["subpaths"][si]["nodes"][ni]
        k = 2 if which == "in" else 4
        if abs(n[k] + item.data["x"] - pos.x()) <= t and abs(n[k + 1] + item.data["y"] - pos.y()) <= t:
            return item, si, ni, which
    return None


def visible_handles(ctl) -> list[tuple]:
    """Poignées montrées en Sélection directe : celles des points choisis et des extrémités de leurs segments."""
    out = []
    for item in ctl.selection():
        chosen = ctl.anchors.get(item.item_id)
        if not chosen:
            continue
        subs = item.data["subpaths"]
        shown = set()
        for si, ni in chosen:
            if si >= len(subs):
                continue
            count = len(subs[si]["nodes"])
            closed = subs[si]["closed"]
            shown.add((si, ni, "in"))
            shown.add((si, ni, "out"))
            if ni > 0 or closed:
                shown.add((si, (ni - 1) % count, "out"))
            if ni < count - 1 or closed:
                shown.add((si, (ni + 1) % count, "in"))
        for si, ni, which in sorted(shown):
            if ni >= len(subs[si]["nodes"]):
                continue
            n = subs[si]["nodes"][ni]
            if (bz.has_in(n) if which == "in" else bz.has_out(n)):
                out.append((item, si, ni, which))
    return out


def _near_objects(ctl, pos: QPointF) -> list:
    t = ctl.tolerance(ANCHOR_PX + 2)
    found = [i for i in ctl.scene.items(QRectF(pos.x() - t, pos.y() - t, 2 * t, 2 * t),
                                        Qt.IntersectsItemBoundingRect, Qt.AscendingOrder)
             if hasattr(i, "geometry_rect") and ctl.editable(i)]
    return found


def segment_at(ctl, pos: QPointF, item) -> tuple | None:
    """(distance, sous-tracé, segment, t) du segment de `item` le plus proche, à la tolérance près."""
    local = (pos.x() - item.data["x"], pos.y() - item.data["y"])
    best = bz.nearest(item.data["subpaths"], local)
    if best is None or best[0] > ctl.tolerance(ANCHOR_PX):
        return None
    return best[0], best[1], best[2], best[3]


class NodeDrag:
    """Glisser des points d'ancrage choisis (avec leurs poignées), d'une poignée, ou d'un segment courbe."""

    def __init__(self, ctl, start: QPointF, mode: str, target=None):
        self.ctl = ctl
        self.start = start
        self.mode = mode                        # « anchors », « handle », « segment »
        self.target = target
        if mode == "anchors":
            self.items = [i for i in ctl.selection() if ctl.anchors.get(i.item_id)]
        else:
            self.items = [target[0]]
        self.original = {i.item_id: bz.copy_subpaths(i.data["subpaths"]) for i in self.items}
        ctl.scene.begin_change(self.items)

    def update(self, pos: QPointF, mods):
        d = pos - self.start
        for item in self.items:
            subs = bz.copy_subpaths(self.original[item.item_id])
            if self.mode == "anchors":
                if mods & Qt.ShiftModifier:
                    d = _constrain45(QPointF(0, 0), d)
                for si, ni in self.ctl.anchors.get(item.item_id, ()):
                    bz.move_node(subs[si]["nodes"][ni], d.x(), d.y())
            elif self.mode == "handle":
                _item, si, ni, which = self.target
                n = subs[si]["nodes"][ni]
                k = 2 if which == "in" else 4
                bz.set_handle(n, which, n[k] + d.x(), n[k + 1] + d.y(), break_link=bool(mods & Qt.AltModifier))
            else:                                               # segment : le tirer au point saisi (courbe)
                _item, si, gi, t = self.target
                sub = subs[si]
                a = sub["nodes"][gi]
                b = sub["nodes"][(gi + 1) % len(sub["nodes"])]
                if bz.is_straight(bz.segment(sub, gi)):
                    bz.move_node(a, d.x(), d.y())
                    bz.move_node(b, d.x(), d.y())
                else:
                    # déplacer le point à t de d : poignées déplacées proportionnellement à leur influence
                    w1 = 3 * (1 - t) ** 2 * t
                    w2 = 3 * (1 - t) * t * t
                    den = w1 * w1 + w2 * w2 or 1.0
                    k1, k2 = w1 / den, w2 / den
                    a[4] += d.x() * k1
                    a[5] += d.y() * k1
                    b[2] += d.x() * k2
                    b[3] += d.y() * k2
                    a[6] = b[6] = 0                             # la courbe tirée casse l'alignement
            item.data["subpaths"] = subs
            item.prepareGeometryChange()
            item.sync()
            item.update()

    def finish(self):
        self.ctl.scene.end_change({"anchors": "Déplacer des points", "handle": "Poignée",
                                   "segment": "Modifier un segment"}[self.mode])

    def cancel(self):
        for item in self.items:
            item.data["subpaths"] = self.original[item.item_id]
            item.prepareGeometryChange()
            item.sync()
            item.update()
        self.ctl.scene.end_change("Annuler")


class DirectTool(Tool):
    name, label = "direct", "Sélection directe (A)"

    def __init__(self, ctl):
        super().__init__(ctl)
        self.gesture = None
        self.pending = None
        self.press_at = None
        self.marquee_from = None

    def press(self, pos, mods):
        ctl = self.ctl
        self.press_at = pos
        self.pending = None
        self.marquee_from = None
        shift = bool(mods & Qt.ShiftModifier)
        hit = bezier_handle_at(ctl, pos)
        if hit is not None:
            self.pending = ("handle", hit)
            return
        hit = anchor_at(ctl, pos)
        if hit is not None:
            item, si, ni = hit
            chosen = ctl.anchors.setdefault(item.item_id, set())
            if shift:
                chosen.symmetric_difference_update({(si, ni)})
                item.setSelected(True)
            elif (si, ni) not in chosen:
                ctl.anchors.clear()
                ctl.anchors[item.item_id] = {(si, ni)}
                ctl.select([item])
            self.pending = ("anchors", None)
            ctl.stateChanged.emit()
            return
        item = ctl.object_at(pos)
        if item is not None:
            seg = segment_at(ctl, pos, item)
            if not shift and not item.isSelected():
                ctl.anchors.clear()
                ctl.select([item])
            elif shift:
                item.setSelected(True)
            if mods & Qt.ControlModifier:                       # Ctrl + glisser : déplacer l'objet entier
                self.pending = ("move", item)
            elif seg is not None:
                self.pending = ("segment", (item, seg[1], seg[2], seg[3]))
            return
        if not shift:
            ctl.clear_selection()
        self.marquee_from = pos

    def drag(self, pos, mods):
        ctl = self.ctl
        if self.gesture is not None:
            self.gesture.update(pos, mods)
            return
        if self.press_at is None:
            return
        if math.dist((pos.x(), pos.y()), (self.press_at.x(), self.press_at.y())) <= ctl.tolerance(DRAG_PX):
            return
        if self.pending is not None:
            mode, target = self.pending
            if mode == "move":
                self.gesture = MoveGesture(ctl, ctl.selection(), self.press_at, bool(mods & Qt.AltModifier))
            else:
                self.gesture = NodeDrag(ctl, self.press_at, mode, target)
            self.gesture.update(pos, mods)
            return
        if self.marquee_from is not None:
            ctl.marquee = QRectF(self.marquee_from, pos).normalized()

    def release(self, pos, mods):
        ctl = self.ctl
        if self.gesture is not None:
            self.gesture.finish()
            self.gesture = None
        elif ctl.marquee is not None:
            marquee_select(ctl, ctl.marquee, mods, anchors=True)
        ctl.marquee = None
        self.press_at = None
        self.pending = None
        self.marquee_from = None

    def hover(self, pos, mods):
        self.ctl.hover = self.ctl.object_at(pos)

    def key_press(self, key, mods) -> bool:
        if key == Qt.Key_Escape and self.gesture is not None:
            self.gesture.cancel()
            self.gesture = None
            return True
        return False

    def cancel(self):
        if self.gesture is not None:
            self.gesture.cancel()
            self.gesture = None
        self.ctl.marquee = None

    def cursor(self):
        return Qt.ArrowCursor
