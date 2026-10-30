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

import math

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QPolygonF

from . import document as doc
from .commands import CommandMixin
from .gestures import GestureMixin
from .items import DesignElement, DesignImageItem, DesignPageItem, DesignShapeItem, DesignTextItem
from .overlay import HIT_PX, ROTATE_PX, DesignOverlay, angle_of, mid

CURSORS = {"tl": Qt.SizeFDiagCursor, "br": Qt.SizeFDiagCursor, "tr": Qt.SizeBDiagCursor, "bl": Qt.SizeBDiagCursor,
           "l": Qt.SizeHorCursor, "r": Qt.SizeHorCursor, "t": Qt.SizeVerCursor, "b": Qt.SizeVerCursor,
           "rot": Qt.PointingHandCursor}


class DesignController(GestureMixin, CommandMixin, QObject):
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
        self.preview_guide = None           # (axe, position) : repère tiré depuis une règle, pas encore posé
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
        from .rulers import Rulers
        from .ui import DesignChrome
        self.ui = DesignChrome(pane, self)
        self.rulers = Rulers(self)
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
        self.rulers.place()
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
        self.rulers.place()
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
            # Élément petit à l'écran : poignées de côté retirées là où elles chevaucheraient les coins.
            zoom = max(0.01, self.scene.zoom)
            w, h = single.size()
            if h * zoom < 36 and not line:
                sides = [s for s in sides if s not in ("t", "b")]
            if w * zoom < 36 and not line:
                sides = [s for s in sides if s not in ("l", "r")]
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
            guide = self.guide_at(pos)
            if guide is not None and self._element_at(pos) is None:
                self._press = ("guide_menu", pos, guide)
                return True
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
        guide = self.guide_at(pos) if mods & Qt.ControlModifier and target is None else None
        if guide is not None:                        # Ctrl + glisser un repère (règle de l'appli)
            page, n = guide
            self.scene.commit_live()
            self._gesture = {"kind": "guide", "page": page, "guide": n, "items": [], "moved": False,
                             "before": self.scene.snapshot([page.item_id]),
                             "guides0": [dict(x) for x in page.data.get("guides") or []]}
            return True
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
            self._marquee_start(pos, scene_pos, mods, on_element=True)
            return True
        if not mods & Qt.ShiftModifier:
            self.scene.clearSelection()
        self._press = ("click", pos, None)
        self._marquee_start(pos, scene_pos, mods, on_element=False)
        return True

    def guide_at(self, view_pos):
        """(page, index) du repère sous le pointeur (6 px), sinon None."""
        scene_pos = self.view.mapToScene(view_pos.toPoint() if hasattr(view_pos, "toPoint") else view_pos)
        page = self._page_at(scene_pos)
        if page is None:
            return None
        local = page.mapFromScene(scene_pos)
        reach = 6.0 / max(0.01, self.scene.zoom)
        for n, guide in enumerate(page.data.get("guides") or []):
            value = local.x() if guide["axis"] == "v" else local.y()
            if abs(value - float(guide["pos"])) <= reach:
                return page, n
        return None

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
        if press[0] == "guide_menu":
            from .menus import guide_menu
            guide_menu(self, press[2], self.view.viewport().mapToGlobal(event.position().toPoint()))
            return True
        if press[0] == "menu":
            from .menus import open_context_menu
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

    # ------------------------------------------------------------------ clavier
    def claims(self, event) -> bool:
        if self.text_editing():                  # style d'une partie du texte : jamais pris par la fenêtre
            return bool(event.modifiers() & Qt.ControlModifier) and event.key() in (
                Qt.Key_B, Qt.Key_I, Qt.Key_U, Qt.Key_Greater, Qt.Key_Less, Qt.Key_Period, Qt.Key_Comma)
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
        if shift and not ctrl and not alt and key == Qt.Key_R:
            self.rulers.set_visible(not self.rulers.visible)
            return True
        if key == Qt.Key_Question or (shift and key == Qt.Key_Comma):
            from .menus import show_shortcuts
            show_shortcuts(self)
            return True
        if not ctrl and not alt and not shift:
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
