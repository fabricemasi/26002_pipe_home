"""Formes et tracés (sans Qt) : rectangle, ellipse, polygone / étoile, et ajustement d'un tracé libre (crayon) en
courbes de Bézier cubiques (algorithme de Schneider, « An Algorithm for Automatically Fitting Digitized Curves »,
Graphics Gems 1990), après lissage et réduction (Ramer-Douglas-Peucker)."""
from __future__ import annotations

import math

from ufoLib2.objects import Contour, Point

KAPPA = 0.5522847498                                    # poignées d'un quart de cercle en cubique


def rectangle(x0: float, y0: float, x1: float, y1: float) -> Contour:
    """Rectangle anti-horaire (sens d'un contour extérieur)."""
    left, right, bottom, top = min(x0, x1), max(x0, x1), min(y0, y1), max(y0, y1)
    return Contour([Point(left, bottom, "line"), Point(right, bottom, "line"),
                    Point(right, top, "line"), Point(left, top, "line")])


def ellipse(x0: float, y0: float, x1: float, y1: float) -> Contour:
    left, right, bottom, top = min(x0, x1), max(x0, x1), min(y0, y1), max(y0, y1)
    cx, cy, rx, ry = (left + right) / 2, (bottom + top) / 2, (right - left) / 2, (top - bottom) / 2
    kx, ky = rx * KAPPA, ry * KAPPA
    return Contour([
        Point(cx, bottom, "curve", True),
        Point(cx + kx, bottom), Point(right, cy - ky), Point(right, cy, "curve", True),
        Point(right, cy + ky), Point(cx + kx, top), Point(cx, top, "curve", True),
        Point(cx - kx, top), Point(left, cy + ky), Point(left, cy, "curve", True),
        Point(left, cy - ky), Point(cx - kx, bottom),
    ])


def polygon(cx: float, cy: float, radius: float, sides: int = 6, inner_ratio: float = 0.0,
            rotation: float = 90.0) -> Contour:
    """Polygone régulier ; `inner_ratio` > 0 : étoile (sommets alternés à radius * inner_ratio)."""
    sides = max(3, int(sides))
    count = sides * 2 if inner_ratio > 0 else sides
    pts = []
    for k in range(count):
        r = radius * inner_ratio if inner_ratio > 0 and k % 2 else radius
        a = math.radians(rotation) + 2 * math.pi * k / count
        pts.append(Point(round(cx + r * math.cos(a), 3), round(cy + r * math.sin(a), 3), "line"))
    return Contour(pts)


# -- tracé libre --

def smooth_polyline(points, strength: int = 2) -> list[tuple[float, float]]:
    """Moyenne glissante (extrémités gardées) : atténue le tremblement de la main."""
    pts = list(points)
    for _ in range(max(0, strength)):
        if len(pts) < 3:
            break
        pts = [pts[0]] + [((a[0] + 2 * b[0] + c[0]) / 4, (a[1] + 2 * b[1] + c[1]) / 4)
                          for a, b, c in zip(pts, pts[1:], pts[2:])] + [pts[-1]]
    return pts


def rdp(points, epsilon: float) -> list[tuple[float, float]]:
    if len(points) < 3:
        return list(points)
    a, b = points[0], points[-1]
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy) or 1e-12
    worst, index = 0.0, 0
    for i in range(1, len(points) - 1):
        p = points[i]
        d = abs(dy * p[0] - dx * p[1] + b[0] * a[1] - b[1] * a[0]) / length if math.hypot(dx, dy) else \
            math.dist(p, a)
        if d > worst:
            worst, index = d, i
    if worst <= epsilon:
        return [a, b]
    return rdp(points[:index + 1], epsilon)[:-1] + rdp(points[index:], epsilon)


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1])


def _add(a, b):
    return (a[0] + b[0], a[1] + b[1])


def _mul(a, s):
    return (a[0] * s, a[1] * s)


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1]


def _norm(a):
    length = math.hypot(*a)
    return (a[0] / length, a[1] / length) if length else (0.0, 0.0)


def _bezier(ctrl, t):
    u = 1 - t
    return (u ** 3 * ctrl[0][0] + 3 * u * u * t * ctrl[1][0] + 3 * u * t * t * ctrl[2][0] + t ** 3 * ctrl[3][0],
            u ** 3 * ctrl[0][1] + 3 * u * u * t * ctrl[1][1] + 3 * u * t * t * ctrl[2][1] + t ** 3 * ctrl[3][1])


def _chord_params(points):
    u = [0.0]
    for a, b in zip(points, points[1:]):
        u.append(u[-1] + math.dist(a, b))
    total = u[-1] or 1.0
    return [v / total for v in u]


