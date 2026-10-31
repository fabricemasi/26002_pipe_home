"""Bézier (sans Qt) sur les contours UFO (ufoLib2) : segments, types de nœuds (coin / lisse / symétrique),
ajout / suppression / division, ouverture / fermeture, sens, point de départ, cubique <-> quadratique.

Rappel UFO : un contour est une liste de points ; un point SUR la courbe porte le type du segment qui s'y TERMINE
(« line », « curve », « qcurve ») ; « move » = premier point d'un contour OUVERT ; les poignées ont type None."""
from __future__ import annotations

import math

from fontTools.cu2qu import curve_to_quadratic
from fontTools.pens.basePen import decomposeQuadraticSegment
from fontTools.pens.pointPen import ReverseContourPointPen
from ufoLib2.objects import Contour, Point

ON = ("move", "line", "curve", "qcurve")


def is_on(point) -> bool:
    return point.type is not None


def is_closed(contour) -> bool:
    return bool(len(contour)) and contour[0].type != "move"


def on_indexes(contour) -> list[int]:
    return [i for i, p in enumerate(contour) if p.type is not None]


def segments(contour) -> list[tuple[int, list[int], int, str]]:
    """Segments (début, poignées, fin, type) en indices du contour, dans l'ordre. Un contour fermé reboucle."""
    ons = on_indexes(contour)
    if not ons:
        return []
    n = len(contour)
    result = []
    closed = is_closed(contour)
    for k, end in enumerate(ons):
        if k == 0 and not closed:
            continue
        start = ons[k - 1]
        if start < end:
            offs = list(range(start + 1, end))
        else:                                             # segment qui reboucle par la fin de la liste
            offs = list(range(start + 1, n)) + list(range(0, end))
        result.append((start, offs, end, contour[end].type))
    return result


def segment_points(contour, seg) -> list[tuple[float, float]]:
    start, offs, end, _kind = seg
    return [(contour[i].x, contour[i].y) for i in [start, *offs, end]]


# -- géométrie des courbes --

def lerp(a, b, t):
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def split_cubic(p0, p1, p2, p3, t):
    """De Casteljau : deux cubiques (exactes)."""
    a, b, c = lerp(p0, p1, t), lerp(p1, p2, t), lerp(p2, p3, t)
    d, e = lerp(a, b, t), lerp(b, c, t)
    f = lerp(d, e, t)
    return (p0, a, d, f), (f, e, c, p3)


def split_quad(p0, p1, p2, t):
    a, b = lerp(p0, p1, t), lerp(p1, p2, t)
    c = lerp(a, b, t)
    return (p0, a, c), (c, b, p2)


def cubic_at(p0, p1, p2, p3, t):
    u = 1 - t
    return (u ** 3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t ** 3 * p3[0],
            u ** 3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t ** 3 * p3[1])


def quad_at(p0, p1, p2, t):
    u = 1 - t
    return (u * u * p0[0] + 2 * u * t * p1[0] + t * t * p2[0], u * u * p0[1] + 2 * u * t * p1[1] + t * t * p2[1])


def quad_segments(points):
    """Segment qcurve UFO (poignées implicites possibles) -> liste de quadratiques (p0, q, p1)."""
    p0, rest = points[0], points[1:]
    if len(rest) == 1:
        return []                                         # dégénéré (aucune poignée) : traité comme une ligne
    out = []
    for q, p in decomposeQuadraticSegment(rest):
        out.append((p0, q, p))
        p0 = p
    return out


def flatten_segment(points, kind, steps: int = 16) -> list[tuple[float, float]]:
    """Points d'une approximation polygonale (sans le premier point)."""
    if kind == "curve" and len(points) == 4:
        return [cubic_at(*points, i / steps) for i in range(1, steps + 1)]
    if kind == "qcurve" and len(points) >= 3:
        out = []
        for quad in quad_segments(points):
            out.extend(quad_at(*quad, i / steps) for i in range(1, steps + 1))
        return out
    return [points[-1]]


