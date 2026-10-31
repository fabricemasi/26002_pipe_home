"""Géométrie des glyphes (sans Qt) : transformations, symétrie, booléens (skia-pathops), suppression des
chevauchements, simplification, arrondi, alignement / distribution, mesures."""
from __future__ import annotations

import math

import pathops
from fontTools.misc.transform import Transform
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.recordingPen import RecordingPen

from . import contours as C


# -- transformations (points choisis, contours, glyphe entier) --

def transform_points(points, matrix: Transform) -> None:
    for p in points:
        p.x, p.y = matrix.transformPoint((p.x, p.y))


def selection_points(glyph, selection) -> list:
    """`selection` : {(contour, indice)} -> objets Point (poignées des nœuds choisis comprises si
    `with_handles`)."""
    return [glyph.contours[c][i] for c, i in sorted(selection) if c < len(glyph.contours)
            and i < len(glyph.contours[c])]


def with_handles(glyph, selection) -> set:
    """Ajoute à la sélection les poignées des nœuds choisis (elles suivent leur nœud lors d'un déplacement)."""
    out = set(selection)
    for c, i in selection:
        contour = glyph.contours[c]
        if contour[i].type is None:
            continue
        prev, nxt = C.neighbours(contour, i)
        for j in (prev, nxt):
            if j is not None and contour[j].type is None:
                out.add((c, j))
    return out


def move_points(glyph, selection, dx: float, dy: float) -> None:
    for p in selection_points(glyph, with_handles(glyph, selection)):
        p.x += dx
        p.y += dy


def transform_glyph(glyph, matrix: Transform, selection=None) -> None:
    """Applique `matrix` aux points choisis (tout le glyphe sans sélection : contours, composants, ancres)."""
    if selection:
        transform_points(selection_points(glyph, with_handles(glyph, selection)), matrix)
        return
    for contour in glyph.contours:
        transform_points(contour, matrix)
    for comp in glyph.components:
        comp.transformation = matrix.transform(comp.transformation)
    for anchor in glyph.anchors:
        anchor.x, anchor.y = matrix.transformPoint((anchor.x, anchor.y))


def around(matrix: Transform, cx: float, cy: float) -> Transform:
    return Transform().translate(cx, cy).transform(matrix).translate(-cx, -cy)


def bounds_of_points(points) -> tuple[float, float, float, float] | None:
    if not points:
        return None
    xs = [p.x for p in points]
    ys = [p.y for p in points]
    return min(xs), min(ys), max(xs), max(ys)


def glyph_bounds(glyph, layer=None) -> tuple[float, float, float, float] | None:
    pen = BoundsPen(layer)
    glyph.draw(pen)
    return pen.bounds


def mirror(glyph, horizontal: bool = True, selection=None) -> None:
    """Symétrie autour du centre de la sélection (ou de la chasse). Les contours sont inversés pour garder le bon
    sens de remplissage."""
    pts = selection_points(glyph, with_handles(glyph, selection)) if selection else None
    if pts:
        x0, y0, x1, y1 = bounds_of_points(pts)
    else:
        b = glyph_bounds(glyph) or (0, 0, glyph.width, 0)
        x0, y0, x1, y1 = (0, b[1], glyph.width, b[3]) if horizontal else b
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    matrix = around(Transform().scale(-1, 1) if horizontal else Transform().scale(1, -1), cx, cy)
    transform_glyph(glyph, matrix, selection)
    touched = {c for c, _i in selection} if selection else set(range(len(glyph.contours)))
    for c in touched:
        if not selection or all((c, i) in with_handles(glyph, selection) for i in range(len(glyph.contours[c]))):
            C.reverse(glyph.contours[c])


def round_coordinates(glyph, grid: float = 1.0) -> None:
    def r(v):
        return round(v / grid) * grid if grid else v
    for contour in glyph.contours:
        for p in contour:
            p.x, p.y = r(p.x), r(p.y)
    for anchor in glyph.anchors:
        anchor.x, anchor.y = r(anchor.x), r(anchor.y)
    glyph.width = round(glyph.width)


# -- booléens (skia-pathops) --

class _Drawable:
    def __init__(self, contour):
        self.contour = contour

    def draw(self, pen):
        self.contour.draw(pen)


def _rebuild(glyph, keep, pen_drawer) -> None:
    kept = [glyph.contours[i] for i in keep]
    glyph.clearContours()
    for contour in kept:
        glyph.contours.append(contour)
    pen_drawer(glyph.getPen())


