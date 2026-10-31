"""Outils de DESSIN du module Illustrator : Plume, ajout / suppression / conversion de points, Rectangle, Ellipse,
Polygone, Étoile, Segment de droite, Crayon, Plan de travail, Main, Zoom, Pipette. Outils de sélection et gestes
partagés : `tools.py`."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QCursor

from . import bezier as bz, model
from .tools import (ANCHOR_PX, DRAG_PX, HANDLE_PX, DirectTool, SelectTool, Tool, _constrain45, _near_objects,
                    anchor_at, bezier_handle_at, box_handles, segment_at)


# ---------------------------------------------------------------- Plume (P)
class PenTool(Tool):
    """Clic = point d'angle ; cliquer-glisser = point lisse (poignées symétriques ; Alt = casser la poignée) ;
    Maj = 45° ; clic sur le premier point = fermer ; Entrée / Échap / Ctrl + clic dans le vide = terminer ouvert ;
    Ctrl+Z pendant le tracé = retirer le dernier point. Sur un tracé choisi : survol d'un segment = ajouter un point,
    d'un point = le supprimer ; clic sur l'extrémité d'un tracé ouvert = le continuer."""
    name, label = "pen", "Plume (P)"

    def __init__(self, ctl):
        super().__init__(ctl)
        self.item = None                    # tracé en cours
        self.sub = None                     # indice du sous-tracé prolongé
        self.before = None                  # état avant (tracé continué) ; None = tracé neuf
        self.dragging = False
        self.closing = False
        self.cursor_pos = None
        self.hover_mode = "draw"            # survol : « draw », « add », « delete », « continue », « close »

    # -- état --
    def nodes(self) -> list:
        return self.item.data["subpaths"][self.sub]["nodes"]

    def _local(self, pos: QPointF) -> tuple[float, float]:
        return pos.x() - self.item.data["x"], pos.y() - self.item.data["y"]

    def _refresh_item(self):
        self.item.prepareGeometryChange()
        self.item.sync()
        self.item.update()

    def press(self, pos, mods):
        ctl = self.ctl
        self.dragging = True
        if self.item is None:
            if self._edit_existing(pos):
                self.dragging = False
                return
            hit = self._open_end_at(pos)
            if hit is not None:                             # continuer un tracé ouvert
                item, si, at_start = hit
                self.item, self.sub = item, si
                ctl.scene.begin_change([item])
                if at_start:
                    bz.reverse(item.data["subpaths"][si])
                    self._refresh_item()
                self.before = True
                self.dragging = False
                return
            self.item = ctl.new_path([{"closed": False, "nodes": [bz.node(0.0, 0.0)]}], pos)
            self.sub = 0
            self.before = None
            return
        nodes = self.nodes()
        if mods & Qt.ControlModifier and self.ctl.object_at(pos) is None:
            self.finish()
            self.dragging = False
            return
        first = nodes[0]
        t = ctl.tolerance(ANCHOR_PX + 1)
        lx, ly = self._local(pos)
        if len(nodes) > 1 and abs(first[0] - lx) <= t and abs(first[1] - ly) <= t:
            self.item.data["subpaths"][self.sub]["closed"] = True
            self.closing = True
            self._refresh_item()
            return
        last = nodes[-1]
        if abs(last[0] - lx) <= t and abs(last[1] - ly) <= t:   # clic sur le dernier point : poignée de sortie retirée
            bz.retract(last, "out")
            self._refresh_item()
            self.dragging = False
            return
        if mods & Qt.ShiftModifier:
            p = _constrain45(QPointF(last[0], last[1]), QPointF(lx, ly))
            lx, ly = p.x(), p.y()
        nodes.append(bz.node(lx, ly))
        self._refresh_item()

    def drag(self, pos, mods):
        if self.item is None or not self.dragging:
            return
        self.cursor_pos = pos
        node = self.nodes()[0] if self.closing else self.nodes()[-1]
        lx, ly = self._local(pos)
        if mods & Qt.ShiftModifier:
            p = _constrain45(QPointF(node[0], node[1]), QPointF(lx, ly))
            lx, ly = p.x(), p.y()
        if math.hypot(lx - node[0], ly - node[1]) < self.ctl.tolerance(1.0):
            return
        if mods & Qt.AltModifier:                           # Alt : seule la poignée de sortie suit (point d'angle)
            node[4], node[5] = lx, ly
            node[6] = 0
        elif self.closing:                                  # fermeture : l'entrée suit la direction du geste
            node[2], node[3] = 2 * node[0] - lx, 2 * node[1] - ly
            if bz.has_out(node):
                bz.set_handle(node, "in", node[2], node[3])
            node[6] = 1
        else:
            bz.set_symmetric(node, lx, ly)
        self._refresh_item()

    def release(self, pos, mods):
        self.dragging = False
        if self.closing:
            self.closing = False
            self.finish()

    def hover(self, pos, mods):
        self.cursor_pos = pos
        mode = "draw"
        if self.item is None:
            if self._target_on_selection(pos, "delete") is not None:
                mode = "delete"
            elif self._target_on_selection(pos, "add") is not None:
                mode = "add"
            elif self._open_end_at(pos) is not None:
                mode = "continue"
        else:
            first = self.nodes()[0]
            lx, ly = self._local(pos)
            t = self.ctl.tolerance(ANCHOR_PX + 1)
            if len(self.nodes()) > 1 and abs(first[0] - lx) <= t and abs(first[1] - ly) <= t:
                mode = "close"
        if mode != self.hover_mode:
            self.hover_mode = mode
            self.ctl.sync_cursor()
        self._update_preview(pos, mods)

    def _update_preview(self, pos, mods):
        """Ligne élastique : du dernier point au curseur, avec la poignée de sortie (aperçu du prochain segment)."""
        if self.item is None:
            self.ctl.preview = None
            return
        last = self.nodes()[-1]
        ox, oy = self.item.data["x"], self.item.data["y"]
        target = pos
        if mods & Qt.ShiftModifier:
            target = _constrain45(QPointF(last[0] + ox, last[1] + oy), pos)
        self.ctl.preview = ("rubber", (last[0] + ox, last[1] + oy), (last[4] + ox, last[5] + oy),
                            (target.x(), target.y()))

    def _target_on_selection(self, pos, what: str):
        for item in self.ctl.selection():
            if what == "delete":
                hit = anchor_at(self.ctl, pos, [item])
                if hit is not None:
                    return hit
            else:
                seg = segment_at(self.ctl, pos, item)
                if seg is not None:
                    return item, seg
        return None

    def _edit_existing(self, pos) -> bool:
        hit = self._target_on_selection(pos, "delete")
        if hit is not None:
            delete_anchor(self.ctl, *hit)
            return True
        hit = self._target_on_selection(pos, "add")
        if hit is not None:
            item, (_d, si, gi, t) = hit
            add_anchor(self.ctl, item, si, gi, t)
            return True
        return False

    def _open_end_at(self, pos):
        t = self.ctl.tolerance(ANCHOR_PX + 1)
        for item in reversed(self.ctl.selection() or _near_objects(self.ctl, pos)):
            ox, oy = item.data["x"], item.data["y"]
            for si, sub in enumerate(item.data["subpaths"]):
                if sub["closed"] or len(sub["nodes"]) < 1:
                    continue
                for at_start, n in ((False, sub["nodes"][-1]), (True, sub["nodes"][0])):
                    if abs(n[0] + ox - pos.x()) <= t and abs(n[1] + oy - pos.y()) <= t:
                        return item, si, at_start
        return None

    def finish(self):
        item, self.item = self.item, None
        self.ctl.preview = None
        self.closing = False
        if item is None:
            return
        subs = item.data["subpaths"]
        sub = subs[self.sub]
        if len(sub["nodes"]) < 2:
            if self.before is None:
                self.ctl.discard(item)
                return
        if self.before is None:
            self.ctl.commit_new(item, "Plume")
        else:
            self.ctl.scene.end_change("Plume")
            self.ctl.select([item])

    def key_press(self, key, mods) -> bool:
        if self.item is None:
            return False
        if key in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Escape):
            self.finish()
            return True
        if key == Qt.Key_Z and mods & Qt.ControlModifier:
            nodes = self.nodes()
            if len(nodes) > 1:
                nodes.pop()
                self._refresh_item()
            else:
                self.cancel()
            return True
        return False

    def cancel(self):
        if self.item is not None:
            self.finish()

    def cursor(self):
        return {"add": Qt.UpArrowCursor, "delete": Qt.ForbiddenCursor, "close": Qt.PointingHandCursor,
                "continue": Qt.PointingHandCursor}.get(self.hover_mode, Qt.CrossCursor)


