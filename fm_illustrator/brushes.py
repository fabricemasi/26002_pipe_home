"""Pinceaux et largeur variable (SANS Qt) : contour d'épaisseur variable calculé comme une SURFACE (comme
Illustrator le montre après « Décomposer l'aspect »).

- `width_profile` d'un tracé : [[t, facteur]] (t = position 0-1 le long du tracé, facteur × `stroke_width`),
  interpolé linéairement ; vide = uniforme. Profils prédéfinis `PROFILES` (noms d'Illustrator : Uniforme, profils
  « fuseau », effilés…). L'outil Largeur (Maj+W) y ajoute / modifie des points.
- `brush` d'un tracé : pointe CALLIGRAPHIQUE {"type": "calligraphic", "angle" (°), "roundness" (0-1), "size"} :
  ellipse de grand axe `size` inclinée de `angle` ; la largeur du trait dépend de la direction (plus large quand
  le trait croise le grand axe). Combinée au profil s'il y en a un.
Le contour : points échantillonnés le long du tracé (`bezier.flatten`), décalés de ± largeur / 2 selon la normale,
extrémités rondes ou plates ; un tracé fermé donne deux boucles de sens opposés (anneau, règle non nulle). Puis
réduction des points presque alignés (0,05 unité, en une passe)."""
from __future__ import annotations

import math

from . import bezier as bz

PROFILES = {
    "uniform": ("Uniforme", []),
    "spindle": ("Fuseau", [[0.0, 0.0], [0.5, 1.0], [1.0, 0.0]]),
    "taper_end": ("Effilé à la fin", [[0.0, 1.0], [1.0, 0.0]]),
    "taper_start": ("Effilé au début", [[0.0, 0.0], [1.0, 1.0]]),
    "taper_both": ("Effilé aux deux bouts", [[0.0, 0.1], [0.2, 1.0], [0.8, 1.0], [1.0, 0.1]]),
    "bulge": ("Renflé", [[0.0, 0.5], [0.5, 1.6], [1.0, 0.5]]),
}
CALLIGRAPHIC = {"type": "calligraphic", "angle": 30.0, "roundness": 0.3, "size": 8.0}


def _num(value, default: float) -> float:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and value == value \
        else default


def valid_profile(raw) -> list:
    out = []
    for p in raw if isinstance(raw, list) else []:
        if isinstance(p, (list, tuple)) and len(p) >= 2:
            out.append([min(1.0, max(0.0, _num(p[0], 0.0))), min(50.0, max(0.0, _num(p[1], 1.0)))])
    out.sort(key=lambda p: p[0])
    return out[:64]


def valid_brush(raw) -> dict | None:
    if not isinstance(raw, dict) or raw.get("type") != "calligraphic":
        return None
    return {"type": "calligraphic", "angle": _num(raw.get("angle"), 30.0) % 180.0,
            "roundness": min(1.0, max(0.02, _num(raw.get("roundness"), 0.3))),
            "size": min(1000.0, max(0.1, _num(raw.get("size"), 8.0)))}


def has_brush(data: dict) -> bool:
    return bool(data.get("width_profile") or data.get("brush"))


def factor_at(profile: list, t: float) -> float:
    if not profile:
        return 1.0
    if t <= profile[0][0]:
        return profile[0][1]
    for (t0, f0), (t1, f1) in zip(profile, profile[1:]):
        if t <= t1:
            return f0 if t1 - t0 < 1e-9 else f0 + (f1 - f0) * (t - t0) / (t1 - t0)
    return profile[-1][1]


def nib_width(brush: dict, direction: float) -> float:
    """Largeur balayée par la pointe elliptique perpendiculairement à la direction `direction` (radians)."""
    a = brush["size"] / 2
    b = a * brush["roundness"]
    phi = direction - math.radians(brush["angle"])
    return 2 * math.sqrt((a * math.sin(phi)) ** 2 + (b * math.cos(phi)) ** 2)


def _flatten_np(sub: dict):
    """Points du sous-tracé (numpy, TOUS les segments d'un coup) : segment courbe échantillonné, droit gardé."""
    import numpy as np
    count = bz.segment_count(sub)
    nodes = sub["nodes"]
    if count == 0:
        return np.array([nodes[0][0]]), np.array([nodes[0][1]])
    segs = np.array([[s[0], s[1], s[2], s[3]] for s in (bz.segment(sub, i) for i in range(count))], dtype=float)
    p0, c1, c2, p3 = segs[:, 0], segs[:, 1], segs[:, 2], segs[:, 3]
    straight = (np.abs(c1 - p0).max(axis=1) < bz.EPS) & (np.abs(c2 - p3).max(axis=1) < bz.EPS)
    length = (np.hypot(*(c1 - p0).T) + np.hypot(*(c2 - c1).T) + np.hypot(*(p3 - c2).T))
    steps = np.where(straight, 1, np.clip(np.ceil(np.sqrt(length / 0.5) * 1.2), 2, 200)).astype(int)
    owner = np.repeat(np.arange(count), steps)
    start = np.concatenate(([0], np.cumsum(steps)[:-1]))
    t = (np.arange(int(steps.sum())) - start[owner] + 1) / steps[owner]
    u = 1.0 - t
    a, b, c, e = (u * u * u)[:, None], (3 * u * u * t)[:, None], (3 * u * t * t)[:, None], (t * t * t)[:, None]
    pts = a * p0[owner] + b * c1[owner] + c * c2[owner] + e * p3[owner]
    return np.concatenate(([nodes[0][0]], pts[:, 0])), np.concatenate(([nodes[0][1]], pts[:, 1]))


