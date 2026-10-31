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


def intersections_with_line(glyph, a, b, steps: int = 32) -> list[tuple[float, float]]:
    """Points où le segment [a, b] coupe les contours (outil de mesure : épaisseurs des fûts)."""
    hits = []
    for contour in glyph.contours:
        poly = C.flatten_contour(contour, steps)
        if C.is_closed(contour):
            poly = poly + poly[:1]
        for p, q in zip(poly, poly[1:]):
            hit = _segment_intersection(a, b, p, q)
            if hit is not None:
                hits.append(hit)
    hits.sort(key=lambda h: math.dist(h, a))
    return hits


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