def add_anchor(ctl, item, si: int, gi: int, t: float):
    ctl.change([item], lambda i: bz.insert_node(i.data["subpaths"][si], gi, t), "Ajouter un point")


def delete_anchor(ctl, item, si: int, ni: int):
    """Outil Suppression de point : le tracé reste continu (les voisins se rejoignent)."""
    empty = []

    def remove(i):
        sub = i.data["subpaths"][si]
        bz.delete_node(sub, ni)
        if len(sub["nodes"]) < 2:
            del i.data["subpaths"][si]
        if not i.data["subpaths"]:
            empty.append(i)
    ctl.change([item], remove, "Supprimer un point")
    ctl.anchors.pop(item.item_id, None)
    if empty:
        ctl.scene.delete_items(empty)


class AddAnchorTool(Tool):
    name, label = "add_anchor", "Ajout de point d'ancrage (+)"

    def press(self, pos, mods):
        item = self.ctl.object_at(pos)
        if item is None:
            return
        seg = segment_at(self.ctl, pos, item)
        if seg is not None:
            add_anchor(self.ctl, item, seg[1], seg[2], seg[3])
            self.ctl.select([item])

    def cursor(self):
        return Qt.UpArrowCursor


class DeleteAnchorTool(Tool):
    name, label = "delete_anchor", "Suppression de point d'ancrage (-)"

    def press(self, pos, mods):
        hit = anchor_at(self.ctl, pos)
        if hit is not None:
            delete_anchor(self.ctl, *hit)

    def cursor(self):
        return Qt.ForbiddenCursor


