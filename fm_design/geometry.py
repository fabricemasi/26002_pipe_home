"""Géométrie PURE du module Design (sans Qt, testable seule) : magnétisme, alignement, répartition, recadrage.
Rectangles = (x, y, w, h) en coordonnées de page."""
from __future__ import annotations


def edges(rect) -> tuple[list[float], list[float]]:
    """Repères d'un rectangle : (gauche, centre, droite), (haut, milieu, bas)."""
    x, y, w, h = rect
    return [x, x + w / 2, x + w], [y, y + h / 2, y + h]


def best_snap(mine: list[float], theirs: list[float], threshold: float):
    """Plus petit décalage (|d| <= seuil) qui pose un repère de `mine` sur un repère de `theirs` :
    (décalage, valeur visée) ou (None, None)."""
    best = None
    for a in mine:
        for b in theirs:
            d = b - a
            if abs(d) <= threshold and (best is None or abs(d) < abs(best[0])):
                best = (d, b)
    return best if best is not None else (None, None)


def snap_move(rect, targets: list, page_size, threshold: float):
    """Magnétisme d'un déplacement : bords et centres de `rect` sur ceux de la page et des `targets`.
    Retourne (dx, dy, guides) ; guides = [("v", x) | ("h", y)]."""
    xs_t, ys_t = [0.0, page_size[0] / 2, page_size[0]], [0.0, page_size[1] / 2, page_size[1]]
    for t in targets:
        ex, ey = edges(t)
        xs_t += ex
        ys_t += ey
    mx, my = edges(rect)
    dx, gx = best_snap(mx, xs_t, threshold)
    dy, gy = best_snap(my, ys_t, threshold)
    guides = []
    if gx is not None:
        guides.append(("v", gx))
    if gy is not None:
        guides.append(("h", gy))
    return dx or 0.0, dy or 0.0, guides


def snap_value(value: float, targets: list[float], threshold: float):
    d, hit = best_snap([value], targets, threshold)
    return (value + d, hit) if d is not None else (value, None)


def align(rects: list, mode: str, reference=None) -> list[tuple[float, float]]:
    """Nouvelles positions (x, y) pour aligner `rects` (left, hcenter, right, top, vcenter, bottom) sur
    `reference` (rectangle de la page avec un seul élément, sinon l'enveloppe de la sélection)."""
    if reference is None:
        reference = union(rects)
    rx, ry, rw, rh = reference
    out = []
    for x, y, w, h in rects:
        if mode == "left":
            x = rx
        elif mode == "hcenter":
            x = rx + (rw - w) / 2
        elif mode == "right":
            x = rx + rw - w
        elif mode == "top":
            y = ry
        elif mode == "vcenter":
            y = ry + (rh - h) / 2
        elif mode == "bottom":
            y = ry + rh - h
        out.append((x, y))
    return out


def distribute(rects: list, axis: str) -> list[tuple[float, float]]:
    """Espaces égaux entre les éléments (axe « h » ou « v »), les extrêmes restent en place."""
    out = [(r[0], r[1]) for r in rects]
    if len(rects) < 3:
        return out
    i, size = (0, 2) if axis == "h" else (1, 3)
    order = sorted(range(len(rects)), key=lambda n: rects[n][i])
    first, last = rects[order[0]], rects[order[-1]]
    span = last[i] + last[size] - first[i]
    gap = (span - sum(rects[n][size] for n in order)) / (len(rects) - 1)
    pos = first[i]
    for n in order:
        x, y = out[n]
        out[n] = (pos, y) if axis == "h" else (x, pos)
        pos += rects[n][size] + gap
    return out


def union(rects: list):
    if not rects:
        return (0.0, 0.0, 0.0, 0.0)
    x0 = min(r[0] for r in rects)
    y0 = min(r[1] for r in rects)
    x1 = max(r[0] + r[2] for r in rects)
    y1 = max(r[1] + r[3] for r in rects)
    return (x0, y0, x1 - x0, y1 - y0)


def crop_edge(crop: list[float], size: tuple[float, float], edge: str, delta: float) -> tuple[list[float], float]:
    """Poignée de côté d'une image : le bord `edge` (l, r, t, b) bouge de `delta` (unités de l'élément) en
    découvrant / cachant l'image SANS changer son échelle. Retourne (recadrage, décalage réellement appliqué),
    borné par l'image source."""
    x0, y0, x1, y1 = crop
    w, h = size
    full_w = w / max(1e-9, x1 - x0)
    full_h = h / max(1e-9, y1 - y0)
    if edge == "l":
        nx = min(max(0.0, x0 + delta / full_w), x1 - 4.0 / full_w)
        return [nx, y0, x1, y1], (nx - x0) * full_w
    if edge == "r":
        nx = max(min(1.0, x1 + delta / full_w), x0 + 4.0 / full_w)
        return [x0, y0, nx, y1], (nx - x1) * full_w
    if edge == "t":
        ny = min(max(0.0, y0 + delta / full_h), y1 - 4.0 / full_h)
        return [x0, ny, x1, y1], (ny - y0) * full_h
    ny = max(min(1.0, y1 + delta / full_h), y0 + 4.0 / full_h)
    return [x0, y0, x1, ny], (ny - y1) * full_h


def pan_crop(crop: list[float], size: tuple[float, float], dx: float, dy: float) -> list[float]:
    """Déplacer l'image DANS son cadre (mode recadrage) : la fenêtre visible glisse en sens inverse, bornée."""
    x0, y0, x1, y1 = crop
    w, h = size
    fw, fh = x1 - x0, y1 - y0
    full_w, full_h = w / max(1e-9, fw), h / max(1e-9, fh)
    nx0 = min(max(0.0, x0 - dx / full_w), 1.0 - fw)
    ny0 = min(max(0.0, y0 - dy / full_h), 1.0 - fh)
    return [nx0, ny0, nx0 + fw, ny0 + fh]


def fit_inside(w: float, h: float, box_w: float, box_h: float, fill: float = 0.6) -> tuple[float, float]:
    """Taille d'une image posée dans une page : au plus `fill` de la page, proportions gardées."""
    if w <= 0 or h <= 0:
        return box_w * fill, box_h * fill
    k = min(box_w * fill / w, box_h * fill / h, 1.0 if max(w, h) < min(box_w, box_h) * fill else 1e9)
    return w * k, h * k
