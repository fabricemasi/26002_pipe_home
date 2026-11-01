"""Transformations géométriques (SANS Qt) : rééchantillonnage affine, transformation de calque, recadrage, taille de
l'image, taille de la zone de travail.

RÈGLE : tout rééchantillonnage part de l'ORIGINAL (jamais du résultat précédent) — un geste interactif refait l'image
depuis la source à chaque pas (`TransformSession`), donc aucune dégradation cumulée ; la validation recalcule en haute
qualité (bicubique). Interpolation en PRÉMULTIPLIÉ (pas de halo aux bords transparents). Les coordonnées sont celles
des CENTRES de pixel + 0,5 (le pixel (i, j) couvre [i, i + 1) × [j, j + 1)).

Matrice : tuple 2 × 3 ((a, b, tx), (c, d, ty)) : x' = a·x + b·y + tx, y' = c·x + d·y + ty (source -> destination)."""
from __future__ import annotations

import math

import numpy as np

from . import compose as C
from .history import CallCommand
from .planes import Plane, rect_intersect

IDENTITY = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0))
QUALITIES = ("nearest", "bilinear", "bicubic")
QUALITY_LABELS = {"nearest": "Au plus proche (pixels francs)", "bilinear": "Bilinéaire", "bicubic": "Bicubique (qualité)"}


# -- matrices --
def compose_matrices(second, first):
    """Applique `first` puis `second`."""
    a = np.vstack([np.array(first, float), [0, 0, 1]])
    b = np.vstack([np.array(second, float), [0, 0, 1]])
    m = b @ a
    return tuple(tuple(float(v) for v in row) for row in m[:2])


def translation(dx, dy):
    return ((1.0, 0.0, float(dx)), (0.0, 1.0, float(dy)))


def scaling(sx, sy, cx=0.0, cy=0.0):
    return ((sx, 0.0, cx - sx * cx), (0.0, sy, cy - sy * cy))


def rotation(degrees, cx=0.0, cy=0.0):
    r = math.radians(degrees)
    c, s = math.cos(r), math.sin(r)
    return ((c, -s, cx - c * cx + s * cy), (s, c, cy - s * cx - c * cy))


def flip(horizontal: bool, cx: float, cy: float):
    return scaling(-1.0 if horizontal else 1.0, 1.0 if horizontal else -1.0, cx, cy)


def apply_point(m, x, y):
    return m[0][0] * x + m[0][1] * y + m[0][2], m[1][0] * x + m[1][1] * y + m[1][2]


def inverse(m):
    a = np.vstack([np.array(m, float), [0, 0, 1]])
    inv = np.linalg.inv(a)
    return tuple(tuple(float(v) for v in row) for row in inv[:2])


def bounds_after(m, rect):
    """Rectangle entier englobant l'image du rectangle `rect` par la matrice."""
    corners = [apply_point(m, x, y) for x in (rect[0], rect[2]) for y in (rect[1], rect[3])]
    xs, ys = [c[0] for c in corners], [c[1] for c in corners]
    return (math.floor(min(xs) + 1e-6), math.floor(min(ys) + 1e-6), math.ceil(max(xs) - 1e-6), math.ceil(max(ys) - 1e-6))


