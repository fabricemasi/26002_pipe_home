"""Cotations du CAD : geometrie PURE (aucun Qt), en coordonnees du DOCUMENT (Y vers le haut, degres, sens
trigonometrique). Une cotation est UNE entite (`cad_dim`) qui produit des segments (lignes d'attache, ligne de cote,
fleches) et un texte ; le dessin du texte est fait par l'element (`cad_items.CadDimItem`).

Champs de l'entite (en plus des proprietes communes des entites CAD) :
- `dim_type`  : "linear" (horizontale / verticale / pivotee : `rot`), "aligned" (parallele aux deux points),
                "radius", "diameter", "angular" ;
- `p1`, `p2`  : points mesures (origines des lignes d'attache) ; rayon / diametre : p1 = centre, p2 = point du cercle ;
                angulaire : p1 et p2 = les deux points (le sommet est `center`) ;
- `pos`       : un point de la ligne de cote (decalage) ; rayon / diametre : ou poser le texte ;
- `rot`       : direction de mesure d'une cotation lineaire (degres : 0 = horizontale, 90 = verticale) ;
- `center`    : sommet d'une cotation angulaire ;
- `dim_text`, `dim_arrow`, `dim_gap`, `dim_over`, `dim_arrow_kind`, `dim_dec`, `dim_unit` : style copie des reglages a
                la creation (hauteur du texte, taille des fleches, ecart d'une ligne d'attache a son origine,
                depassement, forme des fleches, decimales, unites du board par unite de mesure) ;
- `dim_str`   : texte propre ("" = valeur mesuree ; « <> » = la valeur mesuree dans un texte)."""
from __future__ import annotations

import math

from . import cad_geometry as geo

TYPES = ("linear", "aligned", "radius", "diameter", "angular")
ARROW_KINDS = ("triangle", "open", "tick")
MM = 96.0 / 25.4                   # unites du board par millimetre (1 unite = 1/96 de pouce)

STYLE_DEFAULTS = {"dim_text": 2.5 * MM, "dim_arrow": 2.5 * MM, "dim_gap": 1.0 * MM, "dim_over": 1.25 * MM,
                  "dim_arrow_kind": "triangle", "dim_dec": 2, "dim_unit": MM, "dim_str": ""}
GEOMETRY_KEYS = ("p1", "p2", "pos", "center", "rot")


def _pt(value, default=(0.0, 0.0)):
    try:
        return (float(value[0]), float(value[1]))
    except (TypeError, ValueError, IndexError, KeyError):
        return default


