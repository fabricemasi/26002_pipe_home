"""Hachures du CAD : geometrie PURE (aucun Qt), en coordonnees du DOCUMENT (Y vers le haut, degres, sens trigo).

Une hachure (`cad_hatch`) est UNE entite : des CONTOURS (`loops` : polygones fermes, les courbes y sont decoupees en
petits segments) remplis par un MOTIF, comme AutoCAD (remplissage pair / impair : un contour dans un autre = un trou).

Champs : `loops` [[[x, y], ...], ...] ; `hatch_pattern` (solid | lines | cross | brick) ; `hatch_angle` (degres) ;
`hatch_spacing` (unites du board entre deux traits) ; `hatch_origin` (point de depart du motif : il suit l'objet quand
on le deplace, le motif ne glisse donc pas dans la forme) ; `hatch_alpha` (opacite du remplissage plein, 0-100).

Motif d'AutoCAD (`hatch_pattern` « dxf », hachures importees d'un DXF / DWG) : `hatch_lines` = familles de traits du
motif (`{"angle", "base", "offset", "dashes"}`, comme un fichier .pat : traits paralleles a `angle` passant par `base`,
repetes de `offset`, tirets > 0, blancs < 0, points = 0) DANS LE REPERE DE LA HACHURE (angle relatif a `hatch_angle`,
positions relatives a `hatch_origin`, longueurs en multiples de `hatch_spacing`) : deplacer, tourner, mettre a
l'echelle ou retourner la hachure garde son motif ; `hatch_name` = nom du motif (ANSI31, AR-CONC…).

Zone a hachurer :
- `find_region` : a partir d'un POINT INTERNE, la plus petite zone fermee que forment les traits qui l'entourent
  (graphe planaire : traits coupes a leurs intersections, parcours de la face qui contient le point ; les ilots
  fermes a l'interieur deviennent des trous) ;
- `object_loops` : les contours fermes d'objets choisis (cercle, polyligne fermee, ou traits qui se referment)."""
from __future__ import annotations

import math

from . import cad_geometry as geo

PATTERNS = ("solid", "lines", "cross", "brick")      # motifs proposes (commande, panneau Proprietes)
WIPEOUT = "wipeout"                 # MASQUE (WIPEOUT d'AutoCAD) : zone peinte de la couleur du fond PAR-DESSUS les traits
                                    # (les textes restent au-dessus), aucun trait de motif
DXF = "dxf"                                         # motif d'AutoCAD importe (`hatch_lines`)
GRADIENT = "gradient"               # DEGRADE (HATCH d'AutoCAD, remplissage degrade) : de la couleur de l'entite a
                                    # `hatch_color2`, forme `hatch_gradient`, angle `hatch_angle`, `hatch_centered`
GRADIENTS = ("LINEAR", "CYLINDER", "INVCYLINDER", "SPHERICAL", "INVSPHERICAL", "HEMISPHERICAL", "INVHEMISPHERICAL",
             "CURVED", "INVCURVED")
GRADIENT_LABELS = {"LINEAR": "Linéaire", "CYLINDER": "Cylindre", "INVCYLINDER": "Cylindre inversé",
                   "SPHERICAL": "Sphère", "INVSPHERICAL": "Sphère inversée", "HEMISPHERICAL": "Hémisphère",
                   "INVHEMISPHERICAL": "Hémisphère inversé", "CURVED": "Courbe", "INVCURVED": "Courbe inversée"}
MM = 96.0 / 25.4
DEFAULTS = {"hatch_pattern": "lines", "hatch_angle": 45.0, "hatch_spacing": 3.0 * MM, "hatch_alpha": 35.0}
MAX_LINES = 4000                    # traits au plus par famille (l'ecart est agrandi au-dela)
MAX_DASHES = 40000                  # tirets au plus par famille d'un motif d'AutoCAD (au-dela : traits continus)
GEOMETRY_KEYS = ("loops", "hatch_origin", "hatch_angle")