def remove_overlaps(glyph, indexes=None) -> None:
    """Union des contours (tous, ou `indexes`) : chevauchements supprimés, sens corrigé (anti-horaire)."""
    indexes = list(range(len(glyph.contours))) if indexes is None else sorted(indexes)
    targets = [_Drawable(glyph.contours[i]) for i in indexes if C.is_closed(glyph.contours[i])]
    if not targets:
        return
    keep = [i for i in range(len(glyph.contours)) if i not in indexes or not C.is_closed(glyph.contours[i])]
    recorder = RecordingPen()
    pathops.union(targets, recorder)
    _rebuild(glyph, keep, recorder.replay)


BOOLEAN_OPS = ("union", "difference", "intersection", "xor")


def boolean(glyph, operation: str, subject, clip) -> None:
    """Opération booléenne : `subject` et `clip` = indices de contours ; le résultat remplace les deux."""
    if operation not in BOOLEAN_OPS:
        raise ValueError(operation)
    subject, clip = sorted(set(subject)), sorted(set(clip) - set(subject))
    if operation == "union":
        remove_overlaps(glyph, subject + clip)
        return
    used = set(subject) | set(clip)
    keep = [i for i in range(len(glyph.contours)) if i not in used]
    recorder = RecordingPen()
    getattr(pathops, operation)([_Drawable(glyph.contours[i]) for i in subject],
                                [_Drawable(glyph.contours[i]) for i in clip], recorder)
    _rebuild(glyph, keep, recorder.replay)


# -- simplification --

def simplify(glyph, tolerance: float = 0.5) -> int:
    """Retire les nœuds superflus : nœuds de ligne alignés, segments nuls. Renvoie le nombre de points retirés."""
    removed = 0
    for contour in glyph.contours:
        before = len(contour)
        C.remove_overlapping_duplicates(contour, tolerance)
        changed = True
        while changed and len(contour) > 3:
            changed = False
            pts = contour.points
            for i, p in enumerate(pts):
                if p.type != "line":
                    continue
                prev, nxt = C.neighbours(contour, i)
                if prev is None or nxt is None:
                    continue
                a, b = pts[prev], pts[nxt]
                if a.type is None or b.type not in ("line",):
                    continue
                if _distance_to_line((p.x, p.y), (a.x, a.y), (b.x, b.y)) <= tolerance:
                    del pts[i]
                    changed = True
                    break
        removed += before - len(contour)
    return removed


def _distance_to_line(p, a, b) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy)
    if not length:
        return math.dist(p, a)
    return abs(dy * p[0] - dx * p[1] + b[0] * a[1] - b[1] * a[0]) / length


# -- alignement / distribution (points choisis) --

def align(glyph, selection, how: str) -> None:
    """how : left, right, hcenter, top, bottom, vcenter."""
    pts = selection_points(glyph, selection)
    if len(pts) < 2:
        return
    x0, y0, x1, y1 = bounds_of_points(pts)
    nodes = [(c, i) for c, i in selection if glyph.contours[c][i].type is not None] or list(selection)
    for c, i in nodes:
        p = glyph.contours[c][i]
        target_x = {"left": x0, "right": x1, "hcenter": (x0 + x1) / 2}.get(how)
        target_y = {"bottom": y0, "top": y1, "vcenter": (y0 + y1) / 2}.get(how)
        dx = target_x - p.x if target_x is not None else 0
        dy = target_y - p.y if target_y is not None else 0
        move_points(glyph, {(c, i)}, dx, dy)


def distribute(glyph, selection, horizontal: bool = True) -> None:
    nodes = sorted(((c, i) for c, i in selection if glyph.contours[c][i].type is not None),
                   key=lambda ci: (glyph.contours[ci[0]][ci[1]].x if horizontal else glyph.contours[ci[0]][ci[1]].y))
    if len(nodes) < 3:
        return
    first, last = glyph.contours[nodes[0][0]][nodes[0][1]], glyph.contours[nodes[-1][0]][nodes[-1][1]]
    start, end = (first.x, last.x) if horizontal else (first.y, last.y)
    step = (end - start) / (len(nodes) - 1)
    for k, (c, i) in enumerate(nodes[1:-1], 1):
        p = glyph.contours[c][i]
        target = start + step * k
        move_points(glyph, {(c, i)}, target - p.x if horizontal else 0, 0 if horizontal else target - p.y)


# -- mesures --

def measure(a, b) -> dict:
    dx, dy = b[0] - a[0], b[1] - a[1]
    return {"dx": dx, "dy": dy, "distance": math.hypot(dx, dy), "angle": math.degrees(math.atan2(dy, dx))}


def contour_length(contour, steps: int = 32) -> float:
    poly = C.flatten_contour(contour, steps)
    if C.is_closed(contour):
        poly = poly + poly[:1]
    return sum(math.dist(a, b) for a, b in zip(poly, poly[1:]))


