"""Composition du document (SANS Qt), par RÉGION : on ne compose jamais plus que le rectangle demandé.

Règles (testées, `tests/test_photoshop_compose.py`) :
- calque raster : pixels droits -> prémultipliés ; masque (s'il est activé) multiplie l'alpha ; puis opacité du calque ;
  calque invisible = absent (ses calques d'écrêtage aussi) ;
- groupe « passer à travers » (défaut) à opacité 100 %, mode normal, sans masque : ses enfants sont composés
  DIRECTEMENT sur ce qui est dessous ; sinon le groupe est ISOLÉ (ses enfants composés seuls, sur transparent, puis le
  résultat traité comme un calque : opacité, mode, masque). Un groupe « isolé » (passthrough faux) est toujours isolé ;
- masque d'écrêtage : un calque `clip` est limité à l'alpha du calque de base dessous (le premier non écrêté) ; la base
  et ses calques écrêtés sont composés ensemble (isolés), puis posés avec l'opacité et le mode de la BASE ;
- résultat : flottants prémultipliés, 0..1, repère du document, rectangle (x0, y0, x1, y1)."""
from __future__ import annotations

import numpy as np

from .blend import blend_over
from .planes import rect_intersect, rect_size


def premultiplied(rgba: np.ndarray) -> np.ndarray:
    """uint8 droit (h, l, 4) -> float32 prémultiplié 0..1."""
    out = rgba.astype(np.float32) * (1.0 / 255.0)
    out[..., :3] *= out[..., 3:4]
    return out


def to_straight_u8(premult: np.ndarray) -> np.ndarray:
    """float32 prémultiplié -> uint8 DROIT (arrondi au plus proche ; pixels transparents : couleur 0)."""
    alpha = premult[..., 3:4]
    rgb = np.where(alpha > 1e-6, premult[..., :3] / np.maximum(alpha, 1e-6), 0.0)
    out = np.empty(premult.shape, np.uint8)
    out[..., :3] = np.clip(rgb * 255.0 + 0.5, 0, 255)
    out[..., 3] = np.clip(alpha[..., 0] * 255.0 + 0.5, 0, 255)
    return out


def to_premult_u8(premult: np.ndarray) -> np.ndarray:
    """float32 prémultiplié -> uint8 prémultiplié (affichage Qt : ARGB32_Premultiplied = octets B, G, R, A)."""
    out = np.clip(premult * 255.0 + 0.5, 0, 255).astype(np.uint8)
    return out[..., [2, 1, 0, 3]]


def _mask_factor(layer, rect):
    mask = layer.mask
    if mask is None or not mask.enabled:
        return None
    return mask.plane.read(rect).astype(np.float32) * (1.0 / 255.0)


def layer_premult(layer, rect) -> np.ndarray:
    """Contenu du calque dans `rect` (prémultiplié, masque appliqué, SANS l'opacité)."""
    w, h = rect_size(rect)
    if layer.is_group():
        out = compose(layer.children, rect)
    else:
        mine = layer.pix.rect()
        if mine is None or rect_intersect(rect, mine) is None:
            return np.zeros((h, w, 4), np.float32)
        out = premultiplied(layer.pix.read(rect))
    factor = _mask_factor(layer, rect)
    if factor is not None:
        out *= factor
    return out


def _direct_group(layer) -> bool:
    return (layer.is_group() and layer.passthrough and layer.opacity >= 1.0 and layer.blend == "normal"
            and (layer.mask is None or not layer.mask.enabled))


def compose(layers, rect, acc: np.ndarray | None = None) -> np.ndarray:
    """Compose `layers` (du bas vers le haut) dans `rect`, sur `acc` (prémultiplié) ou sur du transparent."""
    w, h = rect_size(rect)
    if acc is None:
        acc = np.zeros((h, w, 4), np.float32)
    i, n = 0, len(layers)
    while i < n:
        base = layers[i]
        i += 1
        followers = []
        while i < n and layers[i].clip:
            followers.append(layers[i])
            i += 1
        if not base.visible:
            continue
        if _direct_group(base) and not followers:
            acc = compose(base.children, rect, acc)
            continue
        src = layer_premult(base, rect)
        for follower in followers:
            if not follower.visible:
                continue
            piece = layer_premult(follower, rect)
            piece *= src[..., 3:4]                                  # limité à l'alpha de la base (0..1, base entière)
            piece *= follower.opacity
            merged = blend_over(src, piece, follower.blend)
            keep = np.where(merged[..., 3:4] > 1e-6, src[..., 3:4] / np.maximum(merged[..., 3:4], 1e-6), 0.0)
            src = merged * keep                                      # l'alpha de la base reste celui de la base
        if base.opacity < 1.0:
            src = src * base.opacity
        acc = blend_over(acc, src, base.blend)
    return acc


def compose_document(doc, rect=None) -> np.ndarray:
    return compose(doc.layers, rect or doc.rect())


def flatten_u8(doc, rect=None) -> np.ndarray:
    """Composition complète, uint8 droit (h, l, 4) : export, aplatissement."""
    return to_straight_u8(compose_document(doc, rect))
