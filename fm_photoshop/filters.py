"""Filtres de base (SANS Qt, NumPy) : flou gaussien (3 passes de flou en boîte par cumul : coût indépendant du rayon),
netteté (masque flou), bruit. Travaillent sur des tableaux float32 `(h, l, canaux)` en PRÉMULTIPLIÉ (couleur et alpha
floutés ensemble : pas de halo aux bords transparents) ; l'appelant fournit la marge nécessaire (`margin(sigma)`)."""
from __future__ import annotations

import numpy as np


def margin(sigma: float) -> int:
    """Pixels autour d'une zone dont dépend le flou de cette zone."""
    return int(np.ceil(sigma * 3.0)) + 1


def _box_sizes(sigma: float, passes: int = 3):
    """Largeurs des boîtes dont la composée approche une gaussienne d'écart-type `sigma` (méthode de Kovesi)."""
    ideal = np.sqrt(12.0 * sigma * sigma / passes + 1.0)
    low = int(np.floor(ideal))
    low -= 1 - low % 2                                    # impair
    high = low + 2
    count_low = int(round((12.0 * sigma * sigma - passes * low * low - 4 * passes * low - 3 * passes) / (-4.0 * low - 4.0)))
    return [low if i < count_low else high for i in range(passes)]


def _box_axis(arr: np.ndarray, size: int, axis: int) -> np.ndarray:
    """Moyenne glissante de largeur impaire `size` le long de `axis` (bords : valeur du bord répétée)."""
    if size <= 1:
        return arr
    r = size // 2
    pad = [(0, 0)] * arr.ndim
    pad[axis] = (r + 1, r)
    padded = np.pad(arr, pad, mode="edge")
    csum = np.cumsum(padded, axis=axis, dtype=np.float64 if arr.dtype == np.float64 else np.float32)
    n = arr.shape[axis]
    hi = np.take(csum, np.arange(size, size + n), axis=axis)
    lo = np.take(csum, np.arange(0, n), axis=axis)
    return ((hi - lo) / size).astype(arr.dtype, copy=False)


def gaussian_blur(arr: np.ndarray, sigma: float) -> np.ndarray:
    """Flou gaussien (approché par 3 boîtes) d'un tableau `(h, l)` ou `(h, l, canaux)`."""
    if sigma <= 0.0:
        return arr.copy()
    out = arr.astype(np.float32, copy=True)
    for size in _box_sizes(sigma):
        out = _box_axis(out, size, 0)
        out = _box_axis(out, size, 1)
    return out


def unsharp(premult: np.ndarray, amount: float, sigma: float, threshold: float = 0.0) -> np.ndarray:
    """Accentuation : original + quantité × (original − flou), limité à [0, alpha] par canal couleur (prémultiplié)."""
    blurred = gaussian_blur(premult, sigma)
    detail = premult - blurred
    if threshold > 0:
        detail = np.where(np.abs(detail) >= threshold, detail, 0.0)
    out = premult.copy()
    alpha = premult[..., 3:4]
    out[..., :3] = np.clip(premult[..., :3] + amount * detail[..., :3], 0.0, alpha)     # couleur prémultipliée <= alpha
    return out


def add_noise(premult: np.ndarray, amount: float, seed: int = 0, mono: bool = True) -> np.ndarray:
    """Bruit gaussien (écart-type `amount`, 0..1) ajouté aux couleurs DROITES, alpha inchangé. Graine fixée : un même
    réglage donne le même résultat (aperçu et application identiques)."""
    rng = np.random.default_rng(seed)
    h, w = premult.shape[:2]
    noise = rng.normal(0.0, amount, (h, w, 1 if mono else 3)).astype(np.float32)
    alpha = premult[..., 3:4]
    out = premult.copy()
    out[..., :3] = np.clip(premult[..., :3] + noise * alpha, 0.0, alpha)
    return out