def outline(data: dict) -> list[dict]:
    """Contour à largeur variable du tracé (sous-tracés fermés, règle non nulle) ; vide si rien à peindre."""
    return [{"closed": True, "nodes": [[x, y, x, y, x, y, 0] for x, y in poly]} for poly in outline_polygons(data)]


def outline_polygons(data: dict) -> list[list[tuple[float, float]]]:
    """Polygones du contour (vectorisé, numpy) : l'affichage les pose d'un bloc (`QPainterPath.addPolygon`)."""
    import numpy as np
    width = float(data.get("stroke_width", 1.0))
    profile = data.get("width_profile") or []
    brush = data.get("brush")
    round_cap = data.get("cap") == "round" or brush is not None
    out = []
    for sub in data.get("subpaths") or []:
        if not sub["nodes"]:
            continue
        x, y = _flatten_np(sub)
        closed = bool(sub.get("closed"))
        if closed and len(x) > 2 and math.hypot(x[0] - x[-1], y[0] - y[-1]) > 1e-9:
            x, y = np.append(x, x[0]), np.append(y, y[0])
        seg = np.hypot(np.diff(x), np.diff(y))
        keep = np.concatenate(([True], seg > 1e-6))
        x, y = x[keep], y[keep]
        if len(x) < 2:
            continue
        s = np.concatenate(([0.0], np.cumsum(np.hypot(np.diff(x), np.diff(y)))))
        total = float(s[-1]) or 1.0
        step = max(2.0, total / 120.0)                 # points intercalés sur les segments longs (droites)
        grid = np.union1d(s, np.arange(0.0, total, step))
        x, y, s = np.interp(grid, s, x), np.interp(grid, s, y), grid
        n = len(x)
        if closed:
            ax, ay = np.roll(x[:-1], 1), np.roll(y[:-1], 1)
            bx, by = np.roll(x[:-1], -1), np.roll(y[:-1], -1)
            ax, ay = np.append(ax, ax[0]), np.append(ay, ay[0])
            bx, by = np.append(bx, bx[0]), np.append(by, by[0])
        else:
            ax, ay = x[np.maximum(np.arange(n) - 1, 0)], y[np.maximum(np.arange(n) - 1, 0)]
            bx, by = x[np.minimum(np.arange(n) + 1, n - 1)], y[np.minimum(np.arange(n) + 1, n - 1)]
        direction = np.arctan2(by - ay, bx - ax)
        if brush:
            a = brush["size"] / 2
            b = a * brush["roundness"]
            phi = direction - math.radians(brush["angle"])
            base = 2 * np.sqrt((a * np.sin(phi)) ** 2 + (b * np.cos(phi)) ** 2)
        else:
            base = np.full(n, width)
        if profile:
            factors = np.interp(s / total, [p[0] for p in profile], [p[1] for p in profile])
        else:
            factors = 1.0
        half = base * factors / 2
        nx, ny = -np.sin(direction), np.cos(direction)
        lx, ly = x + nx * half, y + ny * half
        rx, ry = x - nx * half, y - ny * half
        if closed:
            out.append(_polygon(np.column_stack((lx[:-1], ly[:-1]))))
            out.append(_polygon(np.column_stack((rx[:-1][::-1], ry[:-1][::-1]))))
            continue
        end_cap = _cap((x[-1], y[-1]), (x[-2], y[-2]), float(half[-1]), round_cap)
        start_cap = _cap((x[0], y[0]), (x[1], y[1]), float(half[0]), round_cap)
        parts = [np.column_stack((lx, ly))]
        if end_cap:
            parts.append(np.array(end_cap))
        parts.append(np.column_stack((rx[::-1], ry[::-1])))
        if start_cap:
            parts.append(np.array(start_cap))
        out.append(_polygon(np.concatenate(parts)))     # tout en tableaux : pas d'aller-retour par des listes
    return [poly for poly in out if len(poly) > 2]


