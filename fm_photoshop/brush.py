"""Moteur de brosse (SANS Qt) : coups de pinceau, gomme et peinture de masque par TAMPONS (« dabs »).

Principe (mesuré, voir la doc) : le trait n'est jamais recomposé en entier. Les pixels sont lus / écrits par TUILES de
64 × 64 ; la couverture du trait (flottant) est gardée par tuile ; chaque tampon n'écrit que les pixels qu'il touche.
Débit (flow) : les tampons s'ACCUMULENT (cov += (1 - cov)·tampon·débit) ; opacité : plafond du trait entier
(min(cov, opacité)) ; sélection : multiplie la couverture (bords progressifs respectés). Au `end`, l'étape
d'annulation ne garde que la zone touchée (avant / après)."""
from __future__ import annotations

import math
from dataclasses import dataclass, field, replace

import numpy as np

from .history import TilesCommand
from .planes import rect_intersect

TILE = 64


@dataclass
class Brush:
    name: str = "Rond"
    size: float = 24.0                  # diamètre (pixels du document)
    hardness: float = 0.8               # 0 (très doux) .. 1 (dur)
    opacity: float = 1.0                # plafond du trait
    flow: float = 1.0                   # débit de chaque tampon
    spacing: float = 0.2                # fraction du diamètre entre deux tampons
    smoothing: float = 0.0              # 0 .. 0.95 : lissage du geste
    pressure_size: bool = False
    pressure_flow: bool = False
    color: tuple = (0, 0, 0)
    eraser: bool = False

    def copy(self, **kw) -> "Brush":
        return replace(self, **kw)

    def to_dict(self) -> dict:
        return {k: (list(v) if isinstance(v, tuple) else v) for k, v in self.__dict__.items()}

    @classmethod
    def from_dict(cls, raw: dict) -> "Brush":
        base = cls()
        for key, value in (raw or {}).items():
            if key in base.__dict__ and key != "color":
                try:
                    setattr(base, key, type(getattr(base, key))(value))
                except (TypeError, ValueError):
                    pass
        if isinstance((raw or {}).get("color"), (list, tuple)) and len(raw["color"]) >= 3:
            base.color = tuple(max(0, min(255, int(c))) for c in raw["color"][:3])
        base.hardness = min(1.0, max(0.0, base.hardness))
        base.opacity = min(1.0, max(0.0, base.opacity))
        base.flow = min(1.0, max(0.0, base.flow))
        base.smoothing = min(0.95, max(0.0, base.smoothing))
        base.size = min(5000.0, max(0.5, base.size))
        base.spacing = min(2.0, max(0.02, base.spacing))
        return base


def dab_alpha(cx: float, cy: float, diameter: float, hardness: float, rect) -> np.ndarray:
    """Couverture (float32 h × l, 0..1) d'un tampon rond centré en (cx, cy) sur la zone `rect`."""
    radius = max(0.25, diameter / 2.0)
    xs = (np.arange(rect[0], rect[2], dtype=np.float32) + 0.5 - cx)[None, :]
    ys = (np.arange(rect[1], rect[3], dtype=np.float32) + 0.5 - cy)[:, None]
    dist = np.sqrt(xs * xs + ys * ys)
    if hardness >= 0.999:
        return np.clip(radius - dist + 0.5, 0.0, 1.0).astype(np.float32)
    inner = radius * hardness
    t = np.clip((dist - inner) / max(radius - inner, 1e-6), 0.0, 1.0)
    return (1.0 - t * t * (3.0 - 2.0 * t)).astype(np.float32)


