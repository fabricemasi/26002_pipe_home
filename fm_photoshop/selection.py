"""Sélections (SANS Qt) : un masque de couverture 0..255 limité au document (`Plane` à un canal, hors du plan = 0).

Une couverture PARTIELLE (bords progressifs, contour adouci) est respectée par tous les outils qui reçoivent la
sélection (`coverage(rect) -> float32 0..1`). Opérations : rectangle, ellipse (bords lissés), lasso / polygone, baguette
magique (tolérance, contiguë ou non), plage de couleurs, combinaisons (remplacer, ajouter, soustraire, intersection),
inverser, adoucir (flou gaussien), agrandir, contracter (octogone par itérations)."""
from __future__ import annotations

import numpy as np

from . import filters
from .planes import Plane, rect_intersect, rect_size

MODES = ("replace", "add", "subtract", "intersect")


class Selection:
    def __init__(self, plane: Plane | None = None):
        self.plane = plane or Plane(1, 0)

    # -- lecture --
    def coverage(self, rect) -> np.ndarray:
        return self.plane.read(rect)[..., 0].astype(np.float32) * np.float32(1.0 / 255.0)

    def is_empty(self) -> bool:
        return self.plane.data is None or not self.plane.data.any()

    def bounds(self):
        """Rectangle englobant les pixels sélectionnés (ou None)."""
        data = self.plane.data
        if data is None:
            return None
        rows = np.flatnonzero(data[..., 0].any(axis=1))
        if rows.size == 0:
            return None
        cols = np.flatnonzero(data[..., 0].any(axis=0))
        return (self.plane.x + int(cols[0]), self.plane.y + int(rows[0]), self.plane.x + int(cols[-1]) + 1,
                self.plane.y + int(rows[-1]) + 1)

    def copy(self) -> "Selection":
        out = Plane(1, 0)
        if self.plane.data is not None:
            out.set_all(self.plane.x, self.plane.y, self.plane.data.copy())
        return Selection(out)

    def full(self, doc_rect) -> np.ndarray:
        return self.plane.read(doc_rect)[..., 0]

    @staticmethod
    def from_array(doc_rect, array: np.ndarray) -> "Selection":
        plane = Plane(1, 0)
        plane.set_all(doc_rect[0], doc_rect[1], np.ascontiguousarray(array, np.uint8)[..., None])
        sel = Selection(plane)
        sel.plane.trim()
        return sel


# -- formes --
def rectangle(doc_rect, rect) -> Selection:
    rect = rect_intersect(tuple(int(round(v)) for v in rect), doc_rect)
    sel = Selection()
    if rect is not None:
        sel.plane.set_all(rect[0], rect[1], np.full((rect[3] - rect[1], rect[2] - rect[0], 1), 255, np.uint8))
    return sel


def ellipse(doc_rect, rect) -> Selection:
    """Ellipse inscrite dans `rect` (flottants acceptés), bords lissés par la distance signée normalisée."""
    x0, y0, x1, y1 = rect
    box = rect_intersect((int(np.floor(x0)), int(np.floor(y0)), int(np.ceil(x1)), int(np.ceil(y1))), doc_rect)
    sel = Selection()
    if box is None or x1 - x0 <= 0 or y1 - y0 <= 0:
        return sel
    a, b = (x1 - x0) / 2.0, (y1 - y0) / 2.0
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    xs = (np.arange(box[0], box[2], dtype=np.float32) + 0.5 - cx)[None, :]
    ys = (np.arange(box[1], box[3], dtype=np.float32) + 0.5 - cy)[:, None]
    f = (xs / a) ** 2 + (ys / b) ** 2 - 1.0
    grad = 2.0 * np.sqrt((xs / (a * a)) ** 2 + (ys / (b * b)) ** 2)
    signed = f / np.maximum(grad, 1e-6)                        # distance signée (pixels), négative dedans
    cov = np.clip(0.5 - signed, 0.0, 1.0)
    sel.plane.set_all(box[0], box[1], (cov * 255.0 + 0.5).astype(np.uint8)[..., None])
    sel.plane.trim()
    return sel


