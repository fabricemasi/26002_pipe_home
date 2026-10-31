"""Module Illustrator du board : CONTRÔLEUR (activation, souris, clavier, sélection, commandes).

Activé par le bouton « Illustrator » du sélecteur de modules (`BoardPane.set_module("illustrator")`). Actif, la vue du
board lui confie la souris (boutons gauche et droit) et le clavier ; la molette, le bouton du milieu et Espace tenu
déplacent / zooment toujours le board. Les gestes de chaque outil sont dans `tools.py`.

Règle de l'appli : TOUT déplacement d'élément commence avec Ctrl enfoncé (Sélection : Ctrl + glisser = déplacer,
Ctrl + Alt + glisser = déplacer une copie ; glisser sans Ctrl = cadre de sélection). Modifier la géométrie (poignées de
la boîte, points d'ancrage, poignées de Bézier) n'est pas un déplacement d'élément : sans Ctrl.
Une étape d'annulation par geste ou par commande (annulation du board)."""
from __future__ import annotations

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, Signal
from PySide6.QtWidgets import QGraphicsView

from fm_board import model as board_model
from . import bezier as bz, model
from .items import IllArtboardItem, IllItem, IllPathItem
from .overlay import IllOverlay
from .tools import TOOL_KEYS
from .tools_draw import make_tools

HIT_PX = 5.0                    # tolérance de la souris (pixels d'écran)
NUDGE = 1.0                     # flèches : 1 unité (Maj : 10), comme l'« incrément clavier » d'Illustrator


