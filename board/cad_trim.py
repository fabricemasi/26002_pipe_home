"""AJUSTER (TRIM) : geometrie PURE (aucun Qt), en coordonnees du DOCUMENT.

Une entite (ligne, arc, cercle, polyligne) est une suite de primitives parcourue par une distance curviligne `u` (0 a
`L`). Les ARETES DE COUPE la croisent en des points d'abscisses `t1 < t2 < …`. Un clic en `s` retire le morceau qui
contient `s`, entre l'intersection d'avant et celle d'apres (ou jusqu'au bout si une cote n'en a pas) ; ce qui reste
(zero, un ou deux morceaux) est rendu en primitives, que l'appelant retransforme en entites (`prims_to_entity`).
Un cercle ou une polyligne fermee demande deux intersections au moins ; il reste alors UN morceau (arc ou
polyligne ouverte) qui fait le tour par l'autre cote."""
from __future__ import annotations

import math

from . import cad_geometry as geo
from . import cad_shapes

CLOSED_KINDS = ("cad_circle",)


def is_closed(kind: str, data: dict) -> bool:
    return kind == "cad_circle" or (kind == "cad_pline" and bool(data.get("closed"))
                                    and len(data.get("vertices") or []) > 2)


def _param(prim, point) -> float:
    """Distance curviligne du point (de la primitive) a partir de son debut."""
    if prim[0] == "segment":
        return geo.distance(prim[1], point)
    theta = math.degrees(math.atan2(point[1] - prim[1][1], point[0] - prim[1][0]))
    return cad_shapes.arc_param_of_angle(prim, theta)


def crossings(prims, cutters, eps: float = 1e-7) -> list:
    """Abscisses (distance curviligne sur l'entite) des intersections avec les primitives des aretes de coupe, triees,
    sans doublon."""
    box = cad_shapes.bounds(prims)
    found = []
    offset = 0.0
    for prim in prims:
        length = cad_shapes.prim_length(prim)
        pbox = cad_shapes.prim_bounds(prim)
        for cutter in cutters:
            cbox = cad_shapes.prim_bounds(cutter)
            if (cbox[2] < pbox[0] - eps or cbox[0] > pbox[2] + eps or cbox[3] < pbox[1] - eps
                    or cbox[1] > pbox[3] + eps):
                continue
            for point in cad_shapes.prim_intersections(prim, cutter):
                found.append(offset + min(length, max(0.0, _param(prim, point))))
        offset += length
    found.sort()
    out = []
    for t in found:
        if not out or t - out[-1] > eps * 10 + 1e-9:
            out.append(t)
    del box
    return out


def click_param(prims, point) -> float:
    """Abscisse du point de l'entite le plus proche du clic."""
    _q, _d, index, local = cad_shapes.closest(prims, point)
    return sum(cad_shapes.prim_length(p) for p in prims[:index]) + local


def removed_interval(length: float, params: list, s: float, closed: bool):
    """(debut, fin) du morceau retire autour de `s` — fin < debut = il passe par le point de depart d'un contour ferme —
    ou un message."""
    eps = 1e-7
    if not params:
        return "Aucune arête de coupe ne croise cet objet."
    before = [t for t in params if t < s - eps]
    after = [t for t in params if t > s + eps]
    if not closed:
        return (before[-1] if before else 0.0, after[0] if after else length)
    if len(params) < 2:
        return "Un contour fermé doit être croisé au moins deux fois pour être ajusté."
    return (before[-1] if before else params[-1], after[0] if after else params[0])


def remaining(prims, closed: bool, interval) -> list:
    """Morceaux gardes [[primitives…], …] une fois l'intervalle `interval` retire."""
    length = sum(cad_shapes.prim_length(p) for p in prims)
    lo, hi = interval
    eps = 1e-7
    if not closed:
        out = []
        if lo > eps:
            out.append(cad_shapes.sub_prims(prims, 0.0, lo))
        if hi < length - eps:
            out.append(cad_shapes.sub_prims(prims, hi, length))
        return [piece for piece in out if piece]
    if lo > hi:                                         # le morceau retire passe par le depart : reste [hi, lo]
        piece = cad_shapes.sub_prims(prims, hi, lo)
    else:                                               # reste [hi, L] puis [0, lo]
        piece = cad_shapes.sub_prims(prims, hi, length) + cad_shapes.sub_prims(prims, 0.0, lo)
    return [piece] if piece else []


def trim(kind: str, data: dict, cutters, point, offset=(0.0, 0.0)):
    """Resultat de l'ajustage de l'entite au clic `point` : (intervalle retire, [morceaux]) ou un message."""
    prims = cad_shapes.prims(kind, data, offset)
    closed = is_closed(kind, data)
    length = sum(cad_shapes.prim_length(p) for p in prims)
    if length <= geo.EPS:
        return "Objet sans longueur."
    params = crossings(prims, cutters)
    interval = removed_interval(length, params, click_param(prims, point), closed)
    if isinstance(interval, str):
        return interval
    return interval, remaining(prims, closed, interval), prims


def removed_prims(prims, closed: bool, interval) -> list:
    """Primitives du morceau retire (apercu au survol)."""
    length = sum(cad_shapes.prim_length(p) for p in prims)
    lo, hi = interval
    if closed and lo > hi:
        return cad_shapes.sub_prims(prims, lo, length) + cad_shapes.sub_prims(prims, 0.0, hi)
    return cad_shapes.sub_prims(prims, lo, hi)
