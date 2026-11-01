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


def blend_over(dest: np.ndarray, src: np.ndarray, mode: str = "normal") -> np.ndarray:
    """`src` (prémultiplié, float32 h × l × 4) posé sur `dest` (prémultiplié) ; rend un NOUVEAU tableau."""
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
