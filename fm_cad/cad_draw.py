"""Geometrie PURE (aucun Qt) des commandes ELLIPSE, POLYGONE, RESEAU, JOINDRE, COUPURE, ETIRER, DIVISER / MESURER
(`cad_commands_more`), en coordonnees du DOCUMENT (Y vers le haut, degres, sens trigonometrique).

- ELLIPSE : polyligne d'ARCS qui suit l'ellipse (comme AutoCAD avec PELLIPSE = 1) — l'entite garde tout ce que sait
  faire une polyligne (accrochages, AJUSTER, DECALER, poignees, export) ; ecart a la vraie ellipse < 1/2000 du grand
  axe ; sommets aux quadrants (accrochage « extremite » sur les axes).
- POLYGONE : polyligne fermee reguliere (inscrite, circonscrite, ou par un cote).
- RESEAU : copies (rectangulaire, polaire, le long d'un chemin) : decalages / rotations par copie.
- JOINDRE : objets mis BOUT A BOUT (lignes colineaires -> une ligne, arcs d'un meme cercle -> un arc, sinon une
  polyligne)."""
from __future__ import annotations

import math

from . import cad_geometry as geo
from . import cad_shapes

ELLIPSE_ARCS = 32                    # arcs d'une ellipse complete (multiple de 4 : sommets aux quadrants)


# ==========================================================================
# ELLIPSE
# ==========================================================================

def ellipse_point(center, major, ratio: float, t: float):
    """Point de parametre `t` (radians) : centre + major cos t + minor sin t (minor = major tourne de 90° x ratio)."""
    mx, my = major
    nx, ny = -my * ratio, mx * ratio
    c, s = math.cos(t), math.sin(t)
    return (center[0] + mx * c + nx * s, center[1] + my * c + ny * s)


def ellipse_param(center, major, ratio: float, point) -> float:
    """Parametre (radians, [0, 2 pi[) du point de l'ellipse dans la DIRECTION de `point` vu du centre."""
    a = math.hypot(*major)
    if a <= geo.EPS or ratio <= geo.EPS:
        return 0.0
    ux, uy = major[0] / a, major[1] / a
    dx, dy = point[0] - center[0], point[1] - center[1]
    x = dx * ux + dy * uy
    y = -dx * uy + dy * ux
    return math.atan2(y / ratio, x) % (2.0 * math.pi)


def ellipse_vertices(center, major, ratio: float, start: float = 0.0, end: float = 2.0 * math.pi) -> tuple[list, bool]:
    """(sommets [[x, y, renflement]], fermee) de la polyligne d'arcs : chaque arc passe par ses deux bouts ET le point
    de l'ellipse au parametre milieu (arc par trois points)."""
    full = abs((end - start) % (2.0 * math.pi)) <= 1e-12 or abs(end - start) >= 2.0 * math.pi - 1e-12
    span = 2.0 * math.pi if full else (end - start) % (2.0 * math.pi)
    count = ELLIPSE_ARCS if full else max(2, math.ceil(ELLIPSE_ARCS * span / (2.0 * math.pi)))
    params = [start + span * k / count for k in range(count + 1)]
    vertices = []
    for t0, t1 in zip(params, params[1:]):
        a, m, b = (ellipse_point(center, major, ratio, t) for t in (t0, (t0 + t1) / 2.0, t1))
        found = cad_shapes.arc_from_3_points(a, m, b)
        bulge = 0.0 if found is None else cad_shapes.arc_bulge(found[3])
        vertices.append([a[0], a[1], bulge])
    if not full:
        end_point = ellipse_point(center, major, ratio, params[-1])
        vertices.append([end_point[0], end_point[1], 0.0])
    return vertices, full


# ==========================================================================
# POLYGONE
# ==========================================================================