def polygon(doc_rect, points) -> Selection:
    """Lasso libre ou polygonal : polygone rempli, bords lissés (sur-échantillonnage 4 × 4)."""
    from PIL import Image, ImageDraw
    sel = Selection()
    if len(points) < 3:
        return sel
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    box = rect_intersect((int(np.floor(min(xs))), int(np.floor(min(ys))), int(np.ceil(max(xs))) + 1,
                          int(np.ceil(max(ys))) + 1), doc_rect)
    if box is None:
        return sel
    w, h = rect_size(box)
    scale = 4
    image = Image.new("L", (w * scale, h * scale), 0)
    ImageDraw.Draw(image).polygon([((x - box[0]) * scale - 0.5, (y - box[1]) * scale - 0.5) for x, y in points],
                                  fill=255)           # (centres des pixels sur-échantillonnés aux entiers)
    small = np.asarray(image, np.float32).reshape(h, scale, w, scale).mean(axis=(1, 3))
    sel.plane.set_all(box[0], box[1], (small + 0.5).astype(np.uint8)[..., None])
    sel.plane.trim()
    return sel


# -- baguette magique --
def _runs(mask: np.ndarray):
    """Pour chaque ligne, les segments (début, fin exclus) de pixels vrais."""
    padded = np.zeros((mask.shape[0], mask.shape[1] + 2), np.int8)
    padded[:, 1:-1] = mask
    diff = np.diff(padded, axis=1)
    starts_r, starts_c = np.nonzero(diff == 1)
    ends_r, ends_c = np.nonzero(diff == -1)
    rows = [[] for _ in range(mask.shape[0])]
    for r, s, e in zip(starts_r.tolist(), starts_c.tolist(), ends_c.tolist()):
        rows[r].append((s, e))
    return rows


def _connected(mask: np.ndarray, seed_y: int, seed_x: int) -> np.ndarray:
    """Composante connexe (4-voisinage) du pixel de départ, par segments de lignes (rapide en NumPy/Python)."""
    out = np.zeros(mask.shape, bool)
    if not mask[seed_y, seed_x]:
        return out
    rows = _runs(mask)
    seen = [set() for _ in rows]
    stack = []
    for index, (s, e) in enumerate(rows[seed_y]):
        if s <= seed_x < e:
            stack.append((seed_y, index))
            seen[seed_y].add(index)
    while stack:
        y, index = stack.pop()
        s, e = rows[y][index]
        out[y, s:e] = True
        for ny in (y - 1, y + 1):
            if 0 <= ny < len(rows):
                for nindex, (ns, ne) in enumerate(rows[ny]):
                    if ns < e and ne > s and nindex not in seen[ny]:
                        seen[ny].add(nindex)
                        stack.append((ny, nindex))
    return out


def wand(doc_rect, rgba: np.ndarray, x: int, y: int, tolerance: int = 32, contiguous: bool = True,
         anti_alias: bool = True) -> Selection:
    """Baguette magique sur l'image `rgba` (uint8 droit, taille du document) : pixels dont l'écart maximal sur un
    canal (alpha compris) avec le pixel cliqué est <= tolérance (0..255)."""
    h, w = rgba.shape[:2]
    if not (0 <= x < w and 0 <= y < h):
        return Selection()
    target = rgba[y, x].astype(np.int16)
    close = (np.abs(rgba.astype(np.int16) - target).max(axis=2) <= int(tolerance))
    chosen = _connected(close, y, x) if contiguous else close
    cover = chosen.astype(np.float32)
    if anti_alias:
        cover = np.clip(filters.gaussian_blur(cover, 0.6) * 1.25, 0.0, 1.0) * (1.0 if chosen.any() else 0.0)
        cover = np.where(chosen, np.maximum(cover, 0.5), cover)
    return Selection.from_array(doc_rect, (cover * 255.0 + 0.5).astype(np.uint8))


def color_range(doc_rect, rgba: np.ndarray, color, tolerance: int = 32) -> Selection:
    """Sélection par couleur : tous les pixels proches de `color` (r, g, b), contigus ou non, alpha > 0."""
    diff = np.abs(rgba[..., :3].astype(np.int16) - np.array(color[:3], np.int16)).max(axis=2)
    chosen = (diff <= int(tolerance)) & (rgba[..., 3] > 0)
    return Selection.from_array(doc_rect, chosen.astype(np.uint8) * 255)


