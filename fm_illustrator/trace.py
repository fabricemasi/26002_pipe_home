"""Vectorisation d'une image (SANS Qt ; numpy, déjà dépendance du projet) : à la manière de « Vectorisation de
l'image » d'Illustrator (Image Trace), algorithme propre au module (idée générale de potrace : bords des pixels ->
contours -> courbes ; aucun code repris).

Étapes (`trace(pixels, réglages)`, pixels = tableau H × W × 4 RVBA) :
1. quantification : « bw » (seuil de luminance), « gray » (n niveaux), « color » (n couleurs : k-moyennes sur un
   échantillon) ; pixels presque transparents ignorés ;
2. par couleur, contours = bords des pixels orientés (la couleur à droite du sens de parcours : les trous tournent
   dans l'autre sens, la règle « non nulle » les vide), reliés en boucles ; aux sommets ambigus (deux pixels qui se
   touchent par un coin), on tourne à droite (régions séparées) ;
3. bruit : boucles de moins de `noise` pixels² écartées ;
4. lissage : milieux des bords (escaliers adoucis), Ramer-Douglas-Peucker, angles marqués au-delà de `corner`
   degrés, puis courbes de Bézier par morceaux entre les angles (`fm_font.shapes.fit_cubic`, Schneider) à `fidelity`
   pixels près.
Empilement : la couleur la plus fréquente devient un rectangle de fond (pas de jour entre les zones voisines), les
autres sont posées dessus. Coordonnées : pixels de la grille tracée (l'appelant les ramène à l'image)."""
from __future__ import annotations

import math

import numpy as np

PRESETS = {
    "bw": ("Noir et blanc", {"mode": "bw", "threshold": 128, "ignore_white": True}),
    "gray": ("Niveaux de gris", {"mode": "gray", "colors": 4}),
    "color3": ("3 couleurs", {"mode": "color", "colors": 3}),
    "color6": ("6 couleurs", {"mode": "color", "colors": 6}),
    "color16": ("16 couleurs", {"mode": "color", "colors": 16}),
}
DEFAULTS = {"mode": "color", "colors": 6, "threshold": 128, "detail": 500, "fidelity": 1.5, "noise": 12,
            "corner": 70.0, "ignore_white": False}


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


# ---------------------------------------------------------------- contours
_RIGHT = {(1, 0): (0, 1), (0, 1): (-1, 0), (-1, 0): (0, -1), (0, -1): (1, 0)}     # tourner à droite (Y vers le bas)
_LEFT = {v: k for k, v in _RIGHT.items()}


def loops(mask: np.ndarray) -> list[list[tuple[int, int]]]:
    """Boucles orientées des bords d'un masque booléen (sommets = coins de pixels, seulement les changements de
    direction gardés)."""
    h, w = mask.shape
    pad = np.zeros((h + 2, w + 2), dtype=bool)
    pad[1:-1, 1:-1] = mask
    inside = pad[1:-1, 1:-1]
    out_edges: dict[tuple[int, int], list[tuple[int, int]]] = {}

    def add(ys, xs, sx, sy, dx, dy):
        for y, x in zip(ys.tolist(), xs.tolist()):
            out_edges.setdefault((x + sx, y + sy), []).append((dx, dy))
    ys, xs = np.nonzero(inside & ~pad[:-2, 1:-1])                     # haut : vers +x
    add(ys, xs, 0, 0, 1, 0)
    ys, xs = np.nonzero(inside & ~pad[1:-1, 2:])                      # droite : vers +y
    add(ys, xs, 1, 0, 0, 1)
    ys, xs = np.nonzero(inside & ~pad[2:, 1:-1])                      # bas : vers -x
    add(ys, xs, 1, 1, -1, 0)
    ys, xs = np.nonzero(inside & ~pad[1:-1, :-2])                     # gauche : vers -y
    add(ys, xs, 0, 1, 0, -1)
    result = []
    while out_edges:
        start, dirs = next(iter(out_edges.items()))
        d = dirs.pop()
        if not dirs:
            del out_edges[start]
        loop = [start]
        p = (start[0] + d[0], start[1] + d[1])
        while p != start or False:
            choices = out_edges.get(p)
            if not choices:
                break
            for want in (_RIGHT[d], d, _LEFT[d]):
                if want in choices:
                    nd = want
                    break
            else:
                nd = choices[0]
            choices.remove(nd)
            if not choices:
                del out_edges[p]
            if nd != d:
                loop.append(p)
            d = nd
            p = (p[0] + d[0], p[1] + d[1])
        if len(loop) >= 3:
            result.append(loop)
    return result


