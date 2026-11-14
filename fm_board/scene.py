"""Scene d'un board : elements par identifiant, annulation, reglages de la page, grille, magnetisme et guides,
copier / coller, ordre d'empilement, commentaires.

GRILLE comme Miro (mesuree sur les captures de l'utilisateur, octobre 2026) : fond #f2f2f2, lignes fines par
NIVEAUX de 4 en 4 (pas du monde 4, 16, 64, 256... unites). L'intensite d'un niveau ne depend que de son pas A
L'ECRAN : invisible sous ~12 px, la moitie a 36 px (capture 1 : lignes fines tous les 36 px, #eaeaea sur un
pixel), pleine a partir de ~60 px (capture 1 : toutes les 4 lignes, #e2e2e2 ; capture 2 : tous les 65 px).
Zoomer fait donc apparaitre / s'effacer les niveaux en continu, sans saut ; chaque ligne est posee sur un pixel
entier de la TUILE de grille (pinceau calee sur le monde, refaite seulement au zoom : aucun calcul de lignes
par image, pas de scintillement pendant le deplacement).

MAGNETISME (Reglages > Module MRO, `snap` ; Alt tenu = sans) : bords et centres des elements visibles, grille (le
niveau de grille le plus fin affiche), en deplacement comme en redimensionnement ; seuil en pixels d'ecran
(meme effet a tout zoom) ; guides le long des alignements, chacun avec sa SORTE (`snap_guides`) : « objets internes
aux documents » quand il ne longe QUE des objets internes a un document (traces d'Illustrator, elements d'une page
de Design : `snap_inner()` vrai), « bords des documents » sinon (un bord de document l'emporte)."""
from __future__ import annotations

import copy
import gc
import json
import math
import threading
import time

from PySide6.QtCore import QLineF, QPointF, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QImage, QPaintEngine, QPainter, QPen, QPixmap, QTransform, QUndoStack
from PySide6.QtWidgets import QGraphicsColorizeEffect, QGraphicsItem, QGraphicsScene

from fm_cad import cad_items, cad_model  # noqa: F401 - cad_items : enregistre le type « cad_line »
from fm_design import items as design_items  # noqa: F401 - enregistre les types du module Design
from fm_tableur import board_item as tableur_items  # noqa: F401 - enregistre le type « sheet » du module Tableur
from fm_illustrator import items as ill_items  # noqa: F401 - enregistre les types du module Illustrator
from fm_photoshop import board_item as ps_item  # noqa: F401 - enregistre le type du module Photoshop
from fm_pdf import board_item as pdf_item  # noqa: F401 - enregistre le type du module PDF
from fm_audio import board_item as audio_item  # noqa: F401 - enregistre le type « audio_doc » (cartes audio)
from . import model, serialization, snap_guides
from .snap_guides import GuideLine
from fm_cad.cad_items import unit_of
from .commands import StateCommand
from fm_miro.items import BoardItem, CommentItem, ConnectorItem, FrameItem, InkItem, make_item

GRID_BASE = 4.0
GRID_FACTOR = 4.0
FRAME_Z = -100000.0
INDEX_MIN = 2000.0                      # demi-etendue minimale de l'index de la scene (voir BoardScene.fit_index)
PAGE = "__page__"
# Modules du board (selecteur du board, `BoardPane.set_module`) : leurs elements se grisent ou se masquent a part
# (demande de l'utilisateur). Grise = visible en transparence, ni selectionnable ni modifiable.
MODULES = ("miro", "cad", "design", "tableur", "illustrator", "photoshop", "pdf")
CLIPBOARD_MIME = "application/x-pipeline-board"
SNAP_DEFAULTS = {"enabled": True, "objects": True, "grid": False, "guides": True, "resize": True, "distance": 6}


class _SnapRect(QRectF):
    """Cadre d'un element vers lequel aimanter, avec sa sorte (`inner` : objet interne a un document)."""

    def __init__(self, rect: QRectF, inner: bool):
        super().__init__(rect)
        self.inner = inner


def _snap_target(item) -> _SnapRect:
    inner = getattr(item, "snap_inner", None)
    return _SnapRect(item.scene_rect(), bool(inner()) if inner is not None else False)


def _near(others, value: float, axis: int) -> list:
    """Cadres dont un bord ou le centre (axe 0 = x, 1 = y) tombe sur `value`."""
    if axis == 0:
        return [o for o in others if min(abs(o.left() - value), abs(o.center().x() - value), abs(o.right() - value)) < 0.5]
    return [o for o in others if min(abs(o.top() - value), abs(o.center().y() - value), abs(o.bottom() - value)) < 0.5]


def guide_kind(near) -> str:
    """Sorte d'un guide qui longe les cadres `near` : « objets internes » s'ils le sont TOUS, « bords des documents »
    sinon (rien d'aligne, la grille : bords)."""
    return snap_guides.INNER if near and all(getattr(o, "inner", False) for o in near) else snap_guides.DOCUMENTS


class _FadeEffect(QGraphicsColorizeEffect):
    """Desaturation d'un element grise : niveaux de gris (teinte noire = rien d'ajoute), dosee par la force."""

    def __init__(self):
        super().__init__()
        self.setColor(QColor(0, 0, 0))


