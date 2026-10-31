"""Géométrie des tracés (SANS Qt) : nœuds à poignées (format de `model.py`), segments cubiques, cadres exacts,
point le plus proche, insertion / suppression / conversion de points, transformations affines, formes de base,
données SVG.

Un nœud = [ax, ay, ix, iy, ox, oy, lisse] (ancrage, poignée d'entrée, poignée de sortie). Le segment de n0 à n1 est
la cubique (a0, o0, i1, a1) ; une poignée confondue avec son ancrage = segment droit de ce côté.
Matrice affine m = (a, b, c, d, e, f) : x' = a x + c y + e ; y' = b x + d y + f (ordre de SVG / QTransform)."""
from __future__ import annotations

import math

KAPPA = 0.5522847498                                    # poignées d'un quart de cercle en cubique
EPS = 1e-9


# ---------------------------------------------------------------- nœuds et segments
def node(ax: float, ay: float, ix=None, iy=None, ox=None, oy=None, smooth: int = 0) -> list:
    return [float(ax), float(ay), float(ax if ix is None else ix), float(ay if iy is None else iy),
            float(ax if ox is None else ox), float(ay if oy is None else oy), 1 if smooth else 0]


def anchor(n) -> tuple[float, float]:
    return n[0], n[1]


def has_in(n) -> bool:
    return abs(n[2] - n[0]) > EPS or abs(n[3] - n[1]) > EPS


def has_out(n) -> bool:
    return abs(n[4] - n[0]) > EPS or abs(n[5] - n[1]) > EPS


def segment_count(sub: dict) -> int:
    n = len(sub["nodes"])
    return n if sub.get("closed") and n > 1 else max(0, n - 1)


def segment(sub: dict, index: int) -> tuple:
    """(p0, c1, c2, p3) du segment `index` (du nœud index au suivant)."""
    nodes = sub["nodes"]
    a, b = nodes[index], nodes[(index + 1) % len(nodes)]
    return (a[0], a[1]), (a[4], a[5]), (b[2], b[3]), (b[0], b[1])


def segments(sub: dict):
    for i in range(segment_count(sub)):
        yield segment(sub, i)


def is_straight(seg) -> bool:
    p0, c1, c2, p3 = seg
    return (abs(c1[0] - p0[0]) < EPS and abs(c1[1] - p0[1]) < EPS
            and abs(c2[0] - p3[0]) < EPS and abs(c2[1] - p3[1]) < EPS)


def lerp(a, b, t):
    return a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t


def cubic_at(p0, c1, c2, p3, t):
    u = 1.0 - t
    a, b, c, d = u * u * u, 3 * u * u * t, 3 * u * t * t, t * t * t
    return a * p0[0] + b * c1[0] + c * c2[0] + d * p3[0], a * p0[1] + b * c1[1] + c * c2[1] + d * p3[1]


def split_cubic(p0, c1, c2, p3, t):
    """De Casteljau : deux cubiques qui suivent exactement la première."""
    p01, p12, p23 = lerp(p0, c1, t), lerp(c1, c2, t), lerp(c2, p3, t)
    p012, p123 = lerp(p01, p12, t), lerp(p12, p23, t)
    mid = lerp(p012, p123, t)
    return (p0, p01, p012, mid), (mid, p123, p23, p3)


def _extrema_1d(a, b, c, d) -> list[float]:
    """Valeurs de t dans ]0, 1[ où la dérivée d'une composante de la cubique s'annule."""
    qa = -a + 3 * b - 3 * c + d
    qb = 2 * (a - 2 * b + c)
    qc = b - a
    out = []
    if abs(qa) < EPS:
        if abs(qb) > EPS:
            out.append(-qc / qb)
    else:
        disc = qb * qb - 4 * qa * qc
        if disc >= 0:
            r = math.sqrt(disc)
            out += [(-qb + r) / (2 * qa), (-qb - r) / (2 * qa)]
    return [t for t in out if 0.0 < t < 1.0]


def cubic_bounds(p0, c1, c2, p3) -> tuple[float, float, float, float]:
    xs, ys = [p0[0], p3[0]], [p0[1], p3[1]]
    for t in _extrema_1d(p0[0], c1[0], c2[0], p3[0]) + _extrema_1d(p0[1], c1[1], c2[1], p3[1]):
        x, y = cubic_at(p0, c1, c2, p3, t)
        xs.append(x)
        ys.append(y)
    return min(xs), min(ys), max(xs), max(ys)


