"""Modes de fusion (SANS Qt), formules « séparables » du standard W3C Compositing and Blending, appliquées à des
couleurs DROITES (non prémultipliées) dans l'espace encodé :

    Pr = (1 - αs)·Pb + (1 - αb)·Ps + αs·αb·B(Cb, Cs)        αr = αs + αb - αs·αb

avec P = couleur prémultipliée, C = couleur droite, B = fonction du mode. Mode « normal » : Pr = Ps + (1 - αs)·Pb."""
from __future__ import annotations

import numpy as np

EPS = 1e-6


def _multiply(cb, cs):
    return cb * cs


def _screen(cb, cs):
    return cb + cs - cb * cs


def _hardlight(cb, cs):
    return np.where(cs <= 0.5, cb * (2.0 * cs), _screen(cb, 2.0 * cs - 1.0))


def _overlay(cb, cs):
    return _hardlight(cs, cb)


def _softlight(cb, cs):
    dark = np.where(cb <= 0.25, ((16.0 * cb - 12.0) * cb + 4.0) * cb, np.sqrt(cb))
    return np.where(cs <= 0.5, cb - (1.0 - 2.0 * cs) * cb * (1.0 - cb), cb + (2.0 * cs - 1.0) * (dark - cb))


FUNCTIONS = {
    "multiply": _multiply,
    "screen": _screen,
    "overlay": _overlay,
    "softlight": _softlight,
    "hardlight": _hardlight,
    "darken": np.minimum,
    "lighten": np.maximum,
    "difference": lambda cb, cs: np.abs(cb - cs),
    "exclusion": lambda cb, cs: cb + cs - 2.0 * cb * cs,
    "add": lambda cb, cs: np.minimum(1.0, cb + cs),
}


def blend_over_reference(dest: np.ndarray, src: np.ndarray, mode: str = "normal") -> np.ndarray:
    """Version de RÉFÉRENCE (couleurs droites, avec divisions) : sert aux tests et au mode « lumière tamisée »."""
    src_a = src[..., 3:4]
    if mode == "normal" or mode not in FUNCTIONS:
        return src + dest * (1.0 - src_a)
    dest_a = dest[..., 3:4]
    cb = np.where(dest_a > EPS, dest[..., :3] / np.maximum(dest_a, EPS), 0.0)
    cs = np.where(src_a > EPS, src[..., :3] / np.maximum(src_a, EPS), 0.0)
    mixed = np.clip(FUNCTIONS[mode](cb, cs), 0.0, 1.0)
    out = np.empty_like(dest)
    out[..., :3] = (1.0 - src_a) * dest[..., :3] + (1.0 - dest_a) * src[..., :3] + src_a * dest_a * mixed
    out[..., 3:4] = src_a + dest_a - src_a * dest_a
    return out


def blend_over(dest: np.ndarray, src: np.ndarray, mode: str = "normal") -> np.ndarray:
    """`src` (prémultiplié, float32 h × l × 4) posé sur `dest` (prémultiplié) ; rend un NOUVEAU tableau.

    Formules SANS division, directement en prémultiplié (P = α·C) : le terme de mélange α_s·α_b·B(C_b, C_s) s'écrit
    avec P_s, P_b, α_s, α_b seulement (ex. produit : P_s·P_b ; écran : α_s·P_b + α_b·P_s − P_s·P_b). Seule la
    « lumière tamisée » (racine, branches) passe par la version de référence."""
    src_a = src[..., 3:4]
    if mode == "normal" or mode not in FUNCTIONS:
        return src + dest * (1.0 - src_a)
    if mode == "softlight":
        return blend_over_reference(dest, src, mode)
    dest_a = dest[..., 3:4]
    ps, pb = src[..., :3], dest[..., :3]
    base = (1.0 - src_a) * pb + (1.0 - dest_a) * ps
    if mode == "multiply":
        mix = ps * pb
    elif mode == "screen":
        mix = src_a * pb + dest_a * ps - ps * pb
    elif mode == "exclusion":
        mix = src_a * pb + dest_a * ps - 2.0 * ps * pb
    elif mode in ("darken", "lighten", "difference"):
        a, b = src_a * pb, dest_a * ps
        if mode == "darken":
            mix = np.minimum(a, b)
        elif mode == "lighten":
            mix = np.maximum(a, b)
        else:
            mix = np.abs(a - b)
    elif mode == "add":
        mix = np.minimum(src_a * dest_a, src_a * pb + dest_a * ps)
    elif mode == "hardlight":
        t = 2.0 * ps - src_a
        mix = np.where(t <= 0.0, 2.0 * ps * pb, src_a * pb + dest_a * t - pb * t)
    else:                                                        # overlay : lumière forte, rôles échangés
        t = 2.0 * pb - dest_a
        mix = np.where(t <= 0.0, 2.0 * ps * pb, dest_a * ps + src_a * t - ps * t)
    out = np.empty_like(dest)
    out[..., :3] = base + mix
    out[..., 3:4] = src_a + dest_a - src_a * dest_a
    return out
