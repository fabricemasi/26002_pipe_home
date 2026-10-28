"""Module CAD du board : geometrie PURE des outils de modification (aucun Qt) — DECALER (OFFSET), CHANFREIN
(CHAMFER), RACCORD (FILLET), au comportement d'AutoCAD. Tout en coordonnees du DOCUMENT, sur les primitives de
cad_shapes (`("segment", a, b)`, `("arc", c, r, a0, ouverture)`).

Chaque fonction rend un resultat, ou une CHAINE = message d'erreur clair pour l'utilisateur (cas impossible : lignes
paralleles, distance ou rayon trop grand, rayon nul…) ; rien n'est modifie ici."""
from __future__ import annotations

import math

from . import cad_geometry as geo
from . import cad_shapes as sh

TOL = 1e-9


def _left(d):
    return -d[1], d[0]


# ==========================================================================
# DECALER
# ==========================================================================

def side_of(primitives, point) -> int:
    """+1 si `point` est a GAUCHE du trace (sens de parcours) au plus pres, -1 a droite, 0 dessus."""
    found = sh.closest(primitives, point)
    if found is None:
        return 0
    q, d, i, s = found
    if d <= TOL:
        return 0
    p = primitives[i]
    if p[0] == "arc":
        # Gauche d'un arc parcouru dans le sens trigonometrique = vers le centre.
        inside = geo.distance(point, p[1]) < p[2]
        return (1 if inside else -1) * (1 if p[4] >= 0 else -1)
    t = sh.prim_tangent(p, s)
    return 1 if geo.cross(t, geo.sub(point, q)) > 0 else -1


def offset_prim(p, dist: float):
    """Primitive decalee de `dist` vers sa GAUCHE (negatif : droite) ; chaine si un arc tombe a un rayon <= 0."""
    if p[0] == "segment":
        d = geo.normalize(geo.sub(p[2], p[1]))
        n = geo.mul(_left(d), dist)
        return ("segment", geo.add(p[1], n), geo.add(p[2], n))
    c, r, a0, sweep = p[1], p[2], p[3], p[4]
    radius = r - dist if sweep >= 0 else r + dist
    if radius <= 1e-9 * max(1.0, r):
        return "Le décalage donnerait un arc ou un cercle de rayon nul ou négatif : impossible de ce côté."
    return ("arc", c, radius, a0, sweep)


def _join(p, q, corner):
    """Point de raccord de deux primitives DECALEES consecutives : leur intersection (prolongees) la plus proche du
    sommet d'origine ; None si elles ne se coupent pas."""
    points = sh.prim_intersections(p, q, True, True)
    if not points:
        return None
    return min(points, key=lambda x: geo.distance(x, corner))


def _trim_prim(p, start=None, end=None):
    """Primitive dont le debut et / ou la fin sont deplaces sur `start` / `end` (points de sa droite / son cercle)."""
    if p[0] == "segment":
        return ("segment", start if start is not None else p[1], end if end is not None else p[2])
    c, r, a0, sweep = p[1], p[2], p[3], p[4]
    s_ang = geo.angle_deg(c, start) if start is not None else a0
    e_ang = geo.angle_deg(c, end) if end is not None else a0 + sweep
    if sweep >= 0:
        new = (e_ang - s_ang) % 360.0
        if new <= 1e-9:
            new = 360.0 if sweep > 180 else 0.0
    else:
        new = -((s_ang - e_ang) % 360.0)
        if new >= -1e-9:
            new = -360.0 if sweep < -180 else 0.0
    return ("arc", c, r, s_ang, new)


def offset_prims(primitives, dist: float, closed: bool):
    """Polyligne (ou entite) decalee de `dist` vers la gauche : chaque primitive decalee, puis les sommets
    RACCORDES (intersection des primitives prolongees, comme AutoCAD) ; deux primitives qui ne se coupent plus
    (tangentes) sont reliees telles quelles. Chaine en cas d'impossibilite."""
    out = []
    for p in primitives:
        q = offset_prim(p, dist)
        if isinstance(q, str):
            return q
        out.append(q)
    count = len(out)
    if count == 1:
        return out
    joints = range(count) if closed else range(count - 1)
    starts = [None] * count
    ends = [None] * count
    for i in joints:
        j = (i + 1) % count
        corner = sh.prim_end(primitives[i])
        point = _join(out[i], out[j], corner)
        if point is None:
            continue                                         # tangentes (arc qui prolonge un segment...)
        ends[i] = point
        starts[j] = point
    result = []
    for i, q in enumerate(out):
        trimmed = _trim_prim(q, starts[i], ends[i])
        if sh.prim_length(trimmed) <= TOL:
            continue                                         # segment absorbe par ses voisins
        result.append(trimmed)
    if not result:
        return "Distance de décalage trop grande pour cet objet."
    return result


