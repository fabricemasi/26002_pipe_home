"""Traitements hors temps réel (numpy, sans Qt) qui produisent une NOUVELLE révision du son :
l'original n'est jamais modifié. Tous prennent / rendent des tableaux float32 (canaux, images).

- `time_stretch` : WSOLA (recouvrement-addition avec recherche de similarité), hauteur conservée ;
- `resample` : sinc fenêtré (Blackman) ; `pitch_shift` = étirement puis rééchantillonnage ;
- `noise_reduce` : soustraction spectrale guidée par un profil de bruit, lissée (moins de
  « musical noise »), avec le RÉSIDU retiré pour l'écoute critique ;
- `spectral_edit` : atténuation d'une zone temps × fréquence (bords adoucis) ;
- `declick` : détection d'impulsions et interpolation.
"""
from __future__ import annotations

import numpy as np


def _hann(n: int) -> np.ndarray:
    return (0.5 - 0.5 * np.cos(2 * np.pi * np.arange(n) / n)).astype(np.float32)


# ---------------------------------------------------------------- temps / hauteur
def time_stretch(x: np.ndarray, factor: float, sr: int = 48000, frame_ms: float = 46.0, search_ms: float = 12.0) -> np.ndarray:
    """Durée × `factor` (> 1 : plus long), hauteur inchangée."""
    x = np.atleast_2d(np.asarray(x, np.float32))
    if abs(factor - 1.0) < 1e-6:
        return x.copy()
    N = int(sr * frame_ms / 1000) // 2 * 2
    Ha = N // 2                                   # pas d'analyse nominal (synthèse : N/2)
    Hs = N // 2
    Ha = max(1, int(round(Hs / factor)))
    tol = int(sr * search_ms / 1000)
    w = _hann(N)
    mono = x.mean(axis=0)
    n_out = int(round(x.shape[1] * factor))
    frames = max(1, (n_out - N) // Hs + 2)
    out = np.zeros((x.shape[0], frames * Hs + N), np.float32)
    norm = np.zeros(frames * Hs + N, np.float32)
    pad = np.pad(x, ((0, 0), (tol, N + tol + Ha * 2)))
    mpad = np.pad(mono, (tol, N + tol + Ha * 2))
    prev = 0                                       # position (dans pad) du segment précédent
    for k in range(frames):
        nominal = k * Ha + tol
        if k == 0:
            pos = nominal
        else:
            # segment qui prolonge naturellement le précédent : chercher le plus semblable
            target = mpad[prev + Hs:prev + Hs + N] * w
            lo, hi = nominal - tol, nominal + tol
            seg = mpad[lo:hi + N]
            if len(seg) < N + (hi - lo):
                pos = nominal
            else:
                cor = np.correlate(seg, target, mode="valid")
                pos = lo + int(np.argmax(cor))
        out[:, k * Hs:k * Hs + N] += pad[:, pos:pos + N] * w
        norm[k * Hs:k * Hs + N] += w
        prev = pos
    norm[norm < 1e-3] = 1.0
    out /= norm
    return out[:, :n_out].astype(np.float32)


def resample(x: np.ndarray, ratio: float, half: int = 24) -> np.ndarray:
    """Nouvelle longueur = longueur × ratio (sinc fenêtré, anti-repliement si ratio < 1)."""
    x = np.atleast_2d(np.asarray(x, np.float32))
    n_out = int(round(x.shape[1] * ratio))
    cutoff = min(1.0, ratio) * 0.97
    out = np.zeros((x.shape[0], n_out), np.float32)
    k = np.arange(-half + 1, half + 1)
    for start in range(0, n_out, 8192):
        idx = np.arange(start, min(n_out, start + 8192))
        center = idx / ratio
        c0 = np.floor(center).astype(np.int64)
        taps = c0[:, None] + k[None, :]
        t = center[:, None] - taps
        arg = np.pi * t * cutoff
        sinc = np.where(np.abs(t) < 1e-9, 1.0, np.sin(arg) / np.where(np.abs(arg) < 1e-12, 1, arg))
        win = 0.42 + 0.5 * np.cos(np.pi * t / half) + 0.08 * np.cos(2 * np.pi * t / half)
        h = sinc * win * cutoff
        h /= h.sum(axis=1, keepdims=True)
        valid = (taps >= 0) & (taps < x.shape[1])
        tc = np.clip(taps, 0, x.shape[1] - 1)
        for c in range(x.shape[0]):
            out[c, idx] = np.sum(np.where(valid, x[c][tc], 0.0) * h, axis=1)
    return out


def pitch_shift(x: np.ndarray, semitones: float, sr: int = 48000) -> np.ndarray:
    """Transposition, durée inchangée (étirement WSOLA puis rééchantillonnage)."""
    r = 2.0 ** (semitones / 12.0)
    st = time_stretch(x, r, sr)
    y = resample(st, 1.0 / r)
    n = np.atleast_2d(x).shape[1]
    if y.shape[1] < n:
        y = np.pad(y, ((0, 0), (0, n - y.shape[1])))
    return y[:, :n]


# ---------------------------------------------------------------- STFT
def stft(x: np.ndarray, n_fft: int = 2048, hop: int = 512) -> np.ndarray:
    """(canaux, trames, bins) complexe ; signal complété pour une reconstruction exacte."""
    x = np.atleast_2d(x)
    w = _hann(n_fft)
    pad = np.pad(x, ((0, 0), (n_fft, n_fft + hop)))
    n_frames = (pad.shape[1] - n_fft) // hop + 1
    idx = np.arange(n_fft)[None, :] + hop * np.arange(n_frames)[:, None]
    return np.fft.rfft(pad[:, idx] * w, axis=-1)


def istft(S: np.ndarray, length: int, n_fft: int = 2048, hop: int = 512) -> np.ndarray:
    w = _hann(n_fft)
    frames = np.fft.irfft(S, n=n_fft, axis=-1) * w
    n_frames = S.shape[1]
    total = n_fft + hop * (n_frames - 1)
    out = np.zeros((S.shape[0], total), np.float32)
    norm = np.zeros(total, np.float32)
    for k in range(n_frames):
        out[:, k * hop:k * hop + n_fft] += frames[:, k]
        norm[k * hop:k * hop + n_fft] += w * w
    norm[norm < 1e-8] = 1.0
    out /= norm
    return out[:, n_fft:n_fft + length].astype(np.float32)


# ---------------------------------------------------------------- restauration
def noise_reduce(x: np.ndarray, noise: np.ndarray, reduction_db: float = 18.0, sensitivity: float = 1.5,
                 n_fft: int = 2048, hop: int = 512) -> tuple[np.ndarray, np.ndarray]:
    """Réduction de bruit spectrale. `noise` : extrait de bruit seul (profil). Retourne
    (son traité, résidu retiré) : le résidu s'écoute pour juger les artefacts."""
    x = np.atleast_2d(np.asarray(x, np.float32))
    noise = np.atleast_2d(np.asarray(noise, np.float32))
    S = stft(x, n_fft, hop)
    N = np.abs(stft(noise, n_fft, hop))
    profile = N.mean(axis=1, keepdims=True) * sensitivity           # (canaux, 1, bins)
    if profile.shape[0] != S.shape[0]:
        profile = np.repeat(profile.mean(axis=0, keepdims=True), S.shape[0], axis=0)
    mag = np.abs(S)
    floor = 10 ** (-reduction_db / 20)
    gain = np.clip((mag - profile) / np.maximum(mag, 1e-12), 0.0, 1.0)
    gain = np.maximum(gain, floor)
    # lissage temporel (attaque rapide, relâchement lent) : moins de bruit « musical »
    for k in range(1, gain.shape[1]):
        gain[:, k] = np.maximum(gain[:, k], gain[:, k - 1] * 0.6)
    # lissage fréquentiel sur 3 bins
    gain = (np.roll(gain, 1, axis=-1) + gain + np.roll(gain, -1, axis=-1)) / 3
    y = istft(S * gain, x.shape[1], n_fft, hop)
    return y, (x - y).astype(np.float32)


def spectral_edit(x: np.ndarray, sr: int, t0: float, t1: float, f0: float, f1: float, gain_db: float = -60.0,
                  n_fft: int = 2048, hop: int = 256) -> np.ndarray:
    """Applique `gain_db` à la zone [t0, t1] s × [f0, f1] Hz (bords en cosinus sur ~1 trame / 2 bins)."""
    x = np.atleast_2d(np.asarray(x, np.float32))
    S = stft(x, n_fft, hop)
    times = (np.arange(S.shape[1]) * hop - n_fft) / sr + (n_fft / 2) / sr
    freqs = np.fft.rfftfreq(n_fft, 1.0 / sr)

    def ramp(v, a, b, soft):
        inside = np.clip(np.minimum(v - a, b - v) / soft + 0.5, 0, 1)
        return 0.5 - 0.5 * np.cos(np.pi * inside)
    mt = ramp(times, t0, t1, hop * 2 / sr)
    mf = ramp(freqs, f0, f1, 2 * sr / n_fft)
    g = 10 ** (gain_db / 20)
    mask = 1 - (1 - g) * mt[:, None] * mf[None, :]
    return istft(S * mask[None], x.shape[1], n_fft, hop)


def declick(x: np.ndarray, threshold: float = 8.0, width: int = 16) -> tuple[np.ndarray, int]:
    """Repère les impulsions (dérivée seconde très au-dessus de sa médiane) et les remplace par une
    interpolation cubique. Retourne (son traité, nombre de clics corrigés)."""
    x = np.atleast_2d(np.asarray(x, np.float32)).copy()
    count = 0
    for c in range(x.shape[0]):
        d = np.abs(np.diff(x[c], 2))
        med = np.median(d) + 1e-9
        hits = np.nonzero(d > threshold * med * 10)[0]
        last = -10 * width
        for h in hits:
            if h - last < width:
                continue
            a, b = max(1, h - width // 2), min(x.shape[1] - 2, h + width // 2 + 2)
            xs = np.array([a - 1, a, b, b + 1])
            ys = x[c, xs]
            coef = np.polyfit(xs - a, ys, 3)
            x[c, a:b] = np.polyval(coef, np.arange(a, b) - a)
            count += 1
            last = h
    return x, count
