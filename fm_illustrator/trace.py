"""Vectorisation d'une image (SANS Qt ; numpy, déjà dépendance du projet) : à la manière de « Vectorisation de
l'image » d'Illustrator (Image Trace), algorithme propre au module (aucun code repris).

Étapes (`trace(pixels, réglages)`, pixels = tableau H × W × 4 RVBA) :
1. quantification (ici) : « bw » (seuil de luminance), « gray » (n niveaux), « color » (n couleurs : k-moyennes sur
   un échantillon) ; pixels presque transparents ignorés ; la couleur la plus fréquente devient un rectangle de fond
   (pas de jour entre les zones voisines), les autres sont posées dessus ;
2. contours SUBPIXEL de chaque zone (`trace_contours`) : ligne de niveau d'un champ continu (luminance anticrénelée
   en noir et blanc / gris, masque légèrement flouté en couleur), « marching squares » ; trous dans l'autre sens ;
3. bruit : contours de moins de `noise` px² écartés ;
4. reconstruction (`trace_fit`) : angles concentrés (sommet reconstruit), droites, extrema, puis cubiques à tangentes
   partagées (G1) sous la tolérance `fidelity` px, le moins d'ancres possible.
Réglages : threshold, colors, detail (grand côté de l'image tracée, côté appelant), fidelity (écart maximal, px),
noise (px²), corner (degrés de virage d'un angle), smooth (flou du champ, px ; 0 = la source telle quelle).
Coordonnées : pixels de la grille tracée (l'appelant les ramène à l'image)."""
from __future__ import annotations

import numpy as np

PRESETS = {
    "bw": ("Noir et blanc", {"mode": "bw", "threshold": 128, "ignore_white": True}),
    "gray": ("Niveaux de gris", {"mode": "gray", "colors": 4}),
    "color3": ("3 couleurs", {"mode": "color", "colors": 3}),
    "color6": ("6 couleurs", {"mode": "color", "colors": 6}),
    "color16": ("16 couleurs", {"mode": "color", "colors": 16}),
}
DEFAULTS = {"mode": "color", "colors": 6, "threshold": 128, "detail": 1000, "fidelity": 1.0, "noise": 12,
            "corner": 30.0, "smooth": 0.0, "ignore_white": False}
FINE_KEYS = ("detail", "fidelity", "noise", "corner", "smooth")      # gardés quand on change de préréglage


def settings_for(preset: str, **overrides) -> dict:
    out = dict(DEFAULTS)
    out.update(PRESETS.get(preset, ("", {}))[1])
    out.update(overrides)
    return out


# ---------------------------------------------------------------- quantification
def quantize(pixels: np.ndarray, settings: dict) -> tuple[np.ndarray, list[str]]:
    """-> (étiquettes H × W, -1 = ignoré ; couleurs « #rrggbb » par étiquette)."""
    rgb = pixels[..., :3].astype(np.float32)
    alpha = pixels[..., 3]
    lum = rgb @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
    mode = settings.get("mode", "color")
    if mode == "bw":
        labels = (lum >= float(settings.get("threshold", 128))).astype(np.int32)       # 0 = noir, 1 = blanc
        palette = ["#000000", "#ffffff"]
        if settings.get("ignore_white", True):
            labels[labels == 1] = -1
    elif mode == "gray":
        n = max(2, min(64, int(settings.get("colors", 4))))
        labels = np.minimum((lum / 256.0 * n).astype(np.int32), n - 1)
        palette = []
        for k in range(n):
            sel = lum[labels == k]
            v = int(round(float(sel.mean()))) if sel.size else int((k + 0.5) * 256 / n)
            palette.append(f"#{v:02x}{v:02x}{v:02x}")
    else:
        labels, palette = _kmeans(rgb, max(2, min(64, int(settings.get("colors", 6)))))
    labels[alpha < 128] = -1
    return labels, palette


def _kmeans(rgb: np.ndarray, n: int, iterations: int = 10) -> tuple[np.ndarray, list[str]]:
    flat = rgb.reshape(-1, 3)
    rng = np.random.default_rng(0)                     # graine fixe : même image -> même résultat
    sample = flat[rng.choice(len(flat), size=min(len(flat), 20000), replace=False)] if len(flat) > 20000 else flat
    # Départ « k-means++ » (graine fixe) : chaque centre tiré loin des précédents (proba. ∝ distance²) ; des
    # quantiles de luminance confondaient deux couleurs de même clarté quand une troisième domine.
    centers = np.empty((n, 3), dtype=np.float32)
    centers[0] = sample[rng.integers(len(sample))]
    nearest_d = ((sample - centers[0]) ** 2).sum(axis=1)
    for k in range(1, n):
        total = float(nearest_d.sum())
        index = int(rng.choice(len(sample), p=nearest_d / total)) if total > 0 else int(rng.integers(len(sample)))
        centers[k] = sample[index]
        nearest_d = np.minimum(nearest_d, ((sample - centers[k]) ** 2).sum(axis=1))
    for _ in range(iterations):
        d = ((sample[:, None, :] - centers[None, :, :]) ** 2).sum(axis=2)
        nearest = d.argmin(axis=1)
        for k in range(n):
            members = sample[nearest == k]
            if len(members):
                centers[k] = members.mean(axis=0)
    labels = np.empty(len(flat), dtype=np.int32)
    for start in range(0, len(flat), 65536):            # par blocs : mémoire bornée
        block = flat[start:start + 65536]
        labels[start:start + 65536] = ((block[:, None, :] - centers[None, :, :]) ** 2).sum(axis=2).argmin(axis=1)
    palette = ["#" + "".join(f"{int(round(min(255.0, max(0.0, v)))):02x}" for v in c) for c in centers]
    return labels.reshape(rgb.shape[:2]), palette


def trace(pixels: np.ndarray, settings: dict, progress=None, cancelled=None) -> list[tuple[str, list[dict]]] | None:
    """-> [(couleur, sous-tracés)] du fond vers le dessus. `progress(fait, total)` appelé par couleur ; `cancelled()`
    vrai -> arrêt au prochain contour, None rendu (annulation par Échap)."""
    from . import trace_contours as tc
    from . import trace_fit as tf
    labels, palette = quantize(pixels, settings)
    h, w = labels.shape
    counts = [(int((labels == k).sum()), k) for k in range(len(palette))]
    counts = [c for c in counts if c[0] > 0]
    if not counts:
        return []
    counts.sort(reverse=True)
    out = []
    order = [k for _c, k in counts]
    if not (labels < 0).any() and len(order) > 1:      # image opaque : fond = couleur la plus fréquente
        background = order.pop(0)
        from . import bezier as bz
        out.append((palette[background], bz.rect(0, 0, w, h)))
    noise = float(settings.get("noise", 12))
    fidelity = float(settings.get("fidelity", DEFAULTS["fidelity"]))
    corner = float(settings.get("corner", DEFAULTS["corner"]))
    fields = dict(tc.fields(pixels, labels, palette, settings))
    scale = max(3.0, 0.004 * max(h, w))               # échelle des angles : 3 px jusqu'à 750 px, 4 px à 1 000
    for done, k in enumerate(order):
        subs = []
        for loop in tc.iso_loops(fields[k]):
            if cancelled is not None and cancelled():
                return None
            if abs(tc.area(loop)) < noise:
                continue
            sub = tf.fit_loop(loop, fidelity, corner, scale)
            if sub is not None:
                subs.append(sub)
        if subs:
            out.append((palette[k], subs))
        if progress is not None:
            progress(done + 1, len(order))
    return out