class ConvertTool(Tool):
    """Clic sur un point : lisse <-> angle ; glisser depuis un point = nouvelles poignées symétriques ; glisser une
    poignée = la déplacer seule (point d'angle)."""
    name, label = "convert", "Conversion de point d'ancrage (Maj+C)"

    def __init__(self, ctl):
        super().__init__(ctl)
        self.target = None
        self.moved = False

    def press(self, pos, mods):
        ctl = self.ctl
        self.moved = False
        hit = bezier_handle_at(ctl, pos)
        if hit is not None:
            self.target = ("handle", hit)
            ctl.scene.begin_change([hit[0]])
            return
        hit = anchor_at(ctl, pos)
        if hit is not None:
            self.target = ("anchor", hit)
            ctl.scene.begin_change([hit[0]])
            ctl.select([hit[0]])
            ctl.anchors[hit[0].item_id] = {(hit[1], hit[2])}

    def drag(self, pos, mods):
        if self.target is None:
            return
        kind, hit = self.target
        item = hit[0]
        lx, ly = pos.x() - item.data["x"], pos.y() - item.data["y"]
        n = item.data["subpaths"][hit[1]]["nodes"][hit[2]]
        if kind == "handle":
            bz.set_handle(n, hit[3], lx, ly, break_link=True)
        else:
            bz.set_symmetric(n, lx, ly)
        self.moved = True
        item.prepareGeometryChange()
        item.sync()
        item.update()

    def release(self, pos, mods):
        if self.target is None:
            return
        kind, hit = self.target
        item = hit[0]
        if kind == "anchor" and not self.moved:
            sub = item.data["subpaths"][hit[1]]
            n = sub["nodes"][hit[2]]
            if bz.has_in(n) or bz.has_out(n):
                bz.retract(n)
            else:
                bz.smooth_node(sub, hit[2])
            item.prepareGeometryChange()
            item.sync()
            item.update()
        self.ctl.scene.end_change("Convertir le point")
        self.target = None

    def cancel(self):
        if self.target is not None:
            self.ctl.scene.end_change("Convertir le point")
            self.target = None

    def cursor(self):
        return Qt.PointingHandCursor


# ---------------------------------------------------------------- formes
def place_origin(subs):
    """Géométrie en coordonnées de scène -> origine de l'élément = coin haut gauche de sa boîte."""
    box = bz.bounds(subs) or (0, 0, 0, 0)
    bz.transform(subs, bz.translate(-box[0], -box[1]))
    return subs, QPointF(box[0], box[1])


