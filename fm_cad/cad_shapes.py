"""Module CAD du board : geometrie PURE des entites (aucun Qt), en coordonnees du DOCUMENT (Y vers le haut, angles
en degres, sens trigonometrique, 0 = est — voir cad_geometry).

Chaque entite se ramene a une liste de PRIMITIVES, la seule chose que voient l'accrochage, la selection, le rendu,
l'apercu et les outils (decaler, chanfrein, raccord) :
- `("segment", a, b)` : segment de a a b ;
- `("arc", c, r, a0, sweep)` : arc de centre c, rayon r, partant de l'angle a0 et parcourant `sweep` degres (> 0 :
  sens trigonometrique, < 0 : sens horaire ; |sweep| = 360 : cercle complet).

Types d'entites (`CAD_TYPES`) et leurs champs geometriques :
- `cad_line`   : p1, p2 ;
- `cad_arc`    : center, radius, start, end (degres ; l'arc va de start a end dans le sens trigonometrique, comme
  le DXF) ;
- `cad_circle` : center, radius ;
- `cad_pline`  : vertices [[x, y, bulge], ...], closed (bulge du sommet i = segment i -> i+1 : 0 = droit,
  tan(angle / 4) sinon, > 0 sens trigonometrique — convention LWPOLYLINE du DXF).

Parametre le long d'une entite = distance curviligne depuis son debut (motifs des types de ligne, apercus)."""
from __future__ import annotations

import math

from . import cad_dims, cad_hatch, cad_text
from . import cad_geometry as geo

CAD_TYPES = ("cad_line", "cad_arc", "cad_circle", "cad_pline", "cad_dim", "cad_hatch", "cad_text")
GEOMETRY_KEYS = {"cad_line": ("p1", "p2"), "cad_arc": ("center", "radius", "start", "end"),
                 "cad_circle": ("center", "radius"), "cad_pline": ("vertices", "closed"),
                 "cad_dim": cad_dims.GEOMETRY_KEYS, "cad_hatch": cad_hatch.GEOMETRY_KEYS,
                 "cad_text": cad_text.GEOMETRY_KEYS}
MAX_TESS = 2048                     # segments au plus par arc tessele
ARC_EPS = 1e-9


# ==========================================================================
# Primitives
# ==========================================================================

def _pt(value, default=(0.0, 0.0)):
    try:
        return float(value[0]), float(value[1])
    except (TypeError, ValueError, IndexError):
        return default


