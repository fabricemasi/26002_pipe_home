"""Vectorisation, étape 1 (SANS Qt ; numpy) : contours SUBPIXEL des zones d'une image.

Au lieu de suivre les bords des pixels (escaliers d'un demi-pixel qui se retrouvaient dans les courbes), chaque zone
est décrite par un CHAMP continu, positif dedans, négatif dehors, échantillonné au centre des pixels ; son contour est
la ligne de niveau 0, trouvée par « marching squares » avec interpolation linéaire sur les arêtes :
- noir et blanc : champ = seuil − luminance (image composée sur blanc) : l'anticrénelage de la source place le bord
  au dixième de pixel près ;
- niveaux de gris : distance à la bande de luminance de la zone ;
- couleurs : masque de la zone légèrement flouté (σ 0,7 px) moins 0,5 (pas de gradient exploitable entre deux
  couleurs quelconques : le flou remplace les marches par une transition régulière) ;
- pixels presque transparents : hors de toute zone ; « lissage » (réglage) : flou gaussien du champ.

Orientation : la zone est à DROITE du sens de parcours (Y vers le bas), comme avant : aire positive pour un contour
extérieur, négative pour un trou ; la règle « non nulle » vide les trous. Points de selle : tranchés par la valeur
au centre de la case. Coordonnées : grille des pixels (bords des pixels aux entiers, centres aux demi-entiers)."""
from __future__ import annotations

import numpy as np

COLOR_BLUR = 0.7                                       # px : flou des masques de couleur (marches -> transition)


def gaussian_blur(a: np.ndarray, sigma: float) -> np.ndarray:
    """Flou gaussien séparable (bords répétés) ; `sigma` en pixels, rien sous 0,05."""
    if sigma < 0.05:
        return a
    radius = max(1, int(round(3 * sigma)))
    x = np.arange(-radius, radius + 1, dtype=np.float64)
    k = np.exp(-x * x / (2 * sigma * sigma))
    k /= k.sum()
    out = a.astype(np.float64)
    for axis in (0, 1):
        pad = [(0, 0), (0, 0)]
        pad[axis] = (radius, radius)
        p = np.pad(out, pad, mode="edge")
        acc = np.zeros_like(out)
        n = out.shape[axis]
        for i, w in enumerate(k):
            acc += w * (p[i:i + n, :] if axis == 0 else p[:, i:i + n])
        out = acc
    return out


def luminance(pixels: np.ndarray, over_white: bool = True) -> np.ndarray:
    rgb = pixels[..., :3].astype(np.float64)
    lum = rgb @ np.array([0.299, 0.587, 0.114])
    if over_white:                                     # transparence composée sur blanc (bord anticrénelé gardé)
        alpha = pixels[..., 3].astype(np.float64) / 255.0
        lum = lum * alpha + 255.0 * (1.0 - alpha)
    return lum


def antialiased(lum: np.ndarray) -> bool:
    """Bords anticrénelés ? Parmi les pixels de bord (voisin nettement différent), part de valeurs intermédiaires.
    Image binaire (pixel art, masque, capture sans lissage) : ses marches deviendraient des angles."""
    d = np.zeros(lum.shape, dtype=bool)
    d[:, 1:] |= np.abs(np.diff(lum, axis=1)) > 64
    d[1:, :] |= np.abs(np.diff(lum, axis=0)) > 64
    if d.sum() < 8:
        return True
    mid = (lum > 24) & (lum < 231)
    near = d.copy()
    near[:, :-1] |= d[:, 1:]
    near[:-1, :] |= d[1:, :]
    return float((mid & near).sum()) / float(near.sum()) > 0.12


def fields(pixels: np.ndarray, labels: np.ndarray, palette: list[str], settings: dict):
    """Champ de chaque zone (étiquette k) : (k, tableau H × W, positif dedans). Source sans anticrénelage : même
    léger flou que les masques de couleur (sinon ses marches d'escalier deviennent des angles)."""
    mode = settings.get("mode", "color")
    smooth = float(settings.get("smooth", 0.0))
    if mode in ("bw", "gray") and not antialiased(luminance(pixels)):
        smooth = float(np.hypot(COLOR_BLUR, smooth))
    alpha = pixels[..., 3].astype(np.float64)
    opaque = alpha - 127.5                             # > 0 : pixel assez opaque pour appartenir à une zone
    if mode == "bw":
        lum = gaussian_blur(luminance(pixels), smooth)
        black = float(settings.get("threshold", 128)) - lum
        for k in range(len(palette)):
            if (labels == k).any():
                yield k, (black if k == 0 else np.minimum(-black, opaque))
        return
    if mode == "gray":
        lum = gaussian_blur(luminance(pixels, over_white=False), smooth)
        n = len(palette)
        for k in range(n):
            if not (labels == k).any():
                continue
            lo, hi = k * 256.0 / n, (k + 1) * 256.0 / n
            f = np.full(lum.shape, np.inf)
            if k > 0:
                f = np.minimum(f, lum - lo)
            if k < n - 1:
                f = np.minimum(f, hi - lum)
            yield k, np.minimum(f, opaque)
        return
    sigma = float(np.hypot(COLOR_BLUR, smooth))
    for k in range(len(palette)):
        mask = labels == k
        if mask.any():
            yield k, np.minimum(gaussian_blur(mask.astype(np.float64), sigma) - 0.5, opaque / 255.0)