class ShapeTool(Tool):
    """Glisser = forme (Maj : carré / cercle / proportions ; Alt : depuis le centre) ; clic = forme de 100 unités
    centrée. Polygone / Étoile : flèches haut / bas pendant le geste = côtés / branches."""
    shape = "rect"

    def __init__(self, ctl):
        super().__init__(ctl)
        self.start = None
        self.item = None
        self.sides = 6 if self.shape == "polygon" else 5

    def press(self, pos, mods):
        self.start = pos
        self.item = None

    def geometry(self, a: QPointF, b: QPointF, mods) -> list:
        shape = self.shape
        if shape == "line":
            if mods & Qt.ShiftModifier:
                b = _constrain45(a, b)
            return bz.line(a.x(), a.y(), b.x(), b.y())
        if shape in ("polygon", "star"):
            r = math.hypot(b.x() - a.x(), b.y() - a.y())
            rot = 0.0 if mods & Qt.ShiftModifier else math.degrees(math.atan2(b.y() - a.y(), b.x() - a.x())) + 90
            if shape == "polygon":
                return bz.polygon(a.x(), a.y(), r, self.sides, rot)
            return bz.star(a.x(), a.y(), r, r * 0.5, self.sides, rot)
        dx, dy = b.x() - a.x(), b.y() - a.y()
        if mods & Qt.ShiftModifier:
            d = max(abs(dx), abs(dy))
            dx, dy = math.copysign(d, dx or 1), math.copysign(d, dy or 1)
        if mods & Qt.AltModifier:
            x0, y0, w, h = a.x() - dx, a.y() - dy, 2 * dx, 2 * dy
        else:
            x0, y0, w, h = a.x(), a.y(), dx, dy
        if shape == "ellipse":
            return bz.ellipse(x0 + w / 2, y0 + h / 2, abs(w) / 2, abs(h) / 2)
        return bz.rect(x0, y0, w, h)

    def drag(self, pos, mods):
        if self.start is None:
            return
        ctl = self.ctl
        if self.item is None and math.dist((pos.x(), pos.y()), (self.start.x(), self.start.y())) \
                <= ctl.tolerance(DRAG_PX):
            return
        subs, origin = place_origin(self.geometry(self.start, pos, mods))
        if self.item is None:
            style = dict(ctl.style)
            if self.shape == "line":
                style["fill"] = ""
                if not style.get("stroke"):
                    style["stroke"] = model.DEFAULT_STROKE
            self.item = ctl.new_path(subs, origin, style)
        else:
            self.item.data["subpaths"] = subs
            self.item.data["x"], self.item.data["y"] = origin.x(), origin.y()
            self.item.setPos(origin)
            self.item.prepareGeometryChange()
            self.item.sync()
            self.item.update()
        self.last = (pos, mods)
        box = self.item.geometry_rect()
        ctl.tip = (pos, f"L {box.width():.1f}  H {box.height():.1f}")

    def release(self, pos, mods):
        ctl = self.ctl
        if self.start is None:
            return
        if self.item is None:                               # simple clic : forme de 100 unités centrée sur le clic
            half = QPointF(50, 50)
            a = self.start if self.shape in ("polygon", "star") else self.start - half
            b = self.start + QPointF(0, -50) if self.shape in ("polygon", "star") else self.start + half
            if self.shape == "line":
                a, b = self.start, self.start + QPointF(100, 0)
            subs, origin = place_origin(self.geometry(a, b, Qt.NoModifier))
            style = dict(ctl.style)
            if self.shape == "line":
                style["fill"] = ""
                style["stroke"] = style.get("stroke") or model.DEFAULT_STROKE
            self.item = ctl.new_path(subs, origin, style)
        ctl.commit_new(self.item, self.label.split(" (")[0])
        self.item = None
        self.start = None
        ctl.tip = None

    def key_press(self, key, mods) -> bool:
        if self.shape in ("polygon", "star") and key in (Qt.Key_Up, Qt.Key_Down) and self.start is not None:
            self.sides = max(3 if self.shape == "polygon" else 2, min(100, self.sides + (1 if key == Qt.Key_Up
                                                                                          else -1)))
            if self.item is not None:
                self.drag(*self.last)
            return True
        return False

    def cancel(self):
        if self.item is not None:
            self.ctl.discard(self.item)
            self.item = None
        self.start = None
        self.ctl.tip = None


