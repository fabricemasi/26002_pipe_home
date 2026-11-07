"""Qualité d'AFFICHAGE du canevas (SANS Qt) : agrandissement bicubique de la zone visible, pour comparer avec le voisin le
plus proche (défaut) et le bilinéaire (Qt). N'agit JAMAIS sur les pixels du document : l'image rendue n'est qu'une
présentation, jetée au premier changement du document ou de la vue."""
from __future__ import annotations

import math

import numpy as np

from . import compose as C

DISPLAY_FILTERS = ("nearest", "bilinear", "bicubic")
DISPLAY_LABELS = {"nearest": "Pixels (voisin)", "bilinear": "Bilinéaire", "bicubic": "Bicubique"}


def _taps(positions: np.ndarray, size: int):
    """Indices (4 prises) et poids Catmull-Rom (a = −0,5) pour des positions fractionnaires en espace pixel (le centre
    du pixel k est k). Les bords répliquent le pixel extrême."""
    base = np.floor(positions).astype(np.int64)
    t = (positions - base).astype(np.float32)
    t2, t3 = t * t, t * t * t
    weights = np.stack([-0.5 * t3 + t2 - 0.5 * t, 1.5 * t3 - 2.5 * t2 + 1.0, -1.5 * t3 + 2.0 * t2 + 0.5 * t, 0.5 * t3 - 0.5 * t2], axis=0)
    indices = np.clip(np.stack([base - 1, base, base + 1, base + 2], axis=0), 0, size - 1)
    return indices, weights


def bicubic_view(doc, origin: tuple, step: float, out_size: tuple) -> np.ndarray:
    """Image RGBA (uint8, couleurs PRÉMULTIPLIÉES) de `out_size` = (largeur, hauteur) pixels d'écran. `origin` = coordonnées
    du document du CENTRE du premier pixel d'écran ; `step` = pas document d'un pixel d'écran (1 / zoom)."""
    w, h = out_size
    sx = origin[0] + np.arange(w, dtype=np.float64) * step - 0.5
    sy = origin[1] + np.arange(h, dtype=np.float64) * step - 0.5
    x0, x1 = int(math.floor(sx[0])) - 1, int(math.floor(sx[-1])) + 3
    y0, y1 = int(math.floor(sy[0])) - 1, int(math.floor(sy[-1])) + 3
    rect = (max(0, x0), max(0, y0), min(doc.width, x1), min(doc.height, y1))
    source = C.flatten_u8(doc, rect).astype(np.float32) / 255.0
    alpha = source[..., 3:4]
    source = np.concatenate([source[..., :3] * alpha, alpha], axis=2)          # prémultiplié : pas de frange sombre
    ix, wx = _taps(sx - rect[0], source.shape[1])
    iy, wy = _taps(sy - rect[1], source.shape[0])
    rows = np.zeros((source.shape[0], w, 4), np.float32)
    for k in range(4):                                                         # passe horizontale
        rows += source[:, ix[k], :] * wx[k][None, :, None]
    out = np.zeros((h, w, 4), np.float32)
    for k in range(4):                                                         # passe verticale
        out += rows[iy[k], :, :] * wy[k][:, None, None]
    out = np.clip(out, 0.0, 1.0)
    out[..., :3] = np.minimum(out[..., :3], out[..., 3:4])                     # couleur prémultipliée <= alpha
    return (out * 255.0 + 0.5).astype(np.uint8)
