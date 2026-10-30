"""Module Design du board : CONTRÔLEUR (activation, souris, clavier, sélection, gestes).

Activé par le bouton « Design » du sélecteur de modules (`BoardPane.set_module("design")`). Actif, la vue du board lui
confie la souris (bouton gauche, droit) et le clavier ; la molette, le bouton du milieu et Espace tenu déplacent /
zooment toujours le board.

Gestes (règle de l'appli : TOUT déplacement d'élément commence avec Ctrl enfoncé) :
- clic = choisir (tout le groupe) ; Maj + clic = ajouter / retirer ; glisser SANS Ctrl = cadre de sélection ;
- Ctrl + glisser = déplacer la sélection (magnétisme : bords et centres de la page et des autres éléments ; Alt = sans ;
  déposé sur une autre page = il y passe) ; Ctrl + Alt + glisser = déplacer une COPIE ;
- poignées (sans Ctrl : ce n'est pas un déplacement) : coins = proportions gardées (Maj = libre, formes), côtés =
  largeur / hauteur (texte : largeur ; image : recadrage sans déformer), rotation sous la sélection (Maj = pas de
  15°, aimantée à 45°) ;
- double-clic : texte = édition sur place, image = mode recadrage (poignées = bords visibles, Ctrl + glisser = faire
  glisser l'image dans son cadre ; Entrée / Échap / clic dehors = terminer).
Une étape d'annulation par geste (`scene.push`)."""
from __future__ import annotations

import copy
import math

from PySide6.QtCore import QLineF, QObject, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QPolygonF, QTransform
from PySide6.QtWidgets import QApplication

from . import design_model as dm, document as doc, geometry
from .items import DesignElement, DesignImageItem, DesignPageItem, DesignShapeItem, DesignTextItem
from .overlay import HIT_PX, ROTATE_PX, DesignOverlay, angle_of, mid

CURSORS = {"tl": Qt.SizeFDiagCursor, "br": Qt.SizeFDiagCursor, "tr": Qt.SizeBDiagCursor, "bl": Qt.SizeBDiagCursor,
           "l": Qt.SizeHorCursor, "r": Qt.SizeHorCursor, "t": Qt.SizeVerCursor, "b": Qt.SizeVerCursor,
           "rot": Qt.PointingHandCursor}