class RectTool(ShapeTool):
    name, label, shape = "rect", "Rectangle (M)", "rect"


class EllipseTool(ShapeTool):
    name, label, shape = "ellipse", "Ellipse (L)", "ellipse"


class PolygonTool(ShapeTool):
    name, label, shape = "polygon", "Polygone (flèches pendant le tracé = côtés)", "polygon"


class StarTool(ShapeTool):
    name, label, shape = "star", "Étoile (flèches pendant le tracé = branches)", "star"


class LineTool(ShapeTool):
    name, label, shape = "line", "Segment de droite (\\)", "line"


# ---------------------------------------------------------------- Crayon (N)
class PencilTool(Tool):
    """Tracé à main levée, lissé puis ajusté en courbes de Bézier (algorithme de Schneider, repris de
    `fm_font.shapes.fit_cubic`) ; fermé si la fin revient près du début."""
    name, label = "pencil", "Crayon (N)"
    FIDELITY_PX = 2.5

    def __init__(self, ctl):
        super().__init__(ctl)
        self.points = None

    def press(self, pos, mods):
        self.points = [(pos.x(), pos.y())]

    def drag(self, pos, mods):
        if self.points is None:
            return
        if math.dist(self.points[-1], (pos.x(), pos.y())) >= self.ctl.tolerance(1.5):
            self.points.append((pos.x(), pos.y()))
            self.ctl.preview = ("polyline", list(self.points))

    def release(self, pos, mods):
        points, self.points = self.points, None
        ctl = self.ctl
        ctl.preview = None
        if not points or len(points) < 3:
            return
        from fm_font.shapes import fit_cubic, rdp, smooth_polyline
        tol = ctl.tolerance(self.FIDELITY_PX)
        pts = rdp(smooth_polyline(points, 2), tol * 0.25)
        cubics = fit_cubic(pts, tol)
        if not cubics:
            return
        closed = len(points) > 4 and math.dist(points[0], points[-1]) <= ctl.tolerance(10)
        sub = bz.from_cubics([tuple(tuple(p) for p in c) for c in cubics], closed=closed)
        if closed and not sub["closed"]:
            sub["closed"] = True
        subs, origin = place_origin([sub])
        style = dict(ctl.style)
        if not closed:
            style["fill"] = ""
            style["stroke"] = style.get("stroke") or model.DEFAULT_STROKE
        item = ctl.new_path(subs, origin, style)
        ctl.commit_new(item, "Crayon")

    def cancel(self):
        self.points = None
        self.ctl.preview = None