def bounds(subpaths) -> tuple[float, float, float, float] | None:
    """Cadre EXACT de la géométrie (sans l'épaisseur du contour) ; None si vide."""
    box = None
    for sub in subpaths:
        nodes = sub["nodes"]
        if len(nodes) == 1:
            x, y = nodes[0][0], nodes[0][1]
            box = _union(box, (x, y, x, y))
        for seg in segments(sub):
            box = _union(box, cubic_bounds(*seg))
    return box


def control_bounds(subpaths) -> tuple[float, float, float, float] | None:
    """Cadre de TOUS les points (ancrages et poignées) : contient la courbe ; sert au dessin des poignées."""
    xs = [v for sub in subpaths for n in sub["nodes"] for v in (n[0], n[2], n[4])]
    ys = [v for sub in subpaths for n in sub["nodes"] for v in (n[1], n[3], n[5])]
    return (min(xs), min(ys), max(xs), max(ys)) if xs else None


def _union(a, b):
    if a is None:
        return b
    return min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])


def union_bounds(boxes):
    out = None
    for box in boxes:
        if box is not None:
            out = _union(out, box)
    return out


def flatten_segment(seg, tolerance: float = 0.25) -> list[tuple[float, float]]:
    """Points du segment (sans le premier), assez serrés pour rester à `tolerance` de la courbe."""
    if is_straight(seg):
        return [seg[3]]
    p0, c1, c2, p3 = seg
    d = max(math.dist(p0, c1) + math.dist(c1, c2) + math.dist(c2, p3), EPS)
    steps = max(2, min(200, int(math.ceil(math.sqrt(d / max(tolerance, 1e-3)) * 1.2))))
    return [cubic_at(p0, c1, c2, p3, i / steps) for i in range(1, steps + 1)]


def flatten(sub: dict, tolerance: float = 0.25) -> list[tuple[float, float]]:
    nodes = sub["nodes"]
    if not nodes:
        return []
    pts = [(nodes[0][0], nodes[0][1])]
    for seg in segments(sub):
        pts += flatten_segment(seg, tolerance)
    return pts


def length(sub: dict) -> float:
    pts = flatten(sub, 0.1)
    return sum(math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))


# ---------------------------------------------------------------- recherche
def nearest_on_segment(seg, pos, steps: int = 24) -> tuple[float, float, tuple[float, float]]:
    """(distance, t, point) du point du segment le plus proche de `pos` (échantillonnage puis affinage)."""
    best = (float("inf"), 0.0, seg[0])
    for i in range(steps + 1):
        t = i / steps
        p = cubic_at(*seg, t)
        d = math.dist(p, pos)
        if d < best[0]:
            best = (d, t, p)
    lo, hi = max(0.0, best[1] - 1.0 / steps), min(1.0, best[1] + 1.0 / steps)
    for _ in range(18):                                 # recherche ternaire autour du meilleur échantillon
        m1, m2 = lo + (hi - lo) / 3, hi - (hi - lo) / 3
        if math.dist(cubic_at(*seg, m1), pos) < math.dist(cubic_at(*seg, m2), pos):
            hi = m2
        else:
            lo = m1
    t = (lo + hi) / 2
    p = cubic_at(*seg, t)
    d = math.dist(p, pos)
    return (d, t, p) if d < best[0] else best


def nearest(subpaths, pos) -> tuple | None:
    """(distance, sous-tracé, segment, t, point) le plus proche de `pos` ; None si aucun segment."""
    best = None
    for si, sub in enumerate(subpaths):
        for gi in range(segment_count(sub)):
            seg = segment(sub, gi)
            x0, y0, x1, y1 = control_bounds([{"nodes": [_seg_node(seg[0], seg[1]), _seg_node(seg[3], seg[2])]}])
            if best is not None:                        # segment trop loin pour battre le meilleur : sauté
                dx = max(x0 - pos[0], 0.0, pos[0] - x1)
                dy = max(y0 - pos[1], 0.0, pos[1] - y1)
                if math.hypot(dx, dy) > best[0]:
                    continue
            d, t, p = nearest_on_segment(seg, pos)
            if best is None or d < best[0]:
                best = (d, si, gi, t, p)
    return best


def _seg_node(a, h):
    return [a[0], a[1], h[0], h[1], h[0], h[1], 0]