class DesignController(QObject):
    stateChanged = Signal()                # sélection, page courante, mode : panneaux à jour
    pagesChanged = Signal()                # pages ajoutées / retirées / réordonnées : barre des pages

    def __init__(self, pane):
        super().__init__(pane)
        self.pane = pane
        self.view = pane.view
        self.scene = pane.scene
        self.active = False
        self.hover = None
        self.guides: list = []
        self.marquee: QRectF | None = None
        self.tip = None                     # (point de scène, texte) : taille / angle pendant un geste
        self.crop_item: DesignImageItem | None = None
        self._page_id = ""
        self._gesture = None
        self._press = None
        self.overlay = DesignOverlay(self)
        self.scene.addItem(self.overlay)
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(0)
        self._refresh_timer.timeout.connect(self._refresh)
        self.scene.selectionChanged.connect(self._on_selection)
        self.scene.contentChanged.connect(self.refresh)
        self.view.zoomChanged.connect(lambda _z: self.refresh())
        from .ui import DesignChrome
        self.ui = DesignChrome(pane, self)
        self.refresh()

    # ------------------------------------------------------------------ activation
    def activate(self):
        if self.active:
            return
        self.active = True
        self.view.finish_text_edit()
        self.view.set_tool("select")
        for item in self.scene.selectedItems():
            if not isinstance(item, DesignElement):
                item.setSelected(False)
        self.ui.show()
        self.refresh()
        self.view.setFocus()
        self.stateChanged.emit()

    def deactivate(self):
        if not self.active:
            return
        self._end_gesture(cancel=True)
        self.end_crop()
        self.active = False
        self.hover = None
        self.ui.hide()
        self.refresh()
        self.view._sync_cursor()
        self.stateChanged.emit()

    def refresh(self):
        """Overlay redessiné une fois par passage de boucle (les signaux arrivent par rafales)."""
        self._refresh_timer.start()

    def _refresh(self):
        if self.overlay.scene() is None:
            self.scene.addItem(self.overlay)
        self.overlay.refresh()

    def _on_selection(self):
        try:
            self._selection_changed()
        except RuntimeError:                # scène détruite (fermeture du board) : elle vide sa sélection en partant
            pass

    def _selection_changed(self):
        if self.crop_item is not None and not self.crop_item.isSelected():
            self.end_crop()
        sel = self.selection()
        if sel:
            page = sel[0].page_item()
            if page is not None:
                self._page_id = page.item_id
        self.refresh()
        self.stateChanged.emit()

    # ------------------------------------------------------------------ lecture
    def pages(self) -> list[DesignPageItem]:
        return doc.pages(self.scene)

    def current_page(self) -> DesignPageItem | None:
        page = self.scene.item(self._page_id)
        if isinstance(page, DesignPageItem):
            return page
        pages = self.pages()
        if not pages:
            return None
        center = self.view.view_center()
        for page in pages:
            if page.sceneBoundingRect().contains(center):
                return page
        return min(pages, key=lambda p: (p.sceneBoundingRect().center() - center).manhattanLength())

    def set_current_page(self, page, show: bool = False):
        if page is None:
            return
        changed = page.item_id != self._page_id
        self._page_id = page.item_id
        if show:
            self.show_page(page)
        if changed:
            self.refresh()
            self.stateChanged.emit()

    def show_page(self, page):
        """Page entière à l'écran (marges), comme un changement de page de Canva."""
        rect = page.mapRectToScene(page.content_rect())
        viewport = self.view.viewport().rect()
        if rect.isEmpty() or viewport.isEmpty():
            return
        free = self.ui.free_area() if self.active else viewport       # hors du panneau et des barres
        low, high = self.view.limits()
        zoom = min((free.width() - 80) / rect.width(), (free.height() - 80) / rect.height())
        zoom = max(low, min(high, zoom))
        self.view.set_zoom(zoom)
        offset = QPointF(free.center() - viewport.center()) / self.view.zoom()
        self.view.center_on(rect.center() - offset)

    def selection(self) -> list[DesignElement]:
        return [i for i in self.scene.selectedItems() if isinstance(i, DesignElement)]

    def text_editing(self) -> bool:
        return self.view.editing_text()

    def gesture_kind(self) -> str | None:
        return self._gesture["kind"] if self._gesture else None

    def _element_at(self, view_pos) -> DesignElement | None:
        point = view_pos.toPoint() if hasattr(view_pos, "toPoint") else view_pos
        for item in self.view.items(point):
            while item is not None and not isinstance(item, (DesignElement, DesignPageItem)):
                item = item.parentItem()
            if isinstance(item, DesignElement) and item.isVisible() and self.scene.item_active(item):
                return item
            if isinstance(item, DesignPageItem):
                return None                     # la page cache ce qui est dessous
        return None

    def _page_at(self, scene_pos) -> DesignPageItem | None:
        for page in reversed(self.pages()):
            if page.isVisible() and page.mapRectToScene(page.content_rect()).contains(scene_pos):
                return page
        return None

    # ------------------------------------------------------------------ géométrie de la sélection
    @staticmethod
    def item_polygon(item) -> QPolygonF:
        return item.mapToScene(QPolygonF(item.content_rect()))

    def selection_polygon(self) -> QPolygonF | None:
        sel = self.selection()
        if not sel:
            return None
        if len(sel) == 1:
            return self.item_polygon(sel[0])
        rect = QRectF()
        for item in sel:
            rect = rect.united(item.mapRectToScene(item.content_rect()))
        return QPolygonF(rect)

    def handles(self) -> list[tuple[str, QPointF, float]]:
        """Poignées de la sélection : (nom, point de scène, angle)."""
        sel = self.selection()
        if self.crop_item is not None:
            return self._crop_handles()
        if not sel or any(i.locked() for i in sel):
            return []
        poly = self.selection_polygon()
        tl, tr, br, bl = poly[0], poly[1], poly[2], poly[3]
        angle = angle_of(tl, tr)
        out = []
        single = sel[0] if len(sel) == 1 else None
        line = isinstance(single, DesignShapeItem) and single.data.get("shape") == "line"
        if not line:
            out += [("tl", tl, angle), ("tr", tr, angle), ("br", br, angle), ("bl", bl, angle)]
        if single is not None:
            sides = ["l", "r"]
            if isinstance(single, (DesignShapeItem, DesignImageItem)) and not line:
                sides += ["t", "b"]
            points = {"l": mid(tl, bl), "r": mid(tr, br), "t": mid(tl, tr), "b": mid(bl, br)}
            out += [(s, points[s], angle) for s in sides]
        bottom = mid(bl, br)
        zoom = max(0.01, self.scene.zoom)
        down = QPointF(bl.x() - tl.x(), bl.y() - tl.y())
        length = math.hypot(down.x(), down.y()) or 1.0
        out.append(("rot", bottom + down * (ROTATE_PX / zoom / length), angle))
        return out

    def _handle_at(self, view_pos) -> str | None:
        for name, point, _angle in self.handles():
            v = self.view.mapFromScene(point)
            if abs(v.x() - view_pos.x()) <= HIT_PX and abs(v.y() - view_pos.y()) <= HIT_PX:
                return name
        return None

    # ------------------------------------------------------------------ souris
    def sync_cursor(self) -> bool:
        return False                         # curseurs posés au survol (_hover_at)

    def _hover_at(self, event):
        pos = event.position()
        handle = self._handle_at(pos)
        viewport = self.view.viewport()
        if handle is not None:
            viewport.setCursor(CURSORS[handle])
            hover = None
        else:
            hover = self._element_at(pos)
            if hover is not None and event.modifiers() & Qt.ControlModifier and not hover.locked():
                viewport.setCursor(Qt.SizeAllCursor)
            else:
                viewport.unsetCursor()
        if hover is not self.hover:
            self.hover = hover
            self.overlay.update()

    def mouse_press(self, event) -> bool:
        pos = event.position()
        scene_pos = self.view.mapToScene(pos.toPoint())
        mods = event.modifiers()
        if self.text_editing():
            focus = self.scene.focusItem()
            owner = getattr(focus, "owner", None)
            if owner is not None and owner.mapRectToScene(owner.content_rect()).contains(scene_pos):
                return False                     # clic dans le texte édité : curseur, sélection du texte
            self.view.finish_text_edit()
        if event.button() == Qt.RightButton:
            target = self._element_at(pos)
            if target is not None and not target.isSelected():
                self._select([target])
            self._press = ("menu", pos)
            return True
        if event.button() != Qt.LeftButton:
            return False
        self.hover = None
        handle = self._handle_at(pos)
        if handle is not None:
            self._start_handle(handle, scene_pos, mods)
            return True
        target = self._element_at(pos)
        page = self._page_at(scene_pos)
        if self.crop_item is not None:
            if target is self.crop_item and mods & Qt.ControlModifier:
                self._start_gesture("crop_pan", scene_pos, [target])
                return True
            if target is not self.crop_item:
                self.end_crop()
        if page is not None:
            self.set_current_page(page)
        if mods & Qt.ControlModifier:
            # Règle de l'appli : déplacer = Ctrl + glisser (sur l'élément ou dans la sélection).
            sel = self.selection()
            poly = self.selection_polygon()
            inside = poly is not None and poly.containsPoint(scene_pos, Qt.OddEvenFill)
            if target is not None and not target.isSelected():
                self._select(self._expand([target]))
            if target is not None or inside:
                items = [i for i in (self.selection() or sel) if not i.locked()]
                if items:
                    self._start_gesture("move", scene_pos, items, copy_items=bool(mods & Qt.AltModifier))
                return True
        if target is not None:
            members = self._expand([target])
            if mods & Qt.ShiftModifier:
                on = not target.isSelected()
                for item in members:
                    item.setSelected(on)
                self._press = ("click", pos, None)
                return True
            if not target.isSelected():
                self._select(members)
                self._press = ("click", pos, None)
            else:
                self._press = ("click", pos, members)  # relâché sans glisser : lui seul (sortir d'une multi)
            self._marquee_start(pos, scene_pos, mods, armed=True)
            return True
        if not mods & Qt.ShiftModifier:
            self.scene.clearSelection()
        self._press = ("click", pos, None)
        self._marquee_start(pos, scene_pos, mods, armed=True)
        return True

    def mouse_move(self, event) -> bool:
        pos = event.position()
        gesture = self._gesture
        if gesture is None:
            if self._press is not None and self._press[0] == "marquee":
                self._marquee_move(pos, event.modifiers())
                return True
            if not (event.buttons() & Qt.LeftButton):
                self._hover_at(event)
            return bool(event.buttons() & (Qt.LeftButton | Qt.RightButton)) and not self.text_editing()
        scene_pos = self.view.mapToScene(pos.toPoint())
        gesture["last"] = (scene_pos, event.modifiers())
        self._update_gesture(scene_pos, event.modifiers())
        return True

    def mouse_release(self, event) -> bool:
        press, self._press = self._press, None
        if self._gesture is not None:
            self._end_gesture()
            return True
        if press is None:
            return self.text_editing() is False and event.button() in (Qt.LeftButton, Qt.RightButton)
        if press[0] == "menu":
            from .ui import open_context_menu
            open_context_menu(self, self.view.viewport().mapToGlobal(event.position().toPoint()))
            return True
        if press[0] == "marquee":
            self.marquee = None
            self.refresh()
            if not press[5]:                               # pas glissé : simple clic
                members = press[6]
                if members:
                    self._select(members)
            return True
        return True

    def mouse_double_click(self, event) -> bool:
        if event.button() != Qt.LeftButton:
            return False
        target = self._element_at(event.position())
        if isinstance(target, DesignTextItem) and not target.locked():
            self.edit_text(target)
            return True
        if isinstance(target, DesignImageItem) and not target.locked():
            self.start_crop(target)
            return True
        return target is not None

    # -- cadre de sélection (glisser sans Ctrl) --
    def _marquee_start(self, pos, scene_pos, mods, armed: bool):
        base = self.selection() if mods & Qt.ShiftModifier else []
        members = self._press[2] if self._press and self._press[0] == "click" else None
        self._press = ("marquee", pos, scene_pos, base, mods, False, members)

    def _marquee_move(self, pos, mods):
        _kind, start, start_scene, base, start_mods, moved, members = self._press
        if not moved and (pos - start).manhattanLength() < 4:
            return
        self._press = ("marquee", start, start_scene, base, start_mods, True, None)
        rect = QRectF(start_scene, self.view.mapToScene(pos.toPoint())).normalized()
        self.marquee = rect
        hit = [i for i in doc.elements(self.scene)
               if i.isVisible() and self.scene.item_active(i) and i.mapRectToScene(i.content_rect()).intersects(rect)]
        wanted = set(self._expand(hit)) | set(base)
        for item in doc.elements(self.scene):
            on = item in wanted
            if item.isSelected() != on:
                item.setSelected(on)
        self.refresh()

    def _select(self, items):
        self.scene.blockSignals(True)
        try:
            self.scene.clearSelection()
            for item in items:
                item.setSelected(True)
        finally:
            self.scene.blockSignals(False)
        self.scene.selectionChanged.emit()

    def _expand(self, items) -> list:
        out = []
        for item in items:
            for member in doc.group_members(self.scene, item):
                if member not in out:
                    out.append(member)
        return out

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
        self._gesture = {"kind": kind, "items": items, "start": scene_pos, "before": before, "page": page,
                         "targets": targets, "moved": False,
                         "pos0": {i: QPointF(i.pos()) for i in items},
                         "data0": {i: copy.deepcopy(i.to_dict()) for i in items},
                         "box0": geometry.union([doc.local_box(i) for i in items]), **extra}
        self.refresh()

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
        for axis, value in guides:
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
            sx, sy, guides = geometry.snap_move((x + dx, y + dy, w, h), g["targets"], page.size(), threshold)
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
            xs = [0.0, page.size()[0] / 2, page.size()[0]] + [v for t in g["targets"] for v in geometry.edges(t)[0]]
            ys = [0.0, page.size()[1] / 2, page.size()[1]] + [v for t in g["targets"] for v in geometry.edges(t)[1]]
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
        if cancel or not g["moved"]:
            if g["moved"]:
                self.scene.apply_states(g["before"])
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
        text = {"move": "Déplacer", "resize": "Redimensionner", "multi_resize": "Redimensionner",
                "rotate": "Rotation", "crop_edge": "Recadrer", "crop_pan": "Recadrer"}[g["kind"]]
        self.scene.push(g["before"], self.scene.snapshot(list(g["before"])), text)
        self.refresh()
        self.stateChanged.emit()

    # ------------------------------------------------------------------ texte, recadrage
    def edit_text(self, item: DesignTextItem, select_all: bool = False):
        self.end_crop()
        item.start_edit()
        if select_all and item.text_item is not None:
            from PySide6.QtGui import QTextCursor
            cursor = item.text_item.textCursor()
            cursor.select(QTextCursor.Document)
            item.text_item.setTextCursor(cursor)
        self.refresh()

    def start_crop(self, item: DesignImageItem):
        self._select([item])
        self.crop_item = item
        self.refresh()
        self.stateChanged.emit()

    def end_crop(self):
        if self.crop_item is None:
            return
        self.crop_item = None
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

    # ------------------------------------------------------------------ clavier
    def claims(self, event) -> bool:
        if self.text_editing():
            return False
        key, mods = event.key(), event.modifiers()
        ctrl = bool(mods & Qt.ControlModifier)
        if key in (Qt.Key_Delete, Qt.Key_Backspace, Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down,
                   Qt.Key_PageUp, Qt.Key_PageDown, Qt.Key_Return, Qt.Key_Enter):
            return True
        if ctrl and key in (Qt.Key_C, Qt.Key_X, Qt.Key_V, Qt.Key_D, Qt.Key_G, Qt.Key_A, Qt.Key_B, Qt.Key_I,
                            Qt.Key_U, Qt.Key_K, Qt.Key_L, Qt.Key_E, Qt.Key_R, Qt.Key_J, Qt.Key_P, Qt.Key_BracketLeft,
                            Qt.Key_BracketRight):
            return True
        return not ctrl and Qt.Key_A <= key <= Qt.Key_Z

    def key_press(self, event) -> bool:
        if self.text_editing():
            return False
        key, mods = event.key(), event.modifiers()
        ctrl, shift, alt = (bool(mods & Qt.ControlModifier), bool(mods & Qt.ShiftModifier),
                            bool(mods & Qt.AltModifier))
        sel = self.selection()
        scene = self.scene
        if key == Qt.Key_Escape:
            if self._gesture is not None:
                self._end_gesture(cancel=True)
                return True
            if self.crop_item is not None:
                self.end_crop()
                return True
            if sel:
                scene.clearSelection()
                return True
            return False
        if key in (Qt.Key_Return, Qt.Key_Enter):
            if self.crop_item is not None:
                self.end_crop()
            elif len(sel) == 1 and isinstance(sel[0], DesignTextItem):
                self.edit_text(sel[0])
            return True
        if key in (Qt.Key_Delete, Qt.Key_Backspace):
            if sel:
                scene.delete_items(sel)
            return True
        if ctrl and alt and key == Qt.Key_C:
            self.copy_style()
            return True
        if ctrl and alt and key == Qt.Key_V:
            self.paste_style()
            return True
        if ctrl and alt and key == Qt.Key_P:
            self.present()
            return True
        if event.matches(QKeySequence.Copy):
            self.copy()
            return True
        if event.matches(QKeySequence.Cut):
            self.copy()
            scene.delete_items(sel)
            return True
        if event.matches(QKeySequence.Paste):
            self.paste()
            return True
        if event.matches(QKeySequence.SelectAll):
            page = self.current_page()
            if page is not None:
                self._select([i for i in doc.elements(scene, page) if self.scene.item_active(i)])
            return True
        if ctrl and key == Qt.Key_D:
            self.duplicate()
            return True
        if ctrl and key == Qt.Key_G:
            doc.set_group(scene, sel, grouped=not shift)
            self.stateChanged.emit()
            return True
        if ctrl and key in (Qt.Key_BracketRight, Qt.Key_BracketLeft):
            how = ("front" if alt else "forward") if key == Qt.Key_BracketRight else ("back" if alt else "backward")
            doc.restack(scene, sel, how)
            return True
        if alt and shift and key == Qt.Key_L:
            self.toggle_lock()
            return True
        texts = [i for i in sel if isinstance(i, DesignTextItem)]
        if ctrl and texts:
            toggles = {Qt.Key_B: "bold", Qt.Key_I: "italic", Qt.Key_U: "underline"}
            if not shift and key in toggles:
                field = toggles[key]
                on = not all(i.data.get(field) for i in texts)
                doc.change(scene, texts, lambda i: i.data.update({field: on}), "Style du texte")
                return True
            if shift and key == Qt.Key_K:
                on = not all(i.data.get("uppercase") for i in texts)
                doc.change(scene, texts, lambda i: i.data.update(uppercase=on), "Majuscules")
                return True
            aligns = {Qt.Key_L: "left", Qt.Key_E: "center", Qt.Key_R: "right", Qt.Key_J: "justify"}
            if shift and key in aligns:
                doc.change(scene, texts, lambda i: i.data.update(align=aligns[key]), "Alignement du texte")
                return True
            if shift and key in (Qt.Key_Greater, Qt.Key_Less, Qt.Key_Period, Qt.Key_Comma):
                k = 1.1 if key in (Qt.Key_Greater, Qt.Key_Period) else 1 / 1.1
                doc.change(scene, texts, lambda i: i.data.update(font_size=round(i.data["font_size"] * k, 1)),
                           "Taille du texte")
                return True
        if key in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down) and not ctrl:
            if self.crop_item is not None:
                return True
            movable = [i for i in sel if not i.locked()]
            if movable:
                step = 10 if shift else 1
                dx = {Qt.Key_Left: -step, Qt.Key_Right: step}.get(key, 0)
                dy = {Qt.Key_Up: -step, Qt.Key_Down: step}.get(key, 0)
                before = scene.snapshot([i.item_id for i in movable])
                for item in movable:
                    item.moveBy(dx, dy)
                scene.push(before, scene.snapshot(list(before)), "Déplacer")
                self.refresh()
            return True
        if key in (Qt.Key_PageUp, Qt.Key_PageDown):
            pages = self.pages()
            page = self.current_page()
            if page in pages:
                n = pages.index(page) + (1 if key == Qt.Key_PageDown else -1)
                if 0 <= n < len(pages):
                    self.set_current_page(pages[n], show=True)
            return True
        if not ctrl and not alt:
            shortcuts = {Qt.Key_T: ("text", None), Qt.Key_R: ("shape", "rect"), Qt.Key_C: ("shape", "ellipse"),
                         Qt.Key_L: ("shape", "line")}
            if key in shortcuts:
                kind, shape = shortcuts[key]
                if kind == "text":
                    self.add_text("body")
                else:
                    self.add_shape(shape)
                return True
            if Qt.Key_A <= key <= Qt.Key_Z:
                return True                     # lettres prises : les outils de Miro ne s'activent pas
        return False

    def key_release(self, event) -> bool:
        if self._gesture is not None and event.key() in (Qt.Key_Shift, Qt.Key_Alt):
            last = self._gesture.get("last")
            if last is not None:
                self._update_gesture(last[0], event.modifiers())
            return True
        return False

    # ------------------------------------------------------------------ commandes
    def ensure_page(self) -> DesignPageItem:
        page = self.current_page()
        if page is None:
            w, h = dm.FORMAT_SIZES["square"]
            page = doc.add_page(self.scene, w, h, origin=self.view.view_center(), values={"format": "square"},
                                text="Nouveau design")
            self.set_current_page(page, show=True)
            self.pagesChanged.emit()
        return page

    def add_shape(self, shape: str, values: dict | None = None):
        page = self.ensure_page()
        w, h = page.size()
        side = round(min(w, h) * 0.3, 2)
        data = {"shape": shape, "w": side, "h": side}
        if shape == "line":
            data.update(w=round(w * 0.4, 2), h=24.0, stroke_width=6.0, fill_type="none", stroke=dm.INK)
        data.update(values or {})
        item = doc.add_element(self.scene, page, dm.SHAPE, data, "Ajouter une forme")
        self._select([item])
        return item

    TEXT_PRESETS = {"heading": ("Ajouter un titre", 96.0, True), "subheading": ("Ajouter un sous-titre", 56.0, True),
                    "body": ("Ajouter un peu de texte", 32.0, False)}

    def add_text(self, preset: str = "body", values: dict | None = None, edit: bool = True):
        page = self.ensure_page()
        text, size, bold = self.TEXT_PRESETS.get(preset, self.TEXT_PRESETS["body"])
        w = round(min(page.size()[0] * 0.8, max(200.0, size * len(text) * 0.55)), 2)
        data = {"text": text, "font_size": size, "bold": bold, "w": w, "h": size * 1.3}
        data.update(values or {})
        item = doc.add_element(self.scene, page, dm.TEXT, data, "Ajouter un texte")
        self._select([item])
        if edit:
            self.edit_text(item, select_all=True)
        return item

    def add_image_asset(self, asset: str, width: int, height: int, at: QPointF | None = None):
        page = self.ensure_page()
        pw, ph = page.size()
        w, h = geometry.fit_inside(float(width), float(height), pw, ph)
        values = {"asset": asset, "w": round(w, 2), "h": round(h, 2)}
        if at is not None:
            local = page.mapFromScene(at)
            values.update(x=round(local.x() - w / 2, 2), y=round(local.y() - h / 2, 2))
        item = doc.add_element(self.scene, page, dm.IMAGE, values, "Ajouter une image")
        self._select([item])
        return item

    def add_image_files(self, paths, at: QPointF | None = None) -> bool:
        from PySide6.QtGui import QImageReader
        from fm_board import serialization
        board_path = self.scene.board_path
        if board_path is None:
            return False
        added = False
        for n, path in enumerate(paths):
            reader = QImageReader(str(path))
            reader.setAutoTransform(True)
            size = reader.size()
            if not size.isValid():
                continue
            try:
                name = serialization.import_asset(board_path, path)
            except OSError:
                continue
            point = None if at is None else at + QPointF(30 * n, 30 * n)
            self.add_image_asset(name, size.width(), size.height(), point)
            added = True
        return added

    def drop_files(self, paths, at: QPointF) -> bool:
        page = self._page_at(at)
        if page is not None:
            self.set_current_page(page)
        return self.add_image_files(paths, at if page is not None else None)

    def duplicate(self):
        sel = self.selection()
        page = sel[0].page_item() if sel else None
        if page is None:
            return
        copies = doc.insert_elements(self.scene, page, self.scene.serialize(sel), offset=(20.0, 20.0),
                                     text="Dupliquer")
        self._select(copies)

    def toggle_lock(self):
        sel = self.selection()
        if sel:
            lock = not all(i.locked() for i in sel)
            self.scene.change_items(sel, lambda i: i.data.update(locked=lock),
                                    "Verrouiller" if lock else "Déverrouiller", include_locked=True)
            self.stateChanged.emit()

    def copy(self):
        from PySide6.QtCore import QByteArray, QMimeData
        from fm_board.view import CLIPBOARD_MIME
        sel = self.selection()
        if not sel:
            return
        mime = QMimeData()
        mime.setData(CLIPBOARD_MIME, QByteArray(self.scene.clipboard_payload(self.scene.serialize(sel))))
        texts = [i.data.get("text", "") for i in sel if isinstance(i, DesignTextItem)]
        if texts:
            mime.setText("\n".join(texts))
        QApplication.clipboard().setMimeData(mime)

    def paste(self):
        from fm_board.view import CLIPBOARD_MIME
        mime = QApplication.clipboard().mimeData()
        page = self.ensure_page()
        if mime.hasFormat(CLIPBOARD_MIME):
            dicts, source = self.scene.read_payload(mime.data(CLIPBOARD_MIME).data())
            dicts = [d for d in dicts if d.get("type") in dm.ELEMENT_TYPES]
            if dicts:
                same = all(self.scene.item(d["id"]) is not None and d.get("page") == page.item_id for d in dicts)
                for d in dicts:
                    if d.get("asset") and source and self.scene.board_path is not None:
                        self.scene._bring_asset(d, source)
                copies = doc.insert_elements(self.scene, page, dicts, offset=(20.0, 20.0) if same else (0.0, 0.0))
                self._select(copies)
                return
        if mime.hasUrls():
            from pathlib import Path
            if self.add_image_files([Path(u.toLocalFile()) for u in mime.urls() if u.isLocalFile()]):
                return
        if mime.hasImage() and self.scene.board_path is not None:
            from PySide6.QtCore import QBuffer, QIODevice
            from fm_board import serialization
            image = mime.imageData()
            buffer = QBuffer()
            buffer.open(QIODevice.WriteOnly)
            image.save(buffer, "PNG")
            name = serialization.import_image_bytes(self.scene.board_path, bytes(buffer.data()), ".png")
            self.add_image_asset(name, image.width(), image.height())
            return
        if mime.hasText() and mime.text().strip():
            self.add_text("body", {"text": mime.text().strip(), "bold": False}, edit=False)

    # ------------------------------------------------------------------ style, présentation
    STYLE_KEYS = ("fill", "fill_type", "fill2", "gradient_angle", "stroke", "stroke_width", "stroke_style", "radius",
                  "opacity", "shadow", "font_family", "font_size", "color", "bold", "italic", "underline", "strike",
                  "uppercase", "align", "line_height", "letter_spacing", "text_bg", "text_stroke",
                  "text_stroke_width", "brightness", "contrast", "saturation", "blur", "grayscale", "mask")

    def copy_style(self):
        """Copier le style (Ctrl+Alt+C, comme Canva) : propriétés d'aspect du premier élément choisi."""
        sel = self.selection()
        if sel:
            data = sel[0].to_dict()
            self.style_clipboard = {k: copy.deepcopy(data[k]) for k in self.STYLE_KEYS if k in data}
            self.pane._state.setText("Style copié : Ctrl+Alt+V pour l'appliquer")
            self.stateChanged.emit()

    def paste_style(self):
        """Coller le style (Ctrl+Alt+V) sur la sélection : seulement les propriétés que chaque élément possède."""
        style = getattr(self, "style_clipboard", None)
        sel = self.selection()
        if not style or not sel:
            return

        def mutate(item):
            for key, value in style.items():
                if key in dm.DEFAULTS.get(item.kind, {}):
                    item.data[key] = copy.deepcopy(value)
        doc.change(self.scene, sel, mutate, "Coller le style")

    def present(self, start_page=None):
        """Présentation plein écran (Ctrl+Alt+P), à partir de la page courante."""
        from .present import PresentationWindow
        pages = self.pages()
        if not pages:
            return None
        current = start_page or self.current_page()
        window = PresentationWindow(pages, pages.index(current) if current in pages else 0, self.pane.window())
        window.start()
        return window

    def document_colors(self) -> list[str]:
        """Couleurs utilisées dans le design (« Couleurs du document » de Canva), les plus fréquentes d'abord."""
        counts: dict[str, int] = {}
        keys = ("fill", "fill2", "stroke", "color", "background", "bg2", "text_bg", "text_stroke")
        for item in doc.pages(self.scene) + doc.elements(self.scene):
            for key in keys:
                value = item.data.get(key)
                if isinstance(value, str) and value.startswith("#") and len(value) == 7:
                    counts[value.lower()] = counts.get(value.lower(), 0) + 1
        return [c for c, _n in sorted(counts.items(), key=lambda kv: -kv[1])][:12]
