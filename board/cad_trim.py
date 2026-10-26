"""AJUSTER (TRIM) : geometrie PURE (aucun Qt), en coordonnees du DOCUMENT.

Une entite (ligne, arc, cercle, polyligne) est une suite de primitives parcourue par une distance curviligne `u` (0 a
`L`). Les ARETES DE COUPE la croisent en des points d'abscisses `t1 < t2 < …`. Un clic en `s` retire le morceau qui
contient `s`, entre l'intersection d'avant et celle d'apres (ou jusqu'au bout si une cote n'en a pas) ; ce qui reste
(zero, un ou deux morceaux) est rendu en primitives, que l'appelant retransforme en entites (`prims_to_entity`).
Un cercle ou une polyligne fermee demande deux intersections au moins ; il reste alors UN morceau (arc ou
polyligne ouverte) qui fait le tour par l'autre cote.

Comme AutoCAD : plusieurs points d'un meme objet (trajet, trace a main levee, capture) retirent chacun leur morceau en
UN calcul (`trim_points`) ; `extend_edges` = aretes PROLONGEES (EDGEMODE = 1 : segment -> droite, arc -> cercle) ;
`extend` = PROLONGER (Maj + clic) : l'extremite la plus proche du clic va jusqu'a la premiere limite rencontree."""
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


def crossings(prims, cutters, eps: float = 1e-7, extend_edges: bool = False) -> list:
    """Abscisses (distance curviligne sur l'entite) des intersections avec les primitives des aretes de coupe, triees,
    sans doublon. `extend_edges` : aretes prolongees (droites, cercles complets)."""
    box = cad_shapes.bounds(prims)
    found = []
    offset = 0.0
    for prim in prims:
        length = cad_shapes.prim_length(prim)
        pbox = cad_shapes.prim_bounds(prim)
        for cutter in cutters:
            cbox = cad_shapes.prim_bounds(cutter)
            if not extend_edges and (cbox[2] < pbox[0] - eps or cbox[0] > pbox[2] + eps or cbox[3] < pbox[1] - eps
                                     or cbox[1] > pbox[3] + eps):
                continue
            for point in cad_shapes.prim_intersections(prim, cutter, False, extend_edges):
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


# ==========================================================================
# Plusieurs points d'un meme objet (trajet, main levee, capture) ; mode Rapide
# ==========================================================================

def _merged(length: float, intervals) -> list:
    """Intervalles retires ramenes dans [0, L] (ceux qui passent par le depart coupes en deux), tries, fusionnes."""
    flat = []
    for lo, hi in intervals:
        if lo > hi:
            flat += [(lo, length), (0.0, hi)]
        else:
            flat.append((lo, hi))
    flat.sort()
    out = []
    for lo, hi in flat:
        if out and lo <= out[-1][1] + 1e-9:
            out[-1] = (out[-1][0], max(out[-1][1], hi))
        else:
            out.append((lo, hi))
    return out


def remaining_many(prims, closed: bool, intervals) -> list:
    """Morceaux gardes une fois TOUS les intervalles retires (contour ferme : le morceau qui passe par le depart
    reste d'un seul tenant)."""
    length = sum(cad_shapes.prim_length(p) for p in prims)
    eps = 1e-7
    gaps, start = [], 0.0
    for lo, hi in _merged(length, intervals):
        if lo > start + eps:
            gaps.append((start, lo))
        start = max(start, hi)
    if start < length - eps:
        gaps.append((start, length))
    pieces = [cad_shapes.sub_prims(prims, lo, hi) for lo, hi in gaps]
    if closed and len(gaps) >= 2 and gaps[0][0] <= eps and gaps[-1][1] >= length - eps:
        pieces = [pieces[-1] + pieces[0]] + pieces[1:-1]
    return [piece for piece in pieces if piece]


def removed_many(prims, intervals) -> list:
    """Primitives de tous les morceaux retires (apercu)."""
    length = sum(cad_shapes.prim_length(p) for p in prims)
    out = []
    for lo, hi in _merged(length, intervals):
        out += cad_shapes.sub_prims(prims, lo, hi)
    return out


def trim_points(kind: str, data: dict, cutters, points, quick: bool = False, extend_edges: bool = False,
                offset=(0.0, 0.0)):
    """Ajustage de l'entite en un ou plusieurs points (chacun retire son morceau). Rend un dict
    {"pieces", "removed", "prims"} ; ou {"delete": True, "prims"} en mode Rapide quand rien ne la coupe (comme
    AutoCAD : l'objet qu'on ne peut pas ajuster est EFFACE) ; ou un message."""
    prims = cad_shapes.prims(kind, data, offset)
    closed = is_closed(kind, data)
    length = sum(cad_shapes.prim_length(p) for p in prims)
    if length <= geo.EPS:
        return {"delete": True, "prims": prims} if quick else "Objet sans longueur."
    params = crossings(prims, cutters, extend_edges=extend_edges)
    intervals = []
    for point in points:
        interval = removed_interval(length, params, click_param(prims, point), closed)
        if isinstance(interval, str):
            return {"delete": True, "prims": prims} if quick else interval
        intervals.append(interval)
    return {"pieces": remaining_many(prims, closed, intervals), "removed": removed_many(prims, intervals),
            "prims": prims}


