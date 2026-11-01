"""Affichage du document (Qt) : composition par TUILES de 256 × 256, gardées par session.

Une seule `TileCache` par session, partagée par l'élément du Board et l'éditeur Standard : passer de l'un à l'autre ne
recompose rien. Invalidation EXPLICITE : une modification de pixels (« edit », zone) ne recompose que la partie
touchée des tuiles déjà calculées, et seulement quand on les demande (`tile`) ; un changement de structure
(« structure » : ordre, visibilité, opacité, mode, masque) ou un rechargement vide tout. Tuiles manquantes : calculées
à la demande, ou en tranches de temps (`pump`) pour ne pas figer l'interface sur un grand document."""
from __future__ import annotations

import time

import numpy as np
from PySide6.QtGui import QImage

from . import compose as C
from .planes import rect_intersect, rect_union

TILE = 256


def checker_brush(a: str, b: str, size: int):
    """Damier de transparence (pixels d'ÉCRAN, indépendant du zoom, comme Photoshop)."""
    from PySide6.QtGui import QBrush, QColor, QPainter, QPixmap
    pixmap = QPixmap(size * 2, size * 2)
    painter = QPainter(pixmap)
    painter.fillRect(pixmap.rect(), QColor(a))
    painter.fillRect(0, 0, size, size, QColor(b))
    painter.fillRect(size, size, size, size, QColor(b))
    painter.end()
    return QBrush(pixmap)


class TileCache:
    def __init__(self, session):
        self.session = session
        self.tiles: dict = {}                       # (tx, ty) -> (tableau BGRA prémultiplié, QImage)
        self.pending: dict = {}                     # (tx, ty) -> sous-rectangle du document à recomposer
        self.version = 0                            # +1 à chaque invalidation (les aperçus gardés se comparent dessus)
        self.computed = 0                           # compteur : tuiles / zones recomposées (tests, mesures)
        session.listeners.append(self._on_change)

    def detach(self):
        if self._on_change in self.session.listeners:
            self.session.listeners.remove(self._on_change)

    def _on_change(self, kind, rect):
        if kind in ("edit", "paint") and rect is not None:
            self.invalidate(rect)
        elif kind in ("structure", "reload"):
            self.clear()

    # -- invalidation --
    def clear(self):
        self.tiles.clear()
        self.pending.clear()
        self.version += 1

    def invalidate(self, rect):
        rect = rect_intersect(tuple(rect), self.session.doc.rect())
        if rect is None:
            return
        self.version += 1
        for ty in range(rect[1] // TILE, (rect[3] - 1) // TILE + 1):
            for tx in range(rect[0] // TILE, (rect[2] - 1) // TILE + 1):
                key = (tx, ty)
                if key in self.tiles:
                    sub = rect_intersect(rect, self._rect(key))
                    self.pending[key] = rect_union(self.pending.get(key), sub)

    # -- tuiles --
    def _rect(self, key):
        tx, ty = key
        return rect_intersect((tx * TILE, ty * TILE, tx * TILE + TILE, ty * TILE + TILE), self.session.doc.rect())

    def tile(self, key):
        """Image de la tuile (calculée ou mise à jour si besoin), ou None hors du document."""
        rect = self._rect(key)
        if rect is None:
            return None
        entry = self.tiles.get(key)
        doc = self.session.doc
        if entry is None:
            array = np.ascontiguousarray(C.to_premult_u8(C.compose(doc.layers, rect)))
            image = QImage(array.data, array.shape[1], array.shape[0], array.shape[1] * 4,
                           QImage.Format_ARGB32_Premultiplied)
            entry = self.tiles[key] = (array, image)
            self.pending.pop(key, None)
            self.computed += 1
        elif key in self.pending:
            sub = self.pending.pop(key)
            part = np.ascontiguousarray(C.to_premult_u8(C.compose(doc.layers, sub)))
            array = entry[0]
            array[sub[1] - rect[1]:sub[3] - rect[1], sub[0] - rect[0]:sub[2] - rect[0]] = part
            self.computed += 1
            image = QImage(array.data, array.shape[1], array.shape[0], array.shape[1] * 4,
                           QImage.Format_ARGB32_Premultiplied)         # nouvel objet : Qt jette ses copies gardées
            entry = self.tiles[key] = (array, image)
        return entry[1]

    def keys_for(self, rect):
        rect = rect_intersect(tuple(rect), self.session.doc.rect())
        if rect is None:
            return []
        return [(tx, ty) for ty in range(rect[1] // TILE, (rect[3] - 1) // TILE + 1)
                for tx in range(rect[0] // TILE, (rect[2] - 1) // TILE + 1)]

    def is_ready(self, key) -> bool:
        return key in self.tiles and key not in self.pending

    def pump(self, keys, budget_ms: float = 10.0) -> bool:
        """Calcule des tuiles manquantes / périmées pendant `budget_ms` ; vrai quand tout est prêt."""
        end = time.perf_counter() + budget_ms / 1000.0
        for key in keys:
            if not self.is_ready(key):
                self.tile(key)
                if time.perf_counter() >= end:
                    break
        return all(self.is_ready(k) for k in keys)


def cache_for(session) -> TileCache:
    cache = getattr(session, "tiles", None)
    if cache is None:
        cache = session.tiles = TileCache(session)
    return cache
