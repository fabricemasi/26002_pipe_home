"""Calligraphie (sans Qt) : plume à bec plat (angle fixe), brosse à largeur variable, pression (tablette), lissage,
conversion du tracé en contours éditables (union skia-pathops puis ajustement en cubiques).

Un échantillon du tracé = (x, y, pression 0..1). Sans tablette, la pression vaut 1."""
from __future__ import annotations

import math

import pathops
from fontTools.pens.recordingPen import RecordingPen
from ufoLib2.objects import Contour

from . import shapes
from .contours import cubic_at


class _Poly:
    def __init__(self, pts):
        self.pts = pts

    def draw(self, pen):
        pen.moveTo(self.pts[0])
        for p in self.pts[1:]:
            pen.lineTo(p)
        pen.closePath()


def _resample(samples, spacing: float):
    """Échantillons régulièrement espacés (la vitesse de la main ne change plus la densité)."""
    out = [samples[0]]
    for s in samples[1:]:
        last = out[-1]
        d = math.dist(s[:2], last[:2])
        if d < spacing:
            continue
        steps = int(d // spacing)
        for k in range(1, steps + 1):
            t = k * spacing / d
            out.append((last[0] + (s[0] - last[0]) * t, last[1] + (s[1] - last[1]) * t,
                        last[2] + (s[2] - last[2]) * t))
    if out[-1][:2] != samples[-1][:2]:
        out.append(samples[-1])
    return out


def _smooth(samples, strength: int):
    pts = list(samples)
    for _ in range(max(0, strength)):
        if len(pts) < 3:
            break
        pts = [pts[0]] + [tuple((a[k] + 2 * b[k] + c[k]) / 4 for k in range(3))
                          for a, b, c in zip(pts, pts[1:], pts[2:])] + [pts[-1]]
    return pts


def nib_polygons(samples, width: float, angle: float, pressure: bool = True, contrast: float = 0.0):
    """Plume à bec plat : quadrilatères balayés entre deux échantillons (bec de largeur `width`, incliné de
    `angle` degrés ; `contrast` > 0 donne au bec une petite épaisseur)."""
    a = math.radians(angle)
    ux, uy = math.cos(a), math.sin(a)
    thick = width * contrast / 2
    polys = []
    for p, q in zip(samples, samples[1:]):
        hp = width / 2 * (p[2] if pressure else 1.0)
        hq = width / 2 * (q[2] if pressure else 1.0)
        nx, ny = -uy * thick, ux * thick
        quad = [(p[0] - ux * hp - nx, p[1] - uy * hp - ny), (p[0] + ux * hp + nx, p[1] + uy * hp + ny),
                (q[0] + ux * hq + nx, q[1] + uy * hq + ny), (q[0] - ux * hq - nx, q[1] - uy * hq - ny)]
        polys.append(quad)
    return polys


def brush_polygons(samples, width: float, pressure: bool = True, round_caps: bool = True):
    """Brosse : largeur perpendiculaire au tracé, variable avec la pression ; bouts arrondis."""
    polys = []
    for p, q in zip(samples, samples[1:]):
        dx, dy = q[0] - p[0], q[1] - p[1]
        length = math.hypot(dx, dy)
        if not length:
            continue
        nx, ny = -dy / length, dx / length
        hp = width / 2 * (p[2] if pressure else 1.0)
        hq = width / 2 * (q[2] if pressure else 1.0)
        polys.append([(p[0] + nx * hp, p[1] + ny * hp), (q[0] + nx * hq, q[1] + ny * hq),
                      (q[0] - nx * hq, q[1] - ny * hq), (p[0] - nx * hp, p[1] - ny * hp)])
    if round_caps:
        for s in (samples[0], samples[-1]):
            r = width / 2 * (s[2] if pressure else 1.0)
            if r > 0:
                polys.append([(s[0] + r * math.cos(k * math.pi / 8), s[1] + r * math.sin(k * math.pi / 8))
                              for k in range(16)])
    return polys


def outline(samples, tool: str = "nib", width: float = 80.0, angle: float = 30.0, pressure: bool = True,
            smoothing: int = 2, error: float = 2.0, contrast: float = 0.0) -> list[Contour]:
    """Tracé -> contours éditables : formes balayées unies (pathops), puis chaque contour ajusté en cubiques."""
    samples = [(s[0], s[1], s[2] if len(s) > 2 else 1.0) for s in samples]
    if len(samples) < 2:
        return []
    samples = _smooth(_resample(samples, max(width / 12, 1.0)), smoothing)
    polys = (nib_polygons(samples, width, angle, pressure, contrast) if tool == "nib"
             else brush_polygons(samples, width, pressure))
    polys = [p for p in polys if _area(p) > 1e-6 or _area(p) < -1e-6]
    if not polys:
        return []
    recorder = RecordingPen()
    pathops.union([_Poly(_ccw(p)) for p in polys], recorder)
    result = []
    for poly in _polylines(recorder.value):
        curves = shapes.fit_cubic(poly + [poly[0]], error)
        contour = shapes.curves_to_contour(curves, closed=True)
        if len(contour):
            result.append(contour)
    return result


def _area(poly):
    return sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(poly, poly[1:] + poly[:1])) / 2


def _ccw(poly):
    return poly if _area(poly) > 0 else list(reversed(poly))


def _polylines(value):
    """Enregistrement d'un stylo -> polygones (les courbes éventuelles sont échantillonnées)."""
    out, cur = [], []
    for op, args in value:
        if op == "moveTo":
            cur = [args[0]]
        elif op == "lineTo":
            cur.append(args[0])
        elif op in ("curveTo", "qCurveTo"):
            start = cur[-1]
            pts = [start, *args]
            for k in range(1, 9):
                t = k / 8
                if op == "curveTo" and len(pts) == 4:
                    cur.append(cubic_at(*pts, t))
                else:
                    cur.append(args[-1])
                    break
        elif op in ("closePath", "endPath"):
            if len(cur) > 2:
                if cur[0] == cur[-1]:
                    cur = cur[:-1]
                out.append(cur)
            cur = []
    return out
