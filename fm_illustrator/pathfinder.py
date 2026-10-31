"""Pathfinder (SANS Qt) : opérations booléennes sur les sous-tracés du module, par skia-pathops (BSD-3, déjà dans
`requirements.txt` pour fm_font).

Modes de forme (panneau Pathfinder d'Illustrator) : Réunion, Soustraction (le plus haut ôté des autres), Intersection,
Exclusion. Pathfinders : Division (toutes les zones séparées), Découpe (chaque objet privé de ce qui est au-dessus),
Fusion (découpe + objets de même fond réunis), Recadrage (zones du plus bas objet couvertes par les autres), Contour
(segments des bords), Soustraction arrière (les objets du dessous ôtés du plus haut). Aussi : vectoriser le contour.

Les opérations travaillent sur des tracés en coordonnées de SCÈNE (l'appelant décale les nœuds de chaque objet) ;
l'objet le plus BAS est le premier de la liste. Le résultat garde des nœuds cubiques (quadratiques convertis)."""
from __future__ import annotations

import pathops

from . import bezier as bz

_OPS = {"union": pathops.PathOp.UNION, "difference": pathops.PathOp.DIFFERENCE,
        "intersection": pathops.PathOp.INTERSECTION, "xor": pathops.PathOp.XOR}


def to_path(subpaths, fill_rule: str = "nonzero") -> pathops.Path:
    """Sous-tracés -> `pathops.Path` (sous-tracés ouverts fermés implicitement, comme un fond)."""
    path = pathops.Path(fillType=pathops.FillType.EVEN_ODD if fill_rule == "evenodd" else pathops.FillType.WINDING)
    for sub in subpaths:
        nodes = sub["nodes"]
        if len(nodes) < 2:
            continue
        path.moveTo(nodes[0][0], nodes[0][1])
        count = len(nodes)
        for i in range(count if sub.get("closed") else count - 1):
            p0, c1, c2, p3 = bz.segment(sub, i)
            if bz.is_straight((p0, c1, c2, p3)):
                path.lineTo(*p3)
            else:
                path.cubicTo(c1[0], c1[1], c2[0], c2[1], p3[0], p3[1])
        path.close()
    return path


def from_path(path: pathops.Path) -> list[dict]:
    """`pathops.Path` -> sous-tracés fermés (format du module)."""
    out: list[dict] = []
    cur = None
    last = (0.0, 0.0)
    for verb, pts in path.segments:
        if verb == "moveTo":
            cur = {"closed": False, "nodes": [bz.node(*pts[0])]}
            out.append(cur)
            last = pts[0]
        elif verb == "lineTo":
            cur["nodes"].append(bz.node(*pts[0]))
            last = pts[0]
        elif verb == "curveTo":
            c1, c2, p = pts
            prev = cur["nodes"][-1]
            prev[4], prev[5] = c1
            cur["nodes"].append(bz.node(p[0], p[1], c2[0], c2[1]))
            last = p
        elif verb == "qCurveTo":                       # suite de quadratiques (points implicites) -> cubiques
            *offs, end = pts
            start = last
            for i, q in enumerate(offs):
                p = end if i == len(offs) - 1 else ((q[0] + offs[i + 1][0]) / 2, (q[1] + offs[i + 1][1]) / 2)
                c1 = (start[0] + 2 / 3 * (q[0] - start[0]), start[1] + 2 / 3 * (q[1] - start[1]))
                c2 = (p[0] + 2 / 3 * (q[0] - p[0]), p[1] + 2 / 3 * (q[1] - p[1]))
                prev = cur["nodes"][-1]
                prev[4], prev[5] = c1
                cur["nodes"].append(bz.node(p[0], p[1], c2[0], c2[1]))
                start = p
            last = end
        elif verb in ("closePath", "endPath") and cur is not None:
            if verb == "closePath":
                cur["closed"] = True
                bz.close_if_touching({"closed": False, "nodes": cur["nodes"]}, 1e-6)
                _merge_closing(cur)
            cur = None
    return [s for s in out if len(s["nodes"]) > 1]


