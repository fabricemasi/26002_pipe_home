"""Scene d'un board : elements par identifiant, annulation, reglages de la page, grille, magnetisme et guides,
copier / coller, ordre d'empilement, commentaires.

GRILLE comme Miro (mesuree sur les captures de l'utilisateur, octobre 2026) : fond #f2f2f2, lignes fines par
NIVEAUX de 4 en 4 (pas du monde 4, 16, 64, 256... unites). L'intensite d'un niveau ne depend que de son pas A
L'ECRAN : invisible sous ~12 px, la moitie a 36 px (capture 1 : lignes fines tous les 36 px, #eaeaea sur un
pixel), pleine a partir de ~60 px (capture 1 : toutes les 4 lignes, #e2e2e2 ; capture 2 : tous les 65 px).
Zoomer fait donc apparaitre / s'effacer les niveaux en continu, sans saut ; chaque ligne est posee sur un pixel
entier de la TUILE de grille (pinceau calee sur le monde, refaite seulement au zoom : aucun calcul de lignes
par image, pas de scintillement pendant le deplacement).

MAGNETISME (Reglages > MRO, `snap` ; Alt tenu = sans) : bords et centres des elements visibles, grille (le
niveau de grille le plus fin affiche), en deplacement comme en redimensionnement ; seuil en pixels d'ecran
(meme effet a tout zoom) ; guides magenta le long des alignements."""
from __future__ import annotations

import copy
import json
import math

from PySide6.QtCore import QLineF, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPen, QPixmap, QTransform, QUndoStack
from PySide6.QtWidgets import QGraphicsItem, QGraphicsScene

from . import model, serialization
from .commands import StateCommand
from .items import BoardItem, CommentItem, ConnectorItem, FrameItem, InkItem, make_item

GRID_BASE = 4.0
GRID_FACTOR = 4.0
FRAME_Z = -100000.0
PAGE = "__page__"
CLIPBOARD_MIME = "application/x-pipeline-board"
SNAP_DEFAULTS = {"enabled": True, "objects": True, "grid": False, "guides": True, "resize": True, "distance": 6}


def first_grid_step(scale: float) -> float:
    """Pas du niveau de grille le plus fin a considerer au zoom `scale` (puissances de 4 de GRID_BASE, vers le
    bas pour les forts zooms — 2 000 % — et vers le haut pour les faibles — 0,1 %)."""
    step = GRID_BASE
    while step * scale > 48.0:
        step /= GRID_FACTOR
    while step * scale < 3.0:
        step *= GRID_FACTOR
    return step


def grid_alpha(spacing_px: float) -> float:
    """Intensite (0-1) d'un niveau de grille selon son pas a l'ecran (voir l'entete)."""
    t = max(0.0, min(1.0, (spacing_px - 12.0) / 48.0))
    return t * t * (3 - 2 * t)