def polygon_vertices(center, sides: int, radius_point, inscribed: bool = True) -> list:
    """Sommets d'un polygone regulier : `radius_point` donne le rayon ET l'orientation (inscrit : un sommet y est ;
    circonscrit : le milieu d'un cote y est)."""
    r = geo.distance(center, radius_point)
    a0 = geo.angle_deg(center, radius_point)
    step = 360.0 / sides
    if not inscribed:
        r = r / math.cos(math.radians(step / 2.0))
        a0 += step / 2.0
    return [[*cad_shapes.arc_point(center, r, a0 + k * step), 0.0] for k in range(sides)]


def polygon_from_edge(p1, p2, sides: int) -> list:
    """Sommets d'un polygone regulier dont le premier cote va de p1 a p2 (le polygone a gauche du cote)."""
    out = [[p1[0], p1[1], 0.0]]
    direction = geo.angle_deg(p1, p2)
    length = geo.distance(p1, p2)
    current = p2
    for k in range(1, sides):
        out.append([current[0], current[1], 0.0])
        direction += 360.0 / sides
        current = cad_shapes.arc_point(current, length, direction)
    return out


# ==========================================================================
# RESEAU (copies)
# ==========================================================================

def rect_offsets(columns: int, rows: int, dx: float, dy: float, angle: float = 0.0) -> list:
    """Decalages (document) de chaque copie d'un reseau rectangulaire, l'original (0, 0) exclu ; `angle` = rotation
    des axes du reseau."""
    c, s = math.cos(math.radians(angle)), math.sin(math.radians(angle))
    out = []
    for row in range(rows):
        for col in range(columns):
            if row == 0 and col == 0:
                continue
            x, y = col * dx, row * dy
            out.append((x * c - y * s, x * s + y * c))
    return out


def polar_steps(count: int, fill: float) -> list:
    """Angles (degres) de chaque copie d'un reseau polaire de `count` elements (original compris) sur `fill`
    degres ; 360 : repartis sur le tour (le dernier ne retombe pas sur le premier)."""
    if count < 2:
        return []
    step = fill / count if abs(abs(fill) - 360.0) <= 1e-9 else fill / (count - 1)
    return [step * k for k in range(1, count)]


def path_stations(primitives, count: int, spacing: float | None = None) -> list:
    """(point, direction en degres) de `count` copies le long d'un chemin : reparties de bout en bout (`spacing`
    None), sinon tous les `spacing` depuis le debut. La premiere est au debut du chemin."""
    total = cad_shapes.total_length(primitives)
    if total <= geo.EPS or count < 1:
        return []
    if spacing is None:
        params = [total * k / (count - 1) for k in range(count)] if count > 1 else [0.0]
    else:
        params = [k * spacing for k in range(count) if k * spacing <= total + geo.EPS]
    return [station(primitives, s) for s in params]


def station(primitives, s: float):
    """(point, direction en degres) a la distance curviligne `s` du debut."""
    pos = 0.0
    for p in primitives:
        n = cad_shapes.prim_length(p)
        if s <= pos + n + geo.EPS or p is primitives[-1]:
            local = max(0.0, min(n, s - pos))
            t = cad_shapes.prim_tangent(p, local)
            return cad_shapes.prim_point(p, local), math.degrees(math.atan2(t[1], t[0]))
        pos += n
    return cad_shapes.prim_start(primitives[0]), 0.0


# ==========================================================================
# JOINDRE
# ==========================================================================

def _same(a, b, tol: float) -> bool:
    return geo.distance(a, b) <= tol


def chain(pieces, tol: float) -> list:
    """Morceaux [(primitives, cle)] mis bout a bout (retournes s'il le faut) : [[(primitives, cle), ...], ...] ; chaque
    chaine part du morceau le plus ancien et grandit par ses deux bouts."""
    left = list(pieces)
    chains = []
    while left:
        current = [left.pop(0)]
        grown = True
        while grown:
            grown = False
            head = cad_shapes.prim_start(current[0][0][0])
            tail = cad_shapes.prim_end(current[-1][0][-1])
            for index, (prims, key) in enumerate(left):
                start, end = cad_shapes.prim_start(prims[0]), cad_shapes.prim_end(prims[-1])
                if _same(tail, start, tol):
                    current.append((prims, key))
                elif _same(tail, end, tol):
                    current.append((reverse(prims), key))
                elif _same(head, end, tol):
                    current.insert(0, (prims, key))
                elif _same(head, start, tol):
                    current.insert(0, (reverse(prims), key))
                else:
                    continue
                del left[index]
                grown = True
                break
        chains.append(current)
    return chains


