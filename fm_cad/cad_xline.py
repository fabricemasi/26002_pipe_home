"""LIGNES DE CONSTRUCTION du CAD (XLINE : droite infinie dans les deux sens ; RAY : demi-droite, comme AutoCAD) :
geometrie PURE (aucun Qt), coordonnees du DOCUMENT.

Champs : `p1` (point de base ; origine de la demi-droite) et `p2` (un second point : la direction). Deplacer, tourner,
symetriser, mettre a l'echelle = transformer ces deux points (comme une ligne).
- Accrochages, selection, ajuster, decaler, intersections : un SEGMENT tres long (`EXTENT` de part et d'autre, ou
  vers l'avant pour la demi-droite) en double precision.
- Dessin : la droite DECOUPEE au rectangle visible (`clip`), jamais un trait de cette longueur (lots, GPU) ; elle
  n'entre pas dans l'etendue du dessin (zoom etendu, comme AutoCAD)."""
from __future__ import annotations

import math

EXTENT = 1.0e7                      # demi-longueur du segment de calcul (unites du board ; plus long : la grille
                                    # d accrochage `GridIndex` agrandit ses cellules a 1/10^6 du plus grand objet)
KINDS = ("cad_xline", "cad_ray")


def _pt(value, default=(0.0, 0.0)):
    try:
        x, y = float(value[0]), float(value[1])
    except (TypeError, ValueError, IndexError, KeyError):
        return default
    return (x, y) if math.isfinite(x) and math.isfinite(y) else default


def direction(data: dict) -> tuple:
    a, b = _pt(data.get("p1")), _pt(data.get("p2"), (1.0, 0.0))
    dx, dy = b[0] - a[0], b[1] - a[1]
    n = math.hypot(dx, dy)
    return (1.0, 0.0) if n <= 1e-12 else (dx / n, dy / n)


def ends(kind: str, data: dict, offset=(0.0, 0.0), extent: float = EXTENT) -> tuple:
    """Extremites du segment de calcul (document + `offset`)."""
    a = _pt(data.get("p1"))
    a = (a[0] + offset[0], a[1] + offset[1])
    d = direction(data)
    start = a if kind == "cad_ray" else (a[0] - d[0] * extent, a[1] - d[1] * extent)
    return start, (a[0] + d[0] * extent, a[1] + d[1] * extent)


def prims(kind: str, data: dict, offset=(0.0, 0.0)) -> list:
    start, end = ends(kind, data, offset)
    return [("segment", start, end)]


def piece_entity(kind: str, data: dict, piece: list) -> tuple:
    """Morceau d'une ligne de construction AJUSTEE (primitives d'un segment) -> (type, champs) : les deux bouts au
    loin = la meme droite ; un bout au loin = une demi-droite (comme AutoCAD) ; sinon une ligne."""
    start, end = ends(kind, data)
    a, b = piece[0][1], piece[-1][2]
    far = 1e-6 * EXTENT

    def at(p, q):
        return math.hypot(p[0] - q[0], p[1] - q[1]) <= far
    a_far = kind == "cad_xline" and at(a, start)
    b_far = at(b, end)
    if a_far and b_far:
        return kind, {"p1": list(_pt(data.get("p1"))), "p2": list(_pt(data.get("p2")))}
    if b_far:
        d = direction(data)
        return "cad_ray", {"p1": [a[0], a[1]], "p2": [a[0] + d[0], a[1] + d[1]]}
    if a_far:
        d = direction(data)
        return "cad_ray", {"p1": [b[0], b[1]], "p2": [b[0] - d[0], b[1] - d[1]]}
    return "cad_line", {"p1": [a[0], a[1]], "p2": [b[0], b[1]]}


def clip(kind: str, data: dict, rect, offset=(0.0, 0.0)):
    """Morceau visible ((x0, y0), (x1, y1)) dans `rect` = (xmin, ymin, xmax, ymax) (document) ; None = hors du
    rectangle (Liang-Barsky sur la droite parametree depuis `p1`)."""
    a = _pt(data.get("p1"))
    ax, ay = a[0] + offset[0], a[1] + offset[1]
    dx, dy = direction(data)
    t0, t1 = (0.0 if kind == "cad_ray" else -math.inf), math.inf
    for p, q in ((-dx, ax - rect[0]), (dx, rect[2] - ax), (-dy, ay - rect[1]), (dy, rect[3] - ay)):
        if abs(p) <= 1e-15:
            if q < 0:
                return None
            continue
        t = q / p
        if p < 0:
            t0 = max(t0, t)
        else:
            t1 = min(t1, t)
        if t0 > t1:
            return None
    if not (math.isfinite(t0) and math.isfinite(t1)):
        return None
    return (ax + dx * t0, ay + dy * t0), (ax + dx * t1, ay + dy * t1)
