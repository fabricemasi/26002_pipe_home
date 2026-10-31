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
from . import layers as lay, look, model
from .ctl_commands import CommandMixin
from .ctl_content import ContentMixin
from .items import IllArtboardItem, IllImageItem, IllItem, IllPathItem, IllTextItem
from .overlay import IllOverlay
from .tools import TOOL_KEYS
from .tools_draw import make_tools

HIT_PX = 5.0                    # tolérance de la souris (pixels d'écran)
NUDGE = 1.0                     # flèches : 1 unité (Maj : 10), comme l'« incrément clavier » d'Illustrator ;
NUDGE_BIG = 10.0                # réglables (Réglages : Board > Illustrator, look.push)

class IllustratorController(ContentMixin, CommandMixin, QObject):
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
        self.layer_id = ""                         # calque courant (les objets neufs y vont)
        self._pending_layer = None                 # calque créé avec le 1er objet (même étape d'annulation)
        from .brushes import CALLIGRAPHIC
        self.brush = dict(CALLIGRAPHIC)            # pointe du Pinceau (B)
        self.blob_size = 20.0                      # diamètre de l'outil Forme de tache (Maj+B)
        look.push()                                # réglages recopiés dans les modules chargés
        self.smart_guides = bool(look.value("smart_guides"))     # repères commentés (Ctrl+U : la session)
        self.guides: list = []                     # lignes des repères commentés du geste en cours
        self.last_transform = None                 # {"matrix", "copy"} : Transformer de nouveau (Ctrl+D)
        self.editor = None                         # texte édité sur place (text.TextEditor)
        self._edit = None                          # (élément, avant, neuf, tracé remplacé) de l'édition en cours
        self._forward = False                      # geste de souris confié à l'éditeur de texte (Qt)
        self.hover = None                          # objet survolé (contour accent)
        self.marquee: QRectF | None = None
        self.preview = None                        # dessin temporaire de l'outil (ligne élastique de la plume…)
        self.tip = None                            # (point de scène, texte) : taille / angle pendant un geste
        self.style_clipboard = None
        from .trace import settings_for
        self.trace_settings = settings_for("color6", detail=look.value("trace_detail"))  # (session)
        self._trace_relay = None
        self.tools = make_tools(self)
        self.overlay = IllOverlay(self)
        self.scene.addItem(self.overlay)
        self.scene.selectionChanged.connect(self._on_selection)
        self.scene.contentChanged.connect(self.refresh)
        self.view.zoomChanged.connect(self._on_zoom)
        self.zoom_snapshot = None
        self._painted_rect = None
        from PySide6.QtCore import QTimer
        self._snap_timer = QTimer(self)
        self._snap_timer.setSingleShot(True)
        self._snap_timer.setInterval(300)               # après le retour des images gardées (250 ms, coque)
        self._snap_timer.timeout.connect(self._end_snapshot)
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


    def _on_zoom(self, _zoom):
        """Zoom continu avec beaucoup d'objets visibles : image de la vue reposée à l'échelle (`snapshot.py`)."""
        from . import snapshot
        if self.active and self.view.zooming():
            self._snap_timer.start()
            if self.zoom_snapshot is None:
                snapshot.take(self)
        self.refresh()

    def _end_snapshot(self):
        from . import snapshot
        if self.view.zooming():
            self._snap_timer.start()
            return
        snapshot.drop(self)

    def deactivate(self):
        if not self.active:
            return
        self._end_snapshot()
        self.end_text_edit()
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
        """Réglages changés (look.apply_settings a recopié les valeurs) : dessin temporaire et barres à jour."""
        self.overlay._key = None
        for item in self.artboards():
            item.update()
        self.refresh()
        self.stateChanged.emit()


    def busy(self) -> bool:
        """Échap a quelque chose à annuler ici (geste, tracé en cours, sélection) ; sinon le board décide (fermer)."""
        return bool(self.editor is not None or self.current_tool().busy() or self.selection() or self.artboard_id
                    or self.marquee is not None)


    def shapes(self) -> list[IllPathItem]:
        """Sélection sans les textes : opérations de géométrie (Pathfinder, joindre, tracé transparent…), qui
        demandent des contours (Ctrl+Maj+O), comme dans Illustrator."""
        return [i for i in self.selection() if not isinstance(i, (IllTextItem, IllImageItem))]


    def shapes_all(self) -> list[IllPathItem]:
        """Tous les tracés (ni textes, ni images), du bas vers le haut."""
        return [i for i in self.objects() if not isinstance(i, (IllTextItem, IllImageItem))]


    def texts(self) -> list[IllTextItem]:
        return [i for i in self.selection() if isinstance(i, IllTextItem)]


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
        if not (isinstance(item, IllItem) and item.isVisible() and item.isEnabled() and not item.locked()
                and self.scene.item_active(item)):
            return False
        if isinstance(item, IllPathItem):
            layer = lay.layer_of(self.scene, item)
            return layer is None or not layer.data.get("content_locked")
        return True


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
        """Boîte englobante de la sélection (géométrie, sans l'épaisseur des contours : comme Illustrator) ; un objet
        écrêté compte pour sa partie dans le masque."""
        rect = None
        for item in self.selection() if items is None else items:
            r = item.geometry_rect()
            mask = item.mask_item()
            if mask is not None and mask.data.get("mask") == "clip":
                r = r.intersected(mask.geometry_rect())
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
        layer = self.ensure_layer()
        values = dict(style or self.style)
        values.update(extra)
        data = board_model.new_item(model.PATH, x=round(origin.x(), 3), y=round(origin.y(), 3),
                                    subpaths=subpaths, **values)
        data["layer"] = layer.item_id
        data["z"] = lay.top_z(self.scene, layer, self.objects())
        return self.scene._add(data)


    def commit_new(self, item, text: str):
        ids = [item.item_id]
        layer, self._pending_layer = self._pending_layer, None
        if layer is not None and layer.scene() is not None:
            ids.insert(0, layer.item_id)
        self.scene.push({i: None for i in ids}, self.scene.snapshot(ids), text)
        self.clear_selection()
        item.setSelected(True)
        if layer is not None:
            self.ui.sync_layers()


    def discard(self, item):
        self.scene._remove(item.item_id)
        layer, self._pending_layer = self._pending_layer, None
        if layer is not None and layer.scene() is not None:
            self.scene._remove(layer.item_id)
            self.layer_id = ""


    # ------------------------------------------------------------------ outils
    def current_tool(self):
        return self.tools[self.tool]


    def set_tool(self, name: str):
        if name not in self.tools:
            return
        if name != self.tool:
            self.current_tool().cancel()
            self.end_text_edit()
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
    def _in_editor(self, event) -> bool:
        editor = self.editor
        return editor is not None and editor.sceneBoundingRect().adjusted(-4, -4, 4, 4).contains(
            self.scene_pos(event))


    def mouse_press(self, event) -> bool:
        if self.editor is not None:
            if self._in_editor(event):                      # curseur, sélection du texte : Qt (l'éditeur)
                self._forward = True
                QGraphicsView.mousePressEvent(self.view, event)
                return True
            self.end_text_edit()
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
        if self._forward:
            QGraphicsView.mouseMoveEvent(self.view, event)
            return True
        tool = self.current_tool()
        if event.buttons() & Qt.LeftButton:
            tool.drag(self.scene_pos(event), event.modifiers())
        else:
            tool.hover(self.scene_pos(event), event.modifiers())
        self.refresh()
        return True


    def mouse_release(self, event) -> bool:
        if self._forward:
            self._forward = False
            QGraphicsView.mouseReleaseEvent(self.view, event)
            return True
        if event.button() != Qt.LeftButton:
            return event.button() == Qt.RightButton
        self.current_tool().release(self.scene_pos(event), event.modifiers())
        self.refresh()
        self.stateChanged.emit()
        return True


    def mouse_double_click(self, event) -> bool:
        if event.button() != Qt.LeftButton:
            return False
        if self.editor is not None and self._in_editor(event):
            QGraphicsView.mouseDoubleClickEvent(self.view, event)       # double-clic : un mot choisi
            return True
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
        if self.editor is not None:
            return True                                     # texte en édition : toutes ses touches (Ctrl+Z, C, V…)
        if key in (Qt.Key_Delete, Qt.Key_Backspace, Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down,
                   Qt.Key_Return, Qt.Key_Enter, Qt.Key_Slash, Qt.Key_Plus, Qt.Key_Minus, Qt.Key_Equal,
                   Qt.Key_Backslash):
            return True
        if ctrl and key in (Qt.Key_G, Qt.Key_J, Qt.Key_Y, Qt.Key_A, Qt.Key_2, Qt.Key_3, Qt.Key_8, Qt.Key_BracketLeft,
                            Qt.Key_BracketRight, Qt.Key_At, Qt.Key_Eacute, Qt.Key_QuoteDbl, Qt.Key_Underscore,
                            Qt.Key_O, Qt.Key_7, Qt.Key_Egrave, Qt.Key_P, Qt.Key_D, Qt.Key_U):
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
            step = NUDGE_BIG if shift else NUDGE
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
        elif key == Qt.Key_D:                               # Transformer de nouveau (et non Dupliquer du board)
            self.transform_again()
        elif key == Qt.Key_U:
            self.toggle_smart_guides()
        elif key == Qt.Key_O and shift:
            self.outline_text()
        elif key == Qt.Key_P and shift:                     # Ctrl+Maj+P : Importer
            self.place_dialog()
        elif key in (Qt.Key_7, Qt.Key_Egrave):              # Ctrl+7 (AZERTY : « è »)
            self.release_mask() if alt else self.make_mask("clip")
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
        """Fichiers déposés : SVG = objets, images = images placées (décalées si plusieurs)."""
        done = False
        for n, path in enumerate(paths):
            suffix = path.suffix.lower()
            if suffix == ".svg":
                done = bool(self.import_svg(path, at)) or done
            elif suffix in self.IMAGE_SUFFIXES:
                done = self.place_image(path, at + QPointF(20 * n, 20 * n)) is not None or done
        return done


    # ------------------------------------------------------------------ affichage
    def refresh(self):
        if self.overlay.scene() is not None:
            self.overlay.refresh()


    def change(self, items, change, text: str):
        """`change(item)` modifie `item.data` ; une étape d'annulation."""
        self.scene.change_items([i for i in items if isinstance(i, IllItem)], change, text)
        self.refresh()
        self.stateChanged.emit()