# Grille UNIQUE du board et du module CAD (Reglages > Module MRO > Grille, cles `board_grid_*`) : niveaux de pas
# `base` x `factor`^n ; un niveau apparait en fondu entre `start` et `full` pixels d'ecran ; couleur automatique
# (noire sur un canvas clair, blanche sur un sombre, `intensity` = opacite d'un niveau plein) ou choisie (son
# opacite = celle d'un niveau plein) ; lignes ou points ; pas en unites du board ou dans l'unite de mesure du CAD.
# Un dessin CAD peut imposer son pas (reglages du dessin : `page["cad"]["grid_step"]`, unite de mesure).
GRID_LOOK = {"step": GRID_BASE, "unit": "board", "factor": GRID_FACTOR, "start": 12.0, "full": 60.0, "levels": 12,
             "auto_color": True, "intensity": 0.066, "color": "#11000000", "style": "lines", "thickness": 1,
             "dot": 2, "origin": (0.0, 0.0), "axes": False, "axes_color": "#66ff2f2f", "axes_thickness": 1}


def grid_look(settings: dict) -> dict:
    """Habillage de la grille d'apres les reglages de l'appli (`board_grid_*`)."""
    g = (settings or {}).get
    from app_style import resolve_color_ref

    def number(key, default, low, high, divide=1.0):
        try:
            value = float(g(key, default))
        except (TypeError, ValueError):
            value = default
        return max(low, min(high, value)) / divide
    start = number("board_grid_fade_start", 12, 1, 400)
    return {"step": number("board_grid_step", 400, 1, 1e8, 100.0),
            "unit": "cad" if g("board_grid_unit") == "cad" else "board",
            "factor": int(number("board_grid_factor", 4, 2, 10)),
            "start": start, "full": max(start + 1.0, number("board_grid_fade_full", 60, 2, 800)),
            "levels": int(number("board_grid_levels", 12, 1, 12)),
            "auto_color": bool(g("board_grid_auto_color", True)),
            "intensity": number("board_grid_intensity", 66, 1, 1000, 1000.0),
            "color": resolve_color_ref(g("board_grid_color", "#11000000"), "#11000000"),
            "style": g("board_grid_style") if g("board_grid_style") in ("dots", "crosses") else "lines",
            "thickness": int(number("board_grid_thickness", 1, 1, 6)),
            "dot": int(number("board_grid_dot_size", 2, 1, 12)),
            "origin": (number("board_grid_origin_x", 0, -1e9, 1e9, 100.0),
                       number("board_grid_origin_y", 0, -1e9, 1e9, 100.0)),
            "axes": bool(g("board_grid_axes", False)),
            "axes_color": resolve_color_ref(g("board_grid_axes_color", "#66ff2f2f"), "#66ff2f2f"),
            "axes_thickness": int(number("board_grid_axes_thickness", 1, 1, 6))}


def first_grid_step(scale: float, base: float = GRID_BASE, factor: float = GRID_FACTOR,
                    full: float = 60.0) -> float:
    """Pas du niveau de grille le plus fin a considerer au zoom `scale` (puissances de `factor` de `base`, vers le
    bas pour les forts zooms — 2 000 % — et vers le haut pour les faibles — 0,1 %)."""
    step = base
    while step * scale > full * 0.8:
        step /= factor
    while step * scale < 3.0:
        step *= factor
    return step


def grid_alpha(spacing_px: float, start: float = 12.0, full: float = 60.0) -> float:
    """Intensite (0-1) d'un niveau de grille selon son pas a l'ecran (voir l'entete)."""
    t = max(0.0, min(1.0, (spacing_px - start) / max(1e-9, full - start)))
    return t * t * (3 - 2 * t)


# Chargement PAR TRANCHES d'un gros board ou dessin importe (demande de l'utilisateur : « ca rame enormement » a
# l'ouverture d'un DWG de 40 000 lignes, ~16 s d'interface figee) : au-dela de LOAD_PROGRESSIVE_MIN elements, ils
# sont crees par tranches de LOAD_SLICE_S, l'interface reste vivante entre deux tranches.
LOAD_PROGRESSIVE_MIN = 2000
LOAD_SLICE_S = 0.03
# Passes COMPLETES du ramasse-miettes (generation 2) suspendues pendant ce chargement : elles parcourent tous les
# objets, 40 -> 130 ms chacune a mesure que les elements s'accumulent (mesure : 5 a-coups sur 40 000 lignes).
# Aussi pendant la LECTURE d'un dessin (fil de fond) : une passe complete y bloque aussi l'interface (verrou Python).
_GC_HELD: set = set()                       # demandes en cours (id d'une scene, nom d'une lecture)
_GC_THRESHOLDS = None
_GC_LOCK = threading.Lock()


def hold_gc(key, on: bool):
    """Suspend (`on`) ou rend les passes completes du ramasse-miettes pour `key` ; rendues quand plus aucune
    demande n'est en cours."""
    global _GC_THRESHOLDS
    with _GC_LOCK:
        if on and key not in _GC_HELD:
            if not _GC_HELD:
                _GC_THRESHOLDS = gc.get_threshold()
                gc.set_threshold(_GC_THRESHOLDS[0], _GC_THRESHOLDS[1], 1_000_000)
            _GC_HELD.add(key)
        elif not on and key in _GC_HELD:
            _GC_HELD.discard(key)
            if not _GC_HELD and _GC_THRESHOLDS is not None:
                gc.set_threshold(*_GC_THRESHOLDS)


