"""Spectrogramme en TUILES (sans Qt) : chaque tuile couvre 256 trames STFT (FFT 2048, pas 512),
calculée à partir d'une fenêtre PCM bornée, mise en cache ; niveaux en dB quantifiés sur 8 bits.
La vue ne calcule jamais rien pendant la peinture : elle demande les tuiles visibles à un fil de
travail et dessine celles qui sont prêtes.
"""
from __future__ import annotations

import numpy as np

from . import wavio

N_FFT = 2048
HOP = 512
TILE_FRAMES = 256
TILE_SAMPLES = TILE_FRAMES * HOP
DB_FLOOR = -100.0


def tile_index(sample: int) -> int:
    return max(0, int(sample) // TILE_SAMPLES)


def compute_tile(pcm_path: str, index: int) -> np.ndarray:
    """uint8 (bins = N_FFT/2+1, trames = TILE_FRAMES) : 0 = DB_FLOOR, 255 = 0 dBFS (canaux mélangés)."""
    start = index * TILE_SAMPLES
    data, _ = wavio.read(pcm_path, max(0, start - N_FFT // 2), TILE_SAMPLES + N_FFT)
    mono = data.mean(axis=0) if data.size else np.zeros(0, np.float32)
    if start == 0:
        mono = np.concatenate([np.zeros(N_FFT // 2, np.float32), mono])
    need = TILE_SAMPLES + N_FFT
    if mono.size < need:
        mono = np.pad(mono, (0, need - mono.size))
    w = np.hanning(N_FFT).astype(np.float32)
    idx = np.arange(N_FFT)[None, :] + HOP * np.arange(TILE_FRAMES)[:, None]
    mag = np.abs(np.fft.rfft(mono[idx] * w, axis=-1)) * (2.0 / w.sum())
    db = 20 * np.log10(np.maximum(mag, 1e-12))
    q = np.clip((db - DB_FLOOR) / -DB_FLOOR * 255, 0, 255).astype(np.uint8)
    return q.T.copy()


def bin_freq(b: int, sr: int) -> float:
    return b * sr / N_FFT


def freq_bin(f: float, sr: int) -> int:
    return int(round(f * N_FFT / sr))