class BoardScene(QGraphicsScene):
    contentChanged = Signal()
    pageChanged = Signal()

    def __init__(self, board_path=None, look: dict | None = None, parent=None):
        super().__init__(parent)
        look = look or {}
        self.board_path = board_path
        self.zoom = 1.0
        self.accent = look.get("accent", model.MIRO_ACCENT)
        self.guide_color = QColor(look.get("guides", "#ff2fd0"))
        self.page = dict(model.PAGE_DEFAULTS)
        self.background = QColor(model.MIRO_BACKGROUND)
        self.show_resolved = False
        self.snap = dict(SNAP_DEFAULTS)
        self.exporting = False
        self.export_grid = False
        self.visible_rect = QRectF()
        self.guides: list[QLineF] = []
        self.highlight: QRectF | None = None        # objet vise par l'extremite d'une fleche tiree
        self.undo = QUndoStack(self)
        self.undo.indexChanged.connect(self._on_undo_index)
        self.undo.cleanChanged.connect(self._on_undo_index)
        self.commands: list[StateCommand] = []
        self._items: dict[str, BoardItem] = {}
        self._foreign: list[dict] = []
        self._extra: dict = {}
        self._pending = None
        self._live = None
        self._move_before = None
        self.setItemIndexMethod(QGraphicsScene.BspTreeIndex)
        self.setSceneRect(-500000, -500000, 1000000, 1000000)

    def _on_undo_index(self, *_args):
        self.contentChanged.emit()

    # -- elements --
    def item(self, item_id) -> BoardItem | None:
        return self._items.get(item_id)

    def board_items(self) -> list[BoardItem]:
        return list(self._items.values())

    def _add(self, data: dict) -> BoardItem:
        item = make_item(data)
        if item.kind == "frame" and item.zValue() > FRAME_Z / 2:
            item.setZValue(FRAME_Z + item.zValue())
        if item.kind == "comment":
            item.setZValue(1e7 + item.zValue() % 1e6)
        self.addItem(item)
        self._items[item.item_id] = item
        item.sync()
        if isinstance(item, CommentItem):
            item.follow_target()
        return item

    def _remove(self, item_id):
        item = self._items.pop(item_id, None)
        if item is not None:
            if item.text_item is not None and item.text_item.editing():
                item.text_item.stop()
            self.removeItem(item)
            item.deleteLater()

    def snapshot(self, ids) -> dict:
        out = {}
        for i in ids:
            if i == PAGE:
                out[i] = dict(self.page)
            else:
                out[i] = self._items[i].to_dict() if i in self._items else None
        return out

    def apply_states(self, states: dict):
        self.commit_live()
        for item_id, state in states.items():
            if item_id == PAGE:
                self.set_page(state or {}, record=False)
            elif state is None:
                self._remove(item_id)
            elif item_id in self._items:
                self._items[item_id].apply(state)
            else:
                self._add(state)
        self.refresh_links()

    def push(self, before: dict, after: dict, text: str):
        if before == after:
            return
        command = StateCommand(self, before, after, text)
        self.commands.append(command)
        self.undo.push(command)

    def begin_change(self, items):
        self.commit_live()
        self._pending = self.snapshot([i.item_id for i in items])

    def end_change(self, text: str):
        before, self._pending = self._pending, None
        if before is not None:
            self.push(before, self.snapshot(list(before)), text)

    def change_items(self, items, change, text: str, include_locked: bool = False):
        """`change(item)` modifie `item.data` ; le tout en une etape d'annulation. Les elements verrouilles
        ne changent pas (sauf `include_locked` : le verrou lui-meme)."""
        self.commit_live()
        items = [i for i in items if isinstance(i, BoardItem) and (include_locked or not i.locked())]
        if not items:
            return
        before = self.snapshot([i.item_id for i in items])
        for item in items:
            item.data = item.to_dict()                       # place / texte du moment, puis le changement
            change(item)
            item.apply(item.data)
        self.refresh_links()
        self.push(before, self.snapshot(list(before)), text)

    def live_change(self, key: str, items, change, text: str):
        """Changement continu (curseur, couleur glissee) : applique tout de suite, UNE etape d'annulation par
        geste (`key`) ; le geste se termine au changement suivant d'une autre sorte, a `commit_live`, ou quand
        l'appelant le dit (fermeture d'un menu)."""
        items = [i for i in items if isinstance(i, BoardItem) and not i.locked()]
        ids = [i.item_id for i in items]
        if self._live is None or self._live[0] != key or self._live[1] != ids:
            self.commit_live()
            self._live = (key, ids, self.snapshot(ids), text)
        for item in items:
            item.data = item.to_dict()
            change(item)
            item.apply(item.data)
        self.refresh_links()
        self.contentChanged.emit()

    def commit_live(self):
        live, self._live = self._live, None
        if live is not None:
            _key, ids, before, text = live
            self.push(before, self.snapshot(ids), text)

    def next_z(self) -> float:
        tops = [i.zValue() for i in self._items.values() if i.kind not in ("frame", "comment")]
        return (max(tops) + 1.0) if tops else 1.0

    def add_new(self, data: dict, text: str = "Ajouter", select: bool = True) -> BoardItem:
        self.commit_live()
        if data["type"] == "frame":
            frames = [i.zValue() for i in self._items.values() if i.kind == "frame"]
            data["z"] = (max(frames) + 1.0) if frames else FRAME_Z
        elif data["type"] != "comment":
            data["z"] = self.next_z()
        item = self._add(data)
        self.push({item.item_id: None}, self.snapshot([item.item_id]), text)
        if select:
            self.clearSelection()
            item.setSelected(True)
        return item

    def replace_items(self, removed, added_dicts, text: str) -> list[BoardItem]:
        """Une etape : `removed` disparaissent, `added_dicts` apparaissent (dessin intelligent, gomme de
        precision)."""
        self.commit_live()
        removed_ids = [i.item_id for i in removed]
        before = self.snapshot(removed_ids)
        for item_id in removed_ids:
            self._remove(item_id)
        added = [self._add(d) for d in added_dicts]
        after = {i: None for i in removed_ids}
        after.update(self.snapshot([i.item_id for i in added]))
        before.update({i.item_id: None for i in added})
        self.refresh_links()
        self.push(before, after, text)
        return added

    def delete_items(self, items):
        self.commit_live()
        ids = {i.item_id for i in items if isinstance(i, BoardItem) and not i.locked()}
        if not ids:
            return
        for item in self._items.values():                    # fleches accrochees a un element supprime
            if isinstance(item, ConnectorItem) and item.attached_ids() & ids:
                ids.add(item.item_id)
        detached = [c for c in self._items.values()
                    if isinstance(c, CommentItem) and c.data.get("target") in ids and c.item_id not in ids]
        before = self.snapshot(ids | {c.item_id for c in detached})
        for comment in detached:                             # commentaire d'un element supprime : reste sur place
            comment.data = comment.to_dict()
            comment.data["target"] = ""
        for item_id in ids:
            self._remove(item_id)
        after = {i: None for i in ids}
        after.update(self.snapshot([c.item_id for c in detached]))
        self.push(before, after, "Supprimer")

    def item_moved(self, item):
        if isinstance(item, (ConnectorItem, CommentItem)):
            return
        for other in self._items.values():
            if isinstance(other, ConnectorItem) and item.item_id in other.attached_ids():
                other.sync()
            elif isinstance(other, CommentItem) and other.data.get("target") == item.item_id:
                other.follow_target()

    def refresh_links(self):
        for item in self._items.values():
            if isinstance(item, ConnectorItem):
                item.sync()
            elif isinstance(item, CommentItem):
                item.follow_target()
                item.sync()

    def set_zoom(self, zoom: float):
        """Les textes sont peints a TOUS les zooms (ils restent a leur place et a leur taille ; tres petits a
        l'ecran au dezoom). Un ancien seuil les cachait sous 18 % : mesure, 600 elements textes, 2400 x 1300 :
        deplacement identique (images gardees), zoom ~40 -> ~47 ms par cran — retire (bug signale)."""
        if zoom != self.zoom:
            self.zoom = zoom
            for item in self._items.values():
                if item.isSelected() or isinstance(item, (FrameItem, ConnectorItem)):
                    item.zoom_changed()

    # -- page (reglages du .mro) --
    def set_page(self, page: dict, record: bool = True, text: str = "Réglages de la page"):
        new = dict(model.PAGE_DEFAULTS)
        new.update(self.page)
        new.update(page)
        if record:
            self.commit_live()
            before = {PAGE: dict(self.page)}
        self.page = new
        background = new.get("background")
        self.background = QColor(background if background else model.MIRO_BACKGROUND)
        self.show_resolved = bool(new.get("show_resolved"))
        for item in self._items.values():
            if isinstance(item, CommentItem):
                item.sync()
        self.update()
        self.pageChanged.emit()
        if record:
            self.push(before, {PAGE: dict(self.page)}, text)

    def grid_ink(self) -> QColor:
        """Lignes de la grille : noires sur un fond clair (Miro), blanches sur un fond sombre."""
        return QColor(255, 255, 255) if self.background.lightness() < 110 else QColor(0, 0, 0)

    # -- ordre d'empilement --
    def _restack(self, items, z_of, text):
        order = sorted((i for i in items if i.kind not in ("frame", "comment")), key=lambda i: i.zValue())
        values = iter(z_of(order))

        def change(item):
            if item in order:
                item.data["z"] = next(values)
        self.change_items(order, change, text)

    def bring_to_front(self, items):
        z = self.next_z()
        self._restack(items, lambda order: [z + n for n in range(len(order))], "Premier plan")

    def send_to_back(self, items):
        lows = [i.zValue() for i in self._items.values() if i.kind not in ("frame", "comment")]
        z = min(lows) if lows else 0.0
        self._restack(items, lambda order: [z - len(order) + n for n in range(len(order))], "Arrière-plan")

    def step_z(self, items, step: int):
        """Avancer / reculer d'un rang (au-dessus / en dessous du voisin le plus proche)."""
        others = sorted((i.zValue() for i in self._items.values()
                         if i.kind not in ("frame", "comment") and i not in items))
        if not others:
            return
        order = sorted((i for i in items if i.kind not in ("frame", "comment")), key=lambda i: i.zValue())
        if not order:
            return
        if step > 0:
            above = [z for z in others if z > order[-1].zValue()]
            base = (above[0] + 0.5) if above else order[-1].zValue()
        else:
            below = [z for z in others if z < order[0].zValue()]
            base = (below[-1] - 0.5 - len(order) * 0.01) if below else order[0].zValue()
        self._restack(items, lambda o: [base + n * 0.01 for n in range(len(o))],
                      "Avancer" if step > 0 else "Reculer")

    # -- fichier --
    def load_data(self, data: dict):
        self.undo.clear()
        self.commands.clear()
        self._live = None
        for item_id in list(self._items):
            self._remove(item_id)
        self._foreign = copy.deepcopy(data.get("foreign") or [])
        self._extra = {k: copy.deepcopy(v) for k, v in data.items()
                       if k not in ("format", "version", "page", "view", "items", "foreign")}
        self._version = int(data.get("version", model.VERSION) or model.VERSION)
        self.set_page(data.get("page") or {}, record=False)
        for raw in data.get("items", []):
            self._add(raw)
        self.refresh_links()
        self.undo.setClean()

    def to_data(self, view: dict | None = None) -> dict:
        board = model.empty_board()
        board.update(copy.deepcopy(self._extra))
        board["version"] = max(model.VERSION, getattr(self, "_version", model.VERSION))
        board["page"] = dict(self.page)
        if view:
            board["view"] = view
        items = sorted(self._items.values(), key=lambda i: (i.kind != "frame", i.kind == "comment", i.zValue()))
        board["items"] = [item.to_dict() for item in items] + copy.deepcopy(self._foreign)
        return board

    def content_rect(self) -> QRectF:
        rect = QRectF()
        for item in self._items.values():
            if not isinstance(item, CommentItem):
                rect = rect.united(item.scene_rect())
        return rect

    def assets_in_use(self) -> set[str]:
        """Images referencees par l'etat actuel ET par tout etat encore accessible par l'annulation."""
        names = {i.data.get("asset") for i in self._items.values() if i.kind == "image"}
        names |= model.referenced_assets({"foreign": self._foreign})
        for command in self.commands:
            for state in command.states():
                if isinstance(state, dict) and state.get("asset"):
                    names.add(state["asset"])
        return {n for n in names if n}

    # -- copier / coller --
    def serialize(self, items) -> list[dict]:
        ids = {i.item_id for i in items if isinstance(i, BoardItem)}
        for item in list(self._items.values()):                 # contenu des cadres copies
            if isinstance(item, FrameItem) and item.item_id in ids:
                ids |= {o.item_id for o in self._items.values()
                        if o.kind not in ("frame", "connector", "comment") and item.contains_item(o)}
        out = []
        for item_id in ids:
            item = self._items[item_id]
            if isinstance(item, ConnectorItem) and not item.attached_ids() <= ids:
                continue
            if isinstance(item, CommentItem):
                continue                                         # un commentaire n'est pas copie
            out.append(item.to_dict())
        return sorted(out, key=lambda d: (d["type"] != "frame", d.get("z", 0.0)))

    def paste(self, dicts: list[dict], offset: QPointF, text: str = "Coller", source_board=None) -> list[BoardItem]:
        self.commit_live()
        mapping = {d["id"]: model.new_id() for d in dicts}
        z = self.next_z()
        added = []
        for raw in dicts:
            data = model.normalize_item(copy.deepcopy(raw))
            if data is None:
                continue
            data["id"] = mapping[raw["id"]]
            data["locked"] = False
            if data["type"] == "image" and source_board and self.board_path is not None:
                self._bring_asset(data, source_board)
            if data["type"] == "connector":
                for end in ("src", "dst"):
                    point = dict(data.get(end) or {})
                    if point.get("item"):
                        point["item"] = mapping.get(point["item"], point["item"])
                    else:
                        point["x"] = float(point.get("x", 0.0)) + offset.x()
                        point["y"] = float(point.get("y", 0.0)) + offset.y()
                    data[end] = point
            else:
                data["x"] += offset.x()
                data["y"] += offset.y()
            if data["type"] != "frame":
                data["z"] = z
                z += 1
            added.append(self._add(data))
        self.refresh_links()
        ids = [i.item_id for i in added]
        self.push({i: None for i in ids}, self.snapshot(ids), text)
        self.clearSelection()
        for item in added:
            item.setSelected(True)
        return added

    def _bring_asset(self, data: dict, source_board):
        """Image collee depuis un AUTRE board : copiee dans le dossier de celui-ci (l'autre n'est pas touche)."""
        name = data.get("asset", "")
        if not serialization.is_asset_name(name):
            return
        mine = serialization.asset_path(self.board_path, name)
        theirs = serialization.asset_path(source_board, name)
        if not mine.exists() and theirs.is_file():
            try:
                data["asset"] = serialization.import_asset(self.board_path, theirs)
            except OSError:
                pass

    def clipboard_payload(self, dicts: list[dict]) -> bytes:
        return json.dumps({"format": model.FORMAT, "board": str(self.board_path or ""), "items": dicts},
                          ensure_ascii=False).encode("utf-8")

    @staticmethod
    def read_payload(data: bytes) -> tuple[list[dict], str]:
        try:
            payload = json.loads(bytes(data).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return [], ""
        items = [d for d in payload.get("items", []) if isinstance(d, dict) and "id" in d]
        return items, str(payload.get("board") or "")

    # -- deplacement : annulation + magnetisme --
    def _moving_items(self) -> list[BoardItem]:
        items = [i for i in self.selectedItems()
                 if isinstance(i, BoardItem) and i.flags() & QGraphicsItem.ItemIsMovable]
        for item in list(items):
            if isinstance(item, FrameItem):
                items += [c for c in item.carried() if c not in items]
        return items

    def mousePressEvent(self, event):
        self.commit_live()
        super().mousePressEvent(event)
        self._move_before = None
        grabber = self.mouseGrabberItem()
        if (event.button() == Qt.LeftButton and isinstance(grabber, BoardItem) and grabber._gesture is None
                and grabber.isSelected()):
            moving = self._moving_items()
            if moving:
                self._move_before = self.snapshot([i.item_id for i in moving])

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        if self._move_before is None or not (event.buttons() & Qt.LeftButton):
            return
        if not self.snap_active(event.modifiers()):
            self._set_guides([])
            return
        self._snap_move()

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        self._snap_cache = None
        before, self._move_before = self._move_before, None
        self._set_guides([])
        if before is None:
            return
        moved = [self._items[i] for i in before if i in self._items]
        for comment in (m for m in moved if isinstance(m, CommentItem)):
            self._attach_comment(comment)
        self.push(before, self.snapshot(list(before)), "Deplacer")

    def _attach_comment(self, comment: CommentItem):
        """Commentaire depose sur un element : il s'y accroche ; dans le vide : il est detache."""
        point = comment.pos()
        target = None
        for item in self.items(point):
            while item is not None and not isinstance(item, BoardItem):
                item = item.parentItem()
            if isinstance(item, BoardItem) and item is not comment and not isinstance(item, (CommentItem,
                                                                                            ConnectorItem)):
                target = item
                break
        comment.data = comment.to_dict()
        if target is None:
            comment.data["target"] = ""
        else:
            r = target.scene_rect()
            comment.data.update(target=target.item_id, dx=round(point.x() - r.left(), 2),
                                dy=round(point.y() - r.top(), 2))

    def snap_active(self, modifiers) -> bool:
        return bool(self.snap.get("enabled", True)) and not (modifiers & Qt.AltModifier)

    def _threshold(self) -> float:
        return float(self.snap.get("distance", 6)) / max(0.05, self.zoom)

    def grid_step(self) -> float:
        """Pas du niveau de grille le plus fin affiche (le magnetisme de grille suit ce qu'on voit)."""
        step = first_grid_step(self.zoom)
        while grid_alpha(step * self.zoom) < 0.25:
            step *= GRID_FACTOR
        return step

    def _candidates(self, exclude: set) -> list[QRectF]:
        """Cadres des elements visibles vers lesquels aimanter ; calcules UNE fois par geste (ils ne bougent
        pas pendant qu'on en tire d'autres) : un deplacement ne refait aucun parcours des elements."""
        key = (frozenset(exclude), self.zoom, self.visible_rect)
        cached = getattr(self, "_snap_cache", None)
        if cached is not None and cached[0] == key:
            return cached[1]
        area = self.visible_rect if self.visible_rect.isValid() else QRectF(-1e5, -1e5, 2e5, 2e5)
        rects = [i.scene_rect() for i in self._items.values()
                 if i.item_id not in exclude and not isinstance(i, (ConnectorItem, CommentItem, InkItem))
                 and i.isVisible() and i.scene_rect().intersects(area)]
        self._snap_cache = (key, rects)
        return rects

    @staticmethod
    def _best(values_mine, values_theirs, threshold):
        best = None
        for theirs in values_theirs:
            for mine in values_mine:
                d = theirs - mine
                if abs(d) <= threshold and (best is None or abs(d) < abs(best[0])):
                    best = (d, theirs)
        return best

    def _snap_move(self):
        selected = [i for i in self.selectedItems()
                    if isinstance(i, BoardItem) and i.flags() & QGraphicsItem.ItemIsMovable]
        if not selected:
            return
        moving_ids = set(self._move_before or ())
        rect = QRectF()
        for item in selected:
            rect = rect.united(item.scene_rect())
        threshold = self._threshold()
        mine_x = (rect.left(), rect.center().x(), rect.right())
        mine_y = (rect.top(), rect.center().y(), rect.bottom())
        best_x = best_y = None
        others = self._candidates(moving_ids) if self.snap.get("objects", True) else []
        if others:
            best_x = self._best(mine_x, [v for o in others for v in (o.left(), o.center().x(), o.right())],
                                threshold)
            best_y = self._best(mine_y, [v for o in others for v in (o.top(), o.center().y(), o.bottom())],
                                threshold)
        if self.snap.get("grid", False):
            step = self.grid_step()
            gx = self._best((rect.left(),), (round(rect.left() / step) * step,), threshold)
            gy = self._best((rect.top(),), (round(rect.top() / step) * step,), threshold)
            if gx and (best_x is None or abs(gx[0]) < abs(best_x[0])):
                best_x = (gx[0], None)
            if gy and (best_y is None or abs(gy[0]) < abs(best_y[0])):
                best_y = (gy[0], None)
        dx = best_x[0] if best_x else 0.0
        dy = best_y[0] if best_y else 0.0
        if dx or dy:
            for item in selected:
                item.moveBy(dx, dy)
            rect.translate(dx, dy)
        self._set_guides(self._guide_lines(rect, best_x, best_y, others))

    def _guide_lines(self, rect, best_x, best_y, others) -> list[QLineF]:
        if not self.snap.get("guides", True):
            return []
        guides = []
        if best_x and best_x[1] is not None:
            x = best_x[1]
            near = [o for o in others if min(abs(o.left() - x), abs(o.center().x() - x), abs(o.right() - x)) < 0.5]
            top = min([rect.top()] + [o.top() for o in near])
            bottom = max([rect.bottom()] + [o.bottom() for o in near])
            guides.append(QLineF(x, top, x, bottom))
        if best_y and best_y[1] is not None:
            y = best_y[1]
            near = [o for o in others if min(abs(o.top() - y), abs(o.center().y() - y), abs(o.bottom() - y)) < 0.5]
            left = min([rect.left()] + [o.left() for o in near])
            right = max([rect.right()] + [o.right() for o in near])
            guides.append(QLineF(left, y, right, y))
        return guides

    def snap_resize(self, item, rect: QRectF, transform, handle: str, modifiers, ratio=None) -> QRectF:
        """Redimensionnement (element sans rotation) : les bords TIRES collent aux bords des autres elements et
        a la grille. `rect` est en coordonnees de l'element au debut du geste. `ratio` (largeur / hauteur,
        poignee de coin) : UN seul bord est aimante (le plus proche d'un repere), l'autre dimension en est
        DEDUITE depuis le coin fixe — le ratio reste exact et le cadre ne glisse pas (bug signale)."""
        if not (self.snap_active(modifiers) and self.snap.get("resize", True)):
            self._set_guides([])
            return rect
        if ratio is not None and len(handle) == 2:
            return self._snap_resize_ratio(item, rect, transform, handle, ratio)
        offset = transform.map(QPointF(0, 0))
        scene_rect = rect.translated(offset)
        threshold = self._threshold()
        others = self._candidates({item.item_id}) if self.snap.get("objects", True) else []
        xs = [v for o in others for v in (o.left(), o.center().x(), o.right())]
        ys = [v for o in others for v in (o.top(), o.center().y(), o.bottom())]
        if self.snap.get("grid", False):
            step = self.grid_step()
            xs += [round(scene_rect.left() / step) * step, round(scene_rect.right() / step) * step]
            ys += [round(scene_rect.top() / step) * step, round(scene_rect.bottom() / step) * step]
        guides = []
        left, top, right, bottom = scene_rect.left(), scene_rect.top(), scene_rect.right(), scene_rect.bottom()
        for side in handle:
            if side in "lr":
                value = left if side == "l" else right
                best = self._best((value,), xs, threshold)
                if best:
                    if side == "l":
                        left += best[0]
                    else:
                        right += best[0]
                    guides.append(QLineF(best[1], top - 40, best[1], bottom + 40))
            elif side in "tb":
                value = top if side == "t" else bottom
                best = self._best((value,), ys, threshold)
                if best:
                    if side == "t":
                        top += best[0]
                    else:
                        bottom += best[0]
                    guides.append(QLineF(left - 40, best[1], right + 40, best[1]))
        self._set_guides(guides if self.snap.get("guides", True) else [])
        out = QRectF(QPointF(left, top), QPointF(right, bottom)).normalized()
        return out.translated(-offset)

    def connect_target(self, point: QPointF, exclude=()) -> "BoardItem | None":
        """Objet sous `point` (a quelques pixels d'ecran pres) auquel rattacher une extremite de fleche."""
        reach = 8.0 / max(0.05, self.zoom)
        area = QRectF(point.x() - reach, point.y() - reach, 2 * reach, 2 * reach)
        for item in self.items(area, Qt.IntersectsItemShape, Qt.DescendingOrder):
            while item is not None and not isinstance(item, BoardItem):
                item = item.parentItem()
            if (isinstance(item, BoardItem) and item.item_id not in exclude and item.isVisible()
                    and not isinstance(item, (ConnectorItem, CommentItem, InkItem))):
                return item
        return None

    def set_highlight(self, rect):
        if rect != self.highlight:
            old = self.highlight
            self.highlight = QRectF(rect) if rect is not None else None
            for area in (old, self.highlight):
                if area is not None:
                    self.update(area.adjusted(-20, -20, 20, 20))

    def _snap_resize_ratio(self, item, rect: QRectF, transform, handle: str, ratio: float) -> QRectF:
        offset = transform.map(QPointF(0, 0))
        scene_rect = rect.translated(offset)
        threshold = self._threshold()
        others = self._candidates({item.item_id}) if self.snap.get("objects", True) else []
        xs = [v for o in others for v in (o.left(), o.center().x(), o.right())]
        ys = [v for o in others for v in (o.top(), o.center().y(), o.bottom())]
        if self.snap.get("grid", False):
            step = self.grid_step()
            xs += [round(scene_rect.left() / step) * step, round(scene_rect.right() / step) * step]
            ys += [round(scene_rect.top() / step) * step, round(scene_rect.bottom() / step) * step]
        moving_x = scene_rect.left() if "l" in handle else scene_rect.right()
        moving_y = scene_rect.top() if "t" in handle else scene_rect.bottom()
        fixed_x = scene_rect.right() if "l" in handle else scene_rect.left()
        fixed_y = scene_rect.bottom() if "t" in handle else scene_rect.top()
        best_x = self._best((moving_x,), xs, threshold)
        best_y = self._best((moving_y,), ys, threshold)
        width, height = scene_rect.width(), scene_rect.height()
        guides = []
        if best_x and (best_y is None or abs(best_x[0]) <= abs(best_y[0])):
            width = abs(best_x[1] - fixed_x)
            height = width / ratio
            guides.append(QLineF(best_x[1], scene_rect.top() - 40, best_x[1], scene_rect.bottom() + 40))
        elif best_y:
            height = abs(best_y[1] - fixed_y)
            width = height * ratio
            guides.append(QLineF(scene_rect.left() - 40, best_y[1], scene_rect.right() + 40, best_y[1]))
        if width < 1 or height < 1:
            self._set_guides([])
            return rect
        left = fixed_x - width if "l" in handle else fixed_x
        top = fixed_y - height if "t" in handle else fixed_y
        self._set_guides(guides if self.snap.get("guides", True) else [])
        return QRectF(left, top, width, height).translated(-offset)

    def clear_guides(self):
        self._set_guides([])

    def _set_guides(self, guides):
        if guides or self.guides:
            self.guides = guides
            self.update()

    # -- dessin --
    def _grid_tile(self, scale: float):
        """(pinceau, None) de la grille au zoom `scale` : une TUILE (image) qui contient tous les niveaux
        visibles sur la periode du premier niveau plein ; posee par le pinceau, calee EXACTEMENT sur les
        coordonnees du monde (la tuile est mise a l'echelle de sa periode : aucun ecart avec les objets ni avec
        le magnetisme de grille). Refaite seulement quand le zoom change (petite image, < 1 ms)."""
        levels = []
        step = first_grid_step(scale)
        previous = 0.0
        for _level in range(12):
            alpha = grid_alpha(step * scale)
            gain = alpha - previous
            if gain > 0.004:
                levels.append((step, gain))
            previous = max(previous, alpha)
            if alpha >= 0.999:
                break
            step *= GRID_FACTOR
        period = step                                       # premier niveau plein : la grille se repete
        size = max(4, int(round(period * scale)))
        ink = self.grid_ink()
        key = (size, period, tuple((s, round(g, 3)) for s, g in levels), ink.rgba())
        cached = getattr(self, "_tile", None)
        if cached is not None and cached[0] == key:
            return cached[1]
        image = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
        image.fill(Qt.transparent)
        painter = QPainter(image)
        for level_step, gain in levels:
            color = QColor(ink)
            # 0.066 = noir a 6,6 % = #e2e2e2 sur #f2f2f2 (ligne pleine mesuree) ; les niveaux s'ajoutent.
            color.setAlphaF(min(1.0, 0.066 * gain))
            count = int(round(period / level_step))
            for n in range(count):
                x = int(round(n * size / count))
                painter.fillRect(x, 0, 1, size, color)
                painter.fillRect(0, x, size, 1, color)
        painter.end()
        brush = QBrush(QPixmap.fromImage(image))
        brush.setTransform(QTransform.fromScale(period / size, period / size))
        self._tile = (key, brush)
        return brush

    def drawBackground(self, painter, rect):
        painter.fillRect(rect, self.background)
        if (self.exporting and not self.export_grid) or not self.page.get("grid", True):
            return
        transform = painter.worldTransform()
        scale = transform.m11() or 1.0
        if transform.m12() or transform.m21():
            return                                         # vue tournee : jamais le cas ici
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.fillRect(rect, self._grid_tile(scale))

    def drawForeground(self, painter, rect):
        if self.exporting:
            return
        if self.highlight is not None:
            pen = QPen(QColor(self.accent), 2)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            m = 4.0 / max(0.05, self.zoom)
            painter.drawRect(self.highlight.adjusted(-m, -m, m, m))
        if not self.guides:
            return
        pen = QPen(self.guide_color, 1)
        pen.setCosmetic(True)
        painter.setPen(pen)
        for line in self.guides:
            painter.drawLine(line)