class BoardScene(QGraphicsScene):
    contentChanged = Signal()
    pageChanged = Signal()
    loadProgress = Signal(int, int)                 # elements crees, total (chargement par tranches)

    def __init__(self, board_path=None, look: dict | None = None, parent=None):
        super().__init__(parent)
        look = look or {}
        self.board_path = board_path
        self.zoom = 1.0
        self.pad_zoom = 1.0                         # zoom par paliers des marges des elements (voir set_zoom)
        self.accent = look.get("accent", model.MIRO_ACCENT)
        self.page = dict(model.PAGE_DEFAULTS)
        self.background = QColor(model.MIRO_BACKGROUND)
        self.show_resolved = False
        self.module_look = {module: {"fade": False, "hide": False} for module in MODULES}
        # Etat choisi dans la barre des modules (masquer, griser, isoler) ; `module_look` = ce qui en resulte.
        self.module_state = {module: {"fade": False, "hide": False, "solo": False} for module in MODULES}
        self.snap = dict(SNAP_DEFAULTS)
        self.exporting = False
        self.export_grid = False
        self.visible_rect = QRectF()
        self.guides: list[QLineF] = []
        self.highlight: QRectF | None = None        # objet vise par l'extremite d'une fleche tiree
        self.cad_unit = "mm"                        # module CAD : unite generale (Reglages > Module CAD > Unites)
        self.grid_settings: dict = {}               # Reglages > Module MRO > Grille (BoardPane.apply_settings)
        self._grid_look = None                      # (cle, habillage) : reglages generaux + overrides du dessin
        self.cad_layer = None                       # module CAD : lignes peintes par lots (cad_items.CadLayer)
        self.undo = QUndoStack(self)
        self.undo.indexChanged.connect(self._on_undo_index)
        self.undo.cleanChanged.connect(self._on_undo_index)
        self.commands: list[StateCommand] = []
        self._items: dict[str, BoardItem] = {}
        self._zoomers: list | None = None           # cadres et fleches (zone dependant du zoom), voir set_zoom
        self._plain: list | None = None             # elements hors CAD (voir plain_items)
        self._foreign: list[dict] = []
        self._extra: dict = {}
        self._load_job: dict | None = None          # chargement par tranches en cours (load_data)
        self.bulk_loading = False                   # vrai pendant ce chargement : lignes CAD regroupees a la fin
        self._pending = None
        self._live = None
        self._move_before = None
        self.setItemIndexMethod(QGraphicsScene.BspTreeIndex)
        # Etendue de l'INDEX (arbre BSP) : calee sur le contenu, voir fit_index. La zone de defilement est celle de la
        # vue (BoardView._fit_scroll_area), independante.
        self.setSceneRect(-INDEX_MIN, -INDEX_MIN, 2 * INDEX_MIN, 2 * INDEX_MIN)

    def _on_undo_index(self, *_args):
        self.contentChanged.emit()

    # -- elements --
    def item(self, item_id) -> BoardItem | None:
        return self._items.get(item_id)

    def board_items(self) -> list[BoardItem]:
        return list(self._items.values())

    def plain_items(self) -> list[BoardItem]:
        """Elements du board HORS CAD, gardes jusqu'au prochain ajout / retrait : le zoom (images gardees, marge des
        elements) ne parcourt plus les dizaines de milliers d'entites d'un dessin CAD a chaque geste."""
        if self._plain is None:
            self._plain = [i for i in self._items.values() if not getattr(i, "CAD", False)]
        return self._plain

    def fit_index(self, rect: QRectF):
        """Etendue de la scene = celle de son index spatial (arbre BSP de Qt, profondeur selon le nombre
        d'elements). Elle etait fixee a 10^6 unites : tout un dessin tombait dans UNE case de l'index et chaque
        recherche (peinture d'une partie, element sous la souris) testait des milliers d'elements, en appelant le
        `boundingRect` Python de chacun (mesure, 5 000 lignes CAD : ~2 600 par bande de 3 pixels, ~7 ms). Elle suit
        maintenant le contenu, agrandie par paliers (marge de moitie) : l'index n'est refait que rarement. Un element
        hors de l'etendue reste trouve par Qt (cases du bord), seulement plus lentement."""
        if rect.isNull() or not rect.isValid():
            return
        current = self.sceneRect()
        if current.contains(rect):
            return
        target = current.united(rect)
        pad = max(INDEX_MIN, 0.5 * max(target.width(), target.height()))
        self.setSceneRect(target.adjusted(-pad, -pad, pad, pad))

    def _add(self, data: dict) -> BoardItem:
        item = make_item(data)
        if item.kind == "frame" and item.zValue() > FRAME_Z / 2:
            item.setZValue(FRAME_Z + item.zValue())
        if item.kind == "comment":
            item.setZValue(1e7 + item.zValue() % 1e6)
        self.addItem(item)
        self._items[item.item_id] = item
        self._zoomers = None
        self._plain = None
        hook = getattr(item, "added_to_scene", None)      # module Design : element rattache a sa page
        if hook is not None:
            hook(self)
        if not getattr(item, "SYNCED_ON_ADD", False):     # entites CAD : deja fait a l'entree dans la scene
            item.sync()
        if self.module_styled(self.module_of(item)):
            self.apply_module_look(item)
        if not getattr(item, "SYNCED_ON_ADD", False):     # entites CAD : leur `sync` a deja suivi l'emprise
            self.fit_index(item.scene_rect())
        if isinstance(item, CommentItem):
            item.follow_target()
        return item

    def _remove(self, item_id):
        item = self._items.pop(item_id, None)
        self._zoomers = None
        self._plain = None
        if item is not None:
            if item.text_item is not None and item.text_item.editing():
                item.text_item.stop()
            hook = getattr(item, "removing_from_scene", None)  # page Design : ses elements detaches avant
            if hook is not None:
                hook(self)
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
                self.set_page(state or {}, record=False, replace=True)
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
        for item_id in list(ids):                            # page Design : ses elements avec elle
            hook = getattr(self._items.get(item_id), "dependent_ids", None)   # absent (deja retire) : rien
            if hook is not None:
                ids |= hook(self)
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
        self.fit_index(item.scene_rect())
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
            # PLANTAGES a l'effacement (2026-11-03). L'index BSP de Qt range chaque element sous sa zone
            # (`boundingRect`) et, a sa suppression, ne le retire que des cases de sa zone DU MOMENT : une zone
            # changee sans `prepareGeometryChange` AVANT laisse l'element dans des cases, pointeur mort une fois
            # l'element detruit, relu a la peinture / au survol suivants (mesure : 18 elements retires sur 500 encore
            # trouves par `items()` apres un dezoom puis un zoom). Deux fautes : (1) la marge des elements NON
            # selectionnes (anticrenelage, 2-3 px d'ecran) suivait le zoom sans que personne ne previenne Qt ;
            # (2) les autres (cadres, fleches, selection) etaient prevenus APRES le changement de `self.zoom`.
            # Donc : prevenus d'abord, zoom change ensuite ; la marge hors selection suit `pad_zoom`, puissance de
            # 2 sous le zoom (marge de 1 a 2 fois la voulue) : tous les elements ne sont prevenus qu'au changement
            # de palier (rare). Les elements du CAD (zone sans le zoom hors selection) ne le sont pas.
            # Seuls les elements dont la zone suit le zoom a chaque cran (selectionnes : poignees ; cadres ;
            # fleches) : parcourir tous les elements a chaque cran coutait ~8 ms a 5 000 elements.
            if self._zoomers is None:
                self._zoomers = [i for i in self._items.values() if isinstance(i, (FrameItem, ConnectorItem))]
            targets = self._zoomers + [i for i in self.selectedItems() if isinstance(i, BoardItem)
                                       and not isinstance(i, (FrameItem, ConnectorItem))]
            pad = 2.0 ** math.floor(math.log2(max(zoom, 1e-6)))
            padded = ()
            if pad != self.pad_zoom:                         # palier franchi : les autres aussi (hors CAD)
                padded = [i for i in self.plain_items() if not i.isSelected()
                          and not isinstance(i, (FrameItem, ConnectorItem))]
                for item in padded:
                    item.prepareGeometryChange()             # zone d'avant : retiree de l'index
            for item in targets:
                item.prepareGeometryChange()
            self.zoom, self.pad_zoom = zoom, pad
            for item in targets:
                item.zoom_changed()

    # -- page (reglages du .mro) --
    def set_page(self, page: dict, record: bool = True, text: str = "Réglages de la page", replace: bool = False):
        """`page` fondue dans les reglages de la page ; `replace` (annulation) : `page` EST l'etat complet — une cle
        absente de l'etat d'avant (page « cad » creee par le 1er reglage du dessin) disparait."""
        new = dict(model.PAGE_DEFAULTS)
        if not replace:
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
            elif getattr(item, "CAD", False):
                item.page_changed()                  # calques (ByLayer, visibilite, verrou) relus
        self.update()
        self.pageChanged.emit()
        if record:
            self.push(before, {PAGE: dict(self.page)}, text)

    # -- modules (Miro / CAD) : elements grises ou masques --
    @staticmethod
    def module_of(item) -> str:
        return getattr(item, "MODULE", None) or ("cad" if getattr(item, "CAD", False) else "miro")

    def module_hidden(self, module: str) -> bool:
        return self.module_look[module]["hide"]

    def module_faded(self, module: str) -> bool:
        """Grise (et pas masque : masquer prime)."""
        look = self.module_look[module]
        return look["fade"] and not look["hide"]

    def module_styled(self, module: str) -> bool:
        look = self.module_look[module]
        return look["fade"] or look["hide"]

    def item_active(self, item) -> bool:
        """L'element se choisit a la souris (ni grise ni masque par son module)."""
        return item.isEnabled() and not (self.module_of(item) == "cad" and self.module_styled("cad"))

    def item_opacity(self, item) -> float:
        """Opacite normale d'un element (la gomme la rend apres l'avoir baissee)."""
        hook = getattr(item, "module_opacity", None)          # module Design : opacite propre, page grisee seule
        if hook is not None:
            return hook(self.module_faded(self.module_of(item)))
        return cad_items.FADE_OPACITY if self.module_faded(self.module_of(item)) else 1.0

    def set_module_look(self, module: str, fade: bool | None = None, hide: bool | None = None):
        """Grise / masque les elements d'un module (affichage seulement : rien dans le fichier ni dans l'annulation)."""
        look = self.module_look[module]
        new = {"fade": look["fade"] if fade is None else bool(fade), "hide": look["hide"] if hide is None else bool(hide)}
        if new == look:
            return
        self.module_look[module] = new
        if module == "cad":
            # Etat GLOBAL lu au dessin et a la recherche (`cad_items.cad_module_look`) : seule la selection est retiree.
            if new["fade"] or new["hide"]:
                for item in self.selectedItems():
                    if self.module_of(item) == "cad":
                        item.setSelected(False)
        else:
            for item in list(self._items.values()):
                if self.module_of(item) == module:
                    self.apply_module_look(item)
        self.update()

    def set_module_state(self, module: str, **changes):
        """Barre des modules : masquer (« hide »), griser (« fade »), isoler (« solo »). Isoler : seuls les modules
        isoles restent visibles (masquer ne vaut plus pour eux, griser si) ; les autres sont masques."""
        self.module_state[module] = dict(self.module_state[module], **{k: bool(v) for k, v in changes.items()})
        self._apply_module_states()

    def reset_module_states(self, solo_only: bool = False):
        """Tout afficher et sortir de l'isolation (`solo_only` : sortir de l'isolation seulement)."""
        for state in self.module_state.values():
            state["solo"] = False
            if not solo_only:
                state["fade"] = state["hide"] = False
        self._apply_module_states()

    def _apply_module_states(self):
        solo_any = any(s["solo"] for s in self.module_state.values())
        for module, state in self.module_state.items():
            hide = (not state["solo"]) if solo_any else state["hide"]
            self.set_module_look(module, fade=state["fade"], hide=hide)

    def refresh_faded(self):
        """Opacite ou saturation des elements grises changee (reglage) : elements des modules grises remis a jour."""
        for module in self.module_look:
            if self.module_faded(module) and module != "cad":
                for item in list(self._items.values()):
                    if self.module_of(item) == module:
                        self.apply_module_look(item)
        self.update()

    def apply_module_look(self, item):
        module = self.module_of(item)
        if module == "cad":
            return                                      # module CAD : etat global (`set_module_look`)
        active = not self.module_styled(module)
        if not active and item.isSelected():
            item.setSelected(False)
        item.setEnabled(active)                         # desactive : ni clic, ni selection (Qt), ni edition
        item.setOpacity(self.item_opacity(item))
        self._fade_effect(item, module)
        if isinstance(item, CommentItem):
            item.sync()
        else:
            item.setVisible(not self.module_hidden(module))

    def _fade_effect(self, item, module: str):
        """Saturation des elements grises (reglage, `cad_items.FADE_SATURATION`) : effet de desaturation pose sur
        l'element de tete seulement (ses enfants du meme module en heritent), retire des qu'il ne sert plus. Aucun
        effet a la saturation 100 % (le cas par defaut : rien de plus a peindre)."""
        sat = cad_items.FADE_SATURATION
        parent = item.parentItem()
        want = self.module_faded(module) and sat < 0.999 and not (
            parent is not None and self.module_of(parent) == module)
        effect = item.graphicsEffect()
        if want:
            if effect is None:
                effect = _FadeEffect()
                item.setGraphicsEffect(effect)
            if isinstance(effect, _FadeEffect):
                effect.setStrength(1.0 - sat)
        elif isinstance(effect, _FadeEffect):
            item.setGraphicsEffect(None)

    def cad_style_changed(self):
        """Reglages generaux du CAD (types de ligne, unite) changes : proprietes des lignes relues (seules celles dont
        l'aspect change sont refaites)."""
        for item in self._items.values():
            if getattr(item, "CAD", False):
                item.page_changed()

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
    def load_data(self, data: dict, progressive: bool = False):
        """Remplace le contenu par `data`. `progressive` (ouverture dans le board) : au-dela de
        LOAD_PROGRESSIVE_MIN elements, la suite est creee par tranches (`loadProgress`, `loading()`) ; les lignes
        CAD ne sont regroupees en lots (et peintes) qu'a la fin, une fois."""
        self._load_job = None                                   # un chargement precedent s'arrete
        self.bulk_loading = False
        hold_gc(id(self), False)
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
        raw_items = list(data.get("items", []))
        if progressive and len(raw_items) > LOAD_PROGRESSIVE_MIN:
            self.undo.setClean()
            self.bulk_loading = True
            self._load_job = {"items": raw_items, "next": 0}
            self._bulk_cad_tail = True                          # tout ce qui est charge jusqu'ici : lignes CAD
            hold_gc(id(self), True)
            self.destroyed.connect(lambda _o=None, key=id(self): hold_gc(key, False))     # scene fermee avant la fin
            self._load_slice(self._load_job)
            return
        for raw in raw_items:
            self._add(raw)
        self.refresh_links()
        self.undo.setClean()

    def loading(self) -> bool:
        """Chargement par tranches en cours (`load_data(progressive=True)`)."""
        return self._load_job is not None

    def _load_slice(self, job: dict):
        if job is not self._load_job:
            return                                              # remplace par un autre chargement
        items, index = job["items"], job["next"]
        deadline = time.perf_counter() + LOAD_SLICE_S
        added = []
        while index < len(items):
            added.append(self._add(items[index]))
            index += 1
            if not index % 64 and time.perf_counter() >= deadline:
                break
        job["next"] = index
        layer = getattr(self, "cad_layer", None)
        if layer is not None:
            layer.bulk_append(added)            # lignes CAD : peintes au fur et a mesure (listes de dessin completees)
        if index < len(items):
            self.loadProgress.emit(index, len(items))
            QTimer.singleShot(0, self, lambda: self._load_slice(job))
            return
        self._load_job = None
        self.bulk_loading = False
        hold_gc(id(self), False)
        layer = getattr(self, "cad_layer", None)
        if layer is not None:
            layer.bulk_loaded()
        self.refresh_links()
        self.loadProgress.emit(index, len(items))

    def to_data(self, view: dict | None = None) -> dict:
        board = model.empty_board()
        board.update(copy.deepcopy(self._extra))
        board["version"] = max(model.VERSION, getattr(self, "_version", model.VERSION))
        board["page"] = dict(self.page)
        if view:
            board["view"] = view
        items = sorted(self._items.values(), key=lambda i: (i.kind != "frame", i.kind == "comment", i.zValue()))
        for item in items:                                      # modules a ressources (Photoshop : conteneur du document)
            hook = getattr(item, "before_save", None)
            if hook is not None:
                hook()
        board["items"] = [item.to_dict() for item in items] + copy.deepcopy(self._foreign)
        job = self._load_job
        if job is not None:                                     # jamais un board tronque (enregistrement pendant
            board["items"] += copy.deepcopy(job["items"][job["next"]:])     # le chargement par tranches)
        return board

    def content_rect(self) -> QRectF:
        rect = QRectF()
        for item in self._items.values():
            if not isinstance(item, CommentItem):
                rect = rect.united(item.scene_rect())
        return rect

    def assets_in_use(self) -> set[str]:
        """Images referencees par l'etat actuel ET par tout etat encore accessible par l'annulation."""
        names = {i.data.get("asset") for i in self._items.values() if i.kind == "image" or i.data.get("asset")}
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
            if data.get("asset") and source_board and self.board_path is not None:
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

    @property
    def grid_look(self) -> dict:
        """Habillage EFFECTIF de la grille : Reglages > Module MRO > Grille, remplaces par ceux du dessin (reglages du
        dessin, `page["cad"]["overrides"]`). Garde tant que ni l'un ni l'autre ne change."""
        raw = self.page.get("cad")
        cached = self._grid_look
        if cached is None or cached[0] is not raw or cached[1] is not self.grid_settings:
            own = {k: v for k, v in cad_model.drawing_overrides(raw).items() if k.startswith("board_grid_")}
            cached = self._grid_look = (raw, self.grid_settings, grid_look({**self.grid_settings, **own}))
        return cached[2]

    def _grid_scale(self) -> float:
        """Unites du board par unite du pas de la grille (unite du board, ou unite de mesure du CAD)."""
        return unit_of(self, cad_model.page_cad(self.page)) if self.grid_look["unit"] == "cad" else 1.0

    def grid_base(self) -> float:
        """Pas de base de la grille, en unites du board."""
        return self.grid_look["step"] * self._grid_scale()

    def grid_origin(self) -> tuple[float, float]:
        """Origine de la grille dans la scene (Y du reglage vers le HAUT, comme le CAD)."""
        ox, oy = self.grid_look["origin"]
        k = self._grid_scale()
        return ox * k, -oy * k

    def grid_snap(self, value: float, axis: int, step: float | None = None) -> float:
        """Ligne de grille la plus proche (axe 0 = x, 1 = y de la scene) : magnetisme du board."""
        step = step or self.grid_step()
        origin = self.grid_origin()[axis]
        return round((value - origin) / step) * step + origin

    def grid_step(self) -> float:
        """Pas du niveau de grille le plus fin affiche (le magnetisme de grille, du board comme du CAD, suit ce
        qu'on voit)."""
        look = self.grid_look
        step = first_grid_step(self.zoom, self.grid_base(), look["factor"], look["full"])
        while grid_alpha(step * self.zoom, look["start"], look["full"]) < 0.25:
            step *= look["factor"]
        return step

    def set_grid_settings(self, settings: dict):
        """Reglages generaux de la grille (cles `board_grid_*`)."""
        values = {k: v for k, v in (settings or {}).items() if k.startswith("board_grid_")}
        if values != self.grid_settings:
            self.grid_settings = values
            self.update()

    def _candidates(self, exclude: set) -> list[QRectF]:
        """Cadres des elements visibles vers lesquels aimanter ; calcules UNE fois par geste (ils ne bougent
        pas pendant qu'on en tire d'autres) : un deplacement ne refait aucun parcours des elements."""
        key = (frozenset(exclude), self.zoom, self.visible_rect)
        cached = getattr(self, "_snap_cache", None)
        if cached is not None and cached[0] == key:
            return cached[1]
        area = self.visible_rect if self.visible_rect.isValid() else QRectF(-1e5, -1e5, 2e5, 2e5)
        rects = [_snap_target(i) for i in self._items.values()
                 if i.item_id not in exclude and not isinstance(i, (ConnectorItem, CommentItem, InkItem))
                 and not getattr(i, "CAD", False)
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
            gx = self._best((rect.left(),), (self.grid_snap(rect.left(), 0, step),), threshold)
            gy = self._best((rect.top(),), (self.grid_snap(rect.top(), 1, step),), threshold)
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
            near = _near(others, x, 0)
            top = min([rect.top()] + [o.top() for o in near])
            bottom = max([rect.bottom()] + [o.bottom() for o in near])
            guides.append(GuideLine(x, top, x, bottom, kind=guide_kind(near)))
        if best_y and best_y[1] is not None:
            y = best_y[1]
            near = _near(others, y, 1)
            left = min([rect.left()] + [o.left() for o in near])
            right = max([rect.right()] + [o.right() for o in near])
            guides.append(GuideLine(left, y, right, y, kind=guide_kind(near)))
        return guides

    def _edge_kind(self, others, value: float, axis: int) -> str:
        """Sorte du guide d'un redimensionnement, le long de `value` (un bord ou centre des cadres `others`, axe 0 = x,
        1 = y) : table {valeur : tous internes ?} faite UNE fois par liste de candidats (un geste), puis lue sans
        parcourir les elements (2 000 elements visibles : 2,3 ms par guide et par mouvement autrement)."""
        kept = getattr(self, "_edge_kinds", None)
        if kept is None or kept[0] is not others:
            tables = ({}, {})
            for o in others:
                for table, values in ((tables[0], (o.left(), o.center().x(), o.right())),
                                      (tables[1], (o.top(), o.center().y(), o.bottom()))):
                    for v in values:
                        table[v] = table.get(v, True) and o.inner
            kept = self._edge_kinds = (others, tables)
        return snap_guides.INNER if kept[1][axis].get(value) else snap_guides.DOCUMENTS

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
            xs += [self.grid_snap(scene_rect.left(), 0, step), self.grid_snap(scene_rect.right(), 0, step)]
            ys += [self.grid_snap(scene_rect.top(), 1, step), self.grid_snap(scene_rect.bottom(), 1, step)]
        guides = []
        show = self.snap.get("guides", True)            # guides (et leur sorte) faits seulement s'ils sont montres
        left, top, right, bottom = scene_rect.left(), scene_rect.top(), scene_rect.right(), scene_rect.bottom()
        # Cadre sur SON document (PDF : bas d'une page, largeur du contenu) : tailles de cadre où un bord du
        # document tombe sur le bord du cadre, pour la taille proposee ; plus proches qu'un autre repere : elles
        # l'emportent (guide « Cadre sur son document », `snap_guides.FRAME`).
        own_sizes = getattr(item, "snap_document_sizes", None)
        for side in handle:
            if side in "lr":
                value = left if side == "l" else right
                best = self._best((value,), xs, threshold)
                kind = None
                if own_sizes is not None:
                    widths = own_sizes(right - left, bottom - top)[0]
                    own = self._best((value,), [left + s if side == "r" else right - s for s in widths], threshold)
                    if own and (best is None or abs(own[0]) <= abs(best[0])):
                        best, kind = own, snap_guides.FRAME
                if best:
                    if side == "l":
                        left += best[0]
                    else:
                        right += best[0]
                    if show:
                        guides.append(GuideLine(best[1], top - 40, best[1], bottom + 40,
                                                kind=kind or self._edge_kind(others, best[1], 0)))
            elif side in "tb":
                value = top if side == "t" else bottom
                best = self._best((value,), ys, threshold)
                kind = None
                if own_sizes is not None:
                    heights = own_sizes(right - left, bottom - top)[1]
                    own = self._best((value,), [top + s if side == "b" else bottom - s for s in heights], threshold)
                    if own and (best is None or abs(own[0]) <= abs(best[0])):
                        best, kind = own, snap_guides.FRAME
                if best:
                    if side == "t":
                        top += best[0]
                    else:
                        bottom += best[0]
                    if show:
                        y = bottom if kind else best[1]         # le bas de la page tombe sur le bas du cadre
                        guides.append(GuideLine(left - 40, y, right + 40, y,
                                                kind=kind or self._edge_kind(others, best[1], 1)))
        self._set_guides(guides)
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
            xs += [self.grid_snap(scene_rect.left(), 0, step), self.grid_snap(scene_rect.right(), 0, step)]
            ys += [self.grid_snap(scene_rect.top(), 1, step), self.grid_snap(scene_rect.bottom(), 1, step)]
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
            guides.append(GuideLine(best_x[1], scene_rect.top() - 40, best_x[1], scene_rect.bottom() + 40,
                                    kind=self._edge_kind(others, best_x[1], 0)))
        elif best_y:
            height = abs(best_y[1] - fixed_y)
            width = height * ratio
            guides.append(GuideLine(scene_rect.left() - 40, best_y[1], scene_rect.right() + 40, best_y[1],
                                    kind=self._edge_kind(others, best_y[1], 1)))
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
        le magnetisme de grille). Refaite seulement quand le zoom change (petite image, < 1 ms). Sert aux styles
        points / croix et hors de l'ecran ; a l'ecran, les LIGNES : `_paint_grid_fast`."""
        look = self.grid_look
        levels, period, ink, strength = self._grid_levels(scale)
        size = max(4, int(round(period * scale)))
        origin = self.grid_origin()
        key = (size, period, tuple((s, round(g, 3)) for s, g in levels), ink.rgb(), round(strength, 4),
               look["style"], look["thickness"], look["dot"], origin)
        cached = getattr(self, "_tile", None)
        if cached is not None and cached[0] == key:
            return cached[1]
        image = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
        image.fill(Qt.transparent)
        painter = QPainter(image)
        thick = look["thickness"]
        for level_step, gain in levels:
            color = QColor(ink)
            color.setAlphaF(min(1.0, strength * gain))
            count = int(round(period / level_step))
            spots = [int(round(n * size / count)) for n in range(count)]
            if look["style"] == "dots":                     # points aux croisements
                dot = look["dot"]
                for x in spots:
                    for y in spots:
                        painter.fillRect(x - dot // 2, y - dot // 2, dot, dot, color)
                continue
            if look["style"] == "crosses":                  # croix aux croisements
                arm = look["dot"] + 1
                for x in spots:
                    for y in spots:
                        painter.fillRect(x - arm, y, 2 * arm + thick, thick, color)
                        painter.fillRect(x, y - arm, thick, 2 * arm + thick, color)
                continue
            for x in spots:
                painter.fillRect(x, 0, thick, size, color)
                painter.fillRect(0, x, size, thick, color)
        painter.end()
        brush = QBrush(QPixmap.fromImage(image))
        brush.setTransform(QTransform().translate(origin[0], origin[1]).scale(period / size, period / size))
        self._tile = (key, brush)
        return brush

    def _grid_levels(self, scale: float) -> tuple:
        """(niveaux visibles [(pas, gain d'intensite)], periode = pas du 1er niveau plein, encre, intensite)."""
        look = self.grid_look
        levels = []
        step = first_grid_step(scale, self.grid_base(), look["factor"], look["full"])
        previous = 0.0
        for _level in range(look["levels"]):
            alpha = grid_alpha(step * scale, look["start"], look["full"])
            gain = alpha - previous
            if gain > 0.004:
                levels.append((step, gain))
            previous = max(previous, alpha)
            if alpha >= 0.999:
                break
            step *= look["factor"]
        period = step                                       # premier niveau plein : la grille se repete
        if look["auto_color"]:
            # 0.066 = noir a 6,6 % = #e2e2e2 sur #f2f2f2 (ligne pleine mesuree) ; les niveaux s'ajoutent.
            ink, strength = self.grid_ink(), look["intensity"]
        else:
            ink = QColor(look["color"])
            strength = ink.alphaF()
        return levels, period, ink, strength

    GRID_MAX_LINES = 4000                                   # au-dela (jamais : apparition a 12 px), tuile

    def _paint_grid_fast(self, painter, rect: QRectF, scale: float) -> bool:
        """Fond + grille en LIGNES d'un seul geste, a l'ecran (pas en export). Le pinceau de la tuile, mis a l'echelle
        et lisse, puis le fond coutaient ~5,5 ms par peinture complete en 2400 x 1300 (un tiers d'un cran de zoom a
        5 000 lignes) — et des lignes verticales tracees une a une, plus encore (le moteur remplit un trait vertical
        pixel par pixel, ~75 us chacun). Ici : une BANDE de quelques rangees = le fond avec les verticales deja
        melangees, RECOPIEE (mode Source, aucun melange) sur toute la hauteur, puis les horizontales (rectangles d'une
        rangee : rapides). Chaque ligne tombe sur un pixel entier. False = cas non couvert (export, autre moteur,
        ecran HiDPI, fond translucide, style points / croix, trop de lignes) : fond + tuile."""
        look = self.grid_look
        if (self.exporting or look["style"] != "lines" or self.background.alpha() < 255
                or painter.paintEngine() is None or painter.paintEngine().type() != QPaintEngine.Raster
                or abs((painter.device().devicePixelRatioF() or 1.0) - 1.0) > 1e-6):
            return False
        levels, _period, ink, strength = self._grid_levels(scale)
        transform = painter.worldTransform()
        dx, dy = transform.dx(), transform.dy()
        ox, oy = self.grid_origin()
        thick = max(1, int(look["thickness"]))
        device = transform.mapRect(rect)
        left, top = math.floor(device.left()), math.floor(device.top())
        width, height = math.ceil(device.right()) - left, math.ceil(device.bottom()) - top
        if width <= 0 or height <= 0:
            return True
        band_rows = 32
        band = QImage(width, band_rows, QImage.Format_ARGB32_Premultiplied)
        band.fill(self.background)
        band_painter = QPainter(band)
        rows = []
        for level_step, gain in levels:
            x0, x1 = math.ceil((rect.left() - ox) / level_step), math.floor((rect.right() - ox) / level_step)
            y0, y1 = math.ceil((rect.top() - oy) / level_step), math.floor((rect.bottom() - oy) / level_step)
            if (x1 - x0) + (y1 - y0) > self.GRID_MAX_LINES:
                band_painter.end()
                return False
            color = QColor(ink)
            color.setAlphaF(min(1.0, strength * gain))
            for k in range(x0, x1 + 1):
                band_painter.fillRect(math.floor((ox + k * level_step) * scale + dx + 0.5) - left, 0, thick,
                                      band_rows, color)
            rows += [(QRect(left, math.floor((oy + k * level_step) * scale + dy + 0.5), width, thick), color)
                     for k in range(y0, y1 + 1)]
        band_painter.end()
        brush = QBrush(band)
        brush.setTransform(QTransform.fromTranslate(left, top))
        painter.save()
        painter.resetTransform()
        painter.setRenderHint(QPainter.Antialiasing, False)
        painter.setCompositionMode(QPainter.CompositionMode_Source)
        painter.fillRect(QRect(left, top, width, height), brush)          # recopie, sans melange
        painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
        for r, color in rows:
            painter.fillRect(r, color)
        painter.restore()
        return True

    def drawBackground(self, painter, rect):
        transform = painter.worldTransform()
        scale = transform.m11() or 1.0
        grid = not ((self.exporting and not self.export_grid) or not self.page.get("grid", True))
        if transform.m12() or transform.m21():
            painter.fillRect(rect, self.background)
            return                                         # vue tournee : jamais le cas ici
        if not (grid and self._paint_grid_fast(painter, rect, scale)):
            painter.fillRect(rect, self.background)
            if grid:
                painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
                painter.fillRect(rect, self._grid_tile(scale))
        if grid:
            look = self.grid_look
            if look["axes"]:                                # axes passant par l'origine de la grille
                ox, oy = self.grid_origin()
                pen = QPen(QColor(look["axes_color"]), look["axes_thickness"])
                pen.setCosmetic(True)
                painter.setPen(pen)
                if rect.left() <= ox <= rect.right():
                    painter.drawLine(QPointF(ox, rect.top()), QPointF(ox, rect.bottom()))
                if rect.top() <= oy <= rect.bottom():
                    painter.drawLine(QPointF(rect.left(), oy), QPointF(rect.right(), oy))

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
        snap_guides.draw(painter, self.guides)          # chacun selon sa sorte (Reglages > Module MRO > Magnetisme)
