"""Analyse (numpy, sans Qt) : crête, true peak, loudness ITU-R BS.1770-4 / EBU R128 (intégré,
court terme, LRA), spectre, alignement de sources (micro + pickup), accordeur (YIN).
"""
from __future__ import annotations

import math

import numpy as np

from .dsp_offline import resample


def _biquad(b, a, x):
    y = np.zeros_like(x, dtype=np.float64)
    z1 = z2 = 0.0
    b0, b1, b2 = b
    _, a1, a2 = a
    for i, v in enumerate(x):            # IIR : boucle explicite (analyse hors ligne)
        o = b0 * v + z1
        z1 = b1 * v - a1 * o + z2
        z2 = b2 * v - a2 * o
        y[i] = o
    return y


def _kweight_coeffs(sr: int):
    """Filtres de pondération K (BS.1770) recalculés pour la fréquence `sr`."""
    f0, G, Q = 1681.974450955533, 3.999843853973347, 0.7071752369554196
    K = math.tan(math.pi * f0 / sr)
    Vh = 10 ** (G / 20)
    Vb = Vh ** 0.4996667741545416
    a0 = 1 + K / Q + K * K
    shelf = ([(Vh + Vb * K / Q + K * K) / a0, 2 * (K * K - Vh) / a0, (Vh - Vb * K / Q + K * K) / a0],
             [1, 2 * (K * K - 1) / a0, (1 - K / Q + K * K) / a0])
    f0, Q = 38.13547087602444, 0.5003270373238773
    K = math.tan(math.pi * f0 / sr)
    a0 = 1 + K / Q + K * K
    hp = ([1, -2, 1], [1, 2 * (K * K - 1) / a0, (1 - K / Q + K * K) / a0])
    return shelf, hp


_KW_CACHE: dict = {}
_KW_LEN = 1 << 15


def _kweight(x: np.ndarray, sr: int) -> np.ndarray:
    """Pondération K appliquée par convolution FFT (réponse impulsionnelle des deux biquads,
    tronquée à 32 768 échantillons où elle est éteinte) : linéaire en durée, sans boucle Python."""
    h = _KW_CACHE.get(sr)
    if h is None:
        shelf, hp = _kweight_coeffs(sr)
        imp = np.zeros(_KW_LEN)
        imp[0] = 1.0
        h = _biquad(hp[0], hp[1], _biquad(shelf[0], shelf[1], imp))
        _KW_CACHE[sr] = h
    x = np.atleast_2d(x).astype(np.float64)
    L, B = h.size, 1 << 18
    n = 1 << int(math.ceil(math.log2(B + L)))
    H = np.fft.rfft(h, n)
    out = np.zeros((x.shape[0], x.shape[1] + L), np.float64)
    for s in range(0, x.shape[1], B):
        blk = x[:, s:s + B]
        y = np.fft.irfft(np.fft.rfft(blk, n, axis=-1) * H, n, axis=-1)[:, :blk.shape[1] + L]
        out[:, s:s + y.shape[1]] += y
    return out[:, :x.shape[1]]

def loudness(x: np.ndarray, sr: int) -> dict:
    """{"integrated": LUFS, "short_term_max": LUFS, "lra": LU} (stéréo / mono, poids 1 par canal)."""
    x = np.atleast_2d(np.asarray(x, np.float32))
    y = _kweight(x, sr)
    def blocks(win_s, step_s):
        n, s = int(sr * win_s), int(sr * step_s)
        if y.shape[1] < n:
            return np.array([])
        starts = np.arange(0, y.shape[1] - n + 1, s)
        cs = np.cumsum(np.concatenate([np.zeros((y.shape[0], 1)), y ** 2], axis=1), axis=1)
        ms = (cs[:, starts + n] - cs[:, starts]) / n
        return ms.sum(axis=0)
    def lufs(z):
        return -0.691 + 10 * np.log10(np.maximum(z, 1e-12))
    z = blocks(0.4, 0.1)
    res = {"integrated": -math.inf, "short_term_max": -math.inf, "lra": 0.0}
    if z.size:
        z = z[lufs(z) > -70]
        if z.size:
            rel = lufs(z.mean()) - 10
            z2 = z[lufs(z) > rel]
            if z2.size:
                res["integrated"] = float(lufs(z2.mean()))
    st = blocks(3.0, 0.1)
    if st.size:
        L = lufs(st)
        res["short_term_max"] = float(L.max())
        L = L[L > -70]
        if L.size:
            L = L[L > lufs(st[lufs(st) > -70].mean()) - 20]
            if L.size:
                res["lra"] = float(np.percentile(L, 95) - np.percentile(L, 10))
    return res