def reverse(primitives) -> list:
    return [cad_shapes.reversed_prim(p) for p in reversed(primitives)]


def merge_prims(primitives, tol: float) -> list:
    """Primitives qui se suivent fondues : segments colineaires de meme sens -> un segment ; arcs d'un meme cercle
    et de meme sens -> un arc."""
    out = []
    for p in primitives:
        if out:
            q = out[-1]
            if p[0] == q[0] == "segment":
                d1 = geo.sub(q[2], q[1])
                d2 = geo.sub(p[2], p[1])
                n1, n2 = math.hypot(*d1), math.hypot(*d2)
                if n1 > geo.EPS and n2 > geo.EPS and abs(geo.cross(d1, d2)) <= tol * max(n1, n2) \
                        and d1[0] * d2[0] + d1[1] * d2[1] > 0:
                    out[-1] = ("segment", q[1], p[2])
                    continue
            if p[0] == q[0] == "arc" and _same(p[1], q[1], tol) and abs(p[2] - q[2]) <= tol \
                    and (p[4] > 0) == (q[4] > 0):
                out[-1] = ("arc", q[1], q[2], q[3], q[4] + p[4])
                continue
        out.append(p)
    return out


def joined(chain_pieces, tol: float):
    """(type, champs geometriques) de l'entite qui remplace une chaine de morceaux (ligne, arc, cercle, polyligne)."""
    primitives = merge_prims([p for prims, _key in chain_pieces for p in prims], tol)
    closed = len(primitives) > 1 and _same(cad_shapes.prim_start(primitives[0]),
                                           cad_shapes.prim_end(primitives[-1]), tol)
    if len(primitives) == 1 and primitives[0][0] == "arc" and abs(primitives[0][4]) >= 360.0 - 1e-6:
        p = primitives[0]
        return "cad_circle", {"center": list(p[1]), "radius": p[2]}
    if closed and len(primitives) > 1:
        first, last = primitives[0], primitives[-1]
        if first[0] == last[0] == "arc" and _same(first[1], last[1], tol) and abs(first[2] - last[2]) <= tol \
                and abs(abs(sum(p[4] for p in primitives if p[0] == "arc")) - 360.0) <= 1e-6 \
                and all(p[0] == "arc" for p in primitives):
            return "cad_circle", {"center": list(first[1]), "radius": first[2]}
    return cad_shapes.prims_to_entity(primitives, closed)


# ==========================================================================
# AIRE (aire et perimetre), NUAGE DE REVISION, ALLONGER
# ==========================================================================

def prims_area(primitives) -> float:
    """Aire SIGNEE d'un contour ferme fait de primitives (formule de Green ; arcs exacts)."""
    total = 0.0
    for p in primitives:
        if p[0] == "segment":
            (x0, y0), (x1, y1) = p[1], p[2]
            total += x0 * y1 - x1 * y0
        else:
            (cx, cy), r, a0, sweep = p[1], p[2], p[3], p[4]
            t0, t1 = math.radians(a0), math.radians(a0 + sweep)
            total += r * (cx * (math.sin(t1) - math.sin(t0)) - cy * (math.cos(t1) - math.cos(t0))) \
                + r * r * (t1 - t0)
    return total / 2.0


def polygon_area(points) -> float:
    total = 0.0
    for i in range(len(points)):
        (x0, y0), (x1, y1) = points[i], points[(i + 1) % len(points)]
        total += x0 * y1 - x1 * y0
    return total / 2.0