def _num(value, default=0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if math.isfinite(out) else default


def style_of(data: dict) -> dict:
    out = dict(STYLE_DEFAULTS)
    for key, default in STYLE_DEFAULTS.items():
        if key in data and data[key] is not None:
            out[key] = data[key] if isinstance(default, str) else _num(data[key], default)
    out["dim_text"] = max(1e-6, out["dim_text"])
    out["dim_arrow"] = max(0.0, out["dim_arrow"])
    out["dim_dec"] = max(0, min(8, int(out["dim_dec"])))
    out["dim_unit"] = out["dim_unit"] if out["dim_unit"] > 0 else MM
    if out["dim_arrow_kind"] not in ARROW_KINDS:
        out["dim_arrow_kind"] = "triangle"
    return out


def format_value(value: float, s: dict) -> str:
    """Valeur mesuree (unites du board) -> texte dans l'unite de mesure, decimales fixes, zeros de fin retires."""
    text = f"{value / s['dim_unit']:.{s['dim_dec']}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def _readable(angle: float) -> float:
    """Angle du texte ramene dans ]-90, 90] : il se lit toujours de gauche a droite."""
    angle = (angle + 180.0) % 360.0 - 180.0
    if angle > 90.0:
        angle -= 180.0
    elif angle <= -90.0:
        angle += 180.0
    return angle


def _arrow(tip, body, size: float, kind: str) -> list:
    """Segments d'une fleche dont la pointe est en `tip` et dont le corps s'etend dans la direction `body`."""
    if size <= geo.EPS:
        return []
    n = (-body[1], body[0])
    if kind == "tick":                                   # trait oblique d'architecte (45 degres)
        r = ((body[0] + n[0]) * size * 0.5, (body[1] + n[1]) * size * 0.5)
        return [((tip[0] - r[0], tip[1] - r[1]), (tip[0] + r[0], tip[1] + r[1]))]
    half = size / 6.0 if kind == "triangle" else size / 4.0
    b1 = (tip[0] + body[0] * size + n[0] * half, tip[1] + body[1] * size + n[1] * half)
    b2 = (tip[0] + body[0] * size - n[0] * half, tip[1] + body[1] * size - n[1] * half)
    out = [(tip, b1), (tip, b2)]
    if kind == "triangle":
        out.append((b1, b2))
    return out


def _arrows_on(a, b, size: float, kind: str) -> list:
    """Fleches aux deux bouts d'une ligne de cote a -> b : a l'interieur, ou a l'exterieur (avec un bout de ligne)
    quand la ligne est trop courte."""
    length = geo.distance(a, b)
    if length <= geo.EPS:
        return []
    d = ((b[0] - a[0]) / length, (b[1] - a[1]) / length)
    if kind == "tick" or length >= 2.2 * size:
        return _arrow(a, d, size, kind) + _arrow(b, (-d[0], -d[1]), size, kind)
    tail = 1.8 * size
    out = [(a, (a[0] - d[0] * tail, a[1] - d[1] * tail)), (b, (b[0] + d[0] * tail, b[1] + d[1] * tail))]
    return out + _arrow(a, (-d[0], -d[1]), size, kind) + _arrow(b, d, size, kind)


def _text_box(text: str, height: float) -> float:
    return max(1, len(text)) * 0.6 * height


def _linear(p1, p2, pos, rot: float, s: dict) -> dict:
    r = math.radians(rot)
    d = (math.cos(r), math.sin(r))
    n = (-math.sin(r), math.cos(r))
    t = pos[0] * n[0] + pos[1] * n[1]
    t1 = p1[0] * n[0] + p1[1] * n[1]
    t2 = p2[0] * n[0] + p2[1] * n[1]
    a = (p1[0] + n[0] * (t - t1), p1[1] + n[1] * (t - t1))
    b = (p2[0] + n[0] * (t - t2), p2[1] + n[1] * (t - t2))
    segments = []
    for origin, foot, t0 in ((p1, a, t1), (p2, b, t2)):
        side = 1.0 if t >= t0 else -1.0
        if abs(t - t0) > geo.EPS:
            segments.append(((origin[0] + n[0] * side * s["dim_gap"], origin[1] + n[1] * side * s["dim_gap"]),
                             (foot[0] + n[0] * side * s["dim_over"], foot[1] + n[1] * side * s["dim_over"])))
    value = abs((p2[0] - p1[0]) * d[0] + (p2[1] - p1[1]) * d[1])
    if geo.distance(a, b) > geo.EPS:
        segments.append((a, b))
    segments += _arrows_on(a, b, s["dim_arrow"], s["dim_arrow_kind"])
    angle = _readable(rot)
    up = (-math.sin(math.radians(angle)), math.cos(math.radians(angle)))
    mid = ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)
    gap = s["dim_text"] * 0.5
    return {"segments": segments, "value": value, "prefix": "", "angle": angle,
            "text_pos": (mid[0] + up[0] * gap, mid[1] + up[1] * gap)}