def offset_entity(kind: str, data: dict, dist: float, side_point):
    """(type, champs geometriques) de la copie decalee de `dist` du cote de `side_point` ; chaine si impossible."""
    if kind not in ("cad_line", "cad_arc", "cad_circle", "cad_pline"):
        return "On ne peut décaler que des lignes, arcs, cercles et polylignes."
    if dist <= TOL:
        return "La distance de décalage doit être positive."
    primitives = sh.prims(kind, data)
    if not primitives:
        return "Objet vide."
    side = side_of(primitives, side_point)
    if side == 0:
        return "Le point est sur l'objet : cliquez d'un côté."
    closed = kind == "cad_circle" or (kind == "cad_pline" and bool(data.get("closed")))
    result = offset_prims(primitives, side * dist, closed)
    if isinstance(result, str):
        return result
    if kind == "cad_circle":
        return "cad_circle", {"center": list(result[0][1]), "radius": result[0][2]}
    if kind == "cad_pline":
        return sh.prims_to_entity(result, closed=closed) if len(result) > 1 or closed else \
            sh.prims_to_entity(result)
    return sh.prims_to_entity(result)


def through_distance(kind: str, data: dict, point) -> float:
    """Option « Par » : distance du point a l'objet."""
    return sh.distance_to(sh.prims(kind, data), point)


# ==========================================================================
# CHANFREIN et RACCORD : deux objets « coupes » vers le cote clique
# ==========================================================================

def corner_of(seg1, seg2):
    """Intersection des DROITES de deux segments, None si paralleles."""
    found = geo.line_intersection(seg1[0], seg1[1], seg2[0], seg2[1])
    return None if found is None else found[0]


def _kept_direction(seg, corner, pick):
    """Direction unitaire (depuis le coin) vers le cote GARDE du segment (celui du clic) et le bout de ce cote."""
    a, b = seg
    d = geo.normalize(geo.sub(b, a))
    t_pick = geo.dot(geo.sub(pick, corner), d)
    if abs(t_pick) <= TOL:                                   # clic sur le coin : le bout le plus loin
        t_pick = geo.dot(geo.sub(a, corner), d) + geo.dot(geo.sub(b, corner), d)
    u = d if t_pick > 0 else geo.mul(d, -1.0)
    ta, tb = geo.dot(geo.sub(a, corner), u), geo.dot(geo.sub(b, corner), u)
    far = a if ta >= tb else b
    return u, far, max(ta, tb)


def chamfer_lines(seg1, pick1, seg2, pick2, d1: float, d2: float):
    """Chanfrein de deux segments (a, b) cliques en pick1 / pick2, distances d1 (1er) et d2 (2e) depuis leur coin.
    Rend {"first": (a, b), "second": (a, b), "chamfer": (c1, c2) ou None} (segments ajustes : coupes ou
    prolonges jusqu'au chanfrein), ou une chaine."""
    if d1 < 0 or d2 < 0:
        return "Les distances de chanfrein doivent être positives ou nulles."
    corner = corner_of(seg1, seg2)
    if corner is None:
        return "Les lignes sont parallèles : chanfrein impossible."
    u1, far1, reach1 = _kept_direction(seg1, corner, pick1)
    u2, far2, reach2 = _kept_direction(seg2, corner, pick2)
    if d1 > reach1 + TOL or d2 > reach2 + TOL:
        return "Distance de chanfrein trop grande pour ces lignes."
    c1 = geo.add(corner, geo.mul(u1, d1))
    c2 = geo.add(corner, geo.mul(u2, d2))
    chamfer = None if geo.distance(c1, c2) <= TOL else (c1, c2)
    return {"first": (far1, c1), "second": (far2, c2), "chamfer": chamfer, "corner": corner}


def chamfer_angle_distance(seg1, pick1, seg2, pick2, d1: float, angle_deg: float):
    """Methode distance + angle : d1 sur le 1er segment, chanfrein qui fait `angle_deg` avec lui."""
    corner = corner_of(seg1, seg2)
    if corner is None:
        return "Les lignes sont parallèles : chanfrein impossible."
    u1, _f1, _r1 = _kept_direction(seg1, corner, pick1)
    u2, _f2, _r2 = _kept_direction(seg2, corner, pick2)
    phi = math.acos(max(-1.0, min(1.0, geo.dot(u1, u2))))     # angle au coin
    alpha = math.radians(angle_deg)
    rest = math.pi - alpha - phi
    if alpha <= 0 or rest <= 1e-9:
        return "Angle de chanfrein impossible pour ces lignes."
    d2 = d1 * math.sin(alpha) / math.sin(rest)               # loi des sinus dans le triangle coin, c1, c2
    return chamfer_lines(seg1, pick1, seg2, pick2, d1, d2)