def flatten_contour(contour, steps: int = 16) -> list[tuple[float, float]]:
    segs = segments(contour)
    if not segs:
        return [(p.x, p.y) for p in contour]
    first = contour[segs[0][0]]
    poly = [(first.x, first.y)]
    for seg in segs:
        poly.extend(flatten_segment(segment_points(contour, seg), seg[3], steps))
    return poly


def nearest_on_segment(contour, seg, pos, steps: int = 48) -> tuple[float, float, tuple[float, float]]:
    """(distance, t, point) du point du segment le plus proche de `pos` (recherche par échantillons puis
    affinage local) : sert au survol et au clic « ajouter un point »."""
    pts = segment_points(contour, seg)
    kind = seg[3]

    def at(t):
        if kind == "curve" and len(pts) == 4:
            return cubic_at(*pts, t)
        if kind == "qcurve" and len(pts) == 3:
            return quad_at(*pts, t)
        return lerp(pts[0], pts[-1], t)
    best = (math.inf, 0.0, pts[0])
    for i in range(steps + 1):
        t = i / steps
        p = at(t)
        d = math.hypot(p[0] - pos[0], p[1] - pos[1])
        if d < best[0]:
            best = (d, t, p)
    lo, hi = max(0.0, best[1] - 1 / steps), min(1.0, best[1] + 1 / steps)
    for _ in range(20):
        a, b = lo + (hi - lo) / 3, hi - (hi - lo) / 3
        da = math.dist(at(a), pos)
        db = math.dist(at(b), pos)
        if da < db:
            hi = b
        else:
            lo = a
    t = (lo + hi) / 2
    p = at(t)
    return math.dist(p, pos), t, p


# -- types de nœuds --

def neighbours(contour, index) -> tuple[int | None, int | None]:
    n = len(contour)
    closed = is_closed(contour)
    prev = index - 1 if index > 0 else (n - 1 if closed else None)
    nxt = index + 1 if index < n - 1 else (0 if closed else None)
    return prev, nxt


def set_smooth(contour, index: int, smooth: bool) -> None:
    """Nœud lisse : ses deux poignées (ou poignée + segment droit) alignées ; coin : libres."""
    point = contour[index]
    if not is_on(point):
        return
    point.smooth = smooth
    if smooth:
        align_handles(contour, index)


def align_handles(contour, index: int, keep: int | None = None, symmetric: bool = False) -> None:
    """Aligne les poignées d'un nœud lisse. `keep` : indice de la poignée qui garde sa direction (celle que
    l'utilisateur tire) ; sinon la direction moyenne. Symétrique : même longueur des deux côtés."""
    point = contour[index]
    prev, nxt = neighbours(contour, index)
    if prev is None or nxt is None:
        return
    a, b = contour[prev], contour[nxt]
    a_off, b_off = a.type is None, b.type is None
    if not (a_off or b_off):
        return
    va = (a.x - point.x, a.y - point.y)
    vb = (b.x - point.x, b.y - point.y)
    la, lb = math.hypot(*va), math.hypot(*vb)
    if a_off and b_off:
        if keep == prev and la:
            ux, uy = va[0] / la, va[1] / la
        elif keep == nxt and lb:
            ux, uy = -vb[0] / lb, -vb[1] / lb
        else:
            dx, dy = va[0] / la - vb[0] / lb if la and lb else 0, va[1] / la - vb[1] / lb if la and lb else 0
            d = math.hypot(dx, dy)
            if not d:
                return
            ux, uy = dx / d, dy / d
        if symmetric:
            la = lb = (la if keep == prev else lb if keep == nxt else (la + lb) / 2)
        a.x, a.y = point.x + ux * la, point.y + uy * la
        b.x, b.y = point.x - ux * lb, point.y - uy * lb
    else:
        # une poignée face à un segment droit : la poignée suit la direction du segment
        handle, other = (a, b) if a_off else (b, a)
        lh = math.hypot(handle.x - point.x, handle.y - point.y)
        vo = (point.x - other.x, point.y - other.y)
        lo = math.hypot(*vo)
        if lo and lh:
            handle.x, handle.y = point.x + vo[0] / lo * lh, point.y + vo[1] / lo * lh


