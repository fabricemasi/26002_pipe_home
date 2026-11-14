"""Conversion d'entités du module CAD en tracés Illustrator (SANS Qt) : « Convertir en tracés Illustrator » (clic
droit du CAD), l'inverse de `to_cad`.

- TRAITS (`cad_line`, `cad_arc`, `cad_circle`, `cad_pline`) -> tracé avec contour : couleur et épaisseur EFFECTIVES
  (ByLayer résolu), tirets du type de ligne (`dash`), bouts arrondis si l'extrémité l'est ; arcs -> cubiques
  (90° au plus chacune, écart ~0,03 % du rayon) ; primitives qui se suivent = un sous-tracé, refermé s'il revient
  à son départ (cercle, polyligne fermée).
- HACHURES (`cad_hatch`) -> REMPLISSAGE : plein = fond de la couleur (opacité `hatch_alpha`), pair / impair comme le
  CAD (trous) ; dégradé = dégradé Illustrator (linéaire, radial pour les formes sphériques) ; masque = fond blanc ;
  motif (lignes, croisillons, briques, motif d'AutoCAD) = ses traits, en contour.
Les autres entités (cotes, textes, blocs, images, points, droites infinies) ne sont pas converties (None).

Repères : CAD = document (Y vers le haut) ; Illustrator = scène (Y vers le bas). Tracé rendu avec son origine (x, y)
au coin haut gauche de sa boîte (comme `tools_draw.place_origin`)."""
from __future__ import annotations

import math

from fm_cad import cad_hatch, cad_shapes

from . import bezier as bz, paint

STROKE_KINDS = ("cad_line", "cad_arc", "cad_circle", "cad_pline")
KINDS = STROKE_KINDS + ("cad_hatch",)
THIN = 1.0                      # épaisseur d'un trait fin du CAD (0 = un pixel) dans Illustrator (unités du board)
EPS = 1e-6


def _scene(p) -> tuple[float, float]:
    return float(p[0]), -float(p[1])


def _arc_cubics(c, r, a0, sweep) -> list:
    """Arc (document, degrés, sens trigo si sweep > 0) -> cubiques (scène)."""
    count = max(1, math.ceil(abs(sweep) / 90.0 - 1e-9))
    step = math.radians(sweep) / count
    k = 4.0 / 3.0 * math.tan(step / 4.0)
    out = []
    t = math.radians(a0)
    for _ in range(count):
        t1 = t + step
        p0 = (c[0] + r * math.cos(t), c[1] + r * math.sin(t))
        p3 = (c[0] + r * math.cos(t1), c[1] + r * math.sin(t1))
        c1 = (p0[0] - k * r * math.sin(t), p0[1] + k * r * math.cos(t))
        c2 = (p3[0] + k * r * math.sin(t1), p3[1] - k * r * math.cos(t1))
        out.append(tuple(_scene(p) for p in (p0, c1, c2, p3)))
        t = t1
    return out


def _cubics(prim) -> list:
    if prim[0] == "arc":
        return _arc_cubics(*prim[1:5]) if prim[2] > EPS and abs(prim[4]) > EPS else []
    a, b = _scene(prim[1]), _scene(prim[2])
    if math.dist(a, b) <= EPS:
        return []
    return [(a, a, b, b)]


def subpaths_of(prims) -> list[dict]:
    """Primitives (document) -> sous-tracés (scène) : celles qui se suivent sont enchaînées."""
    runs: list[list] = []
    for prim in prims:
        for cubic in _cubics(prim):
            if runs and math.dist(runs[-1][-1][3], cubic[0]) <= EPS:
                runs[-1].append(cubic)
            else:
                runs.append([cubic])
    out = []
    for run in runs:
        sub = bz.from_cubics(run, False)
        bz.close_if_touching(sub, tolerance=EPS * 10)               # cercle, polyligne fermée
        out.append(sub)
    return out


def _loops_subpaths(loops, offset) -> list[dict]:
    out = []
    for loop in cad_hatch.clean_loops(loops):
        pts = [_scene((p[0] + offset[0], p[1] + offset[1])) for p in loop]
        cubics = [(a, a, b, b) for a, b in zip(pts, pts[1:] + pts[:1]) if math.dist(a, b) > EPS]
        if len(cubics) >= 2:
            sub = bz.from_cubics(cubics, False)
            bz.close_if_touching(sub, tolerance=EPS * 10)
            out.append(sub)
    return out


def _placed(subpaths, values: dict) -> dict | None:
    """Valeurs d'un `ill_path` : géométrie ramenée au coin haut gauche de sa boîte (x, y)."""
    box = bz.bounds(subpaths)
    if not subpaths or box is None:
        return None
    bz.transform(subpaths, bz.translate(-box[0], -box[1]))
    return {"subpaths": subpaths, "x": box[0], "y": box[1], "group": "", "width_profile": [], "brush": None,
            "fill_gradient": None, "stroke_gradient": None, **values}


def _stroke_style(props: dict) -> dict:
    width = float(props.get("lineweight") or 0.0)
    width = width if width > 0 else THIN
    scale = float(props.get("ltscale") or 1.0)
    dash = [max(0.1, abs(v) * scale) for v in props.get("pattern") or ()]
    end = (props.get("end1") or {}).get("style")
    return {"stroke": str(props.get("color") or "#000000").lower()[:7], "stroke_width": width, "dash": dash,
            "cap": "round" if end in ("round", "radius") else "butt", "join": "round" if end == "round" else "miter"}


def entity_to_path(kind: str, data: dict, props: dict, offset=(0.0, 0.0)) -> dict | None:
    """Entité CAD (données, propriétés EFFECTIVES `cad_model.resolve`, place Qt en document) -> valeurs d'un
    `ill_path` ; None si elle n'est pas convertie."""
    if kind in STROKE_KINDS:
        subs = subpaths_of(cad_shapes.prims(kind, data, offset))
        return _placed(subs, {"fill": "", "opacity": 1.0, "fill_rule": "nonzero", **_stroke_style(props)})
    if kind != "cad_hatch":
        return None
    style = cad_hatch.style_of(data)
    color = str(props.get("color") or "#000000").lower()[:7]
    pattern = style["pattern"]
    if pattern in ("solid", cad_hatch.WIPEOUT, cad_hatch.GRADIENT):
        values = {"fill": "#ffffff" if pattern == cad_hatch.WIPEOUT else color, "stroke": "", "fill_rule": "evenodd",
                  "opacity": style["alpha"] / 100.0 if pattern == "solid" else 1.0}
        if pattern == cad_hatch.GRADIENT:
            radial = "SPHERICAL" in style["gradient"]
            values["fill_gradient"] = paint.new_gradient("radial" if radial else "linear", color, style["color2"][:7])
        return _placed(_loops_subpaths(data.get("loops"), offset), values)
    subs = subpaths_of(cad_hatch.prims(data, offset))                 # motif : ses traits
    return _placed(subs, {"fill": "", "opacity": 1.0, "fill_rule": "nonzero", **_stroke_style(props), "dash": []})