def fillet_lines(seg1, pick1, seg2, pick2, radius: float):
    """Raccord de deux segments : {"first", "second", "arc": (c, r, a0, ouverture) ou None}, ou une chaine."""
    if radius < 0:
        return "Le rayon doit être positif ou nul."
    corner = corner_of(seg1, seg2)
    if corner is None:
        return "Les lignes sont parallèles : raccord impossible."
    u1, far1, reach1 = _kept_direction(seg1, corner, pick1)
    u2, far2, reach2 = _kept_direction(seg2, corner, pick2)
    if radius <= TOL:
        return {"first": (far1, corner), "second": (far2, corner), "arc": None, "corner": corner}
    phi = math.acos(max(-1.0, min(1.0, geo.dot(u1, u2))))
    if phi <= 1e-9 or phi >= math.pi - 1e-9:
        return "Les lignes sont alignées : raccord impossible."
    tangent = radius / math.tan(phi / 2.0)
    if tangent > reach1 + TOL or tangent > reach2 + TOL:
        return "Rayon trop grand pour ces lignes."
    t1 = geo.add(corner, geo.mul(u1, tangent))
    t2 = geo.add(corner, geo.mul(u2, tangent))
    bis = geo.normalize(geo.add(u1, u2))
    center = geo.add(corner, geo.mul(bis, radius / math.sin(phi / 2.0)))
    return {"first": (far1, t1), "second": (far2, t2), "arc": _short_arc(center, radius, t1, t2), "corner": corner}


def _short_arc(center, radius, a, b):
    """Arc (c, r, a0, ouverture signee) le plus court de a vers b autour du centre."""
    a0 = geo.angle_deg(center, a)
    a1 = geo.angle_deg(center, b)
    sweep = (a1 - a0) % 360.0
    if sweep > 180.0:
        sweep -= 360.0
    return center, radius, a0, sweep


# -- raccord general (segments et arcs / cercles) --
def _offsets(p, radius):
    """Courbes paralleles a `p` a la distance `radius` (prolongees : droites / cercles complets)."""
    if p[0] == "segment":
        d = geo.normalize(geo.sub(p[2], p[1]))
        out = []
        for k in (1.0, -1.0):
            n = geo.mul(_left(d), k * radius)
            out.append(("segment", geo.add(p[1], n), geo.add(p[2], n)))
        return out
    out = [("arc", p[1], p[2] + radius, 0.0, 360.0)]
    if p[2] - radius > TOL:
        out.append(("arc", p[1], p[2] - radius, 0.0, 360.0))
    return out


def _foot(p, center):
    """Point de tangence du cercle de raccord (centre `center`) sur la primitive prolongee."""
    if p[0] == "segment":
        return geo.project_line(center, p[1], p[2])
    c, r = p[1], p[2]
    d = geo.distance(center, c)
    if d <= TOL:
        return None
    return geo.add(c, geo.mul(geo.sub(center, c), r / d))


def trim_to(p, point, pick):
    """Primitive coupee (ou prolongee) au point `point` (sur sa droite / son cercle), cote du clic garde.
    Un cercle complet n'est jamais coupe (comme AutoCAD) : None = inchange."""
    if p[0] == "segment":
        a, b = p[1], p[2]
        d = geo.sub(b, a)
        n = geo.dot(d, d)
        if n <= TOL:
            return p
        t_point = geo.dot(geo.sub(point, a), d) / n
        t_pick = geo.dot(geo.sub(pick, a), d) / n
        far = b if t_pick >= t_point else a
        return ("segment", far, point)
    c, r, a0, sweep = p[1], p[2], p[3], p[4]
    if abs(sweep) >= 360.0 - 1e-9:
        return None
    # Arc normalise dans le sens trigonometrique.
    if sweep < 0:
        a0, sweep = a0 + sweep, -sweep
    theta_t = geo.angle_deg(c, point)
    theta_p = geo.angle_deg(c, pick)
    options = []
    end = a0 + sweep
    for start, stop in ((theta_t, end), (a0, theta_t)):     # [T -> fin] ou [debut -> T]
        span = (stop - start) % 360.0
        if span <= 1e-9 or span >= 360.0 - 1e-9:
            continue
        if sh.angle_in_arc(theta_p, start, span):
            options.append((span, start))
    if not options:
        return None
    span, start = min(options)
    return ("arc", c, r, start, span)