def _radius(center, point, pos, s: dict) -> dict:
    r = geo.distance(center, point)
    if r <= geo.EPS:
        return {"segments": [], "value": 0.0, "prefix": "R", "angle": 0.0, "text_pos": center}
    d = ((point[0] - center[0]) / r, (point[1] - center[1]) / r)
    reach = max(r, (pos[0] - center[0]) * d[0] + (pos[1] - center[1]) * d[1])
    end = (center[0] + d[0] * reach, center[1] + d[1] * reach)
    segments = [(center, end)] + _arrow(point, (-d[0], -d[1]), s["dim_arrow"], s["dim_arrow_kind"])
    angle = _readable(math.degrees(math.atan2(d[1], d[0])))
    up = (-math.sin(math.radians(angle)), math.cos(math.radians(angle)))
    return {"segments": segments, "value": r, "prefix": "R", "angle": angle, "end": end, "dir": d,
            "text_pos": None, "up": up}


def _diameter(center, point, pos, s: dict) -> dict:
    r = geo.distance(center, point)
    if r <= geo.EPS:
        return {"segments": [], "value": 0.0, "prefix": "Ø", "angle": 0.0, "text_pos": center}
    d = ((point[0] - center[0]) / r, (point[1] - center[1]) / r)
    far = (center[0] - d[0] * r, center[1] - d[1] * r)
    segments = [(far, point)]
    segments += _arrow(point, (-d[0], -d[1]), s["dim_arrow"], s["dim_arrow_kind"])
    segments += _arrow(far, d, s["dim_arrow"], s["dim_arrow_kind"])
    angle = _readable(math.degrees(math.atan2(d[1], d[0])))
    up = (-math.sin(math.radians(angle)), math.cos(math.radians(angle)))
    return {"segments": segments, "value": 2.0 * r, "prefix": "Ø", "angle": angle, "center": center, "up": up,
            "dir": d, "radius": r, "text_pos": None}


def _angular(vertex, p1, p2, pos, s: dict) -> dict:
    """Angle entre les directions sommet -> p1 et sommet -> p2, du cote de `pos` : arc de cote + lignes d'attache."""
    def ang_of(p):
        return math.degrees(math.atan2(p[1] - vertex[1], p[0] - vertex[0]))
    a1, a2 = ang_of(p1), ang_of(p2)
    radius = max(geo.distance(vertex, pos), 1e-6)
    sweep = (a2 - a1) % 360.0
    if (ang_of(pos) - a1) % 360.0 > sweep:               # pos hors de l'angle a1 -> a2 (sens trigo) : l'autre cote
        a1, a2, p1, p2 = a2, a1, p2, p1
        sweep = (a2 - a1) % 360.0

    def at(angle, dist):
        return (vertex[0] + math.cos(math.radians(angle)) * dist, vertex[1] + math.sin(math.radians(angle)) * dist)
    segments = []
    for point, angle in ((p1, a1), (p2, a2)):
        dist = geo.distance(vertex, point)
        if dist < radius:
            start, end = dist + s["dim_gap"], radius + s["dim_over"]
        else:
            start, end = dist - s["dim_gap"], radius - s["dim_over"]
        if abs(end - start) > geo.EPS:
            segments.append((at(angle, start), at(angle, end)))
    kind, size = s["dim_arrow_kind"], s["dim_arrow"]
    segments += _arrow(at(a1, radius), (-math.sin(math.radians(a1)), math.cos(math.radians(a1))), size, kind)
    segments += _arrow(at(a2, radius), (math.sin(math.radians(a2)), -math.cos(math.radians(a2))), size, kind)
    mid_angle = a1 + sweep / 2.0
    mid = at(mid_angle, radius)
    angle = _readable(mid_angle + 90.0)
    up = (-math.sin(math.radians(angle)), math.cos(math.radians(angle)))
    outward = (math.cos(math.radians(mid_angle)), math.sin(math.radians(mid_angle)))
    flip = 1.0 if up[0] * outward[0] + up[1] * outward[1] >= 0 else -1.0
    gap = s["dim_text"] * 0.5 * flip
    return {"segments": segments, "arc": ("arc", vertex, radius, a1, sweep), "value": sweep, "prefix": "",
            "angle": angle, "text_pos": (mid[0] + up[0] * gap, mid[1] + up[1] * gap)}