def flattened(glyph, steps: int = 32) -> list[list[tuple[float, float]]]:
    """Contours aplatis (fermés : premier point répété). À garder pendant un geste : le glyphe ne change pas."""
    polys = []
    for contour in glyph.contours:
        poly = C.flatten_contour(contour, steps)
        polys.append(poly + poly[:1] if C.is_closed(contour) else poly)
    return polys


def intersections_with_line(glyph, a, b, steps: int = 32, polys=None) -> list[tuple[float, float]]:
    """Points où le segment [a, b] coupe les contours (mesure : épaisseurs des fûts ; aperçu du couteau).
    `polys` : contours déjà aplatis (`flattened`), pour ne pas les refaire à chaque mouvement de la souris."""
    hits = []
    for poly in polys if polys is not None else flattened(glyph, steps):
        for p, q in zip(poly, poly[1:]):
            hit = _segment_intersection(a, b, p, q)
            if hit is not None:
                hits.append(hit)
    hits.sort(key=lambda h: math.dist(h, a))
    unique = []                                              # sommet de la polyligne : touché par ses deux côtés
    for h in hits:
        if not unique or math.dist(h, unique[-1]) > 1e-6:
            unique.append(h)
    return unique


def _segment_intersection(a, b, c, d):
    r = (b[0] - a[0], b[1] - a[1])
    s = (d[0] - c[0], d[1] - c[1])
    den = r[0] * s[1] - r[1] * s[0]
    if abs(den) < 1e-12:
        return None
    t = ((c[0] - a[0]) * s[1] - (c[1] - a[1]) * s[0]) / den
    u = ((c[0] - a[0]) * r[1] - (c[1] - a[1]) * r[0]) / den
    if 0 <= t <= 1 and 0 <= u <= 1:
        return a[0] + t * r[0], a[1] + t * r[1]
    return None


# -- arrondi des coins (congé) --

def _unit(v):
    length = math.hypot(*v)
    return (v[0] / length, v[1] / length) if length > 1e-9 else None


def _point_at_distance(pts, corner, distance, from_end: bool):
    """Paramètre t du segment (ligne ou cubique, `pts`) à `distance` du coin (à t = 1 si `from_end`, sinon à
    t = 0) ; None si le segment est trop court. Bissection sur la distance au coin."""
    at = (lambda t: C.cubic_at(*pts, t)) if len(pts) == 4 else (lambda t: C.lerp(pts[0], pts[-1], t))
    far = at(0.0 if from_end else 1.0)
    if math.dist(far, corner) <= distance:
        return None
    lo, hi = (0.0, 1.0)
    for _ in range(60):                                      # f(lo) > 0 du côté éloigné, f(hi) < 0 au coin
        mid = (lo + hi) / 2
        t = mid if from_end else 1 - mid
        if math.dist(at(t), corner) > distance:
            lo = mid
        else:
            hi = mid
    mid = (lo + hi) / 2
    return mid if from_end else 1 - mid


