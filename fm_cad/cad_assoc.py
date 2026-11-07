"""COTATIONS ASSOCIATIVES (phase 5 du cahier des charges, comme DIMASSOC = 2 d'AutoCAD) : logique PURE (aucun Qt).

Une cotation garde, pour chaque point de definition pose SUR un objet (accrochage a une extremite, un milieu, un
centre, un quadrant, un sommet ; ou objet choisi), le LIEN `assoc` :
- `{"p1": [id, poignee, x, y], "p2": [...]}` : id de l'objet, nom de sa poignee (`cad_shapes.grips` : p1 / p2 / mid
  d'une ligne, start / end / mid / center d'un arc, center / q0… d'un cercle, v<i> / m<i> d'une polyligne), et la
  place (document) ou le lien a mis le point la derniere fois ;
- rayon / diametre : `{"circle": [id, cx, cy, r]}` : le centre et le point du cercle suivent (meme direction) ;
- ANGULAIRE : `{"lines": [id1, t1, id2, t2, vx, vy]}` (deux lignes : le sommet = leur intersection, chaque point a la
  meme fraction `t` de sa ligne ; `vx, vy` = le sommet pose la derniere fois), `{"arc": [id, cx, cy]}` (un arc : le
  sommet = son centre, les points = ses extremites), ou des liens de poignee `center` / `p1` / `p2` (sommet et points
  accroches).

Quand l'objet change (deplace, etire, tourne, annule…), la cotation SUIT : ses points reprennent la place de la
poignee (`follow`). Un point que l'utilisateur a deplace lui-meme (ni a l'ancienne place du lien, ni deja a la
nouvelle) DETACHE ce lien (comme AutoCAD : tirer le point d'une cote la rend non associative)."""
from __future__ import annotations

import math

EPS = 1e-6


def _close(a, b, tol: float = EPS) -> bool:
    return abs(a[0] - b[0]) <= tol and abs(a[1] - b[1]) <= tol


def clean(assoc) -> dict:
    """Liens valides (forme du fichier) ; le reste est oublie."""
    out = {}
    if not isinstance(assoc, dict):
        return out
    for key in ("p1", "p2", "center"):
        link = assoc.get(key)
        if isinstance(link, (list, tuple)) and len(link) == 4 and isinstance(link[0], str) \
                and isinstance(link[1], str):
            try:
                out[key] = [link[0], link[1], float(link[2]), float(link[3])]
            except (TypeError, ValueError):
                pass
    link = assoc.get("circle")
    if isinstance(link, (list, tuple)) and len(link) == 4 and isinstance(link[0], str):
        try:
            out["circle"] = [link[0], float(link[1]), float(link[2]), float(link[3])]
        except (TypeError, ValueError):
            pass
    link = assoc.get("lines")
    if isinstance(link, (list, tuple)) and len(link) == 6 and isinstance(link[0], str) and isinstance(link[2], str):
        try:
            out["lines"] = [link[0], float(link[1]), link[2], float(link[3]), float(link[4]), float(link[5])]
        except (TypeError, ValueError):
            pass
    link = assoc.get("arc")
    if isinstance(link, (list, tuple)) and len(link) == 3 and isinstance(link[0], str):
        try:
            out["arc"] = [link[0], float(link[1]), float(link[2])]
        except (TypeError, ValueError):
            pass
    return out