def _num(value, default=0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if math.isfinite(out) else default


def arc_sweep(start: float, end: float) -> float:
    """Ouverture (degres, ]0, 360]) d'un arc qui va de `start` a `end` dans le sens trigonometrique."""
    sweep = (end - start) % 360.0
    return 360.0 if sweep <= 1e-12 else sweep


def bulge_arc(a, b, bulge: float):
    """Segment courbe d'une polyligne (a -> b, renflement `bulge`) -> primitive arc (ou segment si droit)."""
    if abs(bulge) <= 1e-12 or geo.distance(a, b) <= geo.EPS:
        return ("segment", a, b)
    theta = 4.0 * math.atan(bulge)                       # angle au centre, signe
    chord = geo.distance(a, b)
    r = chord / (2.0 * math.sin(abs(theta) / 2.0))
    mid = geo.midpoint(a, b)
    d = geo.normalize(geo.sub(b, a))
    left = (-d[1], d[0])                                 # a gauche de a -> b
    # Distance signee du centre a la corde : negative au-dela d'un demi-tour (centre de l'autre cote).
    offset = r * math.cos(abs(theta) / 2.0)
    side = 1.0 if bulge > 0 else -1.0
    c = geo.add(mid, geo.mul(left, side * offset))
    a0 = math.degrees(math.atan2(a[1] - c[1], a[0] - c[0]))
    return ("arc", c, r, a0, math.degrees(theta))


def arc_bulge(sweep: float) -> float:
    """Renflement d'un segment courbe d'ouverture `sweep` (degres, signe)."""
    return math.tan(math.radians(sweep) / 4.0)


def prims(kind: str, data: dict, offset=(0.0, 0.0)) -> list:
    """Primitives d'une entite (offset = place Qt de l'element, en document)."""
    ox, oy = offset
    if kind == "cad_line":
        a, b = _pt(data.get("p1")), _pt(data.get("p2"))
        return [("segment", (a[0] + ox, a[1] + oy), (b[0] + ox, b[1] + oy))]
    if kind in ("cad_arc", "cad_circle"):
        c = _pt(data.get("center"))
        c = (c[0] + ox, c[1] + oy)
        r = max(0.0, _num(data.get("radius")))
        if kind == "cad_circle":
            return [("arc", c, r, 0.0, 360.0)]
        start = _num(data.get("start"))
        return [("arc", c, r, start, arc_sweep(start, _num(data.get("end"), start + 90.0)))]
    if kind == "cad_hatch":
        return cad_hatch.prims(data, offset)
    if kind == "cad_text":                              # le cadre du texte (choix, fenetres, apercus)
        corners = cad_text.layout(data, offset)["corners"]
        return [("segment", a, b) for a, b in cad_text.box_segments(corners)]
    if kind == "cad_dim":
        found = cad_dims.geometry(data, offset)["prims"]
        if not found:
            a = _pt(data.get("p1"))
            found = [("segment", (a[0] + ox, a[1] + oy), (a[0] + ox, a[1] + oy))]
        return found
    if kind == "cad_pline":
        verts = [(_num(v[0]) + ox, _num(v[1]) + oy, _num(v[2]) if len(v) > 2 else 0.0)
                 for v in (data.get("vertices") or []) if isinstance(v, (list, tuple)) and len(v) >= 2]
        out = []
        count = len(verts)
        closed = bool(data.get("closed")) and count > 2
        for i in range(count if closed else count - 1):
            a, b = verts[i], verts[(i + 1) % count]
            p, q = (a[0], a[1]), (b[0], b[1])
            if geo.distance(p, q) <= geo.EPS:
                continue
            out.append(bulge_arc(p, q, a[2]))
        if not out and verts:
            out.append(("segment", (verts[0][0], verts[0][1]), (verts[0][0], verts[0][1])))
        return out
    return []


def arc_point(c, r, angle_deg):
    rad = math.radians(angle_deg)
    return c[0] + r * math.cos(rad), c[1] + r * math.sin(rad)


def prim_start(p):
    return p[1] if p[0] == "segment" else arc_point(p[1], p[2], p[3])


def prim_end(p):
    return p[2] if p[0] == "segment" else arc_point(p[1], p[2], p[3] + p[4])


def prim_length(p) -> float:
    if p[0] == "segment":
        return geo.distance(p[1], p[2])
    return abs(math.radians(p[4])) * p[2]


def total_length(primitives) -> float:
    return sum(prim_length(p) for p in primitives)


def prim_point(p, s: float):
    """Point a la distance curviligne `s` du debut de la primitive."""
    if p[0] == "segment":
        n = prim_length(p)
        return geo.lerp(p[1], p[2], s / n) if n > geo.EPS else p[1]
    c, r, a0, sweep = p[1], p[2], p[3], p[4]
    if r <= geo.EPS:
        return c
    return arc_point(c, r, a0 + math.copysign(math.degrees(s / r), sweep))


def prim_mid(p):
    return prim_point(p, prim_length(p) / 2.0)


def prim_tangent(p, s: float):
    """Direction unitaire (sens de parcours) a la distance `s`."""
    if p[0] == "segment":
        return geo.normalize(geo.sub(p[2], p[1]))
    c, r, a0, sweep = p[1], p[2], p[3], p[4]
    ang = math.radians(a0 + math.copysign(math.degrees(s / r) if r > geo.EPS else 0.0, sweep))
    sign = 1.0 if sweep >= 0 else -1.0
    return -math.sin(ang) * sign, math.cos(ang) * sign


def sub_prim(p, s0: float, s1: float):
    """Partie de la primitive entre les distances curvilignes s0 < s1."""
    if p[0] == "segment":
        return ("segment", prim_point(p, s0), prim_point(p, s1))
    c, r, a0, sweep = p[1], p[2], p[3], p[4]
    sign = 1.0 if sweep >= 0 else -1.0
    k = math.degrees(1.0 / r) if r > geo.EPS else 0.0
    return ("arc", c, r, a0 + sign * s0 * k, sign * (s1 - s0) * k)


def sub_prims(primitives, u0: float, u1: float) -> list:
    """Morceaux des primitives entre les distances curvilignes u0 < u1 (sur l'entite entiere)."""
    out = []
    pos = 0.0
    for p in primitives:
        n = prim_length(p)
        lo, hi = max(u0, pos), min(u1, pos + n)
        if hi > lo + geo.EPS or (n <= geo.EPS and u0 <= pos <= u1):
            out.append(sub_prim(p, lo - pos, hi - pos))
        pos += n
        if pos >= u1:
            break
    return out


def reversed_prim(p):
    if p[0] == "segment":
        return ("segment", p[2], p[1])
    return ("arc", p[1], p[2], p[3] + p[4], -p[4])


def angle_in_arc(theta: float, a0: float, sweep: float, tol: float = 1e-7) -> bool:
    if abs(sweep) >= 360.0 - 1e-9:
        return True
    if sweep >= 0:
        return (theta - a0) % 360.0 <= sweep + tol or (theta - a0) % 360.0 >= 360.0 - tol
    return (a0 - theta) % 360.0 <= -sweep + tol or (a0 - theta) % 360.0 >= 360.0 - tol


def arc_param_of_angle(p, theta: float) -> float:
    """Distance curviligne du point d'angle `theta` sur l'arc (dans le sens de parcours)."""
    a0, sweep, r = p[3], p[4], p[2]
    d = (theta - a0) % 360.0 if sweep >= 0 else (a0 - theta) % 360.0
    return math.radians(d) * r


# ==========================================================================
# Tessellation, emprise, distance
# ==========================================================================

def arc_steps(r: float, sweep: float, tol: float) -> int:
    if r <= geo.EPS:
        return 1
    tol = max(tol, r * 1e-9)
    step = 2.0 * math.acos(max(-1.0, min(1.0, 1.0 - tol / r)))
    if step <= 1e-12:
        return MAX_TESS
    return max(1, min(MAX_TESS, math.ceil(abs(math.radians(sweep)) / step)))


def tessellate_prim(p, tol: float) -> list:
    """Points de la primitive (debut et fin compris) ; un arc est approche a `tol` pres (fleche)."""
    if p[0] == "segment":
        return [p[1], p[2]]
    c, r, a0, sweep = p[1], p[2], p[3], p[4]
    n = arc_steps(r, sweep, tol)
    return [arc_point(c, r, a0 + sweep * k / n) for k in range(n + 1)]


def tessellate(primitives, tol: float) -> list:
    """Polylignes (listes de points) : les primitives qui se suivent sont mises bout a bout."""
    out = []
    current = None
    for p in primitives:
        pts = tessellate_prim(p, tol)
        if current is not None and geo.distance(current[-1], pts[0]) <= geo.EPS * 10:
            current.extend(pts[1:])
        else:
            current = list(pts)
            out.append(current)
    return out


def display_segments(primitives, tol: float) -> list:
    """Segments [(a, b)] pour l'apercu (fantomes, survol, selection)."""
    out = []
    for pts in tessellate(primitives, tol):
        out.extend((pts[i], pts[i + 1]) for i in range(len(pts) - 1))
    return out


def prim_bounds(p) -> tuple:
    if p[0] == "segment":
        return geo.normalized_rect(p[1], p[2])
    c, r, a0, sweep = p[1], p[2], p[3], p[4]
    pts = [prim_start(p), prim_end(p)]
    for q in (0.0, 90.0, 180.0, 270.0):
        if angle_in_arc(q, a0, sweep):
            pts.append(arc_point(c, r, q))
    xs, ys = [x for x, _y in pts], [y for _x, y in pts]
    return min(xs), min(ys), max(xs), max(ys)


def bounds(primitives) -> tuple:
    boxes = [prim_bounds(p) for p in primitives]
    if not boxes:
        return 0.0, 0.0, 0.0, 0.0
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


def closest_on_prim(p, x):
    """(point le plus proche, distance, distance curviligne) sur la primitive."""
    if p[0] == "segment":
        q, t = geo.project_segment(x, p[1], p[2])
        return q, geo.distance(x, q), t * prim_length(p)
    c, r = p[1], p[2]
    if geo.distance(x, c) <= geo.EPS:
        q = prim_start(p)
        return q, r, 0.0
    theta = math.degrees(math.atan2(x[1] - c[1], x[0] - c[0]))
    if angle_in_arc(theta, p[3], p[4]):
        q = arc_point(c, r, theta)
        return q, geo.distance(x, q), arc_param_of_angle(p, theta)
    s, e = prim_start(p), prim_end(p)
    if geo.distance(x, s) <= geo.distance(x, e):
        return s, geo.distance(x, s), 0.0
    return e, geo.distance(x, e), prim_length(p)


def closest(primitives, x):
    """(point, distance, indice de la primitive, distance curviligne dans elle) le plus proche."""
    best = None
    for i, p in enumerate(primitives):
        q, d, s = closest_on_prim(p, x)
        if best is None or d < best[1]:
            best = (q, d, i, s)
    return best


def distance_to(primitives, x) -> float:
    found = closest(primitives, x)
    return found[1] if found else float("inf")


def in_rect(primitives, rect, tol: float) -> bool:
    """Entite entierement dans le rectangle (selection par FENETRE)."""
    box = bounds(primitives)
    return geo.point_in_rect((box[0], box[1]), rect) and geo.point_in_rect((box[2], box[3]), rect)


def touches_rect(primitives, rect, tol: float) -> bool:
    """Entite qui touche le rectangle (selection par CAPTURE)."""
    for pts in tessellate(primitives, tol):
        for i in range(len(pts) - 1):
            if geo.segment_intersects_rect(pts[i], pts[i + 1], rect):
                return True
        if len(pts) == 1 and geo.point_in_rect(pts[0], rect):
            return True
    return False


# ==========================================================================
# Intersections
# ==========================================================================

def line_circle(a, b, c, r) -> list:
    """Parametres t (point = a + t (b - a)) des intersections de la DROITE (a, b) et du cercle (c, r)."""
    d = geo.sub(b, a)
    f = geo.sub(a, c)
    A = geo.dot(d, d)
    if A <= geo.EPS * geo.EPS:
        return []
    B = 2.0 * geo.dot(f, d)
    C = geo.dot(f, f) - r * r
    disc = B * B - 4 * A * C
    if disc < -1e-9 * max(1.0, B * B):
        return []
    if abs(disc) <= 1e-12 * max(1.0, B * B):
        return [-B / (2 * A)]
    root = math.sqrt(max(0.0, disc))
    return [(-B - root) / (2 * A), (-B + root) / (2 * A)]


def circle_circle(c1, r1, c2, r2) -> list:
    d = geo.distance(c1, c2)
    if d <= geo.EPS or d > r1 + r2 + 1e-9 or d < abs(r1 - r2) - 1e-9:
        return []
    a = (r1 * r1 - r2 * r2 + d * d) / (2 * d)
    h = math.sqrt(max(0.0, r1 * r1 - a * a))
    m = geo.add(c1, geo.mul(geo.sub(c2, c1), a / d))
    if h <= 1e-9:
        return [m]
    off = (-(c2[1] - c1[1]) * h / d, (c2[0] - c1[0]) * h / d)
    return [geo.add(m, off), geo.sub(m, off)]


def _on_prim(p, x, extend: bool, tol: float = 1e-7) -> bool:
    if extend:
        return True
    if p[0] == "segment":
        n = prim_length(p)
        t = geo.project_param(x, p[1], p[2])
        return -tol / max(n, 1.0) <= t <= 1 + tol / max(n, 1.0)
    theta = math.degrees(math.atan2(x[1] - p[1][1], x[0] - p[1][0]))
    return angle_in_arc(theta, p[3], p[4])


def prim_intersections(p, q, extend_p: bool = False, extend_q: bool = False) -> list:
    """Points d'intersection de deux primitives ; `extend_*` : segment -> droite, arc -> cercle complet."""
    if p[0] == "segment" and q[0] == "segment":
        found = geo.line_intersection(p[1], p[2], q[1], q[2])
        if found is None:
            return []
        pts = [found[0]]
    elif p[0] == "segment" or q[0] == "segment":
        seg, arc = (p, q) if p[0] == "segment" else (q, p)
        pts = [geo.lerp(seg[1], seg[2], t) for t in line_circle(seg[1], seg[2], arc[1], arc[2])]
    else:
        pts = circle_circle(p[1], p[2], q[1], q[2])
    return [x for x in pts if _on_prim(p, x, extend_p) and _on_prim(q, x, extend_q)]


# ==========================================================================
# Constructions
# ==========================================================================

def arc_from_3_points(p1, p2, p3):
    """(centre, rayon, angle de depart, ouverture signee) de l'arc qui va de p1 a p3 en passant par p2 ; None si
    les points sont alignes ou confondus."""
    ax, ay = p1
    bx, by = p2
    cx, cy = p3
    d = 2.0 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    scale = max(1.0, abs(ax) + abs(ay) + abs(bx) + abs(by) + abs(cx) + abs(cy))
    if abs(d) <= 1e-12 * scale * scale:
        return None
    ux = ((ax * ax + ay * ay) * (by - cy) + (bx * bx + by * by) * (cy - ay) + (cx * cx + cy * cy) * (ay - by)) / d
    uy = ((ax * ax + ay * ay) * (cx - bx) + (bx * bx + by * by) * (ax - cx) + (cx * cx + cy * cy) * (bx - ax)) / d
    c = (ux, uy)
    r = geo.distance(c, p1)
    a1 = geo.angle_deg(c, p1)
    a3 = geo.angle_deg(c, p3)
    ccw = geo.cross(geo.sub(p2, p1), geo.sub(p3, p2)) > 0
    sweep = (a3 - a1) % 360.0 if ccw else -((a1 - a3) % 360.0)
    return c, r, a1, sweep


def arc_data(c, r, a0, sweep) -> dict:
    """Champs d'un `cad_arc` (toujours dans le sens trigonometrique) pour un arc d'ouverture signee."""
    if sweep < 0:
        a0, sweep = a0 + sweep, -sweep
    return {"center": [c[0], c[1]], "radius": r, "start": a0 % 360.0, "end": (a0 + sweep) % 360.0}


def prims_to_entity(primitives, closed: bool = False):
    """(type, champs geometriques) d'une entite qui suit ces primitives (bout a bout) : ligne, arc ou polyligne."""
    if len(primitives) == 1 and not closed:
        p = primitives[0]
        if p[0] == "segment":
            return "cad_line", {"p1": list(p[1]), "p2": list(p[2])}
        if abs(p[4]) >= 360.0 - 1e-9:
            return "cad_circle", {"center": list(p[1]), "radius": p[2]}
        return "cad_arc", arc_data(p[1], p[2], p[3], p[4])
    vertices = []
    for p in primitives:
        start = prim_start(p)
        bulge = 0.0 if p[0] == "segment" else arc_bulge(p[4])
        vertices.append([start[0], start[1], bulge])
    if not closed and primitives:
        end = prim_end(primitives[-1])
        vertices.append([end[0], end[1], 0.0])
    return "cad_pline", {"vertices": vertices, "closed": bool(closed)}


# ==========================================================================
# Poignees, deplacement
# ==========================================================================

def grips(kind: str, data: dict, offset=(0.0, 0.0)) -> list:
    """[(nom, point)] des poignees (comme AutoCAD) : ligne = extremites + milieu ; arc = extremites, milieu, centre ;
    cercle = centre + quadrants ; polyligne = sommets (v<i>) + milieux des segments (m<i>)."""
    if kind == "cad_dim":
        return cad_dims.grips(data, offset)
    if kind == "cad_text":
        p = _pt(data.get("pos"))
        return [("pos", (p[0] + offset[0], p[1] + offset[1]))]
    if kind == "cad_hatch":
        loops = cad_hatch.clean_loops(data.get("loops"))
        c = cad_hatch.centroid(loops)
        return [("center", (c[0] + offset[0], c[1] + offset[1]))] if loops else []
    p = prims(kind, data, offset)
    if kind == "cad_line":
        a, b = p[0][1], p[0][2]
        return [("p1", a), ("mid", geo.midpoint(a, b)), ("p2", b)]
    if kind == "cad_arc":
        arc = p[0]
        return [("start", prim_start(arc)), ("mid", prim_mid(arc)), ("end", prim_end(arc)), ("center", arc[1])]
    if kind == "cad_circle":
        c, r = p[0][1], p[0][2]
        return [("center", c)] + [(f"q{q}", arc_point(c, r, q)) for q in (0, 90, 180, 270)]
    if kind == "cad_pline":
        verts = [(float(v[0]) + offset[0], float(v[1]) + offset[1], float(v[2]) if len(v) > 2 else 0.0)
                 for v in data.get("vertices") or []]
        out = [(f"v{i}", (v[0], v[1])) for i, v in enumerate(verts)]
        count = len(verts)
        for i in range(count if (data.get("closed") and count > 2) else count - 1):
            a, b = verts[i], verts[(i + 1) % count]
            seg = bulge_arc((a[0], a[1]), (b[0], b[1]), a[2])
            if prim_length(seg) > geo.EPS:
                out.append((f"m{i}", prim_mid(seg)))        # milieu du segment i (sommets i et i + 1)
        return out
    return []


def move_grip_names(kind: str, names) -> bool:
    """Ces poignees deplacent l'entite entiere (et non une partie)."""
    return any(n == "center" or (kind == "cad_line" and n == "mid") or (kind == "cad_text" and n == "pos")
               for n in names)


def translated(kind: str, data: dict, delta) -> dict:
    """TOUS les champs geometriques de l'entite deplacee de `delta` (rayon, fermeture… gardes : une copie en a besoin)."""
    return _complete(kind, data, _translated_part(kind, data, delta))


def _translated_part(kind: str, data: dict, delta) -> dict:
    """Champs geometriques que le deplacement change."""
    dx, dy = delta
    if kind == "cad_dim":
        return cad_dims.translate(data, delta)
    if kind == "cad_hatch":
        return cad_hatch.translate(data, delta)
    if kind == "cad_text":
        return cad_text.translate(data, delta)
    if kind == "cad_line":
        a, b = _pt(data.get("p1")), _pt(data.get("p2"))
        return {"p1": [a[0] + dx, a[1] + dy], "p2": [b[0] + dx, b[1] + dy]}
    if kind in ("cad_arc", "cad_circle"):
        c = _pt(data.get("center"))
        return {"center": [c[0] + dx, c[1] + dy]}
    if kind == "cad_pline":
        return {"vertices": [[float(v[0]) + dx, float(v[1]) + dy, *[float(x) for x in v[2:3]]]
                             for v in data.get("vertices") or []]}
    return {}


def grip_edit(kind: str, data: dict, names, delta, move: bool):
    """Champs geometriques apres avoir tire les poignees `names` de `delta` (ETIREMENT), ou toute l'entite
    (`move`, DEPLACEMENT). None si le resultat est degenere (longueur ou rayon nul, points alignes)."""
    if move or move_grip_names(kind, names):
        return translated(kind, data, delta)
    names = set(names)
    if kind == "cad_dim":
        out = {}
        for name in names:
            if data.get(name) is not None and name in ("p1", "p2", "pos"):
                out[name] = list(geo.add(_pt(data.get(name)), delta))
        if data.get("dim_type") in ("radius", "diameter") and "p1" in out:
            shift = geo.sub(out["p1"], _pt(data.get("p1")))      # centre tire : le point du cercle suit
            out["p2"] = list(geo.add(out.get("p2", _pt(data.get("p2"))), shift))
        return out or None
    if kind == "cad_line":
        a, b = _pt(data.get("p1")), _pt(data.get("p2"))
        if "p1" in names:
            a = geo.add(a, delta)
        if "p2" in names:
            b = geo.add(b, delta)
        if geo.distance(a, b) <= geo.EPS:
            return None
        return {"p1": list(a), "p2": list(b)}
    if kind == "cad_arc":
        arc = prims(kind, data)[0]
        s, m, e = prim_start(arc), prim_mid(arc), prim_end(arc)
        if "start" in names:
            s = geo.add(s, delta)
        if "end" in names:
            e = geo.add(e, delta)
        if "mid" in names:
            m = geo.add(m, delta)
        found = arc_from_3_points(s, m, e)
        return None if found is None else arc_data(*found)
    if kind == "cad_circle":
        c = _pt(data.get("center"))
        r = _num(data.get("radius"))
        for name in names:
            if name.startswith("q"):
                q = geo.add(arc_point(c, r, float(name[1:])), delta)
                r = geo.distance(c, q)
        return None if r <= geo.EPS else {"radius": r}
    if kind == "cad_pline":
        verts = [list(map(float, v[:3])) + [0.0] * (3 - len(v[:3])) for v in data.get("vertices") or []]
        count = len(verts)
        moved = set()
        for name in names:
            if name.startswith("v"):
                moved.add(int(name[1:]))
            elif name.startswith("m"):
                i = int(name[1:])
                moved.update({i, (i + 1) % count})
        for i in moved:
            if 0 <= i < count:
                verts[i][0] += delta[0]
                verts[i][1] += delta[1]
        return {"vertices": verts}
    return None


def pline_segments(data: dict) -> list:
    """[(indice du sommet de depart, primitive)] des segments d'une polyligne (memes indices que `vertices`)."""
    verts = [(float(v[0]), float(v[1]), float(v[2]) if len(v) > 2 else 0.0) for v in data.get("vertices") or []]
    count = len(verts)
    out = []
    for i in range(count if (data.get("closed") and count > 2) else count - 1):
        a, b = verts[i], verts[(i + 1) % count]
        if geo.distance((a[0], a[1]), (b[0], b[1])) > geo.EPS:
            out.append((i, bulge_arc((a[0], a[1]), (b[0], b[1]), a[2])))
    return out


def pline_segment_at(data: dict, point):
    """(indice du sommet de depart, primitive) du segment de polyligne le plus proche de `point`."""
    best = None
    for i, p in pline_segments(data):
        d = closest_on_prim(p, point)[1]
        if best is None or d < best[0]:
            best = (d, i, p)
    return (best[1], best[2]) if best else (None, None)


# ==========================================================================
# Rotation, miroir (champs geometriques de l'entite transformee)
# ==========================================================================

def rotated_point(p, base, degrees: float):
    c, s = math.cos(math.radians(degrees)), math.sin(math.radians(degrees))
    x, y = p[0] - base[0], p[1] - base[1]
    return (base[0] + x * c - y * s, base[1] + x * s + y * c)


def mirrored_point(p, a, b):
    """Symetrique de `p` par rapport a la droite (a, b)."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    length2 = dx * dx + dy * dy
    if length2 <= geo.EPS * geo.EPS:
        return (p[0], p[1])
    t = ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / length2
    fx, fy = a[0] + dx * t, a[1] + dy * t
    return (2.0 * fx - p[0], 2.0 * fy - p[1])


def transformed(kind: str, data: dict, point_fn, angle_fn, flips: bool) -> dict:
    """Champs geometriques de l'entite dont chaque point passe par `point_fn` ; `angle_fn(degres)` transforme une
    direction (rotation : + angle ; miroir : 2 phi - angle) ; `flips` (miroir) inverse l'orientation (renflements,
    debut et fin d'un arc)."""
    if kind == "cad_line":
        a, b = point_fn(_pt(data.get("p1"))), point_fn(_pt(data.get("p2")))
        return {"p1": list(a), "p2": list(b)}
    if kind == "cad_circle":
        return {"center": list(point_fn(_pt(data.get("center"))))}
    if kind == "cad_arc":
        start, end = angle_fn(_num(data.get("start"))), angle_fn(_num(data.get("end")))
        if flips:
            start, end = end, start
        return {"center": list(point_fn(_pt(data.get("center")))), "start": start % 360.0, "end": end % 360.0}
    if kind == "cad_pline":
        out = []
        for v in data.get("vertices") or []:
            q = point_fn((_num(v[0]), _num(v[1])))
            bulge = _num(v[2]) if len(v) > 2 else 0.0
            out.append([q[0], q[1], -bulge if flips else bulge])
        return {"vertices": out}
    if kind == "cad_dim":
        return cad_dims.transform(data, point_fn, angle_fn)
    if kind == "cad_hatch":
        return cad_hatch.transform(data, point_fn, angle_fn)
    if kind == "cad_text":
        return cad_text.transform(data, point_fn, angle_fn, flips)
    return {}


def _complete(kind: str, data: dict, changed: dict) -> dict:
    """Tous les champs geometriques (ceux qu'une transformation ne touche pas — rayon, fermeture… — gardes)."""
    out = {k: copy_value(data[k]) for k in GEOMETRY_KEYS.get(kind, ()) if k in data}
    out.update(changed)
    return out


def copy_value(value):
    return [copy_value(v) for v in value] if isinstance(value, (list, tuple)) else value


def rotated(kind: str, data: dict, base, degrees: float) -> dict:
    return _complete(kind, data, transformed(kind, data, lambda p: rotated_point(p, base, degrees),
                                             lambda a: a + degrees, False))


def scaled_point(p, base, factor: float):
    return (base[0] + (p[0] - base[0]) * factor, base[1] + (p[1] - base[1]) * factor)


def scaled(kind: str, data: dict, base, factor: float) -> dict:
    """Mise a l'echelle uniforme autour de `base` : points, rayons, espacement du motif d'une hachure ; les angles et
    les renflements des polylignes ne changent pas."""
    out = _complete(kind, data, transformed(kind, data, lambda p: scaled_point(p, base, factor), lambda a: a, False))
    if kind in ("cad_circle", "cad_arc"):
        out["radius"] = _num(data.get("radius")) * factor
    if kind == "cad_hatch" and data.get("hatch_spacing") is not None:
        out["hatch_spacing"] = _num(data.get("hatch_spacing")) * factor
    if kind == "cad_text":
        out.update(cad_text.scale(data, factor))
    return out


def mirrored(kind: str, data: dict, a, b) -> dict:
    phi = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))
    return _complete(kind, data, transformed(kind, data, lambda p: mirrored_point(p, a, b),
                                             lambda angle: 2.0 * phi - angle, True))