def geometry(data: dict, offset=(0.0, 0.0)) -> dict:
    """Segments (+ arc de cote d'une cotation angulaire), valeur mesuree, texte et sa place."""
    s = style_of(data)
    ox, oy = offset

    def P(key, default=(0.0, 0.0)):
        p = _pt(data.get(key), default)
        return (p[0] + ox, p[1] + oy)
    kind = data.get("dim_type", "linear")
    p1, p2, pos = P("p1"), P("p2"), P("pos", None) if data.get("pos") is not None else None
    if pos is None:
        pos = ((p1[0] + p2[0]) / 2.0, (p1[1] + p2[1]) / 2.0)
    if kind == "aligned":
        found = _linear(p1, p2, pos, math.degrees(math.atan2(p2[1] - p1[1], p2[0] - p1[0])), s)
    elif kind == "radius":
        found = _radius(p1, p2, pos, s)
    elif kind == "diameter":
        found = _diameter(p1, p2, pos, s)
    elif kind == "angular":
        found = _angular(P("center"), p1, p2, pos, s)
    else:
        found = _linear(p1, p2, pos, _num(data.get("rot"), 0.0), s)
    value = found["value"]
    if kind == "angular":
        text = f"{value:.{s['dim_dec']}f}"
        text = (text.rstrip("0").rstrip(".") if "." in text else text) + "°"
    else:
        text = found["prefix"] + format_value(value, s)
    custom = str(data.get("dim_str") or "")
    if custom:
        text = custom.replace("<>", text)
    height = s["dim_text"]
    width = _text_box(text, height)
    if found["text_pos"] is None:                        # rayon / diametre : texte au bout de la ligne ou au centre
        up = found["up"]
        if kind == "radius":
            d, end = found["dir"], found["end"]
            c = (end[0] + d[0] * (width / 2.0 + height * 0.4), end[1] + d[1] * (width / 2.0 + height * 0.4))
            found["text_pos"] = (c[0] - up[0] * height * 0.5, c[1] - up[1] * height * 0.5)
        else:
            center, r = found["center"], found["radius"]
            if geo.distance(center, pos) > r + height:   # texte pose dehors, a l'endroit choisi
                found["text_pos"] = (pos[0] - up[0] * height * 0.5, pos[1] - up[1] * height * 0.5)
            else:
                found["text_pos"] = (center[0] + up[0] * height * 0.5, center[1] + up[1] * height * 0.5)
    prims = [("segment", a, b) for a, b in found["segments"] if geo.distance(a, b) > geo.EPS]
    if found.get("arc") is not None:
        prims.append(found["arc"])
    return {"prims": prims, "text": text, "text_pos": found["text_pos"], "text_angle": found["angle"],
            "text_height": height, "value": value}


def grips(data: dict, offset=(0.0, 0.0)) -> list:
    """Poignees : points mesures et position de la ligne de cote (centre du cercle / sommet : deplace tout)."""
    ox, oy = offset
    out = []
    for name in ("p1", "p2", "pos"):
        if data.get(name) is not None:
            p = _pt(data.get(name))
            out.append((name, (p[0] + ox, p[1] + oy)))
    return out


def translate(data: dict, delta) -> dict:
    out = {}
    for name in ("p1", "p2", "pos", "center"):
        if data.get(name) is not None:
            p = _pt(data.get(name))
            out[name] = [p[0] + delta[0], p[1] + delta[1]]
    return out


def transform(data: dict, fn, rot_fn=None) -> dict:
    """Points transformes par `fn(point)` ; la direction de mesure d'une cotation lineaire par `rot_fn(angle)`."""
    out = {}
    for name in ("p1", "p2", "pos", "center"):
        if data.get(name) is not None:
            p = fn(_pt(data.get(name)))
            out[name] = [p[0], p[1]]
    if rot_fn is not None and data.get("dim_type", "linear") == "linear":
        out["rot"] = rot_fn(_num(data.get("rot"), 0.0)) % 360.0
    return out
