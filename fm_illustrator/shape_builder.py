"""Outil Shape Builder (Maj+M) : sur les objets choisis, les ZONES (`pathfinder.divide`) se survolent et se combinent.

- survol : la zone sous la souris est hachurée ;
- glisser à travers des zones (ou clic sur une zone) : elles sont réunies en un objet ;
- Alt + glisser / Alt + clic : les zones traversées sont supprimées ;
- les autres zones restent des objets séparés (les objets d'origine sont « divisés », comme Illustrator).
Style de l'objet réuni : celui de la zone où le geste commence (style de son objet d'origine ; Illustrator peut aussi
prendre la couleur du nuancier : non repris). Une étape d'annulation. Zones calculées une fois par sélection
(clé : identifiants + étape d'annulation), pas à chaque mouvement."""
from __future__ import annotations

from PySide6.QtCore import QPointF, Qt

from fm_board import model as board_model
from . import bezier as bz, pathfinder as pf
from .items import qpath
from .tools import Tool


class ShapeBuilderTool(Tool):
    name, label = "shape_builder", "Shape Builder (Maj+M ; Alt = supprimer des zones)"

    def __init__(self, ctl):
        super().__init__(ctl)
        self._key = None
        self.regions: list = []             # [(objet d'origine, sous-tracés en scène, QPainterPath)]
        self.items: list = []
        self.picked: list[int] = []
        self.gesture = None

    # -- zones --
    def _ensure_regions(self):
        ctl = self.ctl
        items = ctl.selection()
        key = (tuple(i.item_id for i in items), ctl.scene.undo.index())
        if key == self._key:
            return
        self._key = key
        self.items = items
        self.regions = []
        if len(items) < 2:
            return
        shapes = [(ctl.scene_subpaths(i), i.data.get("fill_rule", "nonzero")) for i in items]
        for owner, subs in pf.divide(shapes):
            self.regions.append((items[owner], subs, qpath(subs)))

    def region_at(self, pos: QPointF) -> int | None:
        for n in range(len(self.regions) - 1, -1, -1):
            if self.regions[n][2].contains(pos):
                return n
        return None

    def _show(self, indexes, delete: bool = False):
        paths = [self.regions[n][2] for n in indexes]
        self.ctl.preview = ("regions", paths, delete) if paths else None

    # -- gestes --
    def hover(self, pos, mods):
        self._ensure_regions()
        n = self.region_at(pos)
        self._show([] if n is None else [n], bool(mods & Qt.AltModifier))

    def press(self, pos, mods):
        self._ensure_regions()
        n = self.region_at(pos)
        if n is None:
            item = self.ctl.object_at(pos)
            if item is not None:                        # clic sur un objet hors sélection : il rejoint la sélection
                self.ctl.select([item], add=True)
            return
        self.gesture = bool(mods & Qt.AltModifier)
        self.picked = [n]
        self._show(self.picked, self.gesture)

    def drag(self, pos, mods):
        if self.gesture is None:
            return
        n = self.region_at(pos)
        if n is not None and n not in self.picked:
            self.picked.append(n)
        self._show(self.picked, self.gesture)

    def release(self, pos, mods):
        if self.gesture is None:
            return
        delete, picked = self.gesture, list(self.picked)
        self.gesture = None
        self.picked = []
        self.ctl.preview = None
        self.apply(picked, delete)

    def apply(self, picked: list[int], delete: bool) -> list:
        """Remplace les objets choisis par les zones : `picked` réunies (ou supprimées si `delete`)."""
        from .tools_draw import place_origin
        ctl = self.ctl
        if not picked or not self.regions:
            return []
        added = []
        z = max(i.zValue() for i in self.items)
        if not delete:
            merged = pf.combine([(self.regions[n][1], "nonzero") for n in picked], "unite")
            added.append((self.regions[picked[0]][0], merged))
        for n, (owner, subs, _path) in enumerate(self.regions):
            if n not in picked:
                added.append((owner, subs))
        dicts = []
        for k, (owner, subs) in enumerate(added):
            subs, origin = place_origin(bz.copy_subpaths(subs))
            data = owner.to_dict()
            data.update(id=board_model.new_id(), subpaths=subs, x=origin.x(), y=origin.y(), group="",
                        fill_rule="nonzero", z=z - len(added) + 1 + k)
            dicts.append(data)
        new = ctl.scene.replace_items(self.items, dicts, "Shape Builder")
        ctl.select(new)
        self._key = None
        return new

    def key_press(self, key, mods) -> bool:
        if key == Qt.Key_Escape and self.gesture is not None:
            self.cancel()
            return True
        return False

    def key_release(self, key, mods) -> bool:
        return False

    def cancel(self):
        self.gesture = None
        self.picked = []
        self.ctl.preview = None

    def busy(self) -> bool:
        return self.gesture is not None

    def cursor(self):
        return Qt.CrossCursor