def revcloud_vertices(outline, arc_length: float, bulge: float = 0.6) -> list:
    """Sommets d'un NUAGE DE REVISION le long du contour ferme `outline` (points) : des arcs d'environ `arc_length`,
    bombes VERS L'EXTERIEUR (renflement de signe oppose au sens du contour)."""
    pts = [tuple(p) for p in outline]
    if len(pts) > 1 and geo.distance(pts[0], pts[-1]) <= geo.EPS:
        pts.pop()
    if len(pts) < 3 or arc_length <= geo.EPS:
        return []
    sign = 1.0 if polygon_area(pts) > 0 else -1.0             # contour trigonometrique : exterieur a droite (+)
    out = []
    for i in range(len(pts)):
        a, b = pts[i], pts[(i + 1) % len(pts)]
        length = geo.distance(a, b)
        count = max(1, round(length / arc_length))
        for k in range(count):
            p = geo.lerp(a, b, k / count)
            out.append([p[0], p[1], sign * bulge])
    return out


def lengthened(kind: str, data: dict, pick, mode: str, amount: float):
    """Champs geometriques d'une ligne / d'un arc / d'une polyligne ouverte ALLONGE(E) du cote du bout le plus proche
    de `pick` : `mode` = "delta" (de `amount`, negatif = raccourcir ; arc : longueur), "total" (longueur totale),
    "percent" (`amount` % de la longueur) ; message si impossible."""
    if kind == "cad_line":
        a, b = cad_shapes._pt(data.get("p1")), cad_shapes._pt(data.get("p2"))
        length = geo.distance(a, b)
        new = _new_length(length, mode, amount)
        if isinstance(new, str):
            return new
        at_end = geo.distance(pick, b) <= geo.distance(pick, a)
        fixed, moving = (a, b) if at_end else (b, a)
        d = geo.normalize(geo.sub(moving, fixed))
        moved = geo.add(fixed, geo.mul(d, new))
        return {"p1": list(fixed if at_end else moved), "p2": list(moved if at_end else fixed)}
    if kind == "cad_arc":
        prim = cad_shapes.prims(kind, data)[0]
        c, r, a0, sweep = prim[1], prim[2], prim[3], prim[4]
        new = _new_length(abs(math.radians(sweep)) * r, mode, amount)
        if isinstance(new, str):
            return new
        new_sweep = math.degrees(new / r)
        if new_sweep >= 360.0 - 1e-9:
            return "Un arc ne peut pas faire le tour entier."
        start, end = cad_shapes.prim_start(prim), cad_shapes.prim_end(prim)
        if geo.distance(pick, end) <= geo.distance(pick, start):
            return cad_shapes.arc_data(c, r, a0, new_sweep)
        return cad_shapes.arc_data(c, r, a0 + sweep - new_sweep, new_sweep)
    if kind == "cad_pline" and not data.get("closed"):
        verts = [list(map(float, v[:3])) + [0.0] * (3 - len(v[:3])) for v in data.get("vertices") or []]
        if len(verts) < 2:
            return "Polyligne trop courte."
        at_end = geo.distance(pick, verts[-1][:2]) <= geo.distance(pick, verts[0][:2])
        i, j = (len(verts) - 2, len(verts) - 1) if at_end else (1, 0)
        seg_bulge = verts[len(verts) - 2][2] if at_end else verts[0][2]
        if abs(seg_bulge) > 1e-12:
            return "Le segment d'extrémité est courbe : seuls les segments droits s'allongent."
        total = cad_shapes.total_length(cad_shapes.prims(kind, data))
        new_total = _new_length(total, mode, amount)
        if isinstance(new_total, str):
            return new_total
        fixed, moving = verts[i][:2], verts[j][:2]
        seg = geo.distance(fixed, moving)
        new_seg = seg + (new_total - total)
        if new_seg <= geo.EPS:
            return "Le segment d'extrémité deviendrait nul."
        d = geo.normalize(geo.sub(moving, fixed))
        moved = geo.add(fixed, geo.mul(d, new_seg))
        verts[j][0], verts[j][1] = moved
        return {"vertices": verts}
    return "Lignes, arcs et polylignes ouvertes seulement."


def _new_length(length: float, mode: str, amount: float):
    new = length + amount if mode == "delta" else amount if mode == "total" else length * amount / 100.0
    if new <= geo.EPS:
        return "La longueur deviendrait nulle ou négative."
    return new