def round_corner(contour, index: int, radius: float) -> bool:
    """Remplace le nœud en COIN `index` par un arc de rayon `radius` tangent aux deux segments (lignes ou
    cubiques). Les segments sont raccourcis par division EXACTE (leur forme ne change pas) ; l'arc est une
    cubique tangente aux deux (rayon exact entre deux droites ; entre courbes, rayon de l'arc qui joint les deux
    points de tangence situés à la distance du congé). Segment QUADRATIQUE (police TrueType importée) : les seuls
    segments du coin passent d'abord en cubiques (élévation de degré exacte : même forme ; le reste du contour
    reste quadratique, l'export TrueType les reconvertit). False (rien modifié) : nœud lisse ou au bout d'un
    contour ouvert, rayon plus grand qu'un des segments."""
    pts = contour.points
    node = pts[index]
    if node.type is None or node.smooth:
        return False
    segs = C.segments(contour)
    inc = next((s for s in segs if s[2] == index), None)
    out = next((s for s in segs if s[0] == index), None)
    if inc is not None and out is not None and "qcurve" in (inc[3], out[3]):
        backup = [(p, p.x, p.y, p.type, p.smooth) for p in pts]   # les MÊMES objets (repérés par les appelants)
        first = pts[0]
        ends = [pts[s[2]] for s in (inc, out) if s[3] == "qcurve"]
        C.contour_to_cubic(contour, only=ends)
        index = next(i for i, q in enumerate(pts) if q is node)
        if round_corner(contour, index, radius):
            k = next((i for i, q in enumerate(pts) if q is first), 0)   # même point de départ qu'avant
            pts[:] = pts[k:] + pts[:k]
            return True
        for p, x, y, kind, smooth in backup:                  # rien d'arrondi : le contour reste tel quel
            p.x, p.y, p.type, p.smooth = x, y, kind, smooth
        pts[:] = [p for p, *_ in backup]
        return False
    if inc is None or out is None or inc[3] not in ("line", "curve") or out[3] not in ("line", "curve"):
        return False
    if (inc[3] == "curve" and len(inc[1]) != 2) or (out[3] == "curve" and len(out[1]) != 2):
        return False
    pin, pout = C.segment_points(contour, inc), C.segment_points(contour, out)
    corner = (node.x, node.y)
    ua = next((u for u in (_unit((q[0] - corner[0], q[1] - corner[1])) for q in reversed(pin[:-1])) if u), None)
    ub = next((u for u in (_unit((q[0] - corner[0], q[1] - corner[1])) for q in pout[1:]) if u), None)
    if ua is None or ub is None:
        return False
    angle = math.acos(max(-1.0, min(1.0, ua[0] * ub[0] + ua[1] * ub[1])))   # angle intérieur du coin
    if angle < 1e-3 or abs(angle - math.pi) < 1e-3:
        return False
    distance = radius / math.tan(angle / 2)                  # du coin aux points de tangence
    t_in = _point_at_distance(pin, corner, distance, from_end=True)
    t_out = _point_at_distance(pout, corner, distance, from_end=False)
    if t_in is None or t_out is None:
        return False
    if len(pin) == 4:
        (_, a1, b1, p1), _rest = C.split_cubic(*pin, t_in)
        tan1 = _unit((p1[0] - b1[0], p1[1] - b1[1])) or _unit((p1[0] - a1[0], p1[1] - a1[1]))
        inc_new = [a1, b1]
    else:
        p1 = C.lerp(pin[0], pin[1], t_in)
        tan1, inc_new = (-ua[0], -ua[1]), []
    if len(pout) == 4:
        _rest, (p2, c2, d2, _) = C.split_cubic(*pout, t_out)
        tan2 = _unit((c2[0] - p2[0], c2[1] - p2[1])) or _unit((d2[0] - p2[0], d2[1] - p2[1]))
        out_new = [c2, d2]
    else:
        p2 = C.lerp(pout[0], pout[1], t_out)
        tan2, out_new = ub, []
    if tan1 is None or tan2 is None:
        return False
    turn = math.acos(max(-1.0, min(1.0, tan1[0] * tan2[0] + tan1[1] * tan2[1])))
    chord = math.dist(p1, p2)
    if turn < 1e-4 or chord < 1e-9:
        return False
    arc_radius = chord / (2 * math.sin(turn / 2))
    handle = 4 / 3 * math.tan(turn / 4) * arc_radius         # cubique d'un arc de cercle d'ouverture `turn`
    h1 = (p1[0] + tan1[0] * handle, p1[1] + tan1[1] * handle)
    h2 = (p2[0] - tan2[0] * handle, p2[1] - tan2[1] * handle)
    from ufoLib2.objects import Point
    new = [Point(*q) for q in inc_new] + [Point(p1[0], p1[1], inc[3], True), Point(*h1), Point(*h2),
                                          Point(p2[0], p2[1], "curve", True)] + [Point(*q) for q in out_new]
    first = pts[0]
    start_obj = pts[inc[0]]
    doomed = {id(pts[i]) for i in inc[1]} | {id(node)} | {id(pts[i]) for i in out[1]}
    if C.is_closed(contour):                                 # rotation : le début du segment entrant en tête
        k = inc[0]
        ring = pts[k:] + pts[:k]
    else:
        ring = list(pts)
    kept = [q for q in ring if id(q) not in doomed]
    at = next(i for i, q in enumerate(kept) if q is start_obj) + 1
    kept[at:at] = new
    if C.is_closed(contour):
        anchor = first if any(q is first for q in kept) else new[len(inc_new)]
        k = next(i for i, q in enumerate(kept) if q is anchor)
        kept = kept[k:] + kept[:k]
    pts[:] = kept
    return True


def round_corners(glyph, selection, radius: float) -> int:
    """Arrondit les coins choisis (nœuds en coin, entre lignes, cubiques et / ou quadratiques). Renvoie le nombre
    arrondi."""
    done = 0
    by_contour: dict[int, list[int]] = {}
    for c, i in selection:
        by_contour.setdefault(c, []).append(i)
    for c, indexes in by_contour.items():
        contour = glyph.contours[c]
        # Nœuds repérés par OBJET : un segment quadratique converti ajoute des points (indices décalés).
        nodes = [contour.points[i] for i in sorted(indexes, reverse=True) if i < len(contour)]
        for node in nodes:
            i = next((k for k, q in enumerate(contour.points) if q is node), None)
            if i is not None and round_corner(contour, i, radius):
                done += 1
    return done
