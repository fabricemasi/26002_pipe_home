"""Points du CAD (`cad_point`, commande POINT, POINT des DXF / DWG) : geometrie PURE (aucun Qt), coordonnees du
DOCUMENT (Y vers le haut).

Un point = sa position `pos` et son ASPECT, comme les variables PDMODE / PDSIZE d'AutoCAD, COPIE sur chaque point
a sa creation (comme le style d'une cotation : changer le reglage ne touche pas les points existants) :
- `pdmode` : figure de base 0 = point (un trait de longueur nulle : un rond de l'epaisseur du trait), 1 = rien
  (invisible, mais choisi et accroche), 2 = croix +, 3 = croix x, 4 = trait vertical (vers le haut, demi-taille) ;
  + 32 = un cercle autour, + 64 = un carre autour (96 = les deux) ;
- `pdsize` : taille de la figure en unites du board (diametre du cercle, cote du carre, longueur des croix).

La figure est faite de PRIMITIVES ordinaires (traits et arcs : lots, GPU, choix au clic, fenetres) ; l'accrochage
ne voit que le point lui-meme (`snap_prims` : extremite / noeud), jamais les traits de la figure."""
from __future__ import annotations

import math

MM = 96.0 / 25.4
DEFAULTS = {"pdmode": 34, "pdsize": 3.0 * MM}           # cercle + croix de 3 mm (reglages : Module CAD > Points)
BASES = (0, 1, 2, 3, 4)
GEOMETRY_KEYS = ("pos",)


def _num(value, default=0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if math.isfinite(out) else default


def _pt(value):
    try:
        return float(value[0]), float(value[1])
    except (TypeError, ValueError, IndexError, KeyError):
        return 0.0, 0.0


def clean_mode(value) -> int:
    """PDMODE valide : base 0-4, plus 32 (cercle) et / ou 64 (carre) ; autre valeur : 0."""
    try:
        mode = int(value)
    except (TypeError, ValueError):
        return 0
    base, extra = mode % 32, mode - mode % 32
    if base not in BASES or extra not in (0, 32, 64, 96):
        return 0
    return mode


def style_of(data: dict) -> dict:
    return {"pdmode": clean_mode(data.get("pdmode", DEFAULTS["pdmode"])),
            "pdsize": max(0.0, _num(data.get("pdsize"), DEFAULTS["pdsize"]))}


def position(data: dict, offset=(0.0, 0.0)):
    p = _pt(data.get("pos"))
    return p[0] + offset[0], p[1] + offset[1]


def prims(data: dict, offset=(0.0, 0.0)) -> list:
    """Primitives de la figure (au moins une : le point lui-meme si la figure est vide)."""
    x, y = position(data, offset)
    style = style_of(data)
    mode, half = style["pdmode"], style["pdsize"] / 2.0
    base = mode % 32
    out = []
    if half > 0:
        if base == 2:
            out += [("segment", (x - half, y), (x + half, y)), ("segment", (x, y - half), (x, y + half))]
        elif base == 3:
            out += [("segment", (x - half, y - half), (x + half, y + half)),
                    ("segment", (x - half, y + half), (x + half, y - half))]
        elif base == 4:
            out.append(("segment", (x, y), (x, y + half)))
        if mode & 32:
            out.append(("arc", (x, y), half, 0.0, 360.0))
        if mode & 64:
            corners = [(x - half, y - half), (x + half, y - half), (x + half, y + half), (x - half, y + half)]
            out += [("segment", corners[i], corners[(i + 1) % 4]) for i in range(4)]
    if base == 0 or not out:
        out.insert(0, ("segment", (x, y), (x, y)))
    return out


def snap_prims(data: dict, offset=(0.0, 0.0)) -> list:
    p = position(data, offset)
    return [("segment", p, p)]


def translate(data: dict, delta) -> dict:
    x, y = position(data)
    return {"pos": [x + delta[0], y + delta[1]]}


def transform(data: dict, point_fn) -> dict:
    """Rotation, miroir, echelle : seule la position bouge (la figure reste droite et de sa taille, comme AutoCAD)."""
    return {"pos": list(point_fn(position(data)))}
