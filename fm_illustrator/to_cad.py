"""Conversion des tracés Illustrator en entités du module CAD (SANS Qt) : « Convertir en tracés CAD » (menu Objet).

Chaque sous-tracé devient une polyligne CAD (`cad_pline` : sommets [[x, y, renflement]], `closed`) : les segments
droits restent droits, chaque courbe de Bézier est approchée par des ARCS (un arc par 3 points de la courbe, coupé
en deux tant que l'écart dépasse la tolérance), comme la commande SPLINE du CAD. Résultat : ce qu'AutoCAD lit
(LWPOLYLINE à renflements à l'export DXF), avec accrochages et poignées du CAD.

Repères : Illustrator = scène (Y vers le bas) ; CAD = document (Y vers le haut, `cad_items.doc_offset`). Les points
sont retournés AVANT l'ajustement des arcs (le signe du renflement suit le sens réel)."""
from __future__ import annotations

import math

from fm_cad import cad_shapes

from . import bezier as bz

TOLERANCE = 0.05            # écart maximal arc / courbe (unités du board)
MAX_DEPTH = 12              # découpes d'une courbe au plus (au-delà : segments droits)
MAX_SWEEP = 120.0           # ouverture maximale d'un arc (degrés) : au-delà, la courbe est coupée


def _doc(p) -> tuple[float, float]:
    return float(p[0]), -float(p[1])


def _dist_line(p, a, b) -> float:
    """Distance de `p` à la droite (a, b) (à `a` si a == b)."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy)
    if length <= 1e-12:
        return math.hypot(p[0] - a[0], p[1] - a[1])
    return abs((p[0] - a[0]) * dy - (p[1] - a[1]) * dx) / length


def _fit(p0, c1, c2, p3, tol: float, depth: int, out: list):
    """Ajoute à `out` les morceaux (départ, renflement) qui suivent la cubique p0 -> p3 (repère du document)."""
    if math.hypot(p3[0] - p0[0], p3[1] - p0[1]) <= 1e-9 and math.hypot(c1[0] - p0[0], c1[1] - p0[1]) <= 1e-9 \
            and math.hypot(c2[0] - p0[0], c2[1] - p0[1]) <= 1e-9:
        return                                                  # segment nul (nœud doublé)
    if _dist_line(c1, p0, p3) <= tol and _dist_line(c2, p0, p3) <= tol and \
            math.hypot(p3[0] - p0[0], p3[1] - p0[1]) > 1e-9:
        out.append((p0, 0.0))                                   # quasi droit
        return
    if depth < MAX_DEPTH:
        arc = cad_shapes.arc_from_3_points(p0, bz.cubic_at(p0, c1, c2, p3, 0.5), p3)
        if arc is not None and abs(arc[3]) <= MAX_SWEEP:
            center, radius = arc[0], arc[1]
            if all(abs(math.hypot(q[0] - center[0], q[1] - center[1]) - radius) <= tol
                   for q in (bz.cubic_at(p0, c1, c2, p3, t) for t in (0.25, 0.75))):
                out.append((p0, cad_shapes.arc_bulge(arc[3])))
                return
        left, right = bz.split_cubic(p0, c1, c2, p3, 0.5)
        _fit(*left, tol, depth + 1, out)
        _fit(*right, tol, depth + 1, out)
        return
    out.append((p0, 0.0))                                       # trop découpé : segment droit


def subpath_to_pline(sub: dict, tolerance: float = TOLERANCE) -> dict | None:
    """Sous-tracé (coordonnées de la SCÈNE) -> géométrie d'une `cad_pline` {"vertices", "closed"} ; None si vide."""
    if len(sub.get("nodes") or []) < 2:
        return None
    closed = bool(sub.get("closed"))
    pieces: list = []
    for seg in bz.segments(sub):
        p0, c1, c2, p3 = (_doc(p) for p in seg)
        _fit(p0, c1, c2, p3, tolerance, 0, pieces)
    if not pieces:
        return None
    vertices = [[p[0], p[1], b] for p, b in pieces]
    if not closed:
        end = _doc(sub["nodes"][-1][:2])
        vertices.append([end[0], end[1], 0.0])
    if len(vertices) < 2:
        return None
    return {"vertices": vertices, "closed": closed}


def cad_color(data: dict) -> str | None:
    """Couleur de l'entité CAD : celle du fond, sinon du contour (« #rrggbb ») ; None = suivre le calque."""
    for key in ("fill", "stroke"):
        value = data.get(key)
        if isinstance(value, str) and len(value) == 7 and value.startswith("#"):
            return value.lower()
    return None


def plines(subpaths, tolerance: float = TOLERANCE) -> list[dict]:
    """Toutes les polylignes CAD d'un tracé (sous-tracés en coordonnées de la scène)."""
    return [g for g in (subpath_to_pline(s, tolerance) for s in subpaths) if g is not None]