# ---------------------------------------------------------------- Plan de travail (Maj+O)
class ArtboardTool(Tool):
    """Glisser dans le vide = nouveau plan ; clic = le choisir ; poignées = le redimensionner ; Ctrl + glisser = le
    déplacer (règle de l'appli) ; Suppr = le supprimer ; double-clic = le renommer."""
    name, label = "artboard", "Plan de travail (Maj+O)"

    def __init__(self, ctl):
        super().__init__(ctl)
        self.start = None
        self.mode = None
        self.origin = None

    def _handle(self, pos):
        board = self.ctl.selected_artboard()
        if board is None:
            return None
        t = self.ctl.tolerance(HANDLE_PX + 2)
        for name, p in box_handles(board.scene_rect()).items():
            if abs(pos.x() - p.x()) <= t and abs(pos.y() - p.y()) <= t:
                return name
        return None

    def press(self, pos, mods):
        ctl = self.ctl
        self.start = pos
        handle = self._handle(pos)
        board = ctl.artboard_at(pos)
        if handle is not None:
            self.mode = ("resize", handle)
            self.origin = ctl.selected_artboard().scene_rect()
            ctl.scene.begin_change([ctl.selected_artboard()])
        elif board is not None:
            ctl.artboard_id = board.item_id
            ctl.clear_selection()
            if mods & Qt.ControlModifier:
                self.mode = ("move", None)
                self.origin = QPointF(board.pos())
                ctl.scene.begin_change([board])
            else:
                self.mode = None
            ctl.stateChanged.emit()
        else:
            ctl.artboard_id = ""
            self.mode = ("new", None)

    def drag(self, pos, mods):
        ctl = self.ctl
        if self.mode is None or self.start is None:
            return
        kind, handle = self.mode
        if kind == "new":
            ctl.marquee = QRectF(self.start, pos).normalized()
            ctl.tip = (pos, f"L {ctl.marquee.width():.1f}  H {ctl.marquee.height():.1f}")
            return
        board = ctl.selected_artboard()
        if kind == "move":
            board.setPos(self.origin + (pos - self.start))
            return
        r = QRectF(self.origin)
        if "l" in handle:
            r.setLeft(min(pos.x(), r.right() - 1))
        if "r" in handle:
            r.setRight(max(pos.x(), r.left() + 1))
        if "t" in handle:
            r.setTop(min(pos.y(), r.bottom() - 1))
        if "b" in handle:
            r.setBottom(max(pos.y(), r.top() + 1))
        board.prepareGeometryChange()
        board.data.update(x=r.x(), y=r.y(), w=r.width(), h=r.height())
        board.setPos(r.topLeft())
        board.update()
        ctl.tip = (pos, f"L {r.width():.1f}  H {r.height():.1f}")

    def release(self, pos, mods):
        ctl = self.ctl
        mode, self.mode = self.mode, None
        ctl.tip = None
        if mode is None:
            return
        kind, _h = mode
        if kind == "new":
            rect, ctl.marquee = ctl.marquee, None
            if rect is not None and rect.width() > ctl.tolerance(4) and rect.height() > ctl.tolerance(4):
                ctl.add_artboard(rect)
            return
        board = ctl.selected_artboard()
        board.data["x"], board.data["y"] = round(board.pos().x(), 3), round(board.pos().y(), 3)
        ctl.scene.end_change("Déplacer le plan de travail" if kind == "move" else "Taille du plan de travail")

    def double_click(self, pos, mods) -> bool:
        board = self.ctl.artboard_at(pos)
        if board is None:
            return False
        from PySide6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self.ctl.pane, "Plan de travail", "Nom :", text=board.data.get("name", ""))
        if ok and name.strip():
            self.ctl.change([board], lambda b: b.data.update(name=name.strip()), "Renommer le plan de travail")
        return True

    def cancel(self):
        self.mode = None
        self.ctl.marquee = None
        self.ctl.tip = None

    def cursor(self):
        return Qt.CrossCursor


# ---------------------------------------------------------------- Main, Zoom, Pipette
class HandTool(Tool):
    """Main : le board déplace la vue (outil « hand » de la vue, même geste que Espace)."""
    name, label = "hand", "Main (H, ou Espace)"

    def __init__(self, ctl):
        super().__init__(ctl)
        self.last = None

    def press(self, pos, mods):
        self.last = self.ctl.view.mapFromScene(pos)

    def drag(self, pos, mods):
        if self.last is None:
            return
        view = self.ctl.view
        now = QCursor.pos()
        now = view.viewport().mapFromGlobal(now)
        d = now - self.last
        self.last = now
        view.horizontalScrollBar().setValue(view.horizontalScrollBar().value() - d.x())
        view.verticalScrollBar().setValue(view.verticalScrollBar().value() - d.y())

    def release(self, pos, mods):
        self.last = None

    def cursor(self):
        return Qt.OpenHandCursor


class ZoomTool(Tool):
    """Clic = zoom × 2 autour du point ; Alt + clic = ÷ 2."""
    name, label = "zoom", "Zoom (Z ; Alt + clic : arrière)"

    def press(self, pos, mods):
        view = self.ctl.view
        view.zoom_by(0.5 if mods & Qt.AltModifier else 2.0, view.mapFromScene(pos))

    def cursor(self):
        return Qt.CrossCursor


class EyedropperTool(Tool):
    """Clic sur un objet : son style va à la sélection et devient le style courant."""
    name, label = "eyedropper", "Pipette (I)"

    def press(self, pos, mods):
        item = self.ctl.object_at(pos)
        if item is not None:
            self.ctl.eyedrop(item)

    def cursor(self):
        return Qt.PointingHandCursor