def fraction(a, b, p) -> float:
    """Fraction (projection) du point `p` le long du segment a -> b (0 = a, 1 = b)."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    n2 = dx * dx + dy * dy
    return 0.0 if n2 <= 0 else ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / n2


def _intersection(a, b, c, d):
    r = (b[0] - a[0], b[1] - a[1])
    s = (d[0] - c[0], d[1] - c[1])
    den = r[0] * s[1] - r[1] * s[0]
    if abs(den) <= 1e-12 * max(1.0, math.hypot(*r) * math.hypot(*s)):
        return None
    t = ((c[0] - a[0]) * s[1] - (c[1] - a[1]) * s[0]) / den
    return a[0] + r[0] * t, a[1] + r[1] * t


def targets(assoc) -> set:
    """Ids des objets auxquels la cotation est liee."""
    out = set()
    for key in ("p1", "p2", "center", "circle", "arc"):
        link = (assoc or {}).get(key)
        if link:
            out.add(link[0])
    link = (assoc or {}).get("lines")
    if link:
        out.update((link[0], link[2]))
    return out


def grip_at(grips, point, tol: float):
    """Nom de la poignee qui est a `point` (a `tol` pres), sinon None ; [(nom, point)] = `cad_shapes.grips`."""
    best = None
    for name, p in grips:
        d = math.hypot(p[0] - point[0], p[1] - point[1])
        if d <= tol and (best is None or d < best[0]):
            best = (d, name)
    return None if best is None else best[1]


def _follow_angular(points: dict, links: dict, lookup, moved: dict, tol: float):
    """Liens angulaires (`lines`, `arc`) : sommet et points recalcules ; sommet deplace a la main = lien detache."""
    link = links.get("lines")
    if link is not None and "center" in points:
        first, second = lookup(link[0]), lookup(link[2])
        g1 = dict(first[0]) if first is not None else {}
        g2 = dict(second[0]) if second is not None else {}
        if not all(k in g for g in (g1, g2) for k in ("p1", "p2")):
            del links["lines"]
        else:
            vertex = _intersection(g1["p1"], g1["p2"], g2["p1"], g2["p2"])
            current = points["center"]
            if vertex is None:
                pass                                            # lignes devenues paralleles : la cote attend
            elif not _close(current, (link[4], link[5]), tol) and not _close(current, vertex, tol):
                del links["lines"]                              # sommet deplace a la main : lien detache
            else:
                t1, t2 = link[1], link[3]
                p1 = (g1["p1"][0] + (g1["p2"][0] - g1["p1"][0]) * t1, g1["p1"][1] + (g1["p2"][1] - g1["p1"][1]) * t1)
                p2 = (g2["p1"][0] + (g2["p2"][0] - g2["p1"][0]) * t2, g2["p1"][1] + (g2["p2"][1] - g2["p1"][1]) * t2)
                for key, p in (("center", vertex), ("p1", p1), ("p2", p2)):
                    if key in points and not _close(points[key], p, tol):
                        moved[key] = p
                links["lines"] = [link[0], t1, link[2], t2, vertex[0], vertex[1]]
    link = links.get("arc")
    if link is not None and "center" in points:
        found = lookup(link[0])
        grips = dict(found[0]) if found is not None else {}
        if not all(k in grips for k in ("center", "start", "end")):
            del links["arc"]
        elif not _close(points["center"], (link[1], link[2]), tol) and not _close(points["center"], grips["center"],
                                                                                    tol):
            del links["arc"]
        else:
            for key, name in (("center", "center"), ("p1", "start"), ("p2", "end")):
                if key in points and not _close(points[key], grips[name], tol):
                    moved[key] = tuple(grips[name])
            links["arc"] = [link[0], grips["center"][0], grips["center"][1]]


def follow(points: dict, assoc: dict, lookup, tol: float = EPS):
    """Nouveaux points de definition (document) d'une cotation et nouveaux liens : `points` = {"p1": (x, y),
    "p2": ...} actuels ; `lookup(id)` -> (grips [(nom, point)], cercle (centre, rayon) ou None) de l'objet, None s'il
    n'existe plus (lien oublie). Rend (points changes, liens) ; ({}, liens) si rien ne bouge."""
    links = clean(assoc)
    moved = {}
    _follow_angular(points, links, lookup, moved, tol)
    for key in ("p1", "p2", "center"):
        link = links.get(key)
        if link is None or key not in points:
            continue
        found = lookup(link[0])
        if found is None:
            del links[key]
            continue
        target = dict(found[0]).get(link[1])
        if target is None:
            del links[key]
            continue
        current = points[key]
        if _close(current, target, tol):
            links[key] = [link[0], link[1], target[0], target[1]]       # deja a sa place (deplaces ensemble)
            continue
        if not _close(current, (link[2], link[3]), tol):
            del links[key]                                          # point deplace a la main : lien detache
            continue
        moved[key] = (target[0], target[1])
        links[key] = [link[0], link[1], target[0], target[1]]
    link = links.get("circle")
    if link is not None and "p1" in points and "p2" in points:
        found = lookup(link[0])
        circle = found[1] if found is not None else None
        if circle is None:
            del links["circle"]
        else:
            (cx, cy), r = circle
            old_c, old_r = (link[1], link[2]), link[3]
            if not _close(points["p1"], old_c, tol) and not _close(points["p1"], (cx, cy), tol):
                del links["circle"]                                 # centre de la cote deplace a la main
            elif not (_close((cx, cy), old_c, tol) and abs(r - old_r) <= tol and _close(points["p1"], old_c, tol)):
                p2 = points["p2"]
                base = points["p1"]
                dx, dy = p2[0] - base[0], p2[1] - base[1]
                n = math.hypot(dx, dy) or 1.0
                moved["p1"] = (cx, cy)
                moved["p2"] = (cx + dx / n * r, cy + dy / n * r)
                links["circle"] = [link[0], cx, cy, r]
    return moved, links
