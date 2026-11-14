"""Pyramides min/max par canal pour les waveforms (sans Qt).

Niveau 0 : un couple (min, max) par bloc de 64 échantillons ; chaque niveau suivant regroupe
4 blocs (256, 1024, 4096…). Calcul en fond par `compute` (fil de travail), cache versionné
`<clé>.peaks.npz`. Dessin : `Peaks.view` choisit le niveau dont le bloc ≤ échantillons par
pixel, donc un travail borné par la LARGEUR de la vue, jamais par la durée du média.
Au zoom fin (< 64 échantillons par pixel), `pcm_window` lit une fenêtre PCM bornée.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

import numpy as np

from . import media, wavio

PEAKS_VERSION = 1
BASE = 64
FACTOR = 4
MAX_PCM_WINDOW = 1 << 20   # échantillons lus au plus par fenêtre de zoom fin


class Peaks:
    def __init__(self, levels: list, sample_rate: int, frames: int, channels: int):
        self.levels = levels           # [(taille de bloc, mins (ch, n), maxs (ch, n))]
        self.sample_rate = sample_rate
        self.frames = frames
        self.channels = channels

    def level_for(self, spp: float) -> int:
        best = 0
        for i, (bs, _, _) in enumerate(self.levels):
            if bs <= spp:
                best = i
        return best

    def view(self, start: float, spp: float, width: int) -> tuple[np.ndarray, np.ndarray]:
        """(mins, maxs) de forme (canaux, largeur) pour une vue commençant à `start` (échantillon),
        `spp` échantillons par pixel. NaN = hors du média."""
        width = max(0, int(width))
        mins = np.full((self.channels, width), np.nan, np.float32)
        maxs = np.full((self.channels, width), np.nan, np.float32)
        if width == 0 or not self.levels:
            return mins, maxs
        bs, lmin, lmax = self.levels[self.level_for(spp)]
        n = lmin.shape[1]
        edges = (start + np.arange(width + 1) * spp) / bs
        lo = np.clip(np.floor(edges[:-1]).astype(np.int64), 0, n)
        hi = np.clip(np.ceil(edges[1:]).astype(np.int64), 0, n)
        hi = np.maximum(hi, np.minimum(lo + 1, n))
        valid = lo < hi
        if not valid.any():
            return mins, maxs
        idx = np.nonzero(valid)[0]
        # réduction par segments : coût O(largeur × facteur ≤ 4)
        starts = lo[idx]
        for c in range(self.channels):
            mins[c, idx] = _seg(lmin[c], starts, hi[idx], np.min)
            maxs[c, idx] = _seg(lmax[c], starts, hi[idx], np.max)
        return mins, maxs


def _seg(arr: np.ndarray, lo: np.ndarray, hi: np.ndarray, fn) -> np.ndarray:
    span = int((hi - lo).max()) if len(lo) else 0
    if span <= 1:
        return arr[lo].astype(np.float32)
    # fenêtres de largeur `span` bornées : on complète avec la valeur de début (neutre pour min/max)
    k = np.arange(span)
    take = lo[:, None] + k[None, :]
    take = np.where(take < hi[:, None], take, lo[:, None])
    return fn(arr[take], axis=1).astype(np.float32)


def _cache_file(path: str) -> Path:
    st = os.stat(path)
    raw = f"{os.path.normcase(os.path.abspath(path))}|{st.st_size}|{st.st_mtime_ns}|{PEAKS_VERSION}"
    return media.cache_dir() / f"{hashlib.sha1(raw.encode()).hexdigest()}.peaks.npz"


def load_cached(path: str) -> Peaks | None:
    try:
        f = _cache_file(path)
    except OSError:
        return None
    if not f.exists():
        return None
    try:
        with np.load(f) as z:          # fichier refermé aussitôt (Windows : pas de verrou laissé)
            meta = z["meta"]
            levels = []
            i = 0
            while f"min{i}" in z:
                levels.append((int(z[f"bs{i}"]), z[f"min{i}"].astype(np.float32), z[f"max{i}"].astype(np.float32)))
                i += 1
        return Peaks(levels, int(meta[0]), int(meta[1]), int(meta[2]))
    except (OSError, ValueError, KeyError):
        return None


def compute(pcm_path: str, cancel=None, chunk: int = BASE * 16384) -> Peaks:
    """Calcule la pyramide d'un fichier PCM (À APPELER DANS UN FIL DE TRAVAIL) et la met en cache."""
    cached = load_cached(pcm_path)
    if cached is not None:
        return cached
    info = wavio.probe(pcm_path)
    ch = info.channels
    mins, maxs = [], []
    pos = 0
    while pos < info.frames:
        if cancel and cancel():
            raise media.MediaError("calcul des pics annulé")
        data, _ = wavio.read(pcm_path, pos, chunk)
        n = data.shape[1]
        if n == 0:
            break
        pad = (-n) % BASE
        if pad:
            data = np.concatenate([data, np.repeat(data[:, -1:], pad, axis=1)], axis=1)
        blk = data.reshape(ch, -1, BASE)
        mins.append(blk.min(axis=2))
        maxs.append(blk.max(axis=2))
        pos += n
    lmin = np.concatenate(mins, axis=1) if mins else np.zeros((ch, 0), np.float32)
    lmax = np.concatenate(maxs, axis=1) if maxs else np.zeros((ch, 0), np.float32)
    levels = [(BASE, lmin, lmax)]
    bs = BASE
    while levels[-1][1].shape[1] > 1:
        _, a, b = levels[-1]
        pad = (-a.shape[1]) % FACTOR
        if pad:
            a = np.concatenate([a, np.repeat(a[:, -1:], pad, axis=1)], axis=1)
            b = np.concatenate([b, np.repeat(b[:, -1:], pad, axis=1)], axis=1)
        bs *= FACTOR
        levels.append((bs, a.reshape(ch, -1, FACTOR).min(axis=2), b.reshape(ch, -1, FACTOR).max(axis=2)))
    pk = Peaks(levels, info.sample_rate, info.frames, ch)
    try:
        f = _cache_file(pcm_path)
        arrays = {"meta": np.array([info.sample_rate, info.frames, ch], np.int64)}
        for i, (b, a, m) in enumerate(levels):
            arrays[f"bs{i}"] = np.array(b)
            arrays[f"min{i}"] = a.astype(np.float16)
            arrays[f"max{i}"] = m.astype(np.float16)
        tmp = f.with_name(f.name + ".part.npz")
        np.savez(tmp, **arrays)
        os.replace(tmp, f)
    except OSError:
        pass  # cache facultatif
    return pk


def pcm_window(pcm_path: str, start: int, count: int) -> np.ndarray:
    """Échantillons bruts pour le zoom fin, fenêtre bornée à MAX_PCM_WINDOW."""
    count = max(0, min(int(count), MAX_PCM_WINDOW))
    data, _ = wavio.read(pcm_path, max(0, int(start)), count)
    return data
