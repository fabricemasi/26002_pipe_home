"""Dessin « intelligent » (comme le Smart drawing de Miro : un trait a main levee devient une forme propre) et
gomme de precision (couper des traits au lieu de les supprimer).

Reconnaissance, sur les points du trait (coordonnees de scene) :
- trait OUVERT presque droit (corde >= 88 % de la longueur) -> ligne (connecteur sans fleche) ;
- trait FERME (extremites a moins de 20 % de la diagonale) simplifie (Ramer-Douglas-Peucker) : 3 sommets ->
  triangle ; 4 sommets -> losange s'ils sont au milieu des cotes du cadre, sinon rectangle ; sinon ellipse si
  le trait reste a distance reguliere du centre ;
- sinon : None (le trait reste un dessin).
Miro convertit aussi des post-it et d'autres formes : non reproduit (non verifie)."""
from __future__ import annotations

import math

from PySide6.QtCore import QLineF, QPointF, QRectF


def bounds(points) -> QRectF:
    """Cadre des points (QRectF.united ignore les rectangles nuls : il ne sert pas ici)."""
    xs = [p.x() for p in points]
    ys = [p.y() for p in points]
    return QRectF(QPointF(min(xs), min(ys)), QPointF(max(xs), max(ys)))


def _length(points) -> float:
    return sum(QLineF(points[i], points[i + 1]).length() for i in range(len(points) - 1))


def _rdp(points, epsilon):
    if len(points) < 3:
        return list(points)
    line = QLineF(points[0], points[-1])
    best, index = 0.0, 0
    for i in range(1, len(points) - 1):
        d = _distance_to_line(points[i], line)
        if d > best:
            best, index = d, i
    if best > epsilon:
        return _rdp(points[:index + 1], epsilon)[:-1] + _rdp(points[index:], epsilon)
    return [points[0], points[-1]]


def _distance_to_line(point, line: QLineF) -> float:
    dx, dy = line.dx(), line.dy()
    norm = math.hypot(dx, dy)
    if norm < 1e-9:
        return QLineF(point, line.p1()).length()
    return abs(dy * point.x() - dx * point.y() + line.p2().x() * line.p1().y() - line.p2().y() * line.p1().x()) / norm


def recognize(points: list[QPointF]):
    """("line", p1, p2) | ("rect" | "diamond" | "triangle" | "ellipse", QRectF) | None."""
    if len(points) < 4:
        return None
    rect = bounds(points)
    diagonal = math.hypot(rect.width(), rect.height())
    if diagonal < 12:
        return None
    length = _length(points)
    chord = QLineF(points[0], points[-1]).length()
    if chord >= 0.88 * length:
        return ("line", points[0], points[-1])
    if chord > 0.2 * diagonal:
        return None
    closed = list(points) + [points[0]]
    simple = _rdp(closed, 0.06 * diagonal)
    if len(simple) > 2 and QLineF(simple[0], simple[-1]).length() < 0.2 * diagonal:
        simple = simple[:-1]
    vertices = len(simple)
    if vertices == 3:
        return ("triangle", rect)
    if vertices == 4:
        cx, cy = rect.center().x(), rect.center().y()
        mid_hits = sum(1 for p in simple if min(abs(p.x() - cx) / max(1, rect.width()),
                                                 abs(p.y() - cy) / max(1, rect.height())) < 0.15)
        return ("diamond", rect) if mid_hits >= 3 else ("rect", rect)
    center = rect.center()
    rx, ry = max(1.0, rect.width() / 2), max(1.0, rect.height() / 2)
    radii = [math.hypot((p.x() - center.x()) / rx, (p.y() - center.y()) / ry) for p in points]
    mean = sum(radii) / len(radii)
    spread = math.sqrt(sum((r - mean) ** 2 for r in radii) / len(radii))
    if 0.75 < mean < 1.15 and spread < 0.16:
        return ("ellipse", rect)
    if vertices <= 6:
        return ("rect", rect)
    return None


def resample(points, step: float) -> list:
    """Points tous les `step` au plus (pour couper un trait finement)."""
    if len(points) < 2:
        return list(points)
    out = [points[0]]
    for a, b in zip(points, points[1:]):
        seg = QLineF(a, b).length()
        count = max(1, int(seg / max(0.5, step)))
        for n in range(1, count + 1):
            t = n / count
            out.append(QPointF(a.x() + (b.x() - a.x()) * t, a.y() + (b.y() - a.y()) * t))
    return out


def cut(points, center: QPointF, radius: float, step: float) -> list[list] | None:
    """Morceaux d'un trait apres le passage de la gomme de precision (cercle `center`, `radius`) ; None si le
    trait n'est pas touche ; [] s'il disparait entierement."""
    dense = resample(points, step)
    inside = [QLineF(p, center).length() <= radius for p in dense]
    if not any(inside):
        return None
    pieces, current = [], []
    for p, hit in zip(dense, inside):
        if hit:
            if len(current) >= 2:
                pieces.append(current)
            current = []
        else:
            current.append(p)
    if len(current) >= 2:
        pieces.append(current)
    return pieces