def make_symmetric(contour, index: int) -> None:
    point = contour[index]
    if is_on(point):
        point.smooth = True
        align_handles(contour, index, symmetric=True)


# -- ajout / suppression / division --

def insert_point(contour, seg, t: float) -> int:
    """Divise le segment `seg` à `t` (exact pour lignes, cubiques et quadratiques simples). Renvoie l'indice du
    nouveau nœud."""
    start, offs, end, kind = seg
    pts = segment_points(contour, seg)
    t = min(max(t, 1e-4), 1 - 1e-4)
    if kind == "curve" and len(pts) == 4:
        (_, a, b, m), (_, c, d, _) = split_cubic(*pts, t)
        new = [Point(*a), Point(*b), Point(m[0], m[1], "curve", True), Point(*c), Point(*d)]
    elif kind == "qcurve" and len(pts) == 3:
        (_, a, m), (_, b, _) = split_quad(*pts, t)
        new = [Point(*a), Point(m[0], m[1], "qcurve", True), Point(*b)]
    elif kind in ("line", "move") or not offs:
        m = lerp(pts[0], pts[-1], t)
        new = [Point(m[0], m[1], "line")]
    else:
        raise ValueError("Segment quadratique à poignées implicites : convertissez-le d'abord.")
    _replace_offs(contour, seg, new)
    return contour.points.index(new[len(new) // 2]) if len(new) > 1 else contour.points.index(new[0])


def _replace_offs(contour, seg, new_points) -> None:
    """Remplace les poignées du segment (indices À JOUR) par `new_points`, insérés juste avant le nœud de fin."""
    pts = contour.points
    _replace_refs(contour, [pts[i] for i in seg[1]], pts[seg[2]], new_points)


def segment_refs(contour) -> list[tuple]:
    """Segments en OBJETS (début, poignées, fin, type) : restent valables quand une modification décale les
    indices (boucles qui transforment plusieurs segments)."""
    pts = contour.points
    return [(pts[s], [pts[i] for i in offs], pts[e], kind) for s, offs, e, kind in segments(contour)]


def _replace_refs(contour, offs, end_point, new_points) -> None:
    pts = contour.points
    doomed = {id(p) for p in offs}
    pts[:] = [p for p in pts if id(p) not in doomed]
    at = next(i for i, p in enumerate(pts) if p is end_point)
    pts[at:at] = new_points


def delete_points(contour, indexes) -> None:
    """Supprime des points. Nœud : les segments voisins fusionnent (poignées extérieures gardées). Poignée : la
    courbe devient une ligne si plus aucune poignée."""
    pts = contour.points
    doomed = {id(pts[i]) for i in indexes if 0 <= i < len(pts)}
    if not doomed:
        return
    for seg in segments(contour):
        start, offs, end, kind = seg
        if any(id(pts[i]) in doomed for i in offs) and kind in ("curve", "qcurve"):
            left = [i for i in offs if id(pts[i]) not in doomed]
            if not left:
                pts[end].type = "line"
                pts[end].smooth = False
    survivors = [p for p in pts if id(p) not in doomed]
    # Des nœuds supprimés : fusionner les poignées restantes (garder au plus les deux extérieures).
    contour.points[:] = survivors
    _normalize(contour)


def _normalize(contour) -> None:
    """Remet chaque segment dans une forme valide après suppression : cubique = 2 poignées, ligne = 0."""
    pts = contour.points
    if not any(p.type for p in pts):
        pts.clear()
        return
    for seg in reversed(segments(contour)):
        start, offs, end, kind = seg
        end_point = pts[end]
        if not offs:
            if kind in ("curve", "qcurve"):
                end_point.type = "line"
            continue
        if kind == "line":
            end_point.type = "curve"
            kind = "curve"
        if kind == "curve" and len(offs) != 2:
            first, last = pts[offs[0]], pts[offs[-1]]
            new = [Point(first.x, first.y), Point(last.x, last.y)] if len(offs) > 1 else \
                [Point(first.x, first.y), Point(first.x, first.y)]
            _replace_offs(contour, seg, new)
    if not is_closed(contour) and pts and pts[0].type != "move":
        pts[0].type = "move"
    # contour ouvert : les poignées avant le premier nœud ou après le dernier n'ont pas de segment
    if pts and not is_closed(contour):
        while pts and pts[-1].type is None:
            pts.pop()


def remove_overlapping_duplicates(contour, tolerance: float = 0.01) -> None:
    """Supprime les nœuds consécutifs confondus (segments de longueur nulle)."""
    pts = contour.points
    i = 0
    while len(pts) > 2 and i < len(pts):
        p, q = pts[i], pts[(i + 1) % len(pts)]
        if p.type and q.type == "line" and math.hypot(p.x - q.x, p.y - q.y) <= tolerance:
            del pts[(i + 1) % len(pts)]
        else:
            i += 1


# -- ouverture / fermeture, sens, départ --

def set_start_point(contour, index: int) -> None:
    pts = contour.points
    if not is_closed(contour) or not is_on(pts[index]):
        return
    pts[:] = pts[index:] + pts[:index]             # le nœud de départ est le premier point de la liste


def open_at(contour, index: int) -> None:
    """Ouvre un contour fermé au nœud `index` (dédoublé : début et fin)."""
    pts = contour.points
    if not is_closed(contour) or not is_on(pts[index]):
        return
    node = pts[index]
    rotated = pts[index:] + pts[:index]
    end = Point(node.x, node.y, node.type, node.smooth, node.name)
    rotated.append(end)
    rotated[0] = Point(node.x, node.y, "move", False, node.name, node.identifier)
    pts[:] = rotated


def close(contour, tolerance: float = 0.5) -> None:
    """Ferme un contour ouvert ; si le dernier nœud est sur le premier, ils fusionnent."""
    pts = contour.points
    if is_closed(contour) or len(pts) < 2:
        return
    first, last = pts[0], pts[-1]
    if len(pts) > 2 and math.hypot(first.x - last.x, first.y - last.y) <= tolerance and last.type:
        first.type, first.smooth = last.type, last.smooth
        pts.pop()
    else:
        first.type = "line"


def signed_area(contour) -> float:
    poly = flatten_contour(contour, 8)
    area = 0.0
    for (x0, y0), (x1, y1) in zip(poly, poly[1:] + poly[:1]):
        area += x0 * y1 - x1 * y0
    return area / 2


def is_clockwise(contour) -> bool:
    return signed_area(contour) < 0


def reverse(contour) -> None:
    """Inverse le sens (fontTools.ReverseContourPointPen : types de segments correctement décalés)."""
    recorder = _ContourRecorder()
    pen = ReverseContourPointPen(recorder)
    contour.drawPoints(pen)
    if recorder.contours:
        contour.points[:] = recorder.contours[0]


def point_in_polygon(pos, poly) -> bool:
    x, y = pos
    inside = False
    for (x0, y0), (x1, y1) in zip(poly, poly[1:] + poly[:1]):
        if (y0 > y) != (y1 > y) and x < (x1 - x0) * (y - y0) / ((y1 - y0) or 1e-12) + x0:
            inside = not inside
    return inside


def wrong_directions(glyph) -> list:
    """Contours fermés dans le mauvais sens PostScript (convention UFO : extérieurs anti-horaires, contrepoinçons
    horaires selon la profondeur d'imbrication)."""
    closed = [c for c in glyph.contours if is_closed(c)]
    polys = [flatten_contour(c, 8) for c in closed]
    wrong = []
    for i, contour in enumerate(closed):
        if len(polys[i]) < 3:
            continue
        probe = polys[i][0]
        depth = sum(1 for j, other in enumerate(polys) if j != i and point_in_polygon(probe, other))
        area = sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(polys[i], polys[i][1:] + polys[i][:1]))
        if (area > 0) != (depth % 2 == 0):
            wrong.append(contour)
    return wrong


def correct_directions(glyph) -> int:
    """Remet les contours dans le sens PostScript. Renvoie le nombre de contours inversés."""
    wrong = wrong_directions(glyph)
    for contour in wrong:
        reverse(contour)
    return len(wrong)


class _ContourRecorder:
    """Point pen qui reconstruit des listes de Point."""

    def __init__(self):
        self.contours: list[list[Point]] = []

    def beginPath(self, identifier=None, **kwargs):
        self.contours.append([])

    def endPath(self):
        pass

    def addPoint(self, pt, segmentType=None, smooth=False, name=None, identifier=None, **kwargs):
        self.contours[-1].append(Point(pt[0], pt[1], segmentType, smooth, name, identifier))

    def addComponent(self, base, transformation, identifier=None, **kwargs):
        pass


# -- cubique <-> quadratique --

def contour_to_quadratic(contour, max_err: float) -> None:
    """Cubiques -> quadratiques (fontTools.cu2qu, erreur maximale `max_err` en unités)."""
    for start, offs, end_point, kind in segment_refs(contour):
        if kind != "curve" or len(offs) != 2:
            continue
        cubic = [(p.x, p.y) for p in (start, *offs, end_point)]
        quad = curve_to_quadratic(cubic, max_err)
        _replace_refs(contour, offs, end_point, [Point(x, y) for x, y in quad[1:-1]])
        end_point.type = "qcurve"


def contour_to_cubic(contour, only=None) -> None:
    """Quadratiques -> cubiques EXACTES (élévation de degré ; poignées implicites décomposées). `only` : objets
    Point de FIN des seuls segments à convertir (coins arrondis : les deux segments du coin), sinon tous."""
    for start, offs, end_point, kind in segment_refs(contour):
        if kind != "qcurve" or not offs or (only is not None and not any(end_point is p for p in only)):
            continue
        quads = quad_segments([(p.x, p.y) for p in (start, *offs, end_point)])
        new: list[Point] = []
        for k, (p0, q, p1) in enumerate(quads):
            c1 = (p0[0] + 2 / 3 * (q[0] - p0[0]), p0[1] + 2 / 3 * (q[1] - p0[1]))
            c2 = (p1[0] + 2 / 3 * (q[0] - p1[0]), p1[1] + 2 / 3 * (q[1] - p1[1]))
            new += [Point(*c1), Point(*c2)]
            if k < len(quads) - 1:
                new.append(Point(p1[0], p1[1], "curve", True))
        _replace_refs(contour, offs, end_point, new)
        end_point.type = "curve"


def glyph_to_quadratic(glyph, max_err: float) -> None:
    for contour in glyph.contours:
        contour_to_quadratic(contour, max_err)


def glyph_to_cubic(glyph) -> None:
    for contour in glyph.contours:
        contour_to_cubic(contour)


def max_deviation(cubic, quads, samples: int = 64) -> float:
    """Écart maximal entre une cubique et une suite de quadratiques (contrôle de la tolérance, tests)."""
    curve_pts = [cubic_at(*cubic, i / samples) for i in range(samples + 1)]
    quad_pts = []
    for q in quads:
        quad_pts.extend(quad_at(*q, i / samples) for i in range(samples + 1))
    return max(min(math.dist(c, q) for q in quad_pts) for c in curve_pts)


def new_contour(points) -> Contour:
    return Contour([Point(*p) if isinstance(p, tuple) else p for p in points])