def _merge_closing(sub: dict):
    """Dernier nœud confondu avec le premier (fermeture explicite) : fusionnés."""
    nodes = sub["nodes"]
    if len(nodes) > 2 and abs(nodes[0][0] - nodes[-1][0]) < 1e-6 and abs(nodes[0][1] - nodes[-1][1]) < 1e-6:
        last = nodes.pop()
        nodes[0][2], nodes[0][3] = last[2], last[3]


def _op(a: pathops.Path, b: pathops.Path, name: str) -> pathops.Path:
    return pathops.op(a, b, _OPS[name], fix_winding=True)


def _merge_all(paths, fill_type) -> pathops.Path:
    """Tous les contours dans UN tracé, simplifié en une passe : règle « winding » = Réunion, « pair-impair » =
    Exclusion (chaque objet d'abord ramené à sa surface). Enchaîner les XOR deux à deux coûtait ~4 s pour 200
    ellipses qui se chevauchent (le résultat grossit à chaque étape) ; une passe : voir docs/agents/fm_illustrator.md."""
    out = pathops.Path(fillType=fill_type)
    for p in paths:
        q = pathops.Path(p)
        q.simplify(fix_winding=True)
        out.addPath(q)
    out.simplify(fix_winding=True)
    return out


def is_empty(path: pathops.Path) -> bool:
    return abs(path.area) < 1e-6


def combine(shapes: list[tuple[list, str]], mode: str) -> list[dict]:
    """Modes de forme : `shapes` = [(sous-tracés, règle de remplissage)], du plus bas au plus haut.
    « unite », « minus_front », « intersect », « exclude », « minus_back »."""
    paths = [to_path(s, rule) for s, rule in shapes]
    if not paths:
        return []
    if mode == "unite":
        result = _merge_all(paths, pathops.FillType.WINDING)
    elif mode == "minus_front":                         # le plus bas, privé de tout ce qui est au-dessus
        result = paths[0]
        for p in paths[1:]:
            result = _op(result, p, "difference")
    elif mode == "minus_back":                          # le plus haut, privé de tout ce qui est en dessous
        result = paths[-1]
        for p in paths[:-1]:
            result = _op(result, p, "difference")
    elif mode == "intersect":
        result = paths[0]
        for p in paths[1:]:
            result = _op(result, p, "intersection")
    elif mode == "exclude":
        result = _merge_all(paths, pathops.FillType.EVEN_ODD)
    else:
        raise ValueError(mode)
    return from_path(result)


def divide(shapes: list[tuple[list, str]]) -> list[tuple[int, list[dict]]]:
    """Division : toutes les zones délimitées, chacune avec l'indice de l'objet le PLUS HAUT qui la couvre (son
    style). Zones vides écartées."""
    pieces: list[tuple[int, pathops.Path]] = []
    for index, (subs, rule) in enumerate(shapes):
        p = to_path(subs, rule)
        new = []
        rest = p
        for owner, piece in pieces:
            inside = _op(piece, p, "intersection")
            outside = _op(piece, p, "difference")
            if not is_empty(outside):
                new.append((owner, outside))
            if not is_empty(inside):
                new.append((index, inside))
            rest = _op(rest, piece, "difference")
        if not is_empty(rest):
            new.append((index, rest))
        pieces = new
    out = []
    for owner, piece in pieces:
        for sub in _split_regions(piece):
            out.append((owner, sub))
    return out


def _split_regions(path: pathops.Path) -> list[list[dict]]:
    """Une zone = un contour extérieur et ses trous (contours intérieurs) ; contours séparés = zones séparées."""
    subs = from_path(path)
    if len(subs) <= 1:
        return [subs] if subs else []
    outers, holes = [], []
    for sub in subs:
        (outers if _area(sub) * _area(subs[0]) > 0 or not outers else holes).append(sub)
    if not holes:
        return [[s] for s in outers]
    regions = [[o] for o in outers]
    for hole in holes:
        p = (hole["nodes"][0][0], hole["nodes"][0][1])
        for region in regions:
            if bz.point_inside([region[0]], p):
                region.append(hole)
                break
    return regions


def _area(sub: dict) -> float:
    pts = bz.flatten(sub, 1.0)
    return sum(pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1]
               for i in range(len(pts))) / 2