def _generate(points, params, t1, t2):
    first, last = points[0], points[-1]
    c00 = c01 = c11 = x0 = x1 = 0.0
    for p, u in zip(points, params):
        a1 = _mul(t1, 3 * (1 - u) ** 2 * u)
        a2 = _mul(t2, 3 * (1 - u) * u ** 2)
        c00 += _dot(a1, a1)
        c01 += _dot(a1, a2)
        c11 += _dot(a2, a2)
        tmp = _sub(p, _bezier((first, first, last, last), u))
        x0 += _dot(a1, tmp)
        x1 += _dot(a2, tmp)
    det = c00 * c11 - c01 * c01
    seg = math.dist(first, last)
    if abs(det) > 1e-12:
        alpha1 = (x0 * c11 - c01 * x1) / det
        alpha2 = (c00 * x1 - c01 * x0) / det
    else:
        alpha1 = alpha2 = seg / 3
    if alpha1 < 1e-6 * seg or alpha2 < 1e-6 * seg:
        alpha1 = alpha2 = seg / 3
    return (first, _add(first, _mul(t1, alpha1)), _add(last, _mul(t2, alpha2)), last)


def _max_error(points, ctrl, params):
    worst, index = 0.0, len(points) // 2
    for i, (p, u) in enumerate(zip(points, params)):
        d = math.dist(_bezier(ctrl, u), p)
        if d > worst:
            worst, index = d, i
    return worst, index


def _reparam(points, ctrl, params):
    out = []
    for p, u in zip(points, params):
        d = _sub(_bezier(ctrl, u), p)
        q1 = [_mul(_sub(ctrl[i + 1], ctrl[i]), 3) for i in range(3)]
        q2 = [_mul(_sub(q1[i + 1], q1[i]), 2) for i in range(2)]
        uu = 1 - u
        d1 = _add(_add(_mul(q1[0], uu * uu), _mul(q1[1], 2 * u * uu)), _mul(q1[2], u * u))
        d2 = _add(_mul(q2[0], uu), _mul(q2[1], u))
        den = _dot(d1, d1) + _dot(d, d2)
        out.append(min(1.0, max(0.0, u - _dot(d, d1) / den)) if abs(den) > 1e-12 else u)
    return out


def fit_cubic(points, error: float) -> list[tuple]:
    """Suite de cubiques (p0, c1, c2, p3) qui suit `points` à `error` près."""
    pts = [p for i, p in enumerate(points) if i == 0 or math.dist(p, points[i - 1]) > 1e-9]
    if len(pts) < 2:
        return []
    t1 = _norm(_sub(pts[1], pts[0]))
    t2 = _norm(_sub(pts[-2], pts[-1]))
    return _fit(pts, t1, t2, error, 0)


def _fit(pts, t1, t2, error, depth):
    if len(pts) == 2:
        d = math.dist(pts[0], pts[1]) / 3
        return [(pts[0], _add(pts[0], _mul(t1, d)), _add(pts[1], _mul(t2, d)), pts[1])]
    params = _chord_params(pts)
    ctrl = _generate(pts, params, t1, t2)
    worst, split = _max_error(pts, ctrl, params)
    if worst < error:
        return [ctrl]
    if worst < error * 4:
        for _ in range(8):
            params = _reparam(pts, ctrl, params)
            ctrl = _generate(pts, params, t1, t2)
            worst, split = _max_error(pts, ctrl, params)
            if worst < error:
                return [ctrl]
    if depth > 24:
        return [ctrl]
    split = min(max(split, 1), len(pts) - 2)
    center = _norm(_sub(pts[split - 1], pts[split + 1]))
    return (_fit(pts[:split + 1], t1, center, error, depth + 1)
            + _fit(pts[split:], _mul(center, -1), t2, error, depth + 1))


def curves_to_contour(curves, closed: bool = False, corner_angle: float = 25.0) -> Contour:
    """Cubiques bout à bout -> contour UFO ; nœuds lisses là où les tangentes se continuent."""
    if not curves:
        return Contour()
    pts = []
    if not closed:
        pts.append(Point(*curves[0][0], "move"))
    for k, (p0, c1, c2, p3) in enumerate(curves):
        nxt = curves[(k + 1) % len(curves)] if (closed or k + 1 < len(curves)) else None
        smooth = False
        if nxt is not None:
            a = _norm(_sub(p3, c2))
            b = _norm(_sub(nxt[1], nxt[0]))
            smooth = _dot(a, b) > math.cos(math.radians(corner_angle))
        pts += [Point(*c1), Point(*c2), Point(p3[0], p3[1], "curve", smooth)]
    if closed:
        pts = pts[-1:] + pts[:-1]                      # le nœud de départ en tête (convention UFO)
    return Contour(pts)


def pencil_contour(points, error: float = 4.0, smoothing: int = 2, closed: bool = False) -> Contour:
    """Tracé du crayon -> contour éditable (lissé, ajusté)."""
    pts = smooth_polyline(points, smoothing)
    if closed and len(pts) > 2 and pts[0] != pts[-1]:
        pts = pts + [pts[0]]
    return curves_to_contour(fit_cubic(pts, error), closed=closed)