# -- combinaisons et transformations --
def combine(doc_rect, base: Selection | None, new: Selection, mode: str = "replace") -> Selection:
    if mode == "replace" or base is None or base.is_empty():
        return new if mode in ("replace", "add") or base is None else Selection()
    a, b = base.full(doc_rect).astype(np.float32), new.full(doc_rect).astype(np.float32)
    if mode == "add":
        out = np.maximum(a, b)
    elif mode == "subtract":
        out = a * (1.0 - b / 255.0)
    elif mode == "intersect":
        out = a * b / 255.0
    else:
        raise ValueError(f"Mode de combinaison inconnu : {mode}")
    return Selection.from_array(doc_rect, np.clip(out + 0.5, 0, 255).astype(np.uint8))


def invert(doc_rect, sel: Selection) -> Selection:
    return Selection.from_array(doc_rect, 255 - sel.full(doc_rect))


def select_all(doc_rect) -> Selection:
    return rectangle(doc_rect, doc_rect)


def feather(doc_rect, sel: Selection, radius: float) -> Selection:
    """Contour progressif : flou gaussien de la couverture (écart-type = rayon / 2)."""
    if sel.is_empty() or radius <= 0:
        return sel.copy()
    blurred = filters.gaussian_blur(sel.full(doc_rect).astype(np.float32), radius / 2.0)
    return Selection.from_array(doc_rect, np.clip(blurred + 0.5, 0, 255).astype(np.uint8))


def _shift_extreme(arr: np.ndarray, grow: bool) -> np.ndarray:
    """Un pas d'agrandissement (max) ou de contraction (min) sur les 8 voisins."""
    pad = np.pad(arr, 1, mode="constant", constant_values=0) if grow else np.pad(arr, 1, mode="edge")
    op = np.maximum if grow else np.minimum
    out = arr.copy()
    h, w = arr.shape
    for dy in (0, 1, 2):
        for dx in (0, 1, 2):
            out = op(out, pad[dy:dy + h, dx:dx + w])
    return out


def resize(doc_rect, sel: Selection, pixels: int) -> Selection:
    """Agrandir (pixels > 0) ou contracter (< 0) : `pixels` itérations sur les 8 voisins (forme d'octogone)."""
    if sel.is_empty() or pixels == 0:
        return sel.copy()
    arr = sel.full(doc_rect)
    for _ in range(abs(int(pixels))):
        arr = _shift_extreme(arr, pixels > 0)
    return Selection.from_array(doc_rect, arr)


def outline_segments(doc_rect, sel: Selection, threshold: int = 128, limit: int = 40000):
    """Contour de la sélection pour les « fourmis en marche » : segments horizontaux et verticaux fusionnés
    (x0, y0, x1, y1) entre pixels sélectionnés (couverture >= seuil) et non sélectionnés. Rend None au-delà de
    `limit` segments (sélection trop morcelée : l'appelant dessine alors le cadre englobant)."""
    bounds = sel.bounds()
    if bounds is None:
        return []
    box = (max(doc_rect[0], bounds[0] - 1), max(doc_rect[1], bounds[1] - 1), min(doc_rect[2], bounds[2] + 1),
           min(doc_rect[3], bounds[3] + 1))
    inside = sel.plane.read(box)[..., 0] >= threshold
    padded = np.zeros((inside.shape[0] + 2, inside.shape[1] + 2), bool)
    padded[1:-1, 1:-1] = inside
    segments = []
    # arêtes horizontales : entre la ligne y-1 et y ; verticales : entre la colonne x-1 et x
    horizontal = padded[1:, 1:-1] != padded[:-1, 1:-1]                # (h + 1, w)
    vertical = padded[1:-1, 1:] != padded[1:-1, :-1]                  # (h, w + 1)
    for edges, is_h in ((horizontal, True), (vertical, False)):
        grid = edges if is_h else edges.T
        pad = np.zeros((grid.shape[0], grid.shape[1] + 2), np.int8)
        pad[:, 1:-1] = grid
        diff = np.diff(pad, axis=1)
        sr, sc = np.nonzero(diff == 1)
        _er, ec = np.nonzero(diff == -1)
        if len(sr) > limit:
            return None
        for r, a, b in zip(sr.tolist(), sc.tolist(), ec.tolist()):
            if is_h:
                segments.append((box[0] + a, box[1] + r, box[0] + b, box[1] + r))
            else:
                segments.append((box[0] + r, box[1] + a, box[0] + r, box[1] + b))
        if len(segments) > limit:
            return None
    return segments