def _resample(pts: list) -> list:
    """Points intercalés sur les segments longs (une droite n'a que ses deux extrémités : le profil ne s'y verrait
    pas) : pas d'un deux-centième de la longueur, 1 unité au moins."""
    if len(pts) < 2:
        return pts
    total = sum(math.dist(pts[i - 1], pts[i]) for i in range(1, len(pts)))
    step = max(1.0, total / 200.0)
    out = [pts[0]]
    for a, b in zip(pts, pts[1:]):
        d = math.dist(a, b)
        k = int(d // step)
        for j in range(1, k + 1):
            t = j * step / d
            if t < 1.0 - 1e-9:
                out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
        out.append(b)
    return out


def _cap(end, before, w, round_cap: bool) -> list:
    """Points de l'extrémité ronde (demi-cercle, de la gauche vers la droite) ; plate : aucun."""
    if not round_cap or w <= 1e-6:
        return []
    direction = math.atan2(end[1] - before[1], end[0] - before[0])
    steps = max(4, min(24, int(w)))
    return [(end[0] + w * math.cos(direction + math.pi / 2 - math.pi * k / steps),
             end[1] + w * math.sin(direction + math.pi / 2 - math.pi * k / steps)) for k in range(1, steps)]


def _polygon(points) -> list:
    return _thin_np(points, 0.1)


def _thin_np(points, tol: float) -> list:
    """Points presque alignés retirés (vectorisé) : à chaque passe, un point sur deux d'une série de points à moins
    de `tol` de la droite de leurs voisins (jamais deux voisins à la fois : l'écart ne s'accumule pas) ; 3 passes."""
    import numpy as np
    pts = np.asarray(points, dtype=float)
    if len(pts) < 5:
        return pts.tolist()
    for _ in range(3):
        n = len(pts)
        if n < 5:
            break
        a = np.concatenate((pts[-1:], pts[:-1]))
        b = np.concatenate((pts[1:], pts[:1]))
        ab = b - a
        length = np.hypot(ab[:, 0], ab[:, 1])
        cross = np.abs((pts[:, 0] - a[:, 0]) * ab[:, 1] - (pts[:, 1] - a[:, 1]) * ab[:, 0])
        dev = np.where(length > 1e-12, cross / np.maximum(length, 1e-12), np.hypot(*(pts - a).T))
        removable = dev <= tol
        removable[np.arange(n) % 2 == 1] = False          # jamais deux voisins retirés dans la même passe
        if not removable.any():
            break
        pts = pts[~removable]
    return pts.tolist()


def _thin(points: list, tol: float) -> list:
    """Points presque alignés retirés, en UNE passe (écart à la droite entre le dernier point gardé et le suivant) ;
    Ramer-Douglas-Peucker coûtait ~280 ms sur 7 000 points (quasi quadratique), ceci ~5 ms."""
    if len(points) < 4:
        return points
    out = [points[0]]
    for i in range(1, len(points) - 1):
        a, p, b = out[-1], points[i], points[i + 1]
        dx, dy = b[0] - a[0], b[1] - a[1]
        d = math.hypot(dx, dy)
        dev = abs((p[0] - a[0]) * dy - (p[1] - a[1]) * dx) / d if d > 1e-12 else math.dist(a, p)
        if dev > tol:
            out.append(p)
    out.append(points[-1])
    return out


def locate(data: dict, pos) -> tuple | None:
    """(distance, t le long du sous-tracé, point) du point du tracé le plus proche de `pos` (repère de l'élément) ;
    t en fraction de LONGUEUR (comme le profil)."""
    best = None
    for sub in data.get("subpaths") or []:
        pts = bz.flatten(sub, 0.2)
        if sub.get("closed") and pts:
            pts.append(pts[0])
        if len(pts) < 2:
            continue
        lengths = [0.0]
        for i in range(1, len(pts)):
            lengths.append(lengths[-1] + math.dist(pts[i - 1], pts[i]))
        total = lengths[-1] or 1.0
        for i in range(1, len(pts)):
            a, b = pts[i - 1], pts[i]
            dx, dy = b[0] - a[0], b[1] - a[1]
            seg = dx * dx + dy * dy
            u = 0.0 if seg < 1e-12 else max(0.0, min(1.0, ((pos[0] - a[0]) * dx + (pos[1] - a[1]) * dy) / seg))
            p = (a[0] + dx * u, a[1] + dy * u)
            d = math.dist(p, pos)
            if best is None or d < best[0]:
                best = (d, (lengths[i - 1] + math.sqrt(seg) * u) / total, p)
    return best


def stroke_hit_width(data: dict) -> float:
    """Plus grande largeur du contour (zone cliquable, marges)."""
    width = float(data.get("stroke_width", 1.0))
    if data.get("brush"):
        width = float(data["brush"]["size"])
    factor = max([p[1] for p in data.get("width_profile") or []] + [1.0])
    return width * factor
