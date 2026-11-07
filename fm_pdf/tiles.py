"""Cache des tuiles rendues (Qt, sans widget) : QImage par (génération, page, échelle, colonne, ligne), mémoire
bornée en OCTETS (LRU), tuiles « périmées » gardées à l'écran jusqu'à leur remplacement (aucun clignotement quand
un champ de formulaire change)."""
from __future__ import annotations

from collections import OrderedDict

TILE = 512                                    # côté d'une tuile en pixels de l'écran (physiques)


class TileCache:
    def __init__(self, budget_bytes: int = 256 * 1024 * 1024):
        self.budget = int(budget_bytes)
        self._items: OrderedDict = OrderedDict()   # clé -> [image, périmée]
        self._bytes = 0
        self._by_page: dict = {}                    # (génération, page) -> {échelle: {(tx, ty)}}

    def __len__(self):
        return len(self._items)

    @property
    def bytes(self) -> int:
        return self._bytes

    def get(self, key):
        item = self._items.get(key)
        if item is None:
            return None, False
        self._items.move_to_end(key)
        return item[0], item[1]

    def put(self, key, image) -> None:
        old = self._items.pop(key, None)
        if old is not None:
            self._bytes -= old[0].sizeInBytes()
        self._items[key] = [image, False]
        self._bytes += image.sizeInBytes()
        gen, page, scale, tx, ty = key
        self._by_page.setdefault((gen, page), {}).setdefault(scale, set()).add((tx, ty))
        self.trim()

    def _drop(self, key) -> None:
        item = self._items.pop(key, None)
        if item is None:
            return
        self._bytes -= item[0].sizeInBytes()
        gen, page, scale, tx, ty = key
        scales = self._by_page.get((gen, page))
        if scales and scale in scales:
            scales[scale].discard((tx, ty))
            if not scales[scale]:
                del scales[scale]
            if not scales:
                del self._by_page[(gen, page)]

    def trim(self, protect=()) -> None:
        protect = set(protect)
        for key in list(self._items):
            if self._bytes <= self.budget:
                break
            if key not in protect:
                self._drop(key)

    def scales(self, gen, page) -> dict:
        """{échelle: {(tx, ty)}} des tuiles gardées pour cette page."""
        return self._by_page.get((gen, page), {})

    def mark_stale(self, gen, page, scale, tiles) -> None:
        for tx, ty in tiles:
            item = self._items.get((gen, page, scale, tx, ty))
            if item is not None:
                item[1] = True

    def drop_scales_except(self, gen, page, keep) -> None:
        for scale in list(self.scales(gen, page)):
            if scale != keep:
                for tx, ty in list(self.scales(gen, page).get(scale, ())):
                    self._drop((gen, page, scale, tx, ty))

    def drop_generation_except(self, gen) -> None:
        for key in [k for k in self._items if k[0] != gen]:
            self._drop(key)

    def clear(self) -> None:
        self._items.clear()
        self._by_page.clear()
        self._bytes = 0