def trim(shapes: list[tuple[list, str]]) -> list[tuple[int, list[dict]]]:
    """Découpe : chaque objet privé des parties cachées par ceux du dessus (contours retirés par l'appelant)."""
    out = []
    paths = [to_path(s, rule) for s, rule in shapes]
    for index, p in enumerate(paths):
        visible = p
        for above in paths[index + 1:]:
            visible = _op(visible, above, "difference")
        if not is_empty(visible):
            out.append((index, from_path(visible)))
    return out


def merge(shapes: list[tuple[list, str]], fills: list[str]) -> list[tuple[int, list[dict]]]:
    """Fusion : découpe, puis les parties voisines de même fond réunies."""
    pieces = trim(shapes)
    groups: dict[str, tuple[int, pathops.Path]] = {}
    order = []
    for index, subs in pieces:
        key = fills[index]
        p = to_path(subs)
        if key in groups:
            groups[key] = (index, _op(groups[key][1], p, "union"))
        else:
            groups[key] = (index, p)
            order.append(key)
    return [(groups[k][0], from_path(groups[k][1])) for k in order]


def crop(shapes: list[tuple[list, str]]) -> list[tuple[int, list[dict]]]:
    """Recadrage : le plus HAUT objet sert de cadre ; les objets du dessous, découpés (dans leur partie visible)."""
    if len(shapes) < 2:
        return []
    frame = to_path(*shapes[-1])
    out = []
    for index, subs in trim(shapes[:-1]):
        inside = _op(to_path(subs), frame, "intersection")
        if not is_empty(inside):
            out.append((index, from_path(inside)))
    return out


def outline_stroke(subpaths, width: float, cap: str = "butt", join: str = "miter", miter: float = 10.0) -> list:
    """Vectoriser le contour : le trait devient une surface (pathops.Path.stroke)."""
    caps = {"butt": pathops.LineCap.BUTT_CAP, "round": pathops.LineCap.ROUND_CAP,
            "square": pathops.LineCap.SQUARE_CAP}
    joins = {"miter": pathops.LineJoin.MITER_JOIN, "round": pathops.LineJoin.ROUND_JOIN,
             "bevel": pathops.LineJoin.BEVEL_JOIN}
    path = pathops.Path()
    for sub in subpaths:
        nodes = sub["nodes"]
        if len(nodes) < 2:
            continue
        path.moveTo(nodes[0][0], nodes[0][1])
        for i in range(bz.segment_count(sub)):
            p0, c1, c2, p3 = bz.segment(sub, i)
            if bz.is_straight((p0, c1, c2, p3)):
                path.lineTo(*p3)
            else:
                path.cubicTo(c1[0], c1[1], c2[0], c2[1], p3[0], p3[1])
        if sub.get("closed"):
            path.close()
    path.stroke(width, caps.get(cap, pathops.LineCap.BUTT_CAP), joins.get(join, pathops.LineJoin.MITER_JOIN), miter)
    path.convertConicsToQuads()                         # extrémités / angles arrondis : coniques de Skia
    path.simplify(fix_winding=True)
    return from_path(path)


def offset_subpaths(subpaths, distance: float, fill_rule: str = "nonzero") -> list[dict]:
    """Décalage du tracé (effet) : la surface agrandie (distance > 0) ou réduite (< 0) de |distance|, angles en
    onglet ; par le trait de largeur 2 |distance| réuni à la surface ou ôté d'elle."""
    shape = to_path(subpaths, fill_rule)
    shape.simplify(fix_winding=True)
    band = pathops.Path()
    for sub in subpaths:
        nodes = sub["nodes"]
        if len(nodes) < 2:
            continue
        band.moveTo(nodes[0][0], nodes[0][1])
        for i in range(bz.segment_count(sub)):
            p0, c1, c2, p3 = bz.segment(sub, i)
            if bz.is_straight((p0, c1, c2, p3)):
                band.lineTo(*p3)
            else:
                band.cubicTo(c1[0], c1[1], c2[0], c2[1], p3[0], p3[1])
        band.close()                                    # un tracé ouvert a une surface (fermée) : comme Illustrator
    band.stroke(2 * abs(distance), pathops.LineCap.BUTT_CAP, pathops.LineJoin.MITER_JOIN, 4.0)
    band.convertConicsToQuads()
    band.simplify(fix_winding=True)
    return from_path(_op(shape, band, "union" if distance > 0 else "difference"))