def fillet_prims(p1, pick1, p2, pick2, radius: float):
    """Raccord de deux primitives quelconques (segment / arc / cercle) cliquees en pick1 / pick2 : cercle de rayon
    `radius` tangent aux deux, choisi comme AutoCAD d'apres les points cliques (tangences les plus proches des
    clics). Rend {"first": primitive ajustee ou None (inchangee), "second": idem, "arc": (c, r, a0, ouverture)
    ou None}, ou une chaine."""
    if p1[0] == "segment" and p2[0] == "segment":
        found = fillet_lines((p1[1], p1[2]), pick1, (p2[1], p2[2]), pick2, radius)
        if isinstance(found, str):
            return found
        return {"first": ("segment", *found["first"]), "second": ("segment", *found["second"]),
                "arc": found["arc"]}
    if radius < 0:
        return "Le rayon doit être positif ou nul."
    if radius <= TOL:
        points = sh.prim_intersections(p1, p2, True, True)
        if not points:
            return "Les objets ne se coupent pas (même prolongés) : raccord de rayon 0 impossible."
        corner = min(points, key=lambda x: geo.distance(x, pick1) + geo.distance(x, pick2))
        return {"first": trim_to(p1, corner, pick1), "second": trim_to(p2, corner, pick2), "arc": None}
    best = None
    for o1 in _offsets(p1, radius):
        for o2 in _offsets(p2, radius):
            for center in sh.prim_intersections(o1, o2, True, True):
                t1, t2 = _foot(p1, center), _foot(p2, center)
                if t1 is None or t2 is None:
                    continue
                score = geo.distance(t1, pick1) + geo.distance(t2, pick2)
                if best is None or score < best[0]:
                    best = (score, center, t1, t2)
    if best is None:
        return "Rayon trop grand (ou objets trop éloignés) : aucun raccord possible."
    _score, center, t1, t2 = best
    return {"first": trim_to(p1, t1, pick1), "second": trim_to(p2, t2, pick2),
            "arc": _short_arc(center, radius, t1, t2)}


# ==========================================================================
# Polylignes : sommets
# ==========================================================================

def pline_vertex_edit(vertices, closed: bool, index: int, kind: str, value1: float, value2: float = 0.0,
                      angle: float | None = None):
    """Chanfrein (`kind` = "chamfer", distances value1 / value2 ou angle) ou raccord (`kind` = "fillet", rayon
    value1) au sommet `index` d'une polyligne dont les deux segments voisins sont DROITS. Rend la nouvelle liste
    de sommets, ou une chaine."""
    count = len(vertices)
    prev_i = index - 1 if index > 0 else (count - 1 if closed else None)
    next_i = index + 1 if index < count - 1 else (0 if closed else None)
    if prev_i is None or next_i is None:
        return "Sommet d'extrémité : rien à faire."
    if abs(vertices[prev_i][2]) > 1e-12 or abs(vertices[index][2]) > 1e-12:
        return "Segment courbe : seuls les sommets entre deux segments droits sont pris en charge."
    a = tuple(vertices[prev_i][:2])
    v = tuple(vertices[index][:2])
    b = tuple(vertices[next_i][:2])
    if kind == "chamfer":
        if angle is not None:
            found = chamfer_angle_distance((a, v), a, (v, b), b, value1, angle)
        else:
            found = chamfer_lines((a, v), a, (v, b), b, value1, value2)
        if isinstance(found, str):
            return found
        c1, c2 = found["first"][1], found["second"][1]
        new = [[c1[0], c1[1], 0.0]] + ([[c2[0], c2[1], 0.0]] if geo.distance(c1, c2) > TOL else [])
    else:
        found = fillet_lines((a, v), a, (v, b), b, value1)
        if isinstance(found, str):
            return found
        t1, t2 = found["first"][1], found["second"][1]
        if found["arc"] is None:
            return [list(x) for x in vertices]
        bulge = sh.arc_bulge(found["arc"][3])
        new = [[t1[0], t1[1], bulge], [t2[0], t2[1], 0.0]]
    out = [list(x) for x in vertices]
    out[index:index + 1] = new
    return out


def pline_all_vertices(vertices, closed: bool, kind: str, value1: float, value2: float = 0.0,
                       angle: float | None = None):
    """Option « Polyligne » : chanfrein / raccord a TOUS les sommets possibles (entre deux segments droits assez
    longs). Rend (sommets, nombre traites, nombre ignores)."""
    out = [list(x) for x in vertices]
    done = skipped = 0
    index = 0 if closed else 1
    while index < len(out) - (0 if closed else 1):
        result = pline_vertex_edit(out, closed, index, kind, value1, value2, angle)
        if isinstance(result, str):
            skipped += 1
            index += 1
            continue
        added = len(result) - len(out)
        out = result
        done += 1
        index += 1 + added                                   # sommet d'origine suivant (apres ceux crees)
    return out, done, skipped
