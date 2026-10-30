"""Gestes du module Design (mélangés au contrôleur, `GestureMixin`) : cadre de sélection, Ctrl + glisser
(déplacer, copie avec Alt), poignées (redimensionner, recadrer par les côtés d'une image), rotation, sélection
multiple à l'échelle, mode recadrage. Un geste = un état `self._gesture` ; fin = UNE étape d'annulation."""
from __future__ import annotations

import copy
import math

from PySide6.QtCore import QLineF, QPointF, QRectF, Qt
from PySide6.QtGui import QPolygonF, QTransform

from . import design_model as dm, document as doc, geometry
from .items import DesignElement, DesignImageItem, DesignShapeItem, DesignTextItem
from .overlay import angle_of, mid


class GestureMixin:
    # -- cadre de sélection (glisser sans Ctrl) --
    def _marquee_start(self, pos, scene_pos, mods, on_element: bool):
        base = self.selection() if mods & Qt.ShiftModifier else []
        members = self._press[2] if self._press and self._press[0] == "click" else None
        self._press = ("marquee", pos, scene_pos, base, mods, False, members, on_element)

    def _marquee_move(self, pos, mods):
        _kind, start, start_scene, base, start_mods, moved, members, on_element = self._press
        if not moved and (pos - start).manhattanLength() < 4:
            return
        self._press = ("marquee", start, start_scene, base, start_mods, True, None, on_element)
        rect = QRectF(start_scene, self.view.mapToScene(pos.toPoint())).normalized()
        self.marquee = rect
        # Glissé depuis un élément sans Ctrl : rappel de la règle (Ctrl + glisser = déplacer).
        self.tip = (self.view.mapToScene(pos.toPoint()), "Ctrl + glisser pour déplacer") if on_element else None
        hit = [i for i in doc.elements(self.scene)
               if i.isVisible() and self.scene.item_active(i) and i.mapRectToScene(i.content_rect()).intersects(rect)]
        wanted = set(self._expand(hit)) | set(base)
        for item in doc.elements(self.scene):
            on = item in wanted
            if item.isSelected() != on:
                item.setSelected(on)
        self.refresh()

    # ------------------------------------------------------------------ gestes
    def _start_gesture(self, kind, scene_pos, items, copy_items=False, **extra):
        self.scene.commit_live()
        if copy_items:
            page = items[0].page_item()
            if page is not None:
                copies = doc.insert_elements(self.scene, page, self.scene.serialize(items), text="Dupliquer")
                if copies:
                    self._select(copies)
                    items = copies
        before = self.scene.snapshot([i.item_id for i in items])
        page = items[0].page_item() if items else None
        targets = []
        if page is not None and kind in ("move", "resize"):
            targets = [doc.local_box(i) for i in doc.elements(self.scene, page)
                       if i not in items and i.isVisible()]
        frozen = self._freeze_page(page, items) if kind in ("move", "resize", "multi_resize", "rotate") else None
        self._gesture = {"kind": kind, "items": items, "start": scene_pos, "before": before, "page": page,
                         "targets": targets, "moved": False, "frozen": frozen,
                         "pos0": {i: QPointF(i.pos()) for i in items},
                         "data0": {i: copy.deepcopy(i.to_dict()) for i in items},
                         "box0": geometry.union([doc.local_box(i) for i in items]), **extra}
        self.refresh()

    def _freeze_page(self, page, items):
        """Page de beaucoup d'éléments : tout SAUF les éléments manipulés devient une image fixe le temps du geste
        (chaque image du geste ne peint plus que ceux-là). Un élément manipulé passe au-dessus des autres pendant le
        geste (sa vraie place dans l'ordre revient à la fin)."""
        if page is None or page.snapshot is not None or len(page.childItems()) < self.SNAPSHOT_MIN:
            return None
        from PySide6.QtGui import QPixmap
        from . import render
        w, h = page.size()
        ratio = self.view.devicePixelRatioF() or 1.0
        scale = min(self.view.zoom() * ratio, self.SNAPSHOT_SIDE / max(w, h))
        page.snapshot = QPixmap.fromImage(render.render_image(page, max(0.01, scale), exclude=set(items)))
        for item in items:
            item.live = True
        # Les autres éléments MASQUÉS le temps du geste : Qt redessinait leur image gardée à chaque image (1 000
        # éléments : l'essentiel du coût) alors qu'ils sont déjà dans l'image de la page. Choisis : jamais masqués.
        hidden = [c for c in page.childItems() if isinstance(c, DesignElement) and c not in items
                  and c.isVisible() and not c.isSelected()]
        for child in hidden:
            child.setVisible(False)
        page.update()
        return page, hidden

    def _thaw_page(self, frozen, items):
        if frozen is None:
            return
        page, hidden = frozen
        for item in items:
            item.live = False
        for child in hidden:
            if child.scene() is self.scene:
                child.setVisible(True)
        page.snapshot = None
        page.update()
        self.scene.update(page.sceneBoundingRect())

    def _start_handle(self, handle, scene_pos, mods):
        sel = self.selection()
        if handle == "rot":
            poly = self.selection_polygon()
            center = poly.boundingRect().center() if len(sel) > 1 else self.item_polygon(sel[0]).boundingRect().center()
            self._start_gesture("rotate", scene_pos, sel, center=center,
                                angle0=math.degrees(math.atan2(scene_pos.y() - center.y(), scene_pos.x() - center.x())),
                                rot0={i: i.rotation() for i in sel},
                                center0={i: i.mapToScene(i.content_rect().center()) for i in sel})
            return
        if self.crop_item is not None:
            item = self.crop_item
            self._start_gesture("crop_edge", scene_pos, [item], handle=handle,
                                transform=QTransform(item.sceneTransform()))
            return
        if len(sel) == 1:
            item = sel[0]
            self._start_gesture("resize", scene_pos, sel, handle=handle,
                                transform=QTransform(item.sceneTransform()))
            return
        rect = self.selection_polygon().boundingRect()
        anchor = {"tl": rect.bottomRight(), "tr": rect.bottomLeft(), "br": rect.topLeft(),
                  "bl": rect.topRight()}[handle]
        self._start_gesture("multi_resize", scene_pos, sel, handle=handle, anchor=anchor, rect0=rect,
                            center0={i: i.mapToScene(i.content_rect().center()) for i in sel})

    def _update_gesture(self, scene_pos, mods):
        g = self._gesture
        g["moved"] = True
        kind = g["kind"]
        if kind == "move":
            self._do_move(g, scene_pos, mods)
        elif kind == "resize":
            self._do_resize(g, scene_pos, mods)
        elif kind == "multi_resize":
            self._do_multi_resize(g, scene_pos)
        elif kind == "rotate":
            self._do_rotate(g, scene_pos, mods)
        elif kind == "crop_edge":
            self._do_crop_edge(g, scene_pos)
        elif kind == "guide":
            page, n = g["page"], g["guide"]
            local = page.mapFromScene(scene_pos)
            guides = [dict(x) for x in g["guides0"]]
            axis = guides[n]["axis"]
            limit = page.size()[0] if axis == "v" else page.size()[1]
            guides[n]["pos"] = round(min(limit, max(0.0, local.x() if axis == "v" else local.y())), 2)
            page.data["guides"] = guides
            self.tip = (scene_pos, f"{round(guides[n]['pos'])} px")
        elif kind == "crop_pan":
            item = g["items"][0]
            inverse, _ok = item.sceneTransform().inverted()
            d = inverse.map(scene_pos) - inverse.map(g["start"])
            item.data["crop"] = geometry.pan_crop(g["data0"][item]["crop"], item.size(), d.x(), d.y())
            item.update()
        self.refresh()

    def _snap_threshold(self, mods):
        if not self.scene.snap_active(mods) or not self.scene.snap.get("objects", True):
            return None
        return float(self.scene.snap.get("distance", 6)) / max(0.05, self.scene.zoom)

    def _guide_lines(self, page, guides):
        if page is None:
            return []
        w, h = page.size()
        lines = []
        for guide in guides:
            if guide[0] == "seg":                               # espacement égal : le segment entre deux éléments
                _kind, x1, y1, x2, y2 = guide
                lines.append(QLineF(page.mapToScene(QPointF(x1, y1)), page.mapToScene(QPointF(x2, y2))))
                continue
            axis, value = guide
            a, b = (QPointF(value, 0), QPointF(value, h)) if axis == "v" else (QPointF(0, value), QPointF(w, value))
            lines.append(QLineF(page.mapToScene(a), page.mapToScene(b)))
        return lines

    def _do_move(self, g, scene_pos, mods):
        d = scene_pos - g["start"]
        dx, dy = d.x(), d.y()
        threshold = self._snap_threshold(mods)
        page = g["page"]
        self.guides = []
        if threshold is not None and page is not None:
            x, y, w, h = g["box0"]
            sx, sy, guides = geometry.snap_move((x + dx, y + dy, w, h), g["targets"], page.size(), threshold,
                                                page_guides(page))
            dx += sx
            dy += sy
            self.guides = self._guide_lines(page, guides)
        for item in g["items"]:
            p = g["pos0"][item]
            item.setPos(p.x() + dx, p.y() + dy)
        self.tip = None

    def _do_resize(self, g, scene_pos, mods):
        item = g["items"][0]
        handle = g["handle"]
        data0 = g["data0"][item]
        inverse, _ok = g["transform"].inverted()
        local = inverse.map(scene_pos)
        w0, h0 = float(data0["w"]), float(data0["h"])
        left, top, right, bottom = 0.0, 0.0, w0, h0
        if "l" in handle:
            left = min(local.x(), right - dm.MIN_SIZE)
        if "r" in handle:
            right = max(local.x(), left + dm.MIN_SIZE)
        if "t" in handle:
            top = min(local.y(), bottom - dm.MIN_SIZE)
        if "b" in handle:
            bottom = max(local.y(), top + dm.MIN_SIZE)
        threshold = self._snap_threshold(mods)
        page = g["page"]
        self.guides = []
        if threshold is not None and page is not None and abs(item.rotation()) < 1e-6 and len(handle) == 1:
            ox, oy = g["pos0"][item].x(), g["pos0"][item].y()
            gx, gy = page_guides(page)
            xs = [0.0, page.size()[0] / 2, page.size()[0], *gx] + [v for t in g["targets"] for v in geometry.edges(t)[0]]
            ys = [0.0, page.size()[1] / 2, page.size()[1], *gy] + [v for t in g["targets"] for v in geometry.edges(t)[1]]
            guides = []
            if handle in ("l", "r"):
                value = ox + (left if handle == "l" else right)
                snapped, hit = geometry.snap_value(value, xs, threshold)
                if hit is not None:
                    guides.append(("v", hit))
                    if handle == "l":
                        left = min(snapped - ox, right - dm.MIN_SIZE)
                    else:
                        right = max(snapped - ox, left + dm.MIN_SIZE)
            elif handle in ("t", "b"):
                value = oy + (top if handle == "t" else bottom)
                snapped, hit = geometry.snap_value(value, ys, threshold)
                if hit is not None:
                    guides.append(("h", hit))
                    if handle == "t":
                        top = min(snapped - oy, bottom - dm.MIN_SIZE)
                    else:
                        bottom = max(snapped - oy, top + dm.MIN_SIZE)
            self.guides = self._guide_lines(page, guides)
        w, h = right - left, bottom - top
        corner = len(handle) == 2
        data = copy.deepcopy(data0)
        if isinstance(item, DesignTextItem):
            if corner:
                k = max(w / w0, 0.02)
                data["font_size"] = round(max(1.0, float(data0["font_size"]) * k), 2)
                data["spans"] = dm.scale_spans(data0.get("spans") or [], k)
                w = w0 * k
                data["letter_spacing"] = data0.get("letter_spacing", 0.0)
            data["w"] = round(max(dm.MIN_SIZE, w), 2)
        elif isinstance(item, DesignImageItem) and not corner:
            delta = {"l": left, "r": right - w0, "t": top, "b": bottom - h0}[handle]
            crop, applied = geometry.crop_edge(data0["crop"], (w0, h0), handle, delta)
            data["crop"] = crop
            if handle in ("l", "r"):
                w = w0 - applied if handle == "l" else w0 + applied
            else:
                h = h0 - applied if handle == "t" else h0 + applied
            data["w"], data["h"] = round(w, 2), round(h, 2)
        else:
            free = isinstance(item, DesignShapeItem) and bool(mods & Qt.ShiftModifier)
            if corner and not free:
                k = max(w / w0, h / h0)
                w, h = w0 * k, h0 * k
            data["w"], data["h"] = round(w, 2), round(h, 2)
        self._place_resized(item, g, data, handle)
        self.tip = (scene_pos, f"{round(item.size()[0])} × {round(item.size()[1])}")

    def _place_resized(self, item, g, data, handle):
        """Taille nouvelle, le côté / coin OPPOSÉ à la poignée reste en place (rotation comprise)."""
        data0 = g["data0"][item]
        w0, h0 = float(data0["w"]), float(data0["h"])
        item.data = data
        item.apply(data)                                     # un texte recalcule sa hauteur
        w, h = item.size()
        # Le côté / coin opposé reste en place ; côté gauche / droit : le haut reste (un texte change de hauteur).
        left = w0 - w if "l" in handle else 0.0 if "r" in handle else (w0 - w) / 2
        top = h0 - h if "t" in handle else 0.0
        rect = QRectF(left, top, w, h)
        center_scene = g["transform"].map(rect.center())
        parent = item.parentItem()
        center = parent.mapFromScene(center_scene) if parent is not None else center_scene
        item.setTransformOriginPoint(w / 2, h / 2)
        item.setPos(center.x() - w / 2, center.y() - h / 2)

    def _do_multi_resize(self, g, scene_pos):
        anchor, rect0 = g["anchor"], g["rect0"]
        k = max(abs(scene_pos.x() - anchor.x()) / max(1e-6, rect0.width()),
                abs(scene_pos.y() - anchor.y()) / max(1e-6, rect0.height()), 0.02)
        for item in g["items"]:
            data = copy.deepcopy(g["data0"][item])
            item.data = data
            item.data.update(w=round(data["w"] * k, 2), h=round(data["h"] * k, 2))
            for key in ("font_size", "stroke_width", "radius"):
                if key in item.data:
                    item.data[key] = round(float(g["data0"][item][key]) * k, 2)
            if item.data.get("spans"):
                item.data["spans"] = dm.scale_spans(g["data0"][item]["spans"], k)
            item.apply(item.data)
            c0 = g["center0"][item]
            c = QPointF(anchor.x() + (c0.x() - anchor.x()) * k, anchor.y() + (c0.y() - anchor.y()) * k)
            parent = item.parentItem()
            local = parent.mapFromScene(c) if parent is not None else c
            w, h = item.size()
            item.setPos(local.x() - w / 2, local.y() - h / 2)
        self.tip = (scene_pos, f"{round(k * 100)} %")

    def _do_rotate(self, g, scene_pos, mods):
        c = g["center"]
        angle = math.degrees(math.atan2(scene_pos.y() - c.y(), scene_pos.x() - c.x()))
        delta = angle - g["angle0"]
        items = g["items"]
        if len(items) == 1:
            target = g["rot0"][items[0]] + delta
            if mods & Qt.ShiftModifier:
                target = round(target / 15.0) * 15.0
            else:
                near = round(target / 45.0) * 45.0
                if abs(target - near) < 3.0:
                    target = near
            delta = target - g["rot0"][items[0]]
        elif mods & Qt.ShiftModifier:
            delta = round(delta / 15.0) * 15.0
        rad = math.radians(delta)
        cos, sin = math.cos(rad), math.sin(rad)
        for item in items:
            r = ((g["rot0"][item] + delta + 180.0) % 360.0) - 180.0
            item.data["rotation"] = round(r, 2)
            item.setRotation(r)
            if len(items) > 1:
                c0 = g["center0"][item]
                vx, vy = c0.x() - c.x(), c0.y() - c.y()
                nc = QPointF(c.x() + vx * cos - vy * sin, c.y() + vx * sin + vy * cos)
                parent = item.parentItem()
                local = parent.mapFromScene(nc) if parent is not None else nc
                w, h = item.size()
                item.setPos(local.x() - w / 2, local.y() - h / 2)
        shown = items[0].data["rotation"] if len(items) == 1 else round(delta, 1)
        self.tip = (scene_pos, f"{round(shown)}°")

    def _do_crop_edge(self, g, scene_pos):
        item = g["items"][0]
        data0 = g["data0"][item]
        inverse, _ok = g["transform"].inverted()
        local = inverse.map(scene_pos)
        w0, h0 = float(data0["w"]), float(data0["h"])
        crop = list(data0["crop"])
        left, top, right, bottom = 0.0, 0.0, w0, h0
        for edge in g["handle"]:
            pointer = {"l": local.x(), "r": local.x(), "t": local.y(), "b": local.y()}[edge]
            base = {"l": 0.0, "r": w0, "t": 0.0, "b": h0}[edge]
            crop, applied = geometry.crop_edge(crop, (right - left, bottom - top), edge, pointer - base)
            if edge == "l":
                left += applied
            elif edge == "r":
                right += applied
            elif edge == "t":
                top += applied
            else:
                bottom += applied
        data = copy.deepcopy(data0)
        data.update(crop=crop, w=round(right - left, 2), h=round(bottom - top, 2))
        item.data = data
        item.apply(data)
        rect = QRectF(left, top, right - left, bottom - top)
        center_scene = g["transform"].map(rect.center())
        parent = item.parentItem()
        center = parent.mapFromScene(center_scene) if parent is not None else center_scene
        w, h = item.size()
        item.setTransformOriginPoint(w / 2, h / 2)
        item.setPos(center.x() - w / 2, center.y() - h / 2)

    def _end_gesture(self, cancel: bool = False):
        g, self._gesture = self._gesture, None
        self.guides = []
        self.tip = None
        if g is None:
            return
        self._thaw_page(g.get("frozen"), g["items"])
        if cancel or not g["moved"]:
            if g["moved"]:
                self.scene.apply_states(g["before"])
            self.refresh()
            return
        if g["kind"] == "guide":
            page = g["page"]
            self.scene.push(g["before"], self.scene.snapshot([page.item_id]), "Déplacer un repère")
            self.refresh()
            return
        items = [i for i in g["items"] if i.scene() is self.scene]
        if g["kind"] == "move" and items:
            box = QRectF()
            for item in items:
                box = box.united(item.mapRectToScene(item.content_rect()))
            target = self._page_at(box.center())
            if target is not None and target is not g["page"]:
                doc.move_to_page(self.scene, items, target)
                self.set_current_page(target)
        for item in items:
            item.data = item.to_dict()
            self.scene.item_moved(item)
        text = {"move": "Déplacer", "resize": "Redimensionner", "guide": "Repère", "multi_resize": "Redimensionner",
                "rotate": "Rotation", "crop_edge": "Recadrer", "crop_pan": "Recadrer"}[g["kind"]]
        self.scene.push(g["before"], self.scene.snapshot(list(g["before"])), text)
        self.refresh()
        self.stateChanged.emit()

    def crop_full_transform(self) -> QTransform:
        """Image ENTIÈRE (carré unité -> scène) de l'image en recadrage."""
        item = self.crop_item
        x0, y0, x1, y1 = item.data.get("crop", [0, 0, 1, 1])
        w, h = item.size()
        fw, fh = w / max(1e-9, x1 - x0), h / max(1e-9, y1 - y0)
        local = QTransform(fw, 0, 0, fh, -x0 * fw, -y0 * fh)
        return local * item.sceneTransform()

    def crop_full_polygon(self) -> QPolygonF | None:
        if self.crop_item is None:
            return None
        return self.crop_full_transform().map(QPolygonF(QRectF(0, 0, 1, 1)))

    def _crop_handles(self):
        item = self.crop_item
        poly = self.item_polygon(item)
        tl, tr, br, bl = poly[0], poly[1], poly[2], poly[3]
        angle = angle_of(tl, tr)
        return [("tl", tl, angle), ("tr", tr, angle), ("br", br, angle), ("bl", bl, angle),
                ("l", mid(tl, bl), angle), ("r", mid(tr, br), angle), ("t", mid(tl, tr), angle),
                ("b", mid(bl, br), angle)]


def page_guides(page) -> tuple[list, list]:
    """(x des repères verticaux, y des horizontaux) d'une page."""
    guides = page.data.get("guides") or []
    return ([float(g["pos"]) for g in guides if g.get("axis") == "v"],
            [float(g["pos"]) for g in guides if g.get("axis") == "h"])