def path_hits(prims, path) -> list:
    """Points ou le trajet (liste de points, ouvert) croise l'entite, dans l'ordre du trajet."""
    hits = []
    for a, b in zip(path, path[1:]):
        if geo.distance(a, b) <= geo.EPS:
            continue
        seg = ("segment", tuple(a), tuple(b))
        found = []
        for prim in prims:
            found += cad_shapes.prim_intersections(seg, prim)
        found.sort(key=lambda x: geo.distance(a, x))
        hits += found
    return hits


def rect_hits(prims, start, end) -> list:
    """Capture (rectangle de `start` a `end`) : la ou l'objet croise le bord du rectangle, en le parcourant depuis le
    premier coin (comme AutoCAD) ; l'objet tout entier dedans : son point le plus proche du premier coin."""
    (x0, y0), (x1, y1) = start, end
    hits = path_hits(prims, [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)])
    if hits:
        return hits[:1]
    point = cad_shapes.closest(prims, start)[0]
    if min(x0, x1) - 1e-9 <= point[0] <= max(x0, x1) + 1e-9 and min(y0, y1) - 1e-9 <= point[1] <= max(y0, y1) + 1e-9:
        return [point]
    return []


# ==========================================================================
# PROLONGER (Maj + clic) : l'extremite la plus proche du clic jusqu'a la premiere limite
# ==========================================================================

def _extend_segment(prim, at_end: bool, boundaries, extend_edges: bool):
    a, b = prim[1], prim[2]
    n = geo.distance(a, b)
    if n <= geo.EPS:
        return None
    best = None
    for edge in boundaries:
        for x in cad_shapes.prim_intersections(prim, edge, True, extend_edges):
            t = geo.project_param(x, a, b)
            extra = (t - 1.0) * n if at_end else -t * n
            if extra > 1e-7 * max(1.0, n) and (best is None or extra < best[0]):
                best = (extra, (float(x[0]), float(x[1])))
    if best is None:
        return None
    return ("segment", a, best[1]) if at_end else ("segment", best[1], b)


def _extend_arc(prim, at_end: bool, boundaries, extend_edges: bool):
    c, r, a0, sweep = prim[1], prim[2], prim[3], prim[4]
    if r <= geo.EPS or abs(sweep) >= 360.0 - 1e-9:
        return None
    sign = 1.0 if sweep >= 0 else -1.0
    full = ("arc", c, r, 0.0, 360.0)
    best = None
    for edge in boundaries:
        for x in cad_shapes.prim_intersections(full, edge, False, extend_edges):
            theta = math.degrees(math.atan2(x[1] - c[1], x[0] - c[0]))
            extra = (((theta - (a0 + sweep)) if at_end else (a0 - theta)) * sign) % 360.0
            if 1e-7 < extra < 360.0 - abs(sweep) - 1e-7 and (best is None or extra < best):
                best = extra
    if best is None:
        return None
    if at_end:
        return ("arc", c, r, a0, sweep + sign * best)
    return ("arc", c, r, a0 - sign * best, sweep + sign * best)


def extend(kind: str, data: dict, boundaries, point, extend_edges: bool = False, offset=(0.0, 0.0)):
    """PROLONGER l'extremite de l'entite la plus proche de `point` jusqu'a la premiere limite rencontree :
    (type, champs geometriques) ou un message. Lignes, arcs, polylignes ouvertes (leur premier ou dernier segment)."""
    if kind not in ("cad_line", "cad_arc", "cad_pline") or is_closed(kind, data):
        return "On ne peut prolonger que des lignes, des arcs et des polylignes ouvertes."
    prims = cad_shapes.prims(kind, data, offset)
    length = sum(cad_shapes.prim_length(p) for p in prims)
    if not prims or length <= geo.EPS:
        return "Objet sans longueur."
    at_end = click_param(prims, point) > length / 2.0
    index = len(prims) - 1 if at_end else 0
    prim = prims[index]
    grown = (_extend_segment if prim[0] == "segment" else _extend_arc)(prim, at_end, boundaries, extend_edges)
    if grown is None:
        return "Aucune limite ne croise le prolongement de cet objet."
    prims = prims[:index] + [grown] + prims[index + 1:]
    if kind == "cad_pline" and len(prims) == 1:          # une polyligne d'un segment reste une polyligne
        bulge = cad_shapes.arc_bulge(grown[4]) if grown[0] == "arc" else 0.0
        start, end = cad_shapes.prim_start(grown), cad_shapes.prim_end(grown)
        return "cad_pline", {"vertices": [[start[0], start[1], bulge], [end[0], end[1], 0.0]], "closed": False}
    return cad_shapes.prims_to_entity(prims, False)