def _num(value, default=0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if math.isfinite(out) else default


def _pt(value, default=(0.0, 0.0)):
    try:
        return (float(value[0]), float(value[1]))
    except (TypeError, ValueError, IndexError, KeyError):
        return default


def clean_loops(loops) -> list:
    """Contours valides : listes d'au moins trois points finis, sans le point de fermeture repete."""
    out = []
    for loop in loops or []:
        pts = [_pt(p, None) for p in (loop or [])]
        if any(p is None or not (math.isfinite(p[0]) and math.isfinite(p[1])) for p in pts):
            continue
        if len(pts) > 1 and geo.distance(pts[0], pts[-1]) <= geo.EPS:
            pts = pts[:-1]
        if len(pts) >= 3:
            out.append([[p[0], p[1]] for p in pts])
    return out


def clean_families(lines) -> list:
    """Familles valides d'un motif d'AutoCAD (`hatch_lines`) : nombres finis, tirets reels."""
    out = []
    for line in lines or []:
        if not isinstance(line, dict):
            continue
        base, offset = _pt(line.get("base"), None), _pt(line.get("offset"), None)
        if base is None or offset is None or not all(math.isfinite(v) for v in (*base, *offset)):
            continue
        dashes = [v for v in (_num(d, None) for d in (line.get("dashes") or [])) if v is not None]
        out.append({"angle": _num(line.get("angle"), 0.0) % 360.0, "base": [base[0], base[1]],
                    "offset": [offset[0], offset[1]], "dashes": dashes})
    return out


def style_of(data: dict) -> dict:
    pattern = data.get("hatch_pattern")
    families = clean_families(data.get("hatch_lines")) if pattern == DXF else []
    if pattern not in PATTERNS and not families and pattern not in (WIPEOUT, GRADIENT):
        pattern = DEFAULTS["hatch_pattern"]
    color2 = str(data.get("hatch_color2") or "")
    if not (color2.startswith("#") and len(color2) in (7, 9)):
        color2 = "#ffffff"
    return {"pattern": pattern, "angle": _num(data.get("hatch_angle"), DEFAULTS["hatch_angle"]),
            "spacing": max(1e-3, _num(data.get("hatch_spacing"), DEFAULTS["hatch_spacing"])),
            "origin": _pt(data.get("hatch_origin")), "alpha": max(0.0, min(100.0, _num(data.get("hatch_alpha"),
                                                                                      DEFAULTS["hatch_alpha"]))),
            "lines": families, "name": str(data.get("hatch_name") or "") if families else "",
            "color2": color2.lower(),
            "gradient": data.get("hatch_gradient") if data.get("hatch_gradient") in GRADIENTS else "LINEAR",
            "centered": bool(data.get("hatch_centered", True))}


def gradient_stops(name: str) -> list:
    """[(position 0..1, 1 = couleur de l'entite / 2 = seconde couleur)] le long du degrade (forme `name`)."""
    base = name[3:] if name.startswith("INV") else name
    stops = {"LINEAR": [(0.0, 1), (1.0, 2)], "CYLINDER": [(0.0, 1), (0.5, 2), (1.0, 1)],
             "SPHERICAL": [(0.0, 2), (1.0, 1)], "HEMISPHERICAL": [(0.0, 2), (1.0, 1)],
             "CURVED": [(0.0, 1), (0.7, 2), (1.0, 2)]}.get(base, [(0.0, 1), (1.0, 2)])
    if name.startswith("INV"):
        stops = [(t, 3 - c) for t, c in stops]
    return stops


# ==========================================================================
# Polygones
# ==========================================================================

def signed_area(loop) -> float:
    total = 0.0
    for i in range(len(loop)):
        a, b = loop[i], loop[(i + 1) % len(loop)]
        total += a[0] * b[1] - b[0] * a[1]
    return total / 2.0


def inside(loops, p) -> bool:
    """`p` est dans la zone des contours (remplissage pair / impair) ?"""
    hit = False
    x, y = p
    for loop in loops:
        n = len(loop)
        for i in range(n):
            a, b = loop[i], loop[(i + 1) % n]
            if (a[1] > y) != (b[1] > y):
                if x < a[0] + (y - a[1]) * (b[0] - a[0]) / (b[1] - a[1]):
                    hit = not hit
    return hit


def bounds(loops) -> tuple:
    xs = [p[0] for loop in loops for p in loop]
    ys = [p[1] for loop in loops for p in loop]
    if not xs:
        return (0.0, 0.0, 0.0, 0.0)
    return (min(xs), min(ys), max(xs), max(ys))


def boundary_segments(loops) -> list:
    return [(tuple(loop[i]), tuple(loop[(i + 1) % len(loop)])) for loop in loops for i in range(len(loop))]


def distance_to_boundary(loops, p) -> float:
    best = math.inf
    for a, b in boundary_segments(loops):
        best = min(best, geo.distance_point_segment(p, a, b))
    return best


# ==========================================================================
# Motifs : traits qui remplissent les contours
# ==========================================================================

def _scan(poly, positions):
    """Pour chaque position y de `positions` (traits horizontaux y = valeur), les intervalles [x0, x1] a l'interieur
    du polygone (pair / impair) : {position: [(x0, x1), ...]}. Une arete ne coupe que les traits de son intervalle."""
    spacing, first = positions
    crossings: dict = {}
    for loop in poly:
        n = len(loop)
        for i in range(n):
            a, b = loop[i], loop[(i + 1) % n]
            if a[1] == b[1]:
                continue
            (x1, y1), (x2, y2) = (a, b) if a[1] < b[1] else (b, a)
            k0 = math.ceil((y1 - first) / spacing - 1e-12)
            k1 = math.ceil((y2 - first) / spacing - 1e-12) - 1
            for k in range(k0, k1 + 1):
                y = first + k * spacing
                crossings.setdefault(k, []).append(x1 + (y - y1) * (x2 - x1) / (y2 - y1))
    out = {}
    for k, xs in crossings.items():
        xs.sort()
        out[k] = [(xs[j], xs[j + 1]) for j in range(0, len(xs) - 1, 2)]
    return out


def _frame(loops, angle: float, origin):
    c, s = math.cos(math.radians(-angle)), math.sin(math.radians(-angle))
    return [[((x - origin[0]) * c - (y - origin[1]) * s, (x - origin[0]) * s + (y - origin[1]) * c)
             for x, y in loop] for loop in loops], (c, s)


def _back(point, angle: float, origin):
    c, s = math.cos(math.radians(angle)), math.sin(math.radians(angle))
    return (origin[0] + point[0] * c - point[1] * s, origin[1] + point[0] * s + point[1] * c)


def _lines(loops, angle: float, spacing: float, origin) -> list:
    """Traits paralleles a `angle`, `spacing` d'ecart, calees sur `origin`, coupes a la zone."""
    poly, _ = _frame(loops, angle, origin)
    ys = [p[1] for loop in poly for p in loop]
    if not ys:
        return []
    spacing = max(spacing, (max(ys) - min(ys)) / MAX_LINES)
    out = []
    for k, spans in _scan(poly, (spacing, 0.0)).items():
        y = k * spacing
        for x0, x1 in spans:
            if x1 - x0 > geo.EPS:
                out.append((_back((x0, y), angle, origin), _back((x1, y), angle, origin)))
    return out


def _brick(loops, angle: float, spacing: float, origin) -> list:
    """Appareil de briques : rangees de hauteur `spacing`, joints montants tous les 2 x `spacing`, decales d'une rangee
    sur l'autre."""
    poly, _ = _frame(loops, angle, origin)
    xs = [p[0] for loop in poly for p in loop]
    ys = [p[1] for loop in poly for p in loop]
    if not xs:
        return []
    spacing = max(spacing, (max(ys) - min(ys)) / MAX_LINES, (max(xs) - min(xs)) / MAX_LINES)
    out = _lines(loops, angle, spacing, origin)
    turned = [[(y, x) for x, y in loop] for loop in poly]                    # colonnes x = j * spacing : balayage par y
    for j, spans in _scan(turned, (spacing, 0.0)).items():
        x = j * spacing
        for y0, y1 in spans:
            row0, row1 = math.floor(y0 / spacing), math.ceil(y1 / spacing) - 1
            for row in range(row0, row1 + 1):
                if (row - j) % 2:
                    continue                                                 # joints d'une rangee sur deux colonnes
                lo, hi = max(y0, row * spacing), min(y1, (row + 1) * spacing)
                if hi - lo > geo.EPS:
                    out.append((_back((x, lo), angle, origin), _back((x, hi), angle, origin)))
    return out


def family_frame(family: dict, style: dict):
    """(angle, base, pas le long du trait, pas d'une rangee a l'autre, tirets) d'une famille d'un motif d'AutoCAD, en
    coordonnees du DOCUMENT (repere de la hachure applique)."""
    angle, s, origin = style["angle"], style["spacing"], style["origin"]
    base = _back((family["base"][0] * s, family["base"][1] * s), angle, origin)
    rel = math.radians(family["angle"])
    ox, oy = family["offset"][0] * s, family["offset"][1] * s
    along = ox * math.cos(rel) + oy * math.sin(rel)
    across = -ox * math.sin(rel) + oy * math.cos(rel)
    return (angle + family["angle"]) % 360.0, base, along, across, [d * s for d in family["dashes"]]


def _family(loops, family: dict, style: dict) -> list:
    """Traits d'une famille d'un motif d'AutoCAD (tirets et points compris), coupes a la zone."""
    angle, base, along, across, dashes = family_frame(family, style)
    if abs(across) <= geo.EPS:
        return []
    poly, _ = _frame(loops, angle, base)
    ys = [p[1] for loop in poly for p in loop]
    if not ys:
        return []
    step = max(1, math.ceil((max(ys) - min(ys)) / abs(across) / MAX_LINES))     # trop de rangees : une sur `step`
    gap, shift = abs(across) * step, along * step * (1.0 if across > 0 else -1.0)
    rows = _scan(poly, (gap, 0.0))
    period = sum(abs(d) for d in dashes)
    if dashes and period > geo.EPS and any(d >= 0 for d in dashes):
        total = sum(x1 - x0 for spans in rows.values() for x0, x1 in spans)
        if total / period * len(dashes) > MAX_DASHES:
            dashes = []                                         # tirets trop fins pour la zone : traits continus
    else:
        dashes = []
    dot = period * 0.01
    out = []
    for k, spans in rows.items():
        y = k * gap
        phase = k * shift
        for x0, x1 in spans:
            if x1 - x0 <= geo.EPS:
                continue
            if not dashes:
                out.append((_back((x0, y), angle, base), _back((x1, y), angle, base)))
                continue
            pos = phase + math.floor((x0 - phase) / period) * period
            while pos < x1:
                for d in dashes:
                    if d > 0:
                        a, b = max(x0, pos), min(x1, pos + d)
                        if b > a:
                            out.append((_back((a, y), angle, base), _back((b, y), angle, base)))
                    elif d == 0 and x0 <= pos <= x1:            # point : un trait tres court, visible
                        out.append((_back((pos, y), angle, base), _back((min(x1, pos + dot), y), angle, base)))
                    pos += abs(d)
                    if pos >= x1:
                        break
    return out


def pattern_segments(loops, style: dict) -> list:
    """Traits du motif [(a, b)] (rien pour le remplissage plein)."""
    loops = clean_loops(loops)
    if not loops or style["pattern"] in ("solid", WIPEOUT, GRADIENT):
        return []
    if style["pattern"] == DXF:
        return [seg for family in style["lines"] for seg in _family(loops, family, style)]
    angle, spacing, origin = style["angle"], style["spacing"], style["origin"]
    if style["pattern"] == "cross":
        return _lines(loops, angle, spacing, origin) + _lines(loops, angle + 90.0, spacing, origin)
    if style["pattern"] == "brick":
        return _brick(loops, angle, spacing, origin)
    return _lines(loops, angle, spacing, origin)


def prims(data: dict, offset=(0.0, 0.0)) -> list:
    """Primitives de la hachure (ses traits ; un point si rien a tracer, pour que l'entite ait toujours une primitive)."""
    loops = clean_loops(data.get("loops"))
    ox, oy = offset
    segments = pattern_segments(loops, style_of(data))
    if not segments:
        p = loops[0][0] if loops else (0.0, 0.0)
        return [("segment", (p[0] + ox, p[1] + oy), (p[0] + ox, p[1] + oy))]
    return [("segment", (a[0] + ox, a[1] + oy), (b[0] + ox, b[1] + oy)) for a, b in segments]


def centroid(loops):
    box = bounds(loops)
    return ((box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0)


def distance_inside(data: dict, p) -> float:
    """Distance de `p` (dans la zone) au motif le plus proche, calculee sans parcourir les traits (motifs reguliers) ;
    `math.inf` pour un remplissage plein."""
    s = style_of(data)
    if s["pattern"] in ("solid", WIPEOUT, GRADIENT):
        return math.inf
    c, sn = math.cos(math.radians(-s["angle"])), math.sin(math.radians(-s["angle"]))
    x, y = p[0] - s["origin"][0], p[1] - s["origin"][1]
    fx, fy = x * c - y * sn, x * sn + y * c
    sp = s["spacing"]

    def gap(v):
        r = v % sp
        return min(r, sp - r)
    if s["pattern"] == DXF:                                     # trait le plus proche de ses familles (tirets ignores)
        best = math.inf
        for family in s["lines"]:
            angle, base, _along, across, _dashes = family_frame(family, s)
            if abs(across) <= geo.EPS:
                continue
            r = math.radians(angle)
            v = (-(p[0] - base[0]) * math.sin(r) + (p[1] - base[1]) * math.cos(r)) % abs(across)
            best = min(best, v, abs(across) - v)
        return best
    if s["pattern"] == "cross":
        return min(gap(fy), gap(fx))
    return gap(fy)


def transform(data: dict, point_fn, angle_fn, flips: bool = False) -> dict:
    """Hachure transformee (deplacement, rotation, miroir…). Retournee (`flips`), un motif d'AutoCAD l'est aussi dans
    son repere : angles et ordonnees de ses familles changent de signe."""
    out = {"loops": [[list(point_fn((p[0], p[1]))) for p in loop] for loop in clean_loops(data.get("loops"))],
           "hatch_origin": list(point_fn(_pt(data.get("hatch_origin")))),
           "hatch_angle": angle_fn(_num(data.get("hatch_angle"), DEFAULTS["hatch_angle"])) % 360.0}
    if flips and data.get("hatch_lines"):
        out["hatch_lines"] = flipped_families(data.get("hatch_lines"))
    return out


def flipped_families(lines) -> list:
    return [{"angle": (-f["angle"]) % 360.0, "base": [f["base"][0], -f["base"][1]],
             "offset": [f["offset"][0], -f["offset"][1]], "dashes": list(f["dashes"])} for f in clean_families(lines)]


def families_from_world(lines, origin, angle: float, spacing: float) -> list:
    """Familles en coordonnees du DESSIN (comme un HATCH de DXF : angle absolu, base, decalage deja tourne, tirets)
    -> repere de la hachure (`hatch_lines`)."""
    c, s = math.cos(math.radians(-angle)), math.sin(math.radians(-angle))
    out = []
    for a, base, offset, dashes in lines:
        bx, by = base[0] - origin[0], base[1] - origin[1]
        out.append({"angle": (a - angle) % 360.0,
                    "base": [(bx * c - by * s) / spacing, (bx * s + by * c) / spacing],
                    "offset": [(offset[0] * c - offset[1] * s) / spacing, (offset[0] * s + offset[1] * c) / spacing],
                    "dashes": [d / spacing for d in dashes]})
    return out


def families_to_world(data: dict) -> list:
    """Inverse de `families_from_world` : [(angle, base, decalage, tirets)] en coordonnees du document (export)."""
    style = style_of(data)
    r = math.radians(style["angle"])
    out = []
    for family in style["lines"]:
        a, base, _along, _across, dashes = family_frame(family, style)
        ox, oy = family["offset"][0] * style["spacing"], family["offset"][1] * style["spacing"]
        out.append((a, base, (ox * math.cos(r) - oy * math.sin(r), ox * math.sin(r) + oy * math.cos(r)), dashes))
    return out


def translate(data: dict, delta) -> dict:
    return {"loops": [[[p[0] + delta[0], p[1] + delta[1]] for p in loop] for loop in clean_loops(data.get("loops"))],
            "hatch_origin": [_pt(data.get("hatch_origin"))[0] + delta[0], _pt(data.get("hatch_origin"))[1] + delta[1]]}


# ==========================================================================
# Point interne : la zone fermee qui entoure un point
# ==========================================================================

def _key(p, eps):
    return (round(p[0] / eps), round(p[1] / eps))


def _node(segments, eps):
    """Traits coupes a toutes leurs intersections (et aux extremites qui les touchent) : [(a, b)] sans croisement."""
    count = len(segments)
    if count == 0:
        return []
    xs = [v for a, b in segments for v in (a[0], b[0])]
    ys = [v for a, b in segments for v in (a[1], b[1])]
    width, height = max(xs) - min(xs), max(ys) - min(ys)
    side = max(1, int(math.sqrt(count)))
    cell = max(max(width, height) / side, eps * 10.0, 1e-9)
    grid: dict = {}
    for index, (a, b) in enumerate(segments):
        i0, i1 = int((min(a[0], b[0]) - min(xs)) // cell), int((max(a[0], b[0]) - min(xs)) // cell)
        j0, j1 = int((min(a[1], b[1]) - min(ys)) // cell), int((max(a[1], b[1]) - min(ys)) // cell)
        for i in range(i0, i1 + 1):
            for j in range(j0, j1 + 1):
                grid.setdefault((i, j), []).append(index)
    splits = [[] for _ in segments]
    seen = set()
    for members in grid.values():
        for m in range(len(members)):
            for n in range(m + 1, len(members)):
                i, j = members[m], members[n]
                if (i, j) in seen:
                    continue
                seen.add((i, j))
                _intersect(segments[i], segments[j], i, j, splits, eps)
    out = []
    for (a, b), params in zip(segments, splits):
        pts = sorted({min(1.0, max(0.0, t)) for t in params} | {0.0, 1.0})
        prev = a
        for t in pts[1:]:
            q = b if t >= 1.0 else geo.lerp(a, b, t)
            if geo.distance(prev, q) > eps:
                out.append((prev, q))
            prev = q
    return out


def _intersect(s1, s2, i, j, splits, eps):
    a, b = s1
    c, d = s2
    r, s = geo.sub(b, a), geo.sub(d, c)
    lr, ls = geo.length(r), geo.length(s)
    if lr <= eps or ls <= eps:
        return
    if (max(a[0], b[0]) + eps < min(c[0], d[0]) or max(c[0], d[0]) + eps < min(a[0], b[0])
            or max(a[1], b[1]) + eps < min(c[1], d[1]) or max(c[1], d[1]) + eps < min(a[1], b[1])):
        return
    denom = geo.cross(r, s)
    if abs(denom) > 1e-9 * lr * ls:
        qp = geo.sub(c, a)
        t = geo.cross(qp, s) / denom
        u = geo.cross(qp, r) / denom
        if -eps / lr <= t <= 1 + eps / lr and -eps / ls <= u <= 1 + eps / ls:
            splits[i].append(t)
            splits[j].append(u)
        return
    if geo.distance_point_line(c, a, b) > eps:                               # paralleles distincts
        return
    for point in (c, d):                                                     # colineaires : extremites de l'un sur l'autre
        t = geo.project_param(point, a, b)
        if 0.0 < t < 1.0:
            splits[i].append(t)
    for point in (a, b):
        u = geo.project_param(point, c, d)
        if 0.0 < u < 1.0:
            splits[j].append(u)


def _graph(pieces, eps):
    coords, adj = {}, {}
    for a, b in pieces:
        ka, kb = _key(a, eps), _key(b, eps)
        if ka == kb:
            continue
        coords.setdefault(ka, a)
        coords.setdefault(kb, b)
        adj.setdefault(ka, set()).add(kb)
        adj.setdefault(kb, set()).add(ka)
    stack = [k for k, nb in adj.items() if len(nb) < 2]                       # impasses retirees (traits qui pendent)
    while stack:
        k = stack.pop()
        if k not in adj:
            continue
        for other in adj.pop(k):
            if other in adj:
                adj[other].discard(k)
                if len(adj[other]) < 2:
                    stack.append(other)
    return coords, adj


def _components(adj):
    label, comps = {}, []
    for start in adj:
        if start in label:
            continue
        stack, members = [start], set()
        while stack:
            k = stack.pop()
            if k in members:
                continue
            members.add(k)
            stack.extend(adj[k] - members)
        for k in members:
            label[k] = len(comps)
        comps.append(members)
    return label, comps


def _ray(point, coords, adj, allowed):
    """Arete (u, v) du graphe la plus proche a droite de `point` (rayon vers +x), restreinte a `allowed`."""
    best = None
    for u in allowed:
        for v in adj[u]:
            if u >= v:
                continue
            a, b = coords[u], coords[v]
            if (a[1] > point[1]) != (b[1] > point[1]):
                x = a[0] + (point[1] - a[1]) * (b[0] - a[0]) / (b[1] - a[1])
                if x >= point[0] and (best is None or x - point[0] < best[0]):
                    best = (x - point[0], u, v)
    return best


def _trace(coords, adj, start):
    """Contour de la face a GAUCHE de l'arete orientee `start` : a chaque sommet, le virage a gauche le plus serre."""
    u, v = start
    keys = [u]
    cur = start
    for _ in range(100000):
        u, v = cur
        din = math.atan2(coords[v][1] - coords[u][1], coords[v][0] - coords[u][0])
        best, best_turn = None, None
        for w in adj[v]:
            if w == u and len(adj[v]) > 1:
                continue
            dout = math.atan2(coords[w][1] - coords[v][1], coords[w][0] - coords[v][0])
            turn = (dout - din + math.pi) % (2 * math.pi) - math.pi
            if turn == -math.pi:
                turn = math.pi
            if best is None or turn > best_turn:
                best, best_turn = w, turn
        nxt = (v, best)
        if nxt == start:
            return [coords[k] for k in keys]
        keys.append(v)
        cur = nxt
    return None


def _oriented(point, coords, u, v):
    a, b = coords[u], coords[v]
    return (u, v) if geo.cross(geo.sub(b, a), geo.sub(point, a)) >= 0 else (v, u)


def find_region(segments, point, eps: float = 1e-6):
    """(contour exterieur, [trous]) de la plus petite zone fermee autour de `point`, ou un message. `segments` =
    [(a, b)] : le trace de toutes les entites visibles (courbes decoupees)."""
    segments = [(tuple(a), tuple(b)) for a, b in segments]
    if not segments:
        return "Rien à hachurer : aucun objet."
    span = max(max(abs(v) for pt in seg for v in pt) for seg in segments)
    eps = max(eps, span * 1e-9)
    coords, adj = _graph(_node(segments, eps), eps)
    if not adj:
        return "Aucune zone fermée autour de ce point."
    label, comps = _components(adj)
    excluded: set = set()
    holes = []
    outer = None
    for _ in range(64):
        allowed = [k for k in adj if label[k] not in excluded]
        hit = _ray(point, coords, adj, allowed)
        if hit is None:
            return "Aucune zone fermée autour de ce point."
        loop = _trace(coords, adj, _oriented(point, coords, hit[1], hit[2]))
        if loop is None or len(loop) < 3:
            return "Zone mal définie (traits qui ne se referment pas)."
        if signed_area(loop) < 0:                                               # contour d'un ilot : trou, on continue
            holes.append(loop)
            excluded.add(label[hit[1]])
            continue
        outer = loop
        outer_label = label[hit[1]]
        break
    if outer is None:
        return "Aucune zone fermée autour de ce point."
    if not inside([outer], point):
        return "Aucune zone fermée autour de ce point."
    for number, members in enumerate(comps):                                    # ilots que le rayon n'a pas touches
        if number in excluded or number == outer_label:
            continue
        probe = min((coords[k] for k in members), key=lambda p: (p[0], p[1]))
        if not inside([outer], probe):
            continue
        if not all(inside([outer], coords[k]) for k in members):
            continue
        start = (probe[0] - max(eps * 20.0, 1e-9), probe[1])
        hit = _ray(start, coords, adj, [k for k in members])
        if hit is None:
            continue
        loop = _trace(coords, adj, _oriented(start, coords, hit[1], hit[2]))
        if loop is not None and len(loop) >= 3 and signed_area(loop) < 0:
            holes.append(loop)
    return outer, holes


# ==========================================================================
# Objets choisis : leurs contours fermes
# ==========================================================================

def chain_loops(segments, eps: float = 1e-6) -> list:
    """Contours fermes que forment des traits mis bout a bout (chaque sommet a exactement deux traits)."""
    adj, coords = {}, {}
    for a, b in segments:
        ka, kb = _key(a, eps), _key(b, eps)
        if ka == kb:
            continue
        coords.setdefault(ka, a)
        coords.setdefault(kb, b)
        adj.setdefault(ka, []).append(kb)
        adj.setdefault(kb, []).append(ka)
    done: set = set()
    loops = []
    for start in adj:
        if start in done or len(adj[start]) != 2:
            continue
        path, prev, cur = [start], None, start
        closed = False
        while True:
            options = [w for w in adj[cur] if w != prev] if prev is not None else adj[cur][:1]
            if not options:
                break
            nxt = options[0]
            if nxt == start:
                closed = True
                break
            if nxt in path or len(adj.get(nxt, [])) != 2:
                break
            path.append(nxt)
            prev, cur = cur, nxt
        done.update(path)
        if closed and len(path) >= 3:
            loops.append([coords[k] for k in path])
    return loops
