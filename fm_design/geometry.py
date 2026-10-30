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


def snap_move(rect, targets: list, page_size, threshold: float, extra=((), ())):
    """Magnétisme d'un déplacement : bords et centres de `rect` sur ceux de la page, des `targets` et des repères
    de la page (`extra` = (x des repères verticaux, y des horizontaux)). Retourne (dx, dy, guides) ; guides =
    [("v", x) | ("h", y)]."""
    xs_t = [0.0, page_size[0] / 2, page_size[0]] + list(extra[0])
    ys_t = [0.0, page_size[1] / 2, page_size[1]] + list(extra[1])
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
    # Espacement ÉGAL entre deux voisins (comme les repères d'espacement de Canva), si aucun bord ne s'est aimanté.
    for axis in ("x", "y"):
        if (axis == "x" and gx is not None) or (axis == "y" and gy is not None):
            continue
        moved = (rect[0] + (dx or 0.0), rect[1] + (dy or 0.0), rect[2], rect[3])
        found = equal_gap(moved, targets, axis, threshold)
        if found is not None:
            shift, segments = found
            if axis == "x":
                dx = (dx or 0.0) + shift
            else:
                dy = (dy or 0.0) + shift
            guides += [("seg",) + seg for seg in segments]
    return dx or 0.0, dy or 0.0, guides


def equal_gap(rect, targets: list, axis: str, threshold: float):
    """Place `rect` à égale distance de ses plus proches voisins de part et d'autre (sur `axis`), s'ils se
    recouvrent avec lui sur l'autre axe et si le décalage nécessaire est sous le seuil : (décalage, segments à
    tracer (x1, y1, x2, y2)) ou None."""
    i, size, j, other = (0, 2, 1, 3) if axis == "x" else (1, 3, 0, 2)
    lo, hi = rect[j], rect[j] + rect[other]
    start, end = rect[i], rect[i] + rect[size]
    before = [t for t in targets if t[i] + t[size] <= start + threshold and t[j] < hi and t[j] + t[other] > lo]
    after = [t for t in targets if t[i] >= end - threshold and t[j] < hi and t[j] + t[other] > lo]
    if not before or not after:
        return None
    a = max(before, key=lambda t: t[i] + t[size])
    b = min(after, key=lambda t: t[i])
    target = (a[i] + a[size] + b[i] - rect[size]) / 2
    shift = target - start
    if abs(shift) > threshold or target - (a[i] + a[size]) <= 0:
        return None
    mid = max(lo, a[j], b[j]) + (min(hi, a[j] + a[other], b[j] + b[other]) - max(lo, a[j], b[j])) / 2
    first = (a[i] + a[size], target)
    second = (target + rect[size], b[i])
    if axis == "x":
        return shift, [(first[0], mid, first[1], mid), (second[0], mid, second[1], mid)]
    return shift, [(mid, first[0], mid, first[1]), (mid, second[0], mid, second[1])]


def parse_pages(text: str, count: int) -> list[int]:
    """« 1-3, 5 » -> [0, 1, 2, 4] (index), bornés à `count` ; vide ou illisible -> []."""
    out = []
    for part in (text or "").replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            if "-" in part:
                a, b = (int(v) for v in part.split("-", 1))
            else:
                a = b = int(part)
        except ValueError:
            return []
        for n in range(min(a, b), max(a, b) + 1):
            if 1 <= n <= count and n - 1 not in out:
                out.append(n - 1)
    return out


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


def cover_crop(frame_w: float, frame_h: float, image_w: float, image_h: float) -> list[float]:
    """Recadrage centré qui REMPLIT un cadre sans déformer l'image (comme une image déposée dans un cadre)."""
    if min(frame_w, frame_h, image_w, image_h) <= 0:
        return [0.0, 0.0, 1.0, 1.0]
    frame, image = frame_w / frame_h, image_w / image_h
    if image > frame:
        f = frame / image
        return [round((1 - f) / 2, 6), 0.0, round((1 + f) / 2, 6), 1.0]
    f = image / frame
    return [0.0, round((1 - f) / 2, 6), 1.0, round((1 + f) / 2, 6)]


# Grilles de photos : cases en fractions de la page (x, y, l, h) ; l'écart est ajouté à la pose.
GRIDS = {
    "2 colonnes": [(0, 0, .5, 1), (.5, 0, .5, 1)],
    "2 lignes": [(0, 0, 1, .5), (0, .5, 1, .5)],
    "3 colonnes": [(0, 0, 1 / 3, 1), (1 / 3, 0, 1 / 3, 1), (2 / 3, 0, 1 / 3, 1)],
    "2 × 2": [(0, 0, .5, .5), (.5, 0, .5, .5), (0, .5, .5, .5), (.5, .5, .5, .5)],
    "1 + 2": [(0, 0, .6, 1), (.6, 0, .4, .5), (.6, .5, .4, .5)],
    "1 + 3": [(0, 0, 1, .6), (0, .6, 1 / 3, .4), (1 / 3, .6, 1 / 3, .4), (2 / 3, .6, 1 / 3, .4)],
}


def grid_cells(name: str, page_w: float, page_h: float, gap: float) -> list[tuple[float, float, float, float]]:
    """Cases d'une grille (coordonnées de page), séparées de `gap`, avec `gap` de marge au bord."""
    out = []
    for fx, fy, fw, fh in GRIDS[name]:
        x0, y0 = fx * page_w + gap, fy * page_h + gap
        x1, y1 = (fx + fw) * page_w - (gap if fx + fw >= 0.999 else gap / 2), (fy + fh) * page_h - (
            gap if fy + fh >= 0.999 else gap / 2)
        if fx > 0.001:
            x0 = fx * page_w + gap / 2
        if fy > 0.001:
            y0 = fy * page_h + gap / 2
        out.append((round(x0, 2), round(y0, 2), round(x1 - x0, 2), round(y1 - y0, 2)))
    return out
