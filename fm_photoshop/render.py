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
        self.pivot = None                           # réglage au curseur d'UN calque : composition SOUS lui gardée par tuile
        self.pending_props: set = set()             # tuiles à recomposer du calque vers le haut (pivot actif)
        self.computed = 0                           # compteur : tuiles / zones recomposées (tests, mesures)
        session.listeners.append(self._on_change)

    def detach(self):
        if self._on_change in self.session.listeners:
            self.session.listeners.remove(self._on_change)

    def _on_change(self, kind, rect):
        if kind in ("edit", "paint") and rect is not None:
            self.invalidate(rect)
        elif kind == "props" and self.pivot is not None:
            self.pending_props |= set(self.tiles)
            self.version += 1
        elif kind in ("structure", "reload", "props"):
            self.clear()

    # -- invalidation --
    def begin_pivot(self, layer) -> bool:
        """Prépare les réglages en direct de `layer` (calque du niveau supérieur, non écrêté). Les tuiles ne
        recomposent alors que du calque vers le haut ; la composition dessous est calculée une fois par tuile."""
        doc = self.session.doc
        if layer.clip or not any(l is layer for l in doc.layers):
            return False
        if self.pivot is not None and self.pivot["layer"] is layer:
            return True
        self.end_pivot()
        self.pivot = {"layer": layer, "below": {}}
        return True

    def end_pivot(self):
        """Fin du réglage : les tuiles pas encore recomposées sont jetées (recalcul complet à la demande)."""
        for key in self.pending_props:
            self.tiles.pop(key, None)
        self.pending_props.clear()
        self.pivot = None

    def clear(self):
        self.tiles.clear()
        self.pending.clear()
        self.pending_props.clear()
        if self.pivot is not None:
            self.pivot["below"].clear()
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
        elif key in self.pending_props and self.pivot is not None:
            layers = doc.layers
            index = next(i for i, l in enumerate(layers) if l is self.pivot["layer"])
            below = self.pivot["below"].get(key)
            if below is None:
                below = self.pivot["below"][key] = C.compose(layers[:index], rect)
            array = entry[0]
            array[...] = C.to_premult_u8(C.compose(layers[index:], rect, below.copy()))
            self.pending_props.discard(key)
            self.pending.pop(key, None)
            self.computed += 1
            image = QImage(array.data, array.shape[1], array.shape[0], array.shape[1] * 4,
                           QImage.Format_ARGB32_Premultiplied)
            entry = self.tiles[key] = (array, image)
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
        return key in self.tiles and key not in self.pending and key not in self.pending_props

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
