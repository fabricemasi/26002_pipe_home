"""Plan de pixels (SANS Qt) : un tableau uint8 (h, l, canaux) posé à (x, y) dans le repère du document, qui ne couvre
que son contenu et GRANDIT à la demande (une image 4K à 40 calques ne coûte pas 40 × 4K). Hors du tableau, la valeur
est `fill` (0 = transparent pour des pixels, 255 = « tout révéler » pour un masque).

Rectangles : (x0, y0, x1, y1) entiers, bord droit / bas EXCLUS, repère du document (jamais celui du tableau)."""
from __future__ import annotations

import numpy as np

GROW_MARGIN = 96            # marge prise en plus quand le plan grandit : un trait long ne le réalloue pas à chaque point


def rect_union(a, b):
    if a is None:
        return b
    if b is None:
        return a
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


def rect_intersect(a, b):
    r = (max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3]))
    return r if r[0] < r[2] and r[1] < r[3] else None


def rect_size(r):
    return r[2] - r[0], r[3] - r[1]


class Plane:
    __slots__ = ("channels", "fill", "x", "y", "data", "rev", "png")

    def __init__(self, channels: int, fill: int = 0, x: int = 0, y: int = 0, data=None):
        self.channels = channels
        self.fill = fill
        self.x, self.y = x, y
        self.data = data                    # None = vide (partout `fill`)
        self.rev = 0                        # +1 à chaque écriture : invalide les images gardées (PNG, miniatures)
        self.png = None                     # (rev, octets PNG) gardés par le conteneur : seules les écritures le refont

    # -- géométrie --
    def rect(self):
        if self.data is None:
            return None
        h, w = self.data.shape[:2]
        return (self.x, self.y, self.x + w, self.y + h)

    def shift(self, dx: int, dy: int):
        self.x += dx
        self.y += dy
        self.rev += 1

    # -- lecture --
    def read(self, rect) -> np.ndarray:
        """COPIE de la zone (h, l, canaux) ; hors du plan : `fill`."""
        w, h = rect_size(rect)
        out = np.full((h, w, self.channels), self.fill, np.uint8)
        mine = self.rect()
        common = rect_intersect(rect, mine) if mine is not None else None
        if common is not None:
            out[common[1] - rect[1]:common[3] - rect[1], common[0] - rect[0]:common[2] - rect[0]] = \
                self.data[common[1] - self.y:common[3] - self.y, common[0] - self.x:common[2] - self.x]
        return out

    # -- écriture --
    def ensure(self, rect, margin: int = 0):
        """Le plan couvre au moins `rect` (agrandi si besoin, rempli de `fill`)."""
        rect = tuple(rect)
        mine = self.rect()
        if mine is not None and rect_intersect(rect, mine) == rect:
            return
        want = rect if mine is None else rect_union(mine, rect)
        if mine is not None and margin:
            want = (rect[0] - margin if rect[0] < mine[0] else want[0],
                    rect[1] - margin if rect[1] < mine[1] else want[1],
                    rect[2] + margin if rect[2] > mine[2] else want[2],
                    rect[3] + margin if rect[3] > mine[3] else want[3])
        w, h = rect_size(want)
        fresh = np.full((h, w, self.channels), self.fill, np.uint8)
        if mine is not None:
            fresh[mine[1] - want[1]:mine[3] - want[1], mine[0] - want[0]:mine[2] - want[0]] = self.data
        self.x, self.y, self.data = want[0], want[1], fresh

    def write(self, rect, array: np.ndarray, margin: int = GROW_MARGIN):
        rect = tuple(rect)
        self.ensure(rect, margin)
        self.data[rect[1] - self.y:rect[3] - self.y, rect[0] - self.x:rect[2] - self.x] = array
        self.rev += 1

    def set_all(self, x: int, y: int, data: np.ndarray):
        self.x, self.y, self.data = x, y, np.ascontiguousarray(data, np.uint8)
        self.rev += 1

    def clear(self):
        self.data = None
        self.rev += 1

    def trim(self):
        """Réduit le plan à son contenu utile (alpha non nul pour 4 canaux ; différent de `fill` sinon)."""
        if self.data is None:
            return
        probe = self.data[..., 3] != 0 if self.channels == 4 else (self.data != self.fill).any(axis=-1)
        rows = np.flatnonzero(probe.any(axis=1))
        if rows.size == 0:
            self.data = None
            return
        cols = np.flatnonzero(probe.any(axis=0))
        y0, y1, x0, x1 = int(rows[0]), int(rows[-1]) + 1, int(cols[0]), int(cols[-1]) + 1
        if (y0, y1, x0, x1) != (0, self.data.shape[0], 0, self.data.shape[1]):
            self.data = np.ascontiguousarray(self.data[y0:y1, x0:x1])
            self.x += x0
            self.y += y0

    def nbytes(self) -> int:
        return 0 if self.data is None else int(self.data.nbytes)