class Stroke:
    """Un trait sur le plan `pixels` ou `mask` d'un calque. `begin` / `move`* / `end` (-> étape d'annulation)."""

    def __init__(self, layer, target: str, brush: Brush, doc_rect, selection=None):
        if target == "mask" and layer.mask is None:
            raise ValueError("Ce calque n'a pas de masque.")
        if layer.is_group() and target == "pixels":
            raise ValueError("Un groupe n'a pas de pixels : peignez dans un calque.")
        if layer.locked:
            raise ValueError("Le calque est verrouillé.")
        self.layer, self.target, self.brush = layer, target, brush
        self.plane = layer.pix if target == "pixels" else layer.mask.plane
        self.doc_rect = tuple(doc_rect)
        self.selection = selection
        self._orig: dict = {}               # (tx, ty) -> pixels d'origine de la tuile (uint8)
        self._cov: dict = {}                # (tx, ty) -> couverture (float32)
        self._pos = None                    # position lissée
        self._last = None                   # (x, y, pression) du dernier tampon posé
        self._next = 0.0
        self.dirty = None
        self.dabs = 0

    # -- geste --
    def begin(self, x, y, pressure=1.0):
        self._pos = (float(x), float(y))
        self._last = (float(x), float(y), float(pressure))
        self._next = self._step(pressure)
        return self._stamp(x, y, pressure)

    def move(self, x, y, pressure=1.0):
        """Point suivant du geste ; rend la zone modifiée (ou None)."""
        k = self.brush.smoothing
        px, py = self._pos
        target = (px + (x - px) * (1.0 - k), py + (y - py) * (1.0 - k))
        self._pos = target
        return self._segment(target[0], target[1], pressure)

    def _step(self, pressure) -> float:
        size = self.brush.size * (pressure if self.brush.pressure_size else 1.0)
        return max(0.75, self.brush.spacing * max(1.0, size))

    def _segment(self, x, y, pressure):
        x0, y0, p0 = self._last
        dx, dy = x - x0, y - y0
        dist = math.hypot(dx, dy)
        dirty = None
        if dist <= 1e-9:
            return None
        d = self._next
        while d <= dist:
            t = d / dist
            p = p0 + (pressure - p0) * t
            dirty = self._union(dirty, self._stamp(x0 + dx * t, y0 + dy * t, p))
            d += self._step(p)
        self._next = d - dist
        self._last = (x, y, pressure)
        return dirty

    @staticmethod
    def _union(a, b):
        if a is None:
            return b
        if b is None:
            return a
        return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))

    # -- un tampon --
    def _stamp(self, x, y, pressure):
        brush = self.brush
        size = brush.size * (max(0.05, pressure) if brush.pressure_size else 1.0)
        flow = brush.flow * (max(0.05, pressure) if brush.pressure_flow else 1.0)
        reach = size / 2.0 + 1.0
        box = rect_intersect((int(math.floor(x - reach)), int(math.floor(y - reach)),
                              int(math.ceil(x + reach)), int(math.ceil(y + reach))), self.doc_rect)
        if box is None:
            return None
        dab = dab_alpha(x, y, size, brush.hardness, box) * flow
        self.dabs += 1
        for ty in range(box[1] // TILE, (box[3] - 1) // TILE + 1):
            for tx in range(box[0] // TILE, (box[2] - 1) // TILE + 1):
                self._apply_tile(tx, ty, box, dab)
        self.dirty = self._union(self.dirty, box)
        return box

    def _tile(self, tx, ty):
        key = (tx, ty)
        if key not in self._orig:
            rect = rect_intersect((tx * TILE, ty * TILE, tx * TILE + TILE, ty * TILE + TILE), self.doc_rect)
            self._orig[key] = (rect, self.plane.read(rect))
            self._cov[key] = np.zeros((rect[3] - rect[1], rect[2] - rect[0]), np.float32)
        return self._orig[key], self._cov[key]

    def _apply_tile(self, tx, ty, box, dab):
        (trect, orig), cov = self._tile(tx, ty)
        sub = rect_intersect(box, trect)
        if sub is None:
            return
        ly0, ly1, lx0, lx1 = sub[1] - trect[1], sub[3] - trect[1], sub[0] - trect[0], sub[2] - trect[0]
        part = dab[sub[1] - box[1]:sub[3] - box[1], sub[0] - box[0]:sub[2] - box[0]]
        c = cov[ly0:ly1, lx0:lx1]
        c += (1.0 - c) * part
        alpha = np.minimum(c, self.brush.opacity)
        if self.selection is not None:
            alpha = alpha * self.selection.coverage(sub)
        before = orig[ly0:ly1, lx0:lx1]
        self.plane.write(sub, self._result(before, alpha))

    def _result(self, before: np.ndarray, alpha: np.ndarray) -> np.ndarray:
        brush = self.brush
        if self.target == "mask":
            value = 0.299 * brush.color[0] + 0.587 * brush.color[1] + 0.114 * brush.color[2]
            if brush.eraser:
                value = 255.0               # gomme dans un masque : révèle
            m = before[..., 0].astype(np.float32)
            return np.clip(m + (value - m) * alpha + 0.5, 0, 255).astype(np.uint8)[..., None]
        old_a = before[..., 3].astype(np.float32) * (1.0 / 255.0)
        out = before.copy()
        if brush.eraser:
            out[..., 3] = np.clip(old_a * (1.0 - alpha) * 255.0 + 0.5, 0, 255)
            return out
        new_a = alpha + old_a * (1.0 - alpha)
        weight = np.where(new_a > 1e-6, alpha / np.maximum(new_a, 1e-6), 0.0)[..., None]
        color = np.array(brush.color, np.float32)
        rgb = before[..., :3].astype(np.float32) * (1.0 - weight) + color * weight
        out[..., :3] = np.clip(rgb + 0.5, 0, 255)
        out[..., 3] = np.clip(new_a * 255.0 + 0.5, 0, 255)
        return out

    # -- fin --
    def finish_to(self, x, y, pressure=1.0):
        """Rattrape le lissage jusqu'au dernier point brut."""
        if self.brush.smoothing > 0 and self._pos is not None:
            self._pos = (float(x), float(y))
            return self._segment(float(x), float(y), pressure)
        return None

    def end(self, label: str = "Pinceau"):
        """Étape d'annulation (zone touchée seulement), ou None si rien n'a changé."""
        if not self._orig:
            return None
        pieces = []
        for rect, before in self._orig.values():
            after = self.plane.read(rect)
            if not np.array_equal(before, after):
                pieces.append((rect, before, after))
        if not pieces:
            return None
        return TilesCommand(label, self.layer, self.target, pieces)
