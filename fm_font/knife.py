"""COUTEAU (sans Qt) : coupe les contours le long d'un segment [a, b].

Méthode exacte, sans approximation des courbes :
1. intersections exactes du couteau avec chaque segment (lignes, cubiques, quadratiques : `fontTools.misc.
   bezierTools.segmentSegmentIntersections`) ; un nœud y est inséré par division exacte (`contours.insert_point`) ;
2. les points de coupe sont rangés le long du couteau ; deux points consécutifs forment une CORDE si son milieu est
   dans la forme remplie (enroulement non nul, contours seuls) ;
3. chaque corde COUPE un contour fermé en deux (extrémités sur le même contour) ou RELIE deux contours (contour et
   contre-forme : la corde suivante coupera le contour fusionné). Couper un « o » de part en part donne ainsi deux
   formes en C. Les contours OUVERTS sont coupés à chaque point de coupe.
Les nouveaux bords sont des lignes droites ; les nœuds de coupe sont des coins."""
from __future__ import annotations

from fontTools.misc.bezierTools import segmentSegmentIntersections
from fontTools.pens.pointInsidePen import PointInsidePen
from ufoLib2.objects import Contour, Point

from . import contours as C

EPS = 1e-6


def _find_seg(contour, start, end):
    pts = contour.points
    for seg in C.segments(contour):
        if pts[seg[0]] is start and pts[seg[2]] is end:
            return seg
    return None


def _cut_points(glyph, a, b) -> list[tuple[float, Point, Contour]]:
    """Insère les nœuds de coupe ; renvoie [(position le long du couteau, nœud, contour)] sans doublons."""
    hits = []
    for contour in glyph.contours:
        found = {}                                           # id(segment de départ) -> [(t1, t2)]
        for start, offs, end, kind in C.segment_refs(contour):
            pts = [(start.x, start.y)] + [(p.x, p.y) for p in offs] + [(end.x, end.y)]
            if kind == "qcurve" and len(offs) > 1:
                continue                                     # poignées implicites : non coupé (rare, à convertir)
            for hit in segmentSegmentIntersections(pts, [a, b]):
                if -EPS <= hit.t2 <= 1 + EPS and -EPS <= hit.t1 <= 1 + EPS:   # lignes : t non bornés
                    found.setdefault((id(start), id(end)), (start, end, []))[2].append((hit.t1, hit.t2))
        for start, end, values in found.values():
            current_end, scale = end, 1.0
            for t1, t2 in sorted(values, reverse=True):      # de la fin vers le début : t restent valables
                if t1 >= 1 - EPS:
                    hits.append((t2, end, contour))
                    continue
                if t1 <= EPS:
                    hits.append((t2, start, contour))
                    continue
                seg = _find_seg(contour, start, current_end)
                if seg is None:
                    continue
                index = C.insert_point(contour, seg, t1 / scale)
                node = contour.points[index]
                node.smooth = False
                hits.append((t2, node, contour))
                current_end, scale = node, t1
    hits.sort(key=lambda h: h[0])
    unique, seen = [], set()
    for hit in hits:
        if id(hit[1]) not in seen:
            seen.add(id(hit[1]))
            unique.append(hit)
    return unique


def _inside(glyph, x: float, y: float) -> bool:
    pen = PointInsidePen(None, (x, y), evenOdd=False)
    for contour in glyph.contours:
        if C.is_closed(contour):
            contour.draw(pen)
    return pen.getResult()


def _copy(point, kind) -> Point:
    return Point(point.x, point.y, kind, False)


def _contour_of(glyph, point):
    for contour in glyph.contours:
        if any(p is point for p in contour.points):
            return contour
    return None


def _rotated_after(points, point) -> list:
    """Points du contour fermé à partir du suivant de `point`, jusqu'à `point` inclus."""
    i = next(k for k, p in enumerate(points) if p is point)
    return points[i + 1:] + points[:i + 1]


def _split(glyph, contour, pa, pb) -> None:
    after_a = _rotated_after(contour.points, pa)              # ... -> pb ... -> pa
    j = next(k for k, p in enumerate(after_a) if p is pb)
    first = [_copy(pa, "line")] + after_a[:j + 1]             # pa -> ... -> pb, fermé par la ligne pb -> pa
    second = [_copy(pb, "line")] + after_a[j + 1:]            # pb -> ... -> pa, fermé par la ligne pa -> pb
    index = glyph.contours.index(contour)
    glyph.contours[index] = Contour(points=first)
    glyph.contours.insert(index + 1, Contour(points=second))


def _merge(glyph, c1, pa, c2, pb) -> None:
    points = [_copy(pa, "line")] + _rotated_after(c1.points, pa) + [_copy(pb, "line")] + \
        _rotated_after(c2.points, pb)
    glyph.contours[glyph.contours.index(c1)] = Contour(points=points)
    glyph.contours.remove(c2)


def _split_open(glyph, contour, cut_ids) -> int:
    pieces, current = [], []
    for point in contour.points:
        current.append(point)
        if id(point) in cut_ids and len(current) > 1 and point is not contour.points[-1]:
            pieces.append(current)
            current = [_copy(point, "move")]
    pieces.append(current)
    if len(pieces) == 1:
        return 0
    index = glyph.contours.index(contour)
    glyph.contours[index:index + 1] = [Contour(points=p) for p in pieces]
    return len(pieces) - 1


def cut(glyph, a, b) -> int:
    """Coupe `glyph` le long de [a, b] ; renvoie le nombre de cordes traitées (0 : glyphe inchangé)."""
    a, b = (float(a[0]), float(a[1])), (float(b[0]), float(b[1]))
    if (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 < 1e-6:
        return 0
    from .undo import glyph_restore, glyph_snapshot
    before = glyph_snapshot(glyph)
    hits = _cut_points(glyph, a, b)
    count = 0
    open_cuts = {}
    for _t, point, contour in hits:
        if not C.is_closed(contour):
            open_cuts.setdefault(id(contour), (contour, set()))[1].add(id(point))
    chords = []
    closed_hits = [h for h in hits if C.is_closed(h[2])]
    for (t0, p0, _c0), (t1, p1, _c1) in zip(closed_hits, closed_hits[1:]):
        if t1 - t0 < 1e-9:
            continue
        mid = ((p0.x + p1.x) / 2, (p0.y + p1.y) / 2)
        if _inside(glyph, *mid):
            chords.append((p0, p1))
    for pa, pb in chords:
        ca, cb = _contour_of(glyph, pa), _contour_of(glyph, pb)
        if ca is None or cb is None:
            continue
        if ca is cb:
            _split(glyph, ca, pa, pb)
        else:
            _merge(glyph, ca, pa, cb, pb)
        count += 1
    for contour, ids in open_cuts.values():
        count += _split_open(glyph, contour, ids)
    if not count:
        glyph_restore(glyph, before)                        # effleuré sans coupe : pas de nœuds ajoutés
    return count