def peak_dbfs(x: np.ndarray) -> float:
    p = float(np.max(np.abs(x))) if np.size(x) else 0.0
    return 20 * math.log10(p) if p > 0 else -math.inf


def true_peak_dbtp(x: np.ndarray) -> float:
    """Crête vraie par suréchantillonnage ×4 (BS.1770 annexe 2)."""
    up = resample(np.atleast_2d(x), 4.0, half=12)
    return peak_dbfs(up)


def spectrum(x: np.ndarray, sr: int, n_fft: int = 8192) -> tuple[np.ndarray, np.ndarray]:
    """(fréquences, niveau moyen en dB) sur des trames de Hann recouvrantes."""
    m = np.atleast_2d(x).mean(axis=0)
    if m.size < n_fft:
        m = np.pad(m, (0, n_fft - m.size))
    w = np.hanning(n_fft)
    hop = n_fft // 2
    frames = [np.abs(np.fft.rfft(m[i:i + n_fft] * w)) for i in range(0, m.size - n_fft + 1, hop)]
    mag = np.mean(frames, axis=0) * 2 / w.sum()
    return np.fft.rfftfreq(n_fft, 1 / sr), 20 * np.log10(np.maximum(mag, 1e-12))


def align_sources(ref: np.ndarray, other: np.ndarray, max_lag: int = 4800) -> dict:
    """Décalage (échantillons) et polarité de `other` par rapport à `ref` (corrélation croisée FFT).
    lag > 0 : `other` est en retard ; le corriger = avancer `other` de lag."""
    a = np.atleast_2d(ref).mean(axis=0).astype(np.float64)
    b = np.atleast_2d(other).mean(axis=0).astype(np.float64)
    n = 1 << int(math.ceil(math.log2(a.size + b.size)))
    cor = np.fft.irfft(np.fft.rfft(b, n) * np.conj(np.fft.rfft(a, n)), n)
    lags = np.concatenate([np.arange(0, max_lag + 1), np.arange(-max_lag, 0)])
    vals = cor[lags % n]
    k = int(np.argmax(np.abs(vals)))
    lag = int(lags[k])
    norm = math.sqrt(float(np.dot(a, a) * np.dot(b, b))) or 1.0
    return {"lag": lag, "invert": bool(vals[k] < 0), "correlation": float(abs(vals[k]) / norm)}


NOTE_NAMES = ("do", "do#", "ré", "ré#", "mi", "fa", "fa#", "sol", "sol#", "la", "la#", "si")


def pitch_yin(x: np.ndarray, sr: int, fmin: float = 40.0, fmax: float = 1500.0, threshold: float = 0.12) -> float | None:
    """Fréquence fondamentale (YIN) d'un extrait ; None si non voisé."""
    s = np.atleast_2d(x).mean(axis=0).astype(np.float64)
    if s.size == 0 or float(np.sqrt(np.mean(s ** 2))) < 1e-4:     # silence : rien à accorder
        return None
    tau_max = min(int(sr / fmin), s.size // 2)
    tau_min = max(2, int(sr / fmax))
    if tau_max <= tau_min:
        return None
    W = s.size - tau_max
    n = 1 << int(math.ceil(math.log2(s.size * 2)))
    # corrélation FENÊTRÉE r_t = somme_{j<W} x_j x_{j+t}
    acf = np.fft.irfft(np.fft.rfft(s, n) * np.conj(np.fft.rfft(s[:W], n)), n)[:tau_max + 1]
    e = np.concatenate([[0.0], np.cumsum(s ** 2)])
    d = np.array([e[W] - e[0] + e[t + W] - e[t] - 2 * acf[t] for t in range(tau_max + 1)])
    cmnd = np.ones_like(d)
    cmnd[1:] = d[1:] * np.arange(1, tau_max + 1) / np.maximum(np.cumsum(d[1:]), 1e-12)
    for t in range(tau_min, tau_max):
        if cmnd[t] < threshold:
            while t + 1 < tau_max and cmnd[t + 1] < cmnd[t]:
                t += 1
            a, b, c = cmnd[t - 1], cmnd[t], cmnd[t + 1]
            den = a - 2 * b + c
            shift = 0.5 * (a - c) / den if abs(den) > 1e-12 else 0.0
            return sr / (t + shift)
    return None


def tuner(freq: float, ref_a4: float = 440.0) -> dict:
    """{"note": nom, "octave", "midi", "cents"} de la note la plus proche (référence réglable)."""
    midi = 69 + 12 * math.log2(freq / ref_a4)
    n = int(round(midi))
    return {"note": NOTE_NAMES[n % 12], "octave": n // 12 - 1, "midi": n, "cents": round((midi - n) * 100, 1)}