def point_inside(subpaths, pos, rule: str = "nonzero", tolerance: float = 0.5) -> bool:
    """Le point est dans la surface (sous-tracés ouverts fermés implicitement, comme le fond d'Illustrator)."""
    winding = 0
    crossings = 0
    x, y = pos
    for sub in subpaths:
        pts = flatten(sub, tolerance)
        if len(pts) < 3:
            continue
        for i in range(len(pts)):
            (x0, y0), (x1, y1) = pts[i], pts[(i + 1) % len(pts)]
            if (y0 <= y) != (y1 <= y):
                xc = x0 + (y - y0) * (x1 - x0) / (y1 - y0)
                if xc > x:
                    crossings += 1
                    winding += 1 if y1 > y0 else -1
    return (crossings % 2 == 1) if rule == "evenodd" else winding != 0


# ---------------------------------------------------------------- édition des nœuds
def insert_node(sub: dict, seg_index: int, t: float) -> int:
    """Ajoute un point sur le segment, sans changer la forme ; renvoie l'indice du nouveau nœud."""
    nodes = sub["nodes"]
    j = (seg_index + 1) % len(nodes)
    seg = segment(sub, seg_index)
    straight = is_straight(seg)
    left, right = split_cubic(*seg, t)
    a, b = nodes[seg_index], nodes[j]
    mid = left[3]
    if straight:
        new = node(mid[0], mid[1])
    else:
        a[4], a[5] = left[1]
        b[2], b[3] = right[2]
        new = node(mid[0], mid[1], left[2][0], left[2][1], right[1][0], right[1][1], smooth=1)
    nodes.insert(seg_index + 1, new)
    return seg_index + 1


def delete_node(sub: dict, index: int) -> bool:
    """Retire un point d'ancrage ; faux s'il n'en reste qu'un (l'appelant retire alors le sous-tracé)."""
    nodes = sub["nodes"]
    del nodes[index]
    if len(nodes) < 2:
        sub["closed"] = False
    return len(nodes) >= 1


def move_node(n: list, dx: float, dy: float):
    """Déplace un ancrage AVEC ses poignées."""
    for k in (0, 2, 4):
        n[k] += dx
        n[k + 1] += dy


def set_handle(n: list, which: str, x: float, y: float, break_link: bool = False):
    """Pose la poignée « in » ou « out » ; nœud lisse (et pas `break_link`) : l'autre reste alignée (sa longueur
    gardée), comme la Sélection directe d'Illustrator ; `break_link` = point d'angle (Alt)."""
    k = 2 if which == "in" else 4
    o = 4 if which == "in" else 2
    n[k], n[k + 1] = x, y
    if break_link:
        n[6] = 0
        return
    if n[6]:
        other = math.hypot(n[o] - n[0], n[o + 1] - n[1])
        dx, dy = x - n[0], y - n[1]
        d = math.hypot(dx, dy)
        if d > EPS and other > EPS:
            n[o], n[o + 1] = n[0] - dx / d * other, n[1] - dy / d * other


def set_symmetric(n: list, x: float, y: float):
    """Plume : glisser tire la poignée de SORTIE, l'entrée est son symétrique (nœud lisse)."""
    n[4], n[5] = x, y
    n[2], n[3] = 2 * n[0] - x, 2 * n[1] - y
    n[6] = 1 if has_out(n) else 0


def retract(n: list, which: str = "both"):
    if which in ("in", "both"):
        n[2], n[3] = n[0], n[1]
    if which in ("out", "both"):
        n[4], n[5] = n[0], n[1]
    n[6] = 0


def smooth_node(sub: dict, index: int):
    """Convertit en point LISSE : poignées parallèles à la corde des voisins, au tiers des distances (outil Conversion
    de point d'ancrage, clic sur un point d'angle)."""
    nodes = sub["nodes"]
    n = nodes[index]
    count = len(nodes)
    closed = sub.get("closed")
    prev = nodes[index - 1] if (index > 0 or closed) and count > 1 else None
    nxt = nodes[(index + 1) % count] if (index < count - 1 or closed) and count > 1 else None
    if prev is None and nxt is None:
        return
    p = (prev[0], prev[1]) if prev is not None else (2 * n[0] - nxt[0], 2 * n[1] - nxt[1])
    q = (nxt[0], nxt[1]) if nxt is not None else (2 * n[0] - prev[0], 2 * n[1] - prev[1])
    dx, dy = q[0] - p[0], q[1] - p[1]
    d = math.hypot(dx, dy)
    if d < EPS:
        return
    ux, uy = dx / d, dy / d
    lin = math.dist(p, (n[0], n[1])) / 3
    lout = math.dist(q, (n[0], n[1])) / 3
    n[2], n[3] = n[0] - ux * lin, n[1] - uy * lin
    n[4], n[5] = n[0] + ux * lout, n[1] + uy * lout
    n[6] = 1