class IllustratorController(QObject):
    stateChanged = Signal()                # sélection, outil, style courant : barres à jour

    def __init__(self, pane):
        super().__init__(pane)
        self.pane = pane
        self.view = pane.view
        self.scene = pane.scene
        self.active = False
        self.tool = "select"
        self.style = dict(model.DEFAULT_STYLE)     # style des nouveaux objets (fond / contour courants)
        self.focus = "fill"                        # X : le fond ou le contour est au premier plan
        self.anchors: dict[str, set] = {}          # Sélection directe : {id: {(sous-tracé, nœud)}}
        self.artboard_id = ""                      # plan de travail choisi (outil Plan de travail)
        self.hover = None                          # objet survolé (contour accent)
        self.marquee: QRectF | None = None
        self.preview = None                        # dessin temporaire de l'outil (ligne élastique de la plume…)
        self.tip = None                            # (point de scène, texte) : taille / angle pendant un geste
        self.style_clipboard = None
        self.tools = make_tools(self)
        self.overlay = IllOverlay(self)
        self.scene.addItem(self.overlay)
        self.scene.selectionChanged.connect(self._on_selection)
        self.scene.contentChanged.connect(self.refresh)
        self.view.zoomChanged.connect(lambda _z: self.refresh())
        from .ui import IllustratorChrome
        self.ui = IllustratorChrome(pane, self)

    # ------------------------------------------------------------------ activation
    def activate(self):
        if self.active:
            return
        self.active = True
        # Comme Design : seule la zone qui change est repeinte (sélection, survol, ligne élastique).
        self._update_mode = self.view.viewportUpdateMode()
        self.view.setViewportUpdateMode(QGraphicsView.MinimalViewportUpdate)
        self.view.finish_text_edit()
        self.view.set_tool("select")
        for item in self.scene.selectedItems():
            if not isinstance(item, IllItem):
                item.setSelected(False)
        self.ui.show()
        self.refresh()
        self.view.setFocus()
        self.stateChanged.emit()

    def deactivate(self):
        if not self.active:
            return
        self.current_tool().cancel()
        self.active = False
        self.view.setViewportUpdateMode(getattr(self, "_update_mode", QGraphicsView.FullViewportUpdate))
        self.hover = None
        self.preview = None
        self.marquee = None
        self.ui.hide()
        self.refresh()
        self.view._sync_cursor()
        self.stateChanged.emit()

    def apply_settings(self):
        self.refresh()

    def busy(self) -> bool:
        """Échap a quelque chose à annuler ici (geste, tracé en cours, sélection) ; sinon le board décide (fermer)."""
        return bool(self.current_tool().busy() or self.selection() or self.artboard_id or self.marquee is not None)

    # ------------------------------------------------------------------ éléments
    def objects(self) -> list[IllPathItem]:
        return sorted((i for i in self.scene.board_items() if isinstance(i, IllPathItem)), key=lambda i: i.zValue())

    def artboards(self) -> list[IllArtboardItem]:
        return sorted(getattr(self.scene, "ill_artboards", ()), key=lambda i: float(i.data.get("index", 0)))

    def selection(self) -> list[IllPathItem]:
        return sorted((i for i in self.scene.selectedItems() if isinstance(i, IllPathItem)), key=lambda i: i.zValue())

    def selected_artboard(self) -> IllArtboardItem | None:
        item = self.scene.item(self.artboard_id) if self.artboard_id else None
        return item if isinstance(item, IllArtboardItem) else None

    def editable(self, item) -> bool:
        return (isinstance(item, IllItem) and item.isVisible() and item.isEnabled() and not item.locked()
                and self.scene.item_active(item))

    def tolerance(self, px: float = HIT_PX) -> float:
        return px / max(1e-6, self.view.zoom())

    def scene_pos(self, event) -> QPointF:
        return self.view.mapToScene(event.position().toPoint())

    def object_at(self, pos: QPointF, px: float = HIT_PX) -> IllPathItem | None:
        """Objet le plus haut sous `pos` (surface s'il a un fond, sinon son contour, à `px` pixels près)."""
        t = self.tolerance(px)
        for item in self.scene.items(QRectF(pos.x() - t, pos.y() - t, 2 * t, 2 * t), Qt.IntersectsItemBoundingRect,
                                     Qt.DescendingOrder):
            if isinstance(item, IllPathItem) and self.editable(item) and item.contains_scene_point(pos, px):
                return item
        return None

    def artboard_at(self, pos: QPointF) -> IllArtboardItem | None:
        for item in self.scene.items(pos, Qt.IntersectsItemBoundingRect, Qt.DescendingOrder):
            if isinstance(item, IllArtboardItem) and item.isVisible() and item.scene_rect().contains(pos):
                return item
        return None

    def group_of(self, item) -> list[IllPathItem]:
        group = item.data.get("group") or ""
        if not group:
            return [item]
        return [i for i in self.objects() if i.data.get("group") == group]

    def select(self, items, add: bool = False, toggle: bool = False):
        """Sélection en UN changement : signaux de la scène retenus pendant la boucle, puis un seul
        `selectionChanged` (élément par élément, tout le board réagissait à chacun : tout choisir parmi 2 000 prenait
        ~41 s)."""
        scene = self.scene
        before = set(scene.selectedItems())
        wanted = set(items)
        blocked = scene.blockSignals(True)
        try:
            if not add and not toggle:
                for item in before - wanted:
                    item.setSelected(False)
            for item in items:
                item.setSelected(not item.isSelected() if toggle else True)
        finally:
            scene.blockSignals(blocked)
        if set(scene.selectedItems()) != before:
            scene.selectionChanged.emit()

    def clear_selection(self):
        self.scene.clearSelection()
        self.anchors.clear()

    def selection_rect(self, items=None) -> QRectF | None:
        """Boîte englobante de la sélection (géométrie, sans l'épaisseur des contours : comme Illustrator)."""
        rect = None
        for item in self.selection() if items is None else items:
            r = item.geometry_rect()
            rect = r if rect is None else rect.united(r)
        return rect

    def _on_selection(self):
        try:
            alive = {i.item_id for i in self.selection()}
        except RuntimeError:                                 # scène détruite (fermeture du board)
            return
        for key in [k for k in self.anchors if k not in alive]:
            del self.anchors[key]
        self.refresh()
        self.stateChanged.emit()

    # ------------------------------------------------------------------ modifications (une étape chacune)
    def new_path(self, subpaths, origin: QPointF, style: dict | None = None, **extra) -> IllPathItem:
        """Tracé créé SANS étape d'annulation (geste en cours) ; `commit_new` l'enregistre."""
        data = board_model.new_item(model.PATH, x=round(origin.x(), 3), y=round(origin.y(), 3),
                                    subpaths=subpaths, **(style or self.style), **extra)
        data["z"] = self.scene.next_z()
        return self.scene._add(data)

    def commit_new(self, item, text: str):
        self.scene.push({item.item_id: None}, self.scene.snapshot([item.item_id]), text)
        self.clear_selection()
        item.setSelected(True)

    def discard(self, item):
        self.scene._remove(item.item_id)

    def change(self, items, change, text: str):
        """`change(item)` modifie `item.data` ; une étape d'annulation."""
        self.scene.change_items([i for i in items if isinstance(i, IllItem)], change, text)
        self.refresh()
        self.stateChanged.emit()

    def set_style(self, key: str, value, text: str = "Style"):
        """Attribut de peinture : sélection (une étape) et style des nouveaux objets."""
        self.style[key] = value
        items = self.selection()
        if items:
            self.change(items, lambda i: i.data.update({key: value}), text)
        self.stateChanged.emit()

    def live_style(self, key: str, value, text: str = "Style"):
        """Pendant un curseur / une couleur glissée : une étape par geste (`scene.commit_live`)."""
        self.style[key] = value
        items = self.selection()
        if items:
            self.scene.live_change(f"ill:{key}", items, lambda i: i.data.update({key: value}), text)
        self.stateChanged.emit()

    def delete_selection(self):
        if any(self.anchors.values()):
            self.delete_anchors()
            return
        board = self.selected_artboard()
        items = self.selection()
        if board is not None and not items:
            self.scene.delete_items([board])
            self.artboard_id = ""
            return
        if items:
            self.scene.delete_items(items)
            self.anchors.clear()

    def delete_anchors(self):
        """Suppr en Sélection directe : les points choisis et leurs segments disparaissent (le tracé s'ouvre ou se
        coupe), comme Illustrator ; un tracé sans segment disparaît."""
        targets = [i for i in self.selection() if self.anchors.get(i.item_id)]
        empty = []

        def cut(item):
            chosen = self.anchors.get(item.item_id, set())
            out = []
            for si, sub in enumerate(item.data["subpaths"]):
                out += _split_without(sub, {ni for s, ni in chosen if s == si})
            item.data["subpaths"] = out
            if not out:
                empty.append(item)
        self.change(targets, cut, "Supprimer des points")
        self.anchors.clear()
        if empty:
            self.scene.delete_items(empty)

    def nudge(self, dx: float, dy: float):
        if any(self.anchors.values()):
            def move(item):
                for si, ni in self.anchors.get(item.item_id, ()):
                    bz.move_node(item.data["subpaths"][si]["nodes"][ni], dx, dy)
            self.change([i for i in self.selection() if self.anchors.get(i.item_id)], move, "Déplacer des points")
            return
        items = self.selection()
        if items:
            self.change(items, lambda i: i.data.update(x=i.data["x"] + dx, y=i.data["y"] + dy), "Déplacer")

    def transform_selection(self, matrix, text: str, items=None):
        """Matrice (repère de la scène) appliquée aux nœuds de chaque objet."""
        items = self.selection() if items is None else items

        def apply(item):
            px, py = item.data["x"], item.data["y"]
            local = bz.multiply(bz.multiply(bz.translate(px, py), matrix), bz.translate(-px, -py))
            bz.transform(item.data["subpaths"], local)
        self.change(items, apply, text)

    def flip(self, horizontal: bool):
        rect = self.selection_rect()
        if rect is None:
            return
        c = rect.center()
        m = bz.scale(-1, 1, c.x(), c.y()) if horizontal else bz.scale(1, -1, c.x(), c.y())
        self.transform_selection(m, "Symétrie")

    def rotate_selection(self, degrees: float):
        rect = self.selection_rect()
        if rect is not None:
            self.transform_selection(bz.rotate(degrees, rect.center().x(), rect.center().y()), "Rotation")

    def set_group(self, grouped: bool):
        items = self.selection()
        if not items:
            return
        gid = board_model.new_id() if grouped else ""
        self.change(items, lambda i: i.data.update(group=gid), "Grouper" if grouped else "Dissocier")

    def arrange(self, how: str):
        """Disposition : « front » (Ctrl+Maj+]), « forward » (Ctrl+]), « backward » (Ctrl+[), « back » (Ctrl+Maj+[)."""
        items = self.selection()
        if not items:
            return
        if how == "front":
            self.scene.bring_to_front(items)
        elif how == "back":
            self.scene.send_to_back(items)
        else:
            self.scene.step_z(items, 1 if how == "forward" else -1)
        self.refresh()

    def lock_selection(self):
        items = self.selection()
        if items:
            self.scene.clearSelection()
            self.scene.change_items(items, lambda i: i.data.update(locked=True), "Verrouiller")

    def unlock_all(self):
        locked = [i for i in self.objects() if i.locked()]
        if locked:
            self.scene.change_items(locked, lambda i: i.data.update(locked=False), "Tout déverrouiller",
                                    include_locked=True)
            self.select(locked)

    def hide_selection(self):
        items = self.selection()
        if items:
            self.scene.clearSelection()
            self.change(items, lambda i: i.data.update(hidden=True), "Masquer")

    def show_all(self):
        hidden = [i for i in self.objects() if i.data.get("hidden")]
        if hidden:
            self.change(hidden, lambda i: i.data.update(hidden=False), "Tout afficher")
            self.select(hidden)

    def join_selection(self):
        """Joindre (Ctrl+J) : relie les deux extrémités ouvertes les plus proches de la sélection (deux tracés
        ouverts, ou un tracé ouvert qui se ferme)."""
        items = [i for i in self.selection() if any(not s["closed"] for s in i.data["subpaths"])]
        if len(items) == 1:
            def close(item):
                for sub in item.data["subpaths"]:
                    if not sub["closed"] and len(sub["nodes"]) > 1:
                        sub["closed"] = True
                        bz.close_if_touching({"closed": False, "nodes": sub["nodes"]}, 0.01)
                        break
            self.change(items, close, "Joindre")
            return
        if len(items) != 2:
            return
        a, b = items
        best = None
        for ia, sa in enumerate(a.data["subpaths"]):
            if sa["closed"]:
                continue
            for ib, sb in enumerate(b.data["subpaths"]):
                if sb["closed"]:
                    continue
                for a_end in (True, False):
                    for b_start in (True, False):
                        na = sa["nodes"][-1 if a_end else 0]
                        nb = sb["nodes"][0 if b_start else -1]
                        d = (na[0] + a.data["x"] - nb[0] - b.data["x"]) ** 2 + \
                            (na[1] + a.data["y"] - nb[1] - b.data["y"]) ** 2
                        if best is None or d < best[0]:
                            best = (d, ia, ib, a_end, b_start)
        if best is None:
            return
        _d, ia, ib, a_end, b_start = best
        moved = bz.copy_subpaths([b.data["subpaths"][ib]])
        bz.transform(moved, bz.translate(b.data["x"] - a.data["x"], b.data["y"] - a.data["y"]))
        joined = bz.join(a.data["subpaths"][ia], moved[0], a_end, b_start)
        rest_b = [s for k, s in enumerate(b.data["subpaths"]) if k != ib]
        new_a = a.to_dict()
        new_a["id"] = board_model.new_id()          # remplacés : identifiants neufs (annulation de replace_items)
        new_a["subpaths"] = [joined if k == ia else s for k, s in enumerate(a.data["subpaths"])]
        added = [new_a]
        if rest_b:
            new_b = b.to_dict()
            new_b.update(id=board_model.new_id(), subpaths=rest_b)
            added.append(new_b)
        result = self.scene.replace_items([a, b], added, "Joindre")
        self.select(result[:1])

    def make_compound(self, compound: bool):
        """Tracé transparent (Ctrl+8) : les sous-tracés des objets choisis en UN objet (style du plus haut), règle
        pair-impair ; Ctrl+Alt+Maj+8 = défaire en un objet par sous-tracé."""
        items = self.selection()
        if compound and len(items) > 1:
            top = items[-1]
            subs = []
            for item in items:
                moved = bz.copy_subpaths(item.data["subpaths"])
                bz.transform(moved, bz.translate(item.data["x"] - top.data["x"], item.data["y"] - top.data["y"]))
                subs += moved
            data = top.to_dict()
            data.update(id=board_model.new_id(), subpaths=subs, fill_rule="evenodd", group="")
            self.select(self.scene.replace_items(items, [data], "Tracé transparent"))
        elif not compound:
            parts = [i for i in items if len(i.data["subpaths"]) > 1]
            added = []
            for item in parts:
                for sub in item.data["subpaths"]:
                    data = item.to_dict()
                    data.update(subpaths=[sub], id=board_model.new_id(), fill_rule="nonzero")
                    added.append(data)
            if parts:
                self.select(self.scene.replace_items(parts, added, "Défaire le tracé transparent"))

    def copy_style(self):
        items = self.selection()
        if items:
            self.style_clipboard = model.style_of(items[-1].data)

    def paste_style(self):
        style = self.style_clipboard
        if style and self.selection():
            self.change(self.selection(), lambda i: i.data.update(style), "Coller le style")

    def eyedrop(self, source: IllPathItem):
        """Pipette (I) : le style de `source` va à la sélection et devient le style courant."""
        style = model.style_of(source.data)
        self.style.update(style)
        targets = [i for i in self.selection() if i is not source]
        if targets:
            self.change(targets, lambda i: i.data.update(style), "Pipette")
        self.stateChanged.emit()

    def swap_fill_stroke(self):
        """Maj+X : intervertit fond et contour (sélection et style courant)."""
        self.style["fill"], self.style["stroke"] = self.style["stroke"], self.style["fill"]
        items = self.selection()
        if items:
            self.change(items, lambda i: i.data.update(fill=i.data["stroke"], stroke=i.data["fill"]),
                        "Intervertir fond et contour")
        self.stateChanged.emit()

    def default_colors(self):
        """D : fond blanc, contour noir 1 pt."""
        values = {"fill": model.DEFAULT_FILL, "stroke": model.DEFAULT_STROKE, "stroke_width": 1.0}
        self.style.update(values)
        if self.selection():
            self.change(self.selection(), lambda i: i.data.update(values), "Couleurs par défaut")
        self.stateChanged.emit()

    def set_none(self):
        """/ : aucun pour l'attribut au premier plan (fond ou contour)."""
        self.set_style(self.focus, "", "Aucun")

    # -- plans de travail --
    def add_artboard(self, rect: QRectF | None = None, name: str = "", size=None) -> IllArtboardItem:
        boards = self.artboards()
        index = (max(float(b.data.get("index", 0)) for b in boards) + 1) if boards else 0
        if rect is None:
            w, h = size or (model.DEFAULTS[model.ARTBOARD]["w"], model.DEFAULTS[model.ARTBOARD]["h"])
            if boards:                                       # à droite du dernier, comme Illustrator
                last = boards[-1].scene_rect()
                rect = QRectF(last.right() + 40, last.top(), w, h)
            else:
                c = self.view.view_center()
                rect = QRectF(c.x() - w / 2, c.y() - h / 2, w, h)
        data = board_model.new_item(model.ARTBOARD, x=round(rect.x(), 3), y=round(rect.y(), 3),
                                    w=round(rect.width(), 3), h=round(rect.height(), 3), index=index,
                                    name=name or f"Plan de travail {len(boards) + 1}")
        item = self.scene.add_new(data, "Nouveau plan de travail", select=False)
        self.artboard_id = item.item_id
        self.refresh()
        return item

    def current_artboard(self) -> IllArtboardItem | None:
        """Plan choisi, sinon celui qui contient la sélection, sinon celui au centre de la vue, sinon le premier."""
        board = self.selected_artboard()
        if board is not None:
            return board
        rect = self.selection_rect()
        boards = self.artboards()
        for point in ([rect.center()] if rect is not None else []) + [self.view.view_center()]:
            for b in boards:
                if b.scene_rect().contains(point):
                    return b
        return boards[0] if boards else None

    # -- export / import SVG --
    def export_data(self, area: QRectF | None, only_selection: bool = False) -> list[dict]:
        items = self.selection() if only_selection else self.objects()
        out = []
        for item in items:
            if area is not None and not item.sceneBoundingRect().intersects(area):
                continue
            out.append(item.to_dict())
        return out

    def export_svg(self, path, board: IllArtboardItem | None = None, only_selection: bool = False):
        from pathlib import Path
        from . import svg
        if board is not None:
            r = board.scene_rect()
            area = (r.x(), r.y(), r.width(), r.height())
            text = svg.export_svg(self.export_data(r, only_selection), area,
                                  background="", title=str(board.data.get("name", "")))
        else:
            text = svg.export_svg(self.export_data(None, only_selection))
        target = Path(path)
        part = target.with_name(target.name + ".part")
        part.write_text(text, encoding="utf-8")
        part.replace(target)                                 # écriture atomique
        return target

    def import_svg(self, path, at: QPointF | None = None) -> list[IllPathItem]:
        """Objets d'un fichier SVG posés au centre de la vue (une étape) ; groupes gardés."""
        from pathlib import Path
        from . import svg
        entities = svg.import_svg(Path(path).read_text(encoding="utf-8"))
        box = bz.union_bounds(svg._object_bounds(e) for e in entities)
        if box is None:
            return []
        at = at or self.view.view_center()
        dx, dy = at.x() - (box[0] + box[2]) / 2, at.y() - (box[1] + box[3]) / 2
        groups = {}
        added = []
        z = self.scene.next_z()
        for e in entities:
            e = dict(e)
            if e.get("group"):
                e["group"] = groups.setdefault(e["group"], board_model.new_id())
            data = board_model.new_item(model.PATH, **{k: v for k, v in e.items() if k not in ("id", "type")})
            data["x"], data["y"], data["z"] = dx, dy, z
            z += 1
            added.append(data)
        items = self.scene.replace_items([], added, "Importer un SVG")
        self.select(items)
        return items

    # ------------------------------------------------------------------ outils
    def current_tool(self):
        return self.tools[self.tool]

    def set_tool(self, name: str):
        if name not in self.tools:
            return
        if name != self.tool:
            self.current_tool().cancel()
        self.tool = name
        if name != "direct":
            self.anchors.clear()
        if name != "artboard":
            self.artboard_id = ""
        self.preview = None
        self.sync_cursor()
        self.refresh()
        self.stateChanged.emit()

    # ------------------------------------------------------------------ événements (appelés par BoardView)
    def mouse_press(self, event) -> bool:
        if event.button() == Qt.RightButton:
            self.current_tool().cancel()
            from .menus import open_context_menu
            open_context_menu(self, event.globalPosition().toPoint(), self.scene_pos(event))
            return True
        if event.button() != Qt.LeftButton:
            return False
        self.scene.commit_live()
        self.current_tool().press(self.scene_pos(event), event.modifiers())
        self.refresh()
        return True

    def mouse_move(self, event) -> bool:
        tool = self.current_tool()
        if event.buttons() & Qt.LeftButton:
            tool.drag(self.scene_pos(event), event.modifiers())
        else:
            tool.hover(self.scene_pos(event), event.modifiers())
        self.refresh()
        return True

    def mouse_release(self, event) -> bool:
        if event.button() != Qt.LeftButton:
            return event.button() == Qt.RightButton
        self.current_tool().release(self.scene_pos(event), event.modifiers())
        self.refresh()
        self.stateChanged.emit()
        return True

    def mouse_double_click(self, event) -> bool:
        if event.button() != Qt.LeftButton:
            return False
        return self.current_tool().double_click(self.scene_pos(event), event.modifiers())

    def sync_cursor(self) -> bool:
        if not self.active:
            return False
        self.view.viewport().setCursor(self.current_tool().cursor())
        return True

    def claims(self, event) -> bool:
        """Raccourcis gardés en mode Illustrator (la fenêtre principale ne les reçoit pas)."""
        key, mods = event.key(), event.modifiers()
        ctrl = bool(mods & Qt.ControlModifier)
        if key in (Qt.Key_Delete, Qt.Key_Backspace, Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down,
                   Qt.Key_Return, Qt.Key_Enter, Qt.Key_Slash, Qt.Key_Plus, Qt.Key_Minus, Qt.Key_Equal,
                   Qt.Key_Backslash):
            return True
        if ctrl and key in (Qt.Key_G, Qt.Key_J, Qt.Key_Y, Qt.Key_A, Qt.Key_2, Qt.Key_3, Qt.Key_8, Qt.Key_BracketLeft,
                            Qt.Key_BracketRight, Qt.Key_At, Qt.Key_Eacute, Qt.Key_QuoteDbl, Qt.Key_Underscore):
            return True
        return not ctrl and Qt.Key_A <= key <= Qt.Key_Z

    def key_press(self, event) -> bool:
        key, mods = event.key(), event.modifiers()
        ctrl, shift, alt = (bool(mods & Qt.ControlModifier), bool(mods & Qt.ShiftModifier),
                            bool(mods & Qt.AltModifier))
        tool = self.current_tool()
        if tool.key_press(key, mods):
            self.refresh()
            return True
        if key == Qt.Key_Escape:
            if self.selection() or self.artboard_id:
                self.clear_selection()
                self.artboard_id = ""
                self.refresh()
                return True
            return False                                     # rien à annuler : le board décide (fermer…)
        if key in (Qt.Key_Delete, Qt.Key_Backspace):
            self.delete_selection()
            return True
        arrows = {Qt.Key_Left: (-1, 0), Qt.Key_Right: (1, 0), Qt.Key_Up: (0, -1), Qt.Key_Down: (0, 1)}
        if key in arrows and not ctrl:
            step = NUDGE * (10 if shift else 1)
            self.nudge(arrows[key][0] * step, arrows[key][1] * step)
            return True
        if ctrl:
            return self._ctrl_key(key, shift, alt)
        if alt:
            return False
        if shift and key == Qt.Key_X:
            self.swap_fill_stroke()
            return True
        if not shift and key == Qt.Key_X:
            self.focus = "stroke" if self.focus == "fill" else "fill"
            self.stateChanged.emit()
            return True
        if not shift and key == Qt.Key_D:
            self.default_colors()
            return True
        if key == Qt.Key_Slash:
            self.set_none()
            return True
        name = TOOL_KEYS.get((key, shift))
        if name is not None:
            self.set_tool(name)
            return True
        return False

    def _ctrl_key(self, key, shift: bool, alt: bool) -> bool:
        if key == Qt.Key_G:
            self.set_group(not shift)
        elif key == Qt.Key_J:
            self.join_selection()
        elif key == Qt.Key_Y:
            self.toggle_outline()
        elif key == Qt.Key_A:
            if shift:
                self.clear_selection()
            else:
                self.select([i for i in self.objects() if self.editable(i)])
        elif key in (Qt.Key_2, Qt.Key_Eacute):              # Ctrl+2 (clavier AZERTY : « é »)
            self.unlock_all() if alt else self.lock_selection()
        elif key in (Qt.Key_3, Qt.Key_QuoteDbl):            # Ctrl+3 (AZERTY : « " »)
            self.show_all() if alt else self.hide_selection()
        elif key in (Qt.Key_8, Qt.Key_Underscore):          # Ctrl+8 (AZERTY : « _ »)
            self.make_compound(not (alt and shift))
        elif key == Qt.Key_BracketRight:
            self.arrange("front" if shift else "forward")
        elif key == Qt.Key_BracketLeft:
            self.arrange("back" if shift else "backward")
        else:
            return False                                     # Ctrl+Z / C / V / X / D… : le board
        self.refresh()
        return True

    def key_release(self, event) -> bool:
        return self.current_tool().key_release(event.key(), event.modifiers())

    def drop_files(self, paths, at: QPointF) -> bool:
        svgs = [p for p in paths if p.suffix.lower() == ".svg"]
        for path in svgs:
            self.import_svg(path, at)
        return bool(svgs)

    def toggle_outline(self):
        """Mode Tracés (Ctrl+Y) : contours fins sans peinture (affichage seulement)."""
        self.scene.ill_outline = not bool(getattr(self.scene, "ill_outline", False))
        for item in self.objects():
            item.update()
        self.stateChanged.emit()

    # ------------------------------------------------------------------ affichage
    def refresh(self):
        if self.overlay.scene() is not None:
            self.overlay.refresh()


def _split_without(sub: dict, removed: set) -> list[dict]:
    """Sous-tracés restants quand les nœuds `removed` (et leurs segments) disparaissent."""
    nodes = sub["nodes"]
    if not removed:
        return [sub]
    count = len(nodes)
    if sub.get("closed"):
        start = min(removed)
        order = [(start + k) % count for k in range(1, count)]           # après le 1er nœud retiré
    else:
        order = list(range(count))
    runs, run = [], []
    for index in order:
        if index in removed:
            if run:
                runs.append(run)
            run = []
        else:
            run.append(nodes[index])
    if run:
        runs.append(run)
    out = []
    for run in runs:
        if len(run) > 1:
            run[0][2], run[0][3] = run[0][0], run[0][1]                  # extrémités : sans poignée vers le vide
            run[-1][4], run[-1][5] = run[-1][0], run[-1][1]
            out.append({"closed": False, "nodes": run})
    return out