# ---------------------------------------------------------------- marching squares
def iso_loops(field: np.ndarray) -> list[np.ndarray]:
    """Lignes de niveau 0 du champ : boucles fermées (tableaux n × 2, sans répéter le 1er point), zone à droite."""
    h, w = field.shape
    f = np.asarray(field, dtype=np.float64)
    f = np.where(np.isfinite(f), f, np.where(f > 0, 1e6, -1e6))
    P = np.empty((h + 2, w + 2))
    P[1:-1, 1:-1] = f
    # Bordure : opposé du voisin -> le contour d'une zone qui touche le bord passe exactement sur le bord de l'image.
    P[0, 1:-1] = -np.maximum(np.abs(f[0]), 1e-3)
    P[-1, 1:-1] = -np.maximum(np.abs(f[-1]), 1e-3)
    P[1:-1, 0] = -np.maximum(np.abs(f[:, 0]), 1e-3)
    P[1:-1, -1] = -np.maximum(np.abs(f[:, -1]), 1e-3)
    P[0, 0] = P[0, -1] = P[-1, 0] = P[-1, -1] = -1e-3
    inside = P > 0
    W = w + 2
    a, b = inside[:-1, :-1], inside[:-1, 1:]           # coins de chaque case : haut-gauche, haut-droite,
    c, d = inside[1:, 1:], inside[1:, :-1]             # bas-droite, bas-gauche
    case = a * 8 + b * 4 + c * 2 + d * 1
    rows, cols = np.nonzero((case > 0) & (case < 15))
    if not len(rows):
        return []
    H_OFF = 0
    V_OFF = (h + 2) * W

    def hk(i, j):                                     # arête horizontale (i, j) - (i, j + 1)
        return H_OFF + i * W + j

    def vk(i, j):                                     # arête verticale (i, j) - (i + 1, j)
        return V_OFF + i * W + j

    nxt: dict[int, int] = {}
    for i, j, k in zip(rows.tolist(), cols.tolist(), case[rows, cols].tolist()):
        ia, ib, ic, idd = k & 8, k & 4, k & 2, k & 1
        top, right, bottom, left = hk(i, j), vk(i, j + 1), hk(i + 1, j), vk(i, j)
        if k == 10:                                    # selle : haut-gauche et bas-droite dedans
            center = (P[i, j] + P[i, j + 1] + P[i + 1, j + 1] + P[i + 1, j]) > 0
            if center:                                 # dedans reliés : on coupe les coins extérieurs
                nxt[top] = right
                nxt[bottom] = left
            else:
                nxt[top] = left
                nxt[bottom] = right
            continue
        if k == 5:                                     # selle : haut-droite et bas-gauche dedans
            center = (P[i, j] + P[i, j + 1] + P[i + 1, j + 1] + P[i + 1, j]) > 0
            if center:
                nxt[left] = top
                nxt[right] = bottom
            else:
                nxt[right] = top
                nxt[left] = bottom
            continue
        # Parcours horaire haut -> droite -> bas -> gauche : le segment va du passage dedans -> dehors au passage
        # dehors -> dedans (la zone reste à droite).
        start = end = None
        for edge, frm, to in ((top, ia, ib), (right, ib, ic), (bottom, ic, idd), (left, idd, ia)):
            if frm and not to:
                start = edge
            elif to and not frm:
                end = edge
        nxt[start] = end

    def point(key):
        if key < V_OFF:
            i, j = divmod(key - H_OFF, W)
            p0, p1 = P[i, j], P[i, j + 1]
            t = p0 / (p0 - p1)
            return (j - 0.5 + t, i - 0.5)
        i, j = divmod(key - V_OFF, W)
        p0, p1 = P[i, j], P[i + 1, j]
        t = p0 / (p0 - p1)
        return (j - 0.5, i - 0.5 + t)

    loops = []
    while nxt:
        first, cur = next(iter(nxt.items()))
        del nxt[first]
        chain = [first]
        while cur != first and cur in nxt:
            chain.append(cur)
            cur = nxt.pop(cur)
        if cur == first and len(chain) >= 3:
            pts = np.array([point(key) for key in chain])
            keep = np.ones(len(pts), dtype=bool)        # points confondus (passage sur un échantillon nul)
            keep[1:] = np.hypot(*np.diff(pts, axis=0).T) > 1e-9
            pts = pts[keep]
            if len(pts) >= 3:
                loops.append(pts)
    return loops


def area(pts) -> float:
    """Aire signée (positive : contour extérieur, zone à droite avec Y vers le bas)."""
    p = np.asarray(pts, dtype=np.float64)
    x, y = p[:, 0], p[:, 1]
    return float((x * np.roll(y, -1) - np.roll(x, -1) * y).sum() / 2)