# -- rééchantillonnage --
def _reduce(premult: np.ndarray, factor_x: int, factor_y: int) -> np.ndarray:
    """Moyenne par blocs (anticrénelage avant une forte réduction)."""
    h, w = premult.shape[:2]
    h2, w2 = h // factor_y * factor_y, w // factor_x * factor_x
    if h2 == 0 or w2 == 0:
        return premult
    cut = premult[:h2, :w2]
    return cut.reshape(h2 // factor_y, factor_y, w2 // factor_x, factor_x, 4).mean(axis=(1, 3), dtype=np.float32)


def _cubic_weights(t):
    """Poids de Catmull-Rom pour les 4 échantillons autour d'une fraction t (shape (..., 4))."""
    t2, t3 = t * t, t * t * t
    return np.stack([-0.5 * t3 + t2 - 0.5 * t, 1.5 * t3 - 2.5 * t2 + 1.0, -1.5 * t3 + 2.0 * t2 + 0.5 * t,
                     0.5 * t3 - 0.5 * t2], axis=-1)


def sample(premult: np.ndarray, sx: np.ndarray, sy: np.ndarray, quality: str) -> np.ndarray:
    """Échantillonne `premult` (h, l, 4 float32) aux coordonnées SOURCE (pixels flottants, bord haut-gauche du pixel =
    entier) ; hors de l'image : transparent."""
    h, w = premult.shape[:2]
    pad = np.zeros((h + 6, w + 6, 4), np.float32)
    pad[3:-3, 3:-3] = premult
    # position du centre du pixel i : i + 0,5 -> indice flottant = coordonnée − 0,5
    fx, fy = sx - 0.5, sy - 0.5
    if quality == "nearest":
        ix = np.clip(np.floor(sx).astype(np.int64) + 3, 0, w + 5)
        iy = np.clip(np.floor(sy).astype(np.int64) + 3, 0, h + 5)
        out = pad[iy, ix]
        inside = (sx >= 0) & (sx < w) & (sy >= 0) & (sy < h)
        return out * inside[..., None]
    x0, y0 = np.floor(fx), np.floor(fy)
    tx, ty = (fx - x0).astype(np.float32), (fy - y0).astype(np.float32)
    ix, iy = x0.astype(np.int64) + 3, y0.astype(np.int64) + 3
    if quality == "bilinear":
        ix = np.clip(ix, 0, w + 4)
        iy = np.clip(iy, 0, h + 4)
        a, b = pad[iy, ix], pad[iy, ix + 1]
        c, d = pad[iy + 1, ix], pad[iy + 1, ix + 1]
        tx, ty = tx[..., None], ty[..., None]
        return (a * (1 - tx) + b * tx) * (1 - ty) + (c * (1 - tx) + d * tx) * ty
    ix = np.clip(ix, 1, w + 3)
    iy = np.clip(iy, 1, h + 3)
    wx, wy = _cubic_weights(tx), _cubic_weights(ty)
    out = np.zeros(sx.shape + (4,), np.float32)
    for j in range(4):
        row = np.zeros_like(out)
        for i in range(4):
            row += pad[iy + j - 1, ix + i - 1] * wx[..., i, None]
        out += row * wy[..., j, None]
    return np.clip(out, 0.0, 1.0)


def resample(data: np.ndarray, origin, matrix, quality: str = "bicubic"):
    """Transforme les pixels `data` (RGBA uint8 droit) posés à `origin` = (x, y) par `matrix`. Rend (x, y, nouvelles
    données uint8) ou None si l'image sort de tout. La source est lue SANS jamais être modifiée."""
    h, w = data.shape[:2]
    rect = (origin[0], origin[1], origin[0] + w, origin[1] + h)
    dest = bounds_after(matrix, rect)
    dw, dh = dest[2] - dest[0], dest[3] - dest[1]
    if dw <= 0 or dh <= 0 or dw * dh > 600_000_000:
        return None
    premult = C.premultiplied(data)
    inv = inverse(matrix)
    # forte réduction : moyenne par blocs d'abord (sinon crénelage)
    scale_x = math.hypot(inv[0][0], inv[1][0])
    scale_y = math.hypot(inv[0][1], inv[1][1])
    fx, fy = max(1, int(scale_x)), max(1, int(scale_y))
    pre_x, pre_y = 1, 1
    if quality != "nearest" and (fx > 1 or fy > 1):
        premult = _reduce(premult, fx, fy)
        pre_x, pre_y = fx, fy
    xs = np.arange(dest[0], dest[2], dtype=np.float64) + 0.5
    ys = np.arange(dest[1], dest[3], dtype=np.float64) + 0.5
    gx, gy = np.meshgrid(xs, ys)
    sx = (inv[0][0] * gx + inv[0][1] * gy + inv[0][2] - origin[0]) / pre_x
    sy = (inv[1][0] * gx + inv[1][1] * gy + inv[1][2] - origin[1]) / pre_y
    out = sample(premult, sx.astype(np.float32), sy.astype(np.float32), quality)
    result = C.to_straight_u8(out)
    if not result[..., 3].any():
        return None
    return dest[0], dest[1], result


# -- transformation d'un calque (geste interactif ou numérique) --
class TransformSession:
    """Transformation d'UN calque (pixels et masque) avec aperçu : toujours recalculée depuis l'original."""

    def __init__(self, layer):
        self.layer = layer
        self.matrix = IDENTITY
        self.planes = []
        for node in layer.walk():
            if node.pix is not None and node.pix.data is not None:
                self.planes.append((node.pix, node.pix.x, node.pix.y, node.pix.data.copy()))
            if node.mask is not None and node.mask.plane.data is not None:
                self.planes.append((node.mask.plane, node.mask.plane.x, node.mask.plane.y, node.mask.plane.data.copy()))

    def rect(self):
        rect = None
        for plane, x, y, data in self.planes:
            r = (x, y, x + data.shape[1], y + data.shape[0])
            rect = r if rect is None else (min(rect[0], r[0]), min(rect[1], r[1]), max(rect[2], r[2]), max(rect[3], r[3]))
        return rect

    def center(self):
        r = self.rect()
        return ((r[0] + r[2]) / 2.0, (r[1] + r[3]) / 2.0) if r else (0.0, 0.0)

    def render(self, matrix, quality="bilinear"):
        """Pose dans le calque le résultat de `matrix` appliquée à l'ORIGINAL ; rend la zone à repeindre."""
        self.matrix = matrix
        touched = self.rect()
        for plane, x, y, data in self.planes:
            if plane.channels == 4:
                out = resample(data, (x, y), matrix, quality)
                if out is None:
                    plane.clear()
                else:
                    plane.set_all(out[0], out[1], out[2])
            else:                                           # masque : un canal, rééchantillonné en niveaux de gris
                rgba = np.repeat(data, 4, axis=2)
                rgba[..., 3] = 255
                out = resample(rgba, (x, y), matrix, quality)
                if out is None:
                    plane.clear()
                else:
                    plane.set_all(out[0], out[1], out[2][..., :1].copy())
        after = bounds_after(matrix, touched) if touched else None
        return after if touched is None else (min(touched[0], after[0]), min(touched[1], after[1]),
                                             max(touched[2], after[2]), max(touched[3], after[3]))

    def cancel(self):
        for plane, x, y, data in self.planes:
            plane.set_all(x, y, data.copy())
        self.matrix = IDENTITY

    def command(self, quality="bicubic", label="Transformation"):
        """Recalcule en qualité finale puis rend l'étape d'annulation (état d'origine <-> état final)."""
        rect = self.render(self.matrix, quality)
        final = [(p, p.x, p.y, None if p.data is None else p.data.copy()) for p, *_ in self.planes]
        original = self.planes

        def restore(states):
            for plane, x, y, data in states:
                if data is None:
                    plane.clear()
                else:
                    plane.set_all(x, y, data.copy())
        return CallCommand(label, lambda: restore(final), lambda: restore(original), rect=rect)


# -- document --
def _all_planes(doc):
    for node in doc.walk():
        if node.pix is not None:
            yield node.pix
        if node.mask is not None:
            yield node.mask.plane


def _snapshot(doc):
    return [(p, p.x, p.y, None if p.data is None else p.data.copy()) for p in _all_planes(doc)]


def _restore(states):
    for plane, x, y, data in states:
        if data is None:
            plane.clear()
        else:
            plane.set_all(x, y, data.copy())


def crop(doc, rect, delete_cropped: bool = True):
    """Recadre le document sur `rect` : tous les calques sont décalés ; les pixels hors cadre sont supprimés
    (`delete_cropped`) ou gardés cachés au-delà du document."""
    rect = rect_intersect(tuple(int(v) for v in rect), doc.rect())
    if rect is None:
        raise ValueError("Le cadre de recadrage est hors du document.")
    old = _snapshot(doc)
    old_size = (doc.width, doc.height)
    new_size = (rect[2] - rect[0], rect[3] - rect[1])

    def do():
        _restore(old)
        for plane in _all_planes(doc):
            if plane.data is None:
                continue
            if delete_cropped:
                keep = plane.read(rect)
                plane.set_all(0, 0, keep)
                if plane.channels == 4:
                    plane.trim()
            else:
                plane.shift(-rect[0], -rect[1])
        doc.width, doc.height = new_size

    def undo():
        _restore(old)
        doc.width, doc.height = old_size
    do()
    return CallCommand("Recadrer", do, undo)


def canvas_size(doc, width: int, height: int, anchor=(0.5, 0.5)):
    """Taille de la zone de travail : les calques gardent leurs pixels, décalés selon l'ancrage (0..1, 0..1)."""
    width, height = int(width), int(height)
    if width < 1 or height < 1:
        raise ValueError("Dimensions invalides.")
    dx = round((width - doc.width) * anchor[0])
    dy = round((height - doc.height) * anchor[1])
    old_size = (doc.width, doc.height)
    old = _snapshot(doc)

    def do():
        _restore(old)
        for plane in _all_planes(doc):
            if plane.data is not None:
                plane.shift(dx, dy)
        doc.width, doc.height = width, height

    def undo():
        _restore(old)
        doc.width, doc.height = old_size
    do()
    return CallCommand("Taille de la zone de travail", do, undo)


def resize_image(doc, width: int, height: int, quality: str = "bicubic"):
    """Taille de l'image : tous les calques rééchantillonnés UNE fois depuis leur original."""
    width, height = int(width), int(height)
    if width < 1 or height < 1:
        raise ValueError("Dimensions invalides.")
    sx, sy = width / doc.width, height / doc.height
    matrix = scaling(sx, sy, 0.0, 0.0)
    old = _snapshot(doc)
    old_size = (doc.width, doc.height)

    def do():
        _restore(old)
        for plane in _all_planes(doc):
            if plane.data is None:
                continue
            if plane.channels == 4:
                out = resample(plane.data, (plane.x, plane.y), matrix, quality)
            else:
                rgba = np.repeat(plane.data, 4, axis=2)
                rgba[..., 3] = 255
                got = resample(rgba, (plane.x, plane.y), matrix, quality)
                out = None if got is None else (got[0], got[1], got[2][..., :1].copy())
            if out is None:
                plane.clear()
            else:
                plane.set_all(out[0], out[1], out[2])
        doc.width, doc.height = width, height

    def undo():
        _restore(old)
        doc.width, doc.height = old_size
    do()
    return CallCommand("Taille de l'image", do, undo)


def flip_canvas(doc, horizontal: bool):
    """Symétrie de TOUT le document (zone de travail retournée) : exacte, sans rééchantillonnage."""
    old = _snapshot(doc)

    def do():
        _restore(old)
        for plane in _all_planes(doc):
            if plane.data is None:
                continue
            if horizontal:
                plane.set_all(doc.width - plane.x - plane.data.shape[1], plane.y, plane.data[:, ::-1].copy())
            else:
                plane.set_all(plane.x, doc.height - plane.y - plane.data.shape[0], plane.data[::-1].copy())

    def undo():
        _restore(old)
    do()
    return CallCommand("Symétrie horizontale" if horizontal else "Symétrie verticale", do, undo)