def reverse(sub: dict):
    nodes = sub["nodes"]
    nodes.reverse()
    for n in nodes:
        n[2], n[3], n[4], n[5] = n[4], n[5], n[2], n[3]
    if sub.get("closed") and nodes:                     # même point de départ
        nodes.insert(0, nodes.pop())


def join(a: dict, b: dict, a_end: bool, b_start: bool) -> dict:
    """Relie deux sous-tracés OUVERTS (Joindre, Ctrl+J) : fin (ou début) de `a` à début (ou fin) de `b`."""
    a = {"closed": False, "nodes": [list(n) for n in a["nodes"]]}
    b = {"closed": False, "nodes": [list(n) for n in b["nodes"]]}
    if not a_end:
        reverse(a)
    if not b_start:
        reverse(b)
    last, first = a["nodes"][-1], b["nodes"][0]
    if math.dist((last[0], last[1]), (first[0], first[1])) < 0.01:      # points confondus : un seul
        last[4], last[5] = first[4], first[5]
        b["nodes"].pop(0)
    a["nodes"] += b["nodes"]
    return a


def close_if_touching(sub: dict, tolerance: float = 0.01) -> bool:
    """Ferme un sous-tracé dont les extrémités se touchent (fusionnées en un point)."""
    nodes = sub["nodes"]
    if sub.get("closed") or len(nodes) < 3:
        return False
    first, last = nodes[0], nodes[-1]
    if math.dist((first[0], first[1]), (last[0], last[1])) > tolerance:
        return False
    first[2], first[3] = last[2], last[3]
    nodes.pop()
    sub["closed"] = True
    return True


# ---------------------------------------------------------------- transformations
IDENTITY = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def multiply(m1, m2):
    """m1 puis m2."""
    a1, b1, c1, d1, e1, f1 = m1
    a2, b2, c2, d2, e2, f2 = m2
    return (a1 * a2 + b1 * c2, a1 * b2 + b1 * d2, c1 * a2 + d1 * c2, c1 * b2 + d1 * d2,
            e1 * a2 + f1 * c2 + e2, e1 * b2 + f1 * d2 + f2)


def translate(dx, dy):
    return (1.0, 0.0, 0.0, 1.0, float(dx), float(dy))


def scale(sx, sy, cx=0.0, cy=0.0):
    return (float(sx), 0.0, 0.0, float(sy), cx - sx * cx, cy - sy * cy)


def rotate(degrees, cx=0.0, cy=0.0):
    """Rotation de `degrees` (sens horaire à l'écran : Y vers le bas)."""
    a = math.radians(degrees)
    c, s = math.cos(a), math.sin(a)
    return (c, s, -s, c, cx - c * cx + s * cy, cy - s * cx - c * cy)


def shear(kx, ky=0.0, cx=0.0, cy=0.0):
    return multiply(multiply(translate(-cx, -cy), (1.0, ky, kx, 1.0, 0.0, 0.0)), translate(cx, cy))


def apply(m, x, y):
    a, b, c, d, e, f = m
    return a * x + c * y + e, b * x + d * y + f


def transform(subpaths, m) -> None:
    """Applique la matrice à tous les nœuds (ancrages et poignées), sur place."""
    for sub in subpaths:
        for n in sub["nodes"]:
            for k in (0, 2, 4):
                n[k], n[k + 1] = apply(m, n[k], n[k + 1])


def copy_subpaths(subpaths) -> list:
    return [{"closed": bool(s.get("closed")), "nodes": [list(n) for n in s["nodes"]]} for s in subpaths]