class GradientTool(Tool):
    """Glisser sur les objets choisis (ou sur l'objet sous la souris) : direction d'un dégradé linéaire, ou centre et
    rayon d'un radial ; un objet sans dégradé en reçoit un (blanc -> noir, comme Illustrator). Une étape."""
    name, label = "gradient", "Dégradé (G)"

    def __init__(self, ctl):
        super().__init__(ctl)
        self.start = None
        self.items = None

    def press(self, pos, mods):
        ctl = self.ctl
        items = ctl.selection()
        hit = ctl.object_at(pos)
        if hit is not None and hit not in items:
            ctl.select([hit])
            items = [hit]
        if not items:
            return
        self.start = pos
        self.items = items
        ctl.scene.begin_change(items)

    def drag(self, pos, mods):
        if self.start is None:
            return
        from . import paint
        end = _constrain45(self.start, pos) if mods & Qt.ShiftModifier else pos
        for item in self.items:
            box = bz.bounds(item.data["subpaths"])
            if box is None:
                continue
            g = item.data.get("fill_gradient") or paint.new_gradient("linear")
            ox, oy = item.data["x"], item.data["y"]
            item.data["fill_gradient"] = paint.set_from_drag(g, box, (self.start.x() - ox, self.start.y() - oy),
                                                             (end.x() - ox, end.y() - oy))
            item.sync()
            item.update()
        self.ctl.preview = ("polyline", [(self.start.x(), self.start.y()), (end.x(), end.y())])

    def release(self, pos, mods):
        if self.start is None:
            return
        self.ctl.preview = None
        self.ctl.scene.end_change("Dégradé")
        self.start = None
        self.items = None
        self.ctl.stateChanged.emit()

    def cancel(self):
        if self.start is not None:
            self.ctl.scene.end_change("Dégradé")
        self.start = None
        self.items = None
        self.ctl.preview = None

    def cursor(self):
        return Qt.CrossCursor


TOOL_CLASSES = [SelectTool, DirectTool, PenTool, AddAnchorTool, DeleteAnchorTool, ConvertTool, RectTool, EllipseTool,
                PolygonTool, StarTool, LineTool, PencilTool, ArtboardTool, HandTool, ZoomTool, EyedropperTool,
                GradientTool]


class TypeTool(Tool):
    """Texte (T) : clic = texte de point ; glisser = texte captif (cadre) ; clic sur un tracé OUVERT = texte
    curviligne (le tracé devient le tracé de base, comme Illustrator) ; clic sur un texte = l'éditer."""
    name, label = "type", "Texte (T ; sur un tracé ouvert : texte curviligne)"

    def __init__(self, ctl):
        super().__init__(ctl)
        self.start = None

    def press(self, pos, mods):
        self.start = pos

    def drag(self, pos, mods):
        if self.start is None:
            return
        rect = QRectF(self.start, pos).normalized()
        if rect.width() > self.ctl.tolerance(DRAG_PX) or rect.height() > self.ctl.tolerance(DRAG_PX):
            self.ctl.marquee = rect
            self.ctl.tip = (pos, f"L {rect.width():.1f}  H {rect.height():.1f}")

    def release(self, pos, mods):
        ctl = self.ctl
        start, self.start = self.start, None
        rect, ctl.marquee = ctl.marquee, None
        ctl.tip = None
        if start is None:
            return
        if rect is not None:
            item = ctl.new_text(rect.topLeft(), mode="area", w=round(rect.width(), 3), h=round(rect.height(), 3))
            ctl.begin_text_edit(item, None, new=True)
            return
        hit = ctl.object_at(pos)
        if hit is not None and hasattr(hit, "layout_box"):
            ctl.begin_text_edit(hit, pos)
            return
        if hit is not None and any(not s["closed"] and len(s["nodes"]) > 1 for s in hit.data["subpaths"]):
            sub = next(s for s in hit.data["subpaths"] if not s["closed"] and len(s["nodes"]) > 1)
            item = ctl.new_text(QPointF(hit.data["x"], hit.data["y"]), mode="path",
                                subpaths=bz.copy_subpaths([sub]))
            hit.setVisible(False)                        # remplacé à la fin de l'édition (une étape)
            ctl.begin_text_edit(item, None, new=True, replaced=hit)
            return
        item = ctl.new_text(pos)
        ctl.begin_text_edit(item, None, new=True)

    def cancel(self):
        self.start = None
        self.ctl.marquee = None
        self.ctl.tip = None

    def busy(self) -> bool:
        return self.start is not None

    def cursor(self):
        return Qt.IBeamCursor


def make_tools(ctl) -> dict:
    from .shape_builder import ShapeBuilderTool
    return {cls.name: cls(ctl) for cls in TOOL_CLASSES + [ShapeBuilderTool, TypeTool]}