def _area(pts) -> float:
    return sum(pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1]
               for i in range(len(pts))) / 2


def _midpoints(loop) -> list[tuple[float, float]]:
    """Points au milieu des bords (et des segments longs : leurs extrémités à un demi-pixel) : escaliers adoucis."""
    out = []
    n = len(loop)
    for i in range(n):
        a, b = loop[i], loop[(i + 1) % n]
        length = abs(b[0] - a[0]) + abs(b[1] - a[1])
        dx, dy = (b[0] - a[0]) / length, (b[1] - a[1]) / length
        if length > 1:
            out.append((a[0] + dx * 0.5, a[1] + dy * 0.5))
            out.append((b[0] - dx * 0.5, b[1] - dy * 0.5))
        else:
            out.append(((a[0] + b[0]) / 2, (a[1] + b[1]) / 2))
    return out


def _turn(a, b, c) -> float:
    v1 = (b[0] - a[0], b[1] - a[1])
    v2 = (c[0] - b[0], c[1] - b[1])
    n1, n2 = math.hypot(*v1), math.hypot(*v2)
    if n1 < 1e-9 or n2 < 1e-9:
        return 0.0
    return math.degrees(math.acos(max(-1.0, min(1.0, (v1[0] * v2[0] + v1[1] * v2[1]) / (n1 * n2)))))


def smooth_loop(loop, fidelity: float, corner: float) -> dict | None:
    """Boucle de pixels -> sous-tracé fermé (format du module) : angles gardés, courbes ailleurs."""
    from fm_font.shapes import fit_cubic, rdp
    from . import bezier as bz
    pts = _midpoints(loop)
    closed = pts + [pts[0]]
    simple = rdp(closed, max(0.35, fidelity * 0.4))[:-1]
    if len(simple) < 3:
        return None
    n = len(simple)
    corners = [i for i in range(n) if _turn(simple[i - 1], simple[i], simple[(i + 1) % n]) >= corner]
    if not corners:                                     # forme toute en courbe : coupée en deux morceaux
        corners = [0, n // 2]
    cubics = []
    for k, start in enumerate(corners):
        end = corners[(k + 1) % len(corners)]
        piece = [simple[i % n] for i in range(start, (end if end > start else end + n) + 1)]
        if len(piece) == 2:
            a, b = piece
            cubics.append((a, a, b, b))
        else:
            cubics += [tuple(tuple(p) for p in c) for c in fit_cubic(piece, fidelity)]
    if not cubics:
        return None
    nodes = []
    for p0, c1, c2, p3 in cubics:
        if nodes:
            nodes[-1][4], nodes[-1][5] = c1
        else:
            nodes.append(bz.node(p0[0], p0[1], None, None, c1[0], c1[1]))
        nodes.append(bz.node(p3[0], p3[1], c2[0], c2[1]))
    last = nodes.pop()                                  # retour au départ : fusionné avec le 1er nœud
    nodes[0][2], nodes[0][3] = last[2], last[3]
    if len(nodes) < 2:                                  # boucle minuscule réduite à un point : écartée
        return None
    corner_points = {simple[i] for i in corners}
    for nd in nodes:
        if (nd[0], nd[1]) not in corner_points and (bz.has_in(nd) and bz.has_out(nd)):
            nd[6] = 1
    return {"closed": True, "nodes": nodes}


def trace(pixels: np.ndarray, settings: dict, progress=None) -> list[tuple[str, list[dict]]]:
    """-> [(couleur, sous-tracés)] du fond vers le dessus. `progress(fait, total)` appelé par couleur."""
    labels, palette = quantize(pixels, settings)
    h, w = labels.shape
    counts = [(int((labels == k).sum()), k) for k in range(len(palette))]
    counts = [c for c in counts if c[0] > 0]
    if not counts:
        return []
    counts.sort(reverse=True)
    out = []
    order = [k for _c, k in counts]
    background = None
    if not (labels < 0).any() and len(order) > 1:      # image opaque : fond = couleur la plus fréquente
        background = order.pop(0)
        from . import bezier as bz
        out.append((palette[background], bz.rect(0, 0, w, h)))
    noise = float(settings.get("noise", 12))
    fidelity = float(settings.get("fidelity", 1.5))
    corner = float(settings.get("corner", 70.0))
    for done, k in enumerate(order):
        subs = []
        for loop in loops(labels == k):
            if abs(_area(loop)) < noise:
                continue
            sub = smooth_loop(loop, fidelity, corner)
            if sub is not None:
                subs.append(sub)
        if subs:
            out.append((palette[k], subs))
        if progress is not None:
            progress(done + 1, len(order))
    return out