# ---------------------------------------------------------------- formes de base
def rect(x, y, w, h, radius: float = 0.0) -> list:
    if w < 0:
        x, w = x + w, -w
    if h < 0:
        y, h = y + h, -h
    r = max(0.0, min(float(radius), w / 2, h / 2))
    if r <= EPS:
        nodes = [node(x, y), node(x + w, y), node(x + w, y + h), node(x, y + h)]
        return [{"closed": True, "nodes": nodes}]
    k = r * KAPPA
    nodes = [node(x + r, y, x + r - k, y), node(x + w - r, y, None, None, x + w - r + k, y),
             node(x + w, y + r, x + w, y + r - k), node(x + w, y + h - r, None, None, x + w, y + h - r + k),
             node(x + w - r, y + h, x + w - r + k, y + h), node(x + r, y + h, None, None, x + r - k, y + h),
             node(x, y + h - r, x, y + h - r + k), node(x, y + r, None, None, x, y + r - k)]
    return [{"closed": True, "nodes": nodes}]


def ellipse(cx, cy, rx, ry) -> list:
    rx, ry = abs(rx), abs(ry)
    kx, ky = rx * KAPPA, ry * KAPPA
    nodes = [node(cx, cy - ry, cx - kx, cy - ry, cx + kx, cy - ry, 1),
             node(cx + rx, cy, cx + rx, cy - ky, cx + rx, cy + ky, 1),
             node(cx, cy + ry, cx + kx, cy + ry, cx - kx, cy + ry, 1),
             node(cx - rx, cy, cx - rx, cy + ky, cx - rx, cy - ky, 1)]
    return [{"closed": True, "nodes": nodes}]


def polygon(cx, cy, radius, sides: int = 6, rotation: float = 0.0) -> list:
    sides = max(3, int(sides))
    nodes = []
    for i in range(sides):
        a = math.radians(rotation - 90 + 360 * i / sides)
        nodes.append(node(cx + radius * math.cos(a), cy + radius * math.sin(a)))
    return [{"closed": True, "nodes": nodes}]


def star(cx, cy, outer, inner, points: int = 5, rotation: float = 0.0) -> list:
    points = max(2, int(points))
    nodes = []
    for i in range(points * 2):
        r = outer if i % 2 == 0 else inner
        a = math.radians(rotation - 90 + 180 * i / points)
        nodes.append(node(cx + r * math.cos(a), cy + r * math.sin(a)))
    return [{"closed": True, "nodes": nodes}]


def line(x0, y0, x1, y1) -> list:
    return [{"closed": False, "nodes": [node(x0, y0), node(x1, y1)]}]


def from_cubics(cubics, closed: bool = False) -> dict:
    """Sous-tracé depuis une suite de cubiques (p0, c1, c2, p3) qui se suivent (crayon, ajustement)."""
    if not cubics:
        return {"closed": False, "nodes": []}
    nodes = [node(*cubics[0][0])]
    for p0, c1, c2, p3 in cubics:
        nodes[-1][4], nodes[-1][5] = c1
        nodes.append(node(p3[0], p3[1], c2[0], c2[1]))
    for n in nodes[1:-1]:                                # jointures tangentes : lisses
        a = math.atan2(n[1] - n[3], n[0] - n[2])
        b = math.atan2(n[5] - n[1], n[4] - n[0])
        n[6] = 1 if abs(math.remainder(a - b, 2 * math.pi)) < 0.05 else 0
    sub = {"closed": False, "nodes": nodes}
    if closed:
        close_if_touching(sub, tolerance=1.0)
    return sub


# ---------------------------------------------------------------- SVG
def _num(v: float) -> str:
    text = f"{v:.3f}".rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def svg_d(subpaths, dx: float = 0.0, dy: float = 0.0) -> str:
    """Attribut `d` d'un chemin SVG (M, L, C, Z), décalé de (dx, dy)."""
    out = []
    for sub in subpaths:
        nodes = sub["nodes"]
        if not nodes:
            continue
        out.append(f"M{_num(nodes[0][0] + dx)} {_num(nodes[0][1] + dy)}")
        count = segment_count(sub)
        for index in range(count):
            p0, c1, c2, p3 = segment(sub, index)
            if is_straight((p0, c1, c2, p3)):
                if sub.get("closed") and index == count - 1:
                    continue                            # dernier segment droit d'un tracé fermé : Z le trace
                out.append(f"L{_num(p3[0] + dx)} {_num(p3[1] + dy)}")
            else:
                out.append(f"C{_num(c1[0] + dx)} {_num(c1[1] + dy)} {_num(c2[0] + dx)} {_num(c2[1] + dy)} "
                           f"{_num(p3[0] + dx)} {_num(p3[1] + dy)}")
        if sub.get("closed"):
            out.append("Z")
    return "".join(out)
