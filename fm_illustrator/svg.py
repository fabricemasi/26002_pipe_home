"""Export et import SVG (SANS Qt) des éléments Illustrator.

Export : un fichier par plan de travail (viewBox = le plan, unités du board = px CSS), ou l'ensemble des objets ;
chaque tracé = un `<path>` (fond, contour, épaisseur, extrémités, jointures, tirets, règle de remplissage, opacité),
groupes = `<g>`, dégradés = `<linearGradient>` / `<radialGradient>` (userSpaceOnUse) dans `<defs>`.
Import : `<path>` (M L H V C S Q T A Z, absolus et relatifs), `<rect>` (coins arrondis), `<circle>`, `<ellipse>`,
`<line>`, `<polyline>`, `<polygon>`, `<g>` ; attributs et `style` en ligne ; `transform` (matrix, translate, scale,
rotate, skewX, skewY) appliqué aux nœuds ; `<image>` (URI data: ou fichier, copiée dans le board par l'appelant) ;
dégradés `url(#id)` (objectBoundingBox ou userSpaceOnUse, `href` vers
les arrêts d'un autre dégradé ; `gradientTransform` ignoré). Non lus : CSS de `<style>`, `<use>`, texte, images,
masques."""
from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape, quoteattr

from . import bezier as bz, model, paint

SVG_NS = "http://www.w3.org/2000/svg"


# ---------------------------------------------------------------- export
def _paint(color: str) -> tuple[str, float]:
    """(couleur « #rrggbb » ou « none », opacité) depuis « #rrggbb » / « #aarrggbb » / vide."""
    if not color:
        return "none", 1.0
    if len(color) == 9:
        return "#" + color[3:], int(color[1:3], 16) / 255.0
    return color, 1.0


def path_element(data: dict, dx: float = 0.0, dy: float = 0.0, refs: dict | None = None) -> str:
    """`<path>` ; `refs` = {"fill" / "stroke": "url(#id)"} pour un dégradé."""
    from . import appearance, brushes
    d = bz.svg_d(appearance.render_subpaths(data), data.get("x", 0.0) + dx, data.get("y", 0.0) + dy)
    if not d:
        return ""
    above = ""                                          # contour à largeur variable : une surface au-dessus
    if data.get("stroke") and brushes.has_brush(data):
        color, op = _paint(data["stroke"])
        if (refs or {}).get("stroke"):
            color, op = refs["stroke"], 1.0
        extra = f' fill-opacity="{bz._num(op)}"' if op < 1 else ""
        bd = bz.svg_d(brushes.outline(data), data.get("x", 0.0) + dx, data.get("y", 0.0) + dy)
        above = f'<path d="{bd}" fill="{color}"{extra}/>' if bd else ""
        data = dict(data, stroke="")
    under = []                                          # contours supplémentaires (aspect) : sous l'objet
    for stroke in data.get("extra_strokes") or []:
        color, op = _paint(stroke["color"])
        op *= float(stroke.get("opacity", 1.0))
        extra = f' stroke-opacity="{bz._num(op)}"' if op < 1 else ""
        under.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{bz._num(stroke["width"])}"'
                     f'{extra}/>')
    refs = refs or {}
    fill, fill_op = _paint(data.get("fill", ""))
    stroke, stroke_op = _paint(data.get("stroke", ""))
    if refs.get("fill"):
        fill, fill_op = refs["fill"], 1.0
    if refs.get("stroke") and stroke != "none":
        stroke, stroke_op = refs["stroke"], 1.0
    attrs = [f'd="{d}"', f'fill="{fill}"']
    if fill != "none" and fill_op < 1.0:
        attrs.append(f'fill-opacity="{bz._num(fill_op)}"')
    if fill != "none" and data.get("fill_rule") == "evenodd":
        attrs.append('fill-rule="evenodd"')
    width = float(data.get("stroke_width", 1.0))
    if stroke != "none" and width > 0:
        attrs.append(f'stroke="{stroke}" stroke-width="{bz._num(width)}"')
        if stroke_op < 1.0:
            attrs.append(f'stroke-opacity="{bz._num(stroke_op)}"')
        if data.get("cap", "butt") != "butt":
            attrs.append(f'stroke-linecap="{data["cap"]}"')
        if data.get("join", "miter") != "miter":
            attrs.append(f'stroke-linejoin="{data["join"]}"')
        elif float(data.get("miter", 10.0)) != 4.0:
            attrs.append(f'stroke-miterlimit="{bz._num(float(data.get("miter", 10.0)))}"')
        dash = [v for v in data.get("dash") or [] if v > 0]
        if dash:
            attrs.append(f'stroke-dasharray="{" ".join(bz._num(v) for v in dash)}"')
    opacity = float(data.get("opacity", 1.0))
    if opacity < 1.0:
        attrs.append(f'opacity="{bz._num(opacity)}"')
    if data.get("name"):
        attrs.append(f"id={quoteattr(_xml_id(data['name']))}")
    element = "".join(under) + f"<path {' '.join(attrs)}/>" + above
    fid = (refs or {}).get("filter")
    if fid:
        return f'<g filter="url(#{fid})">{element}</g>'
    return f"<g>{element}</g>" if under or above else element


def _xml_id(name: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("_") or "objet"
    return text if text[0].isalpha() or text[0] == "_" else "_" + text


def image_element(data: dict, dx: float, dy: float, href: str) -> str:
    """`<image>` : rectangle (0, 0, w, h) et matrice de l'objet (décalée à sa place)."""
    if not href:
        return ""
    a, b, c, d, e, f = data.get("matrix") or (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    num = bz._num
    e += data.get("x", 0.0) + dx
    f += data.get("y", 0.0) + dy
    extra = f' opacity="{num(float(data["opacity"]))}"' if float(data.get("opacity", 1.0)) < 1 else ""
    return (f'<image width="{num(data.get("w", 100.0))}" height="{num(data.get("h", 100.0))}" '
            f'preserveAspectRatio="none" transform="matrix({num(a)} {num(b)} {num(c)} {num(d)} {num(e)} {num(f)})"'
            f'{extra} href={quoteattr(href)}/>')


def export_svg(objects: list[dict], area: tuple[float, float, float, float] | None = None,
               background: str = "", title: str = "", text_svg=None, image_href=None) -> str:
    """Document SVG des `objects` (dicts `ill_path`, déjà dans l'ordre de dessin). `area` = (x, y, l, h) : zone
    exportée (un plan de travail), origine du SVG en son coin ; None = cadre de tous les objets."""
    if area is None:
        box = bz.union_bounds(_object_bounds(o) for o in objects)
        if box is None:
            box = (0.0, 0.0, 1.0, 1.0)
        area = (box[0], box[1], max(1.0, box[2] - box[0]), max(1.0, box[3] - box[1]))
    x, y, w, h = area
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             f'<svg xmlns="{SVG_NS}" version="1.1" width="{bz._num(w)}" height="{bz._num(h)}" '
             f'viewBox="0 0 {bz._num(w)} {bz._num(h)}">']
    if title:
        lines.append(f"<title>{escape(title)}</title>")
    if background:
        color, op = _paint(background)
        extra = f' fill-opacity="{bz._num(op)}"' if op < 1 else ""
        lines.append(f'<rect width="{bz._num(w)}" height="{bz._num(h)}" fill="{color}"{extra}/>')
    defs, refs_of = [], {}
    for n, data in enumerate(objects):
        box = bz.bounds(data.get("subpaths") or [])
        for which in ("fill", "stroke"):
            g = data.get(f"{which}_gradient")
            if g and box is not None and (which == "fill" or data.get("stroke")):
                gid = f"degrade{len(defs) + 1}"
                defs.append(paint.svg_gradient(g, box, gid, data.get("x", 0.0) - x, data.get("y", 0.0) - y))
                refs_of.setdefault(n, {})[which] = f"url(#{gid})"
    from . import appearance
    for n, data in enumerate(objects):
        if data.get("type") != model.TEXT and appearance.has_raster(data):
            fid = f"effets{n + 1}"
            defs.append(appearance.svg_filter(data, fid))
            refs_of.setdefault(n, {})["filter"] = fid
    wrap = {}                                           # groupe masqué -> attribut du <g>
    for n, data in enumerate(objects):
        kind, g = data.get("mask"), data.get("group") or ""
        if not kind or not g or g in wrap:
            continue
        mid = f"masque{len(wrap) + 1}"
        if data.get("type") == model.TEXT:
            inner = text_svg(data, -x, -y) if text_svg is not None else ""
        else:
            inner = path_element(dict(data, fill=data.get("fill") or ("#000000" if kind == "clip" else "")),
                                 -x, -y, refs_of.get(n))
        if kind == "clip":
            defs.append(f'<clipPath id="{mid}">{inner}</clipPath>')
            wrap[g] = f'clip-path="url(#{mid})"'
        else:
            if data.get("mask_invert"):                 # inversé : blanc partout, puis le masque en différence
                inner = (f'<rect x="-100000" y="-100000" width="200000" height="200000" fill="#ffffff"/>'
                         f'<g style="mix-blend-mode:difference">{inner}</g>')
            defs.append(f'<mask id="{mid}" maskUnits="userSpaceOnUse" x="-100000" y="-100000" width="200000" '
                        f'height="200000">{inner}</mask>')
            wrap[g] = f'mask="url(#{mid})"'
    if defs:
        lines.append("<defs>" + "".join(defs) + "</defs>")
    group = None
    for n, data in enumerate(objects):
        if data.get("hidden"):
            continue
        g = data.get("group") or ""
        if g != group:
            if group:
                lines.append("</g>")
            if g:
                lines.append(f"<g {wrap[g]}>" if g in wrap else "<g>")
            group = g
        if data.get("mask") and g in wrap:              # le masque est dans <defs>
            continue
        if data.get("type") == model.TEXT:              # texte : `text.svg_text` (mise en page Qt), fourni
            element = text_svg(data, -x, -y) if text_svg is not None else ""
        elif data.get("type") == model.IMAGE:           # image : incorporée (`image_href`, fourni)
            element = image_element(data, -x, -y, image_href(data) if image_href is not None else "")
            fid = (refs_of.get(n) or {}).get("filter")
            if element and fid:
                element = f'<g filter="url(#{fid})">{element}</g>'
        else:
            element = path_element(data, -x, -y, refs_of.get(n))
        if element:
            lines.append(element)
    if group:
        lines.append("</g>")
    lines.append("</svg>")
    return "\n".join(lines) + "\n"


def _object_bounds(data: dict):
    if data.get("type") == model.IMAGE:
        m = data.get("matrix") or (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
        w, h = float(data.get("w", 100.0)), float(data.get("h", 100.0))
        pts = [bz.apply(m, px, py) for px, py in ((0, 0), (w, 0), (w, h), (0, h))]
        ox, oy = data.get("x", 0.0), data.get("y", 0.0)
        return (min(p[0] for p in pts) + ox, min(p[1] for p in pts) + oy, max(p[0] for p in pts) + ox,
                max(p[1] for p in pts) + oy)
    if data.get("type") == model.TEXT and data.get("mode") != "path":     # estimation sans Qt (import, cadre)
        size = float(data.get("font_size", 16.0))
        lines = str(data.get("text", "")).split("\n")
        x, y = data.get("x", 0.0), data.get("y", 0.0)
        w = max(len(line) for line in lines) * size * 0.55
        return x, y - size, x + w, y + size * float(data.get("leading", 1.2)) * (len(lines) - 1) + size * 0.3
    box = bz.bounds(data.get("subpaths") or [])
    if box is None:
        return None
    ox, oy = data.get("x", 0.0), data.get("y", 0.0)
    return box[0] + ox, box[1] + oy, box[2] + ox, box[3] + oy


# ---------------------------------------------------------------- import : données de chemin
_TOKEN = re.compile(r"[MmLlHhVvCcSsQqTtAaZz]|[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")
_ARGS = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "S": 4, "Q": 4, "T": 2, "A": 7, "Z": 0}


def parse_d(d: str) -> list[dict]:
    """Sous-tracés (format du module) depuis l'attribut `d` d'un chemin SVG."""
    tokens = _TOKEN.findall(d or "")
    subs: list[dict] = []
    cur = None
    x = y = 0.0
    start = (0.0, 0.0)
    last_ctrl = None                    # dernière poignée cubique (S) ou quadratique (T)
    i = 0
    cmd = ""

    def new_sub(px, py):
        nonlocal cur
        cur = {"closed": False, "nodes": [bz.node(px, py)]}
        subs.append(cur)

    def curve(c1, c2, p):
        nonlocal x, y
        if cur is None:
            new_sub(x, y)
        prev = cur["nodes"][-1]
        prev[4], prev[5] = c1
        cur["nodes"].append(bz.node(p[0], p[1], c2[0], c2[1]))
        x, y = p

    def line_to(px, py):
        nonlocal x, y
        if cur is None:
            new_sub(x, y)
        cur["nodes"].append(bz.node(px, py))
        x, y = px, py

    while i < len(tokens):
        tok = tokens[i]
        if tok.isalpha():
            cmd = tok
            i += 1
            if cmd in "Zz":
                if cur is not None:
                    bz.close_if_touching(cur, 1e-6)
                    cur["closed"] = len(cur["nodes"]) > 1
                    x, y = start
                    cur = None
                continue
        if not cmd:
            break
        upper = cmd.upper()
        n = _ARGS[upper]
        if upper == "A":                                # drapeaux d'arc parfois collés (« 0 01 »)
            args = []
            while len(args) < 7 and i < len(tokens) and not tokens[i].isalpha():
                t = tokens[i]
                if len(args) in (3, 4) and len(t) > 1 and t[0] in "01" and not t.startswith(("0.", "1.")):
                    args.append(float(t[0]))
                    tokens[i] = t[1:]
                    continue
                args.append(float(t))
                i += 1
        else:
            args = [float(t) for t in tokens[i:i + n]]
            i += n
        if len(args) < n:
            break
        rel = cmd.islower()
        ox, oy = (x, y) if rel else (0.0, 0.0)
        if upper == "M":
            x, y = args[0] + ox, args[1] + oy
            new_sub(x, y)
            start = (x, y)
            cmd = "l" if rel else "L"                    # paires suivantes = lignes
            last_ctrl = None
        elif upper == "L":
            line_to(args[0] + ox, args[1] + oy)
            last_ctrl = None
        elif upper == "H":
            line_to(args[0] + (x if rel else 0.0), y)
            last_ctrl = None
        elif upper == "V":
            line_to(x, args[0] + (y if rel else 0.0))
            last_ctrl = None
        elif upper == "C":
            c1 = (args[0] + ox, args[1] + oy)
            c2 = (args[2] + ox, args[3] + oy)
            curve(c1, c2, (args[4] + ox, args[5] + oy))
            last_ctrl = ("C", c2)
        elif upper == "S":
            c1 = (2 * x - last_ctrl[1][0], 2 * y - last_ctrl[1][1]) if last_ctrl and last_ctrl[0] == "C" else (x, y)
            c2 = (args[0] + ox, args[1] + oy)
            curve(c1, c2, (args[2] + ox, args[3] + oy))
            last_ctrl = ("C", c2)
        elif upper in ("Q", "T"):
            if upper == "Q":
                q = (args[0] + ox, args[1] + oy)
                p = (args[2] + ox, args[3] + oy)
            else:
                q = (2 * x - last_ctrl[1][0], 2 * y - last_ctrl[1][1]) if last_ctrl and last_ctrl[0] == "Q" \
                    else (x, y)
                p = (args[0] + ox, args[1] + oy)
            c1 = (x + 2 / 3 * (q[0] - x), y + 2 / 3 * (q[1] - y))
            c2 = (p[0] + 2 / 3 * (q[0] - p[0]), p[1] + 2 / 3 * (q[1] - p[1]))
            curve(c1, c2, p)
            last_ctrl = ("Q", q)
        elif upper == "A":
            p = (args[5] + ox, args[6] + oy)
            for c1, c2, end in arc_to_cubics((x, y), args[0], args[1], args[2], bool(args[3]), bool(args[4]), p):
                curve(c1, c2, end)
            x, y = p
            last_ctrl = None
    return [s for s in subs if len(s["nodes"]) > 1 or s["closed"]]


def arc_to_cubics(p0, rx, ry, phi, large, sweep, p1) -> list[tuple]:
    """Arc elliptique SVG (notes d'implémentation SVG 1.1, annexe F.6) en cubiques (c1, c2, fin)."""
    if math.dist(p0, p1) < 1e-12:
        return []
    rx, ry = abs(rx), abs(ry)
    if rx < 1e-12 or ry < 1e-12:
        return [(p0, p1, p1)]
    a = math.radians(phi % 360)
    ca, sa = math.cos(a), math.sin(a)
    dx, dy = (p0[0] - p1[0]) / 2, (p0[1] - p1[1]) / 2
    x1 = ca * dx + sa * dy
    y1 = -sa * dx + ca * dy
    lam = x1 * x1 / (rx * rx) + y1 * y1 / (ry * ry)
    if lam > 1:
        rx, ry = rx * math.sqrt(lam), ry * math.sqrt(lam)
    num = rx * rx * ry * ry - rx * rx * y1 * y1 - ry * ry * x1 * x1
    den = rx * rx * y1 * y1 + ry * ry * x1 * x1
    k = math.sqrt(max(0.0, num / den)) if den else 0.0
    if large == sweep:
        k = -k
    cxp, cyp = k * rx * y1 / ry, -k * ry * x1 / rx
    cx = ca * cxp - sa * cyp + (p0[0] + p1[0]) / 2
    cy = sa * cxp + ca * cyp + (p0[1] + p1[1]) / 2

    def ang(ux, uy, vx, vy):
        return math.atan2(ux * vy - uy * vx, ux * vx + uy * vy)
    t1 = ang(1, 0, (x1 - cxp) / rx, (y1 - cyp) / ry)
    dt = ang((x1 - cxp) / rx, (y1 - cyp) / ry, (-x1 - cxp) / rx, (-y1 - cyp) / ry)
    if not sweep and dt > 0:
        dt -= 2 * math.pi
    elif sweep and dt < 0:
        dt += 2 * math.pi
    parts = max(1, int(math.ceil(abs(dt) / (math.pi / 2) - 1e-9)))
    step = dt / parts
    alpha = 4 / 3 * math.tan(step / 4)
    out = []

    def pt(t):
        x, y = rx * math.cos(t), ry * math.sin(t)
        return ca * x - sa * y + cx, sa * x + ca * y + cy

    def deriv(t):
        x, y = -rx * math.sin(t), ry * math.cos(t)
        return ca * x - sa * y, sa * x + ca * y
    t = t1
    for _ in range(parts):
        s, e = pt(t), pt(t + step)
        ds, de = deriv(t), deriv(t + step)
        out.append(((s[0] + alpha * ds[0], s[1] + alpha * ds[1]), (e[0] - alpha * de[0], e[1] - alpha * de[1]), e))
        t += step
    last = out[-1]
    out[-1] = (last[0], last[1], p1)                    # fin exacte
    return out


# ---------------------------------------------------------------- import : document
_NUM = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")
NAMED = {"black": "#000000", "white": "#ffffff", "red": "#ff0000", "green": "#008000", "blue": "#0000ff",
         "yellow": "#ffff00", "gray": "#808080", "grey": "#808080", "orange": "#ffa500", "purple": "#800080"}


def parse_transform(text: str):
    m = bz.IDENTITY
    for name, args in re.findall(r"(matrix|translate|scale|rotate|skewX|skewY)\s*\(([^)]*)\)", text or ""):
        v = [float(t) for t in _NUM.findall(args)]
        if name == "matrix" and len(v) == 6:
            t = tuple(v)
        elif name == "translate" and v:
            t = bz.translate(v[0], v[1] if len(v) > 1 else 0.0)
        elif name == "scale" and v:
            t = bz.scale(v[0], v[1] if len(v) > 1 else v[0])
        elif name == "rotate" and v:
            t = bz.rotate(v[0], v[1], v[2]) if len(v) >= 3 else bz.rotate(v[0])
        elif name == "skewX" and v:
            t = (1.0, 0.0, math.tan(math.radians(v[0])), 1.0, 0.0, 0.0)
        elif name == "skewY" and v:
            t = (1.0, math.tan(math.radians(v[0])), 0.0, 1.0, 0.0, 0.0)
        else:
            continue
        m = bz.multiply(t, m)                           # la transformation la plus à droite s'applique d'abord
    return m


def parse_color(text, current="#000000") -> str | None:
    """« #rgb », « #rrggbb », « rgb(r, g, b) », noms courants ; « none » = "" ; None = non précisé / inconnu."""
    if text is None:
        return None
    t = text.strip().lower()
    if t == "none" or t == "transparent":
        return ""
    if t == "currentcolor":
        return current
    if t.startswith("#") and len(t) == 4:
        return "#" + "".join(c * 2 for c in t[1:])
    if t.startswith("#") and len(t) == 7:
        return t
    if t.startswith("rgb"):
        v = _NUM.findall(t)
        if len(v) >= 3:
            vals = [float(x) * (2.55 if "%" in t else 1.0) for x in v[:3]]
            return "#" + "".join(f"{max(0, min(255, round(c))):02x}" for c in vals)
    return NAMED.get(t)


def _styles(el, inherited: dict) -> dict:
    style = dict(inherited)
    for key in ("fill", "stroke", "stroke-width", "opacity", "fill-opacity", "stroke-opacity", "stroke-linecap",
                "stroke-linejoin", "stroke-miterlimit", "stroke-dasharray", "fill-rule", "display", "stop-color",
                "stop-opacity", "offset", "font-size", "font-family", "font-weight", "font-style"):
        if el.get(key) is not None:
            style[key] = el.get(key)
    for part in (el.get("style") or "").split(";"):
        if ":" in part:
            k, v = part.split(":", 1)
            style[k.strip()] = v.strip()
    return style


def _length(text, default=0.0) -> float:
    if text is None:
        return default
    v = _NUM.findall(str(text))
    return float(v[0]) if v else default


def _shape_subpaths(tag: str, el) -> list:
    g = el.get
    if tag == "path":
        return parse_d(g("d", ""))
    if tag == "rect":
        w, h = _length(g("width")), _length(g("height"))
        if w <= 0 or h <= 0:
            return []
        rx = _length(g("rx"), -1)
        ry = _length(g("ry"), -1)
        r = max(rx, ry) if max(rx, ry) > 0 else 0.0
        return bz.rect(_length(g("x")), _length(g("y")), w, h, r)
    if tag == "circle":
        r = _length(g("r"))
        return bz.ellipse(_length(g("cx")), _length(g("cy")), r, r) if r > 0 else []
    if tag == "ellipse":
        rx, ry = _length(g("rx")), _length(g("ry"))
        return bz.ellipse(_length(g("cx")), _length(g("cy")), rx, ry) if rx > 0 and ry > 0 else []
    if tag == "line":
        return bz.line(_length(g("x1")), _length(g("y1")), _length(g("x2")), _length(g("y2")))
    if tag in ("polyline", "polygon"):
        v = [float(t) for t in _NUM.findall(g("points", ""))]
        nodes = [bz.node(v[i], v[i + 1]) for i in range(0, len(v) - 1, 2)]
        return [{"closed": tag == "polygon" and len(nodes) > 2, "nodes": nodes}] if len(nodes) > 1 else []
    return []


def _gradients(root) -> dict:
    """{id: (élément, arrêts)} des dégradés du document (arrêts hérités par `href`)."""
    found = {}
    for el in root.iter():
        tag = el.tag.split("}", 1)[-1] if isinstance(el.tag, str) else ""
        if tag in ("linearGradient", "radialGradient") and el.get("id"):
            stops = []
            for stop in el:
                if (stop.tag.split("}", 1)[-1] if isinstance(stop.tag, str) else "") != "stop":
                    continue
                st = _styles(stop, {})
                color = parse_color(st.get("stop-color", "#000000")) or "#000000"
                op = _length(st.get("stop-opacity"), 1.0)
                if op < 1.0:
                    color = f"#{max(0, min(255, round(op * 255))):02x}{color[1:]}"
                offset = st.get("offset", stop.get("offset", "0"))
                value = _length(offset, 0.0) / (100.0 if "%" in str(offset) else 1.0)
                stops.append([value, color])
            found[el.get("id")] = (tag, el, stops)
    for gid, (tag, el, stops) in list(found.items()):
        ref = (el.get("{http://www.w3.org/1999/xlink}href") or el.get("href") or "").lstrip("#")
        if not stops and ref in found:
            found[gid] = (tag, el, found[ref][2])
    return found


def _gradient_of(value, gradients: dict, box) -> dict | None:
    m = re.match(r"\s*url\(\s*#([^)\s]+)\s*\)", value or "")
    if not m or m.group(1) not in gradients or box is None:
        return None
    tag, el, stops = gradients[m.group(1)]
    x0, y0, x1, y1 = box
    w, h = max(x1 - x0, 1e-9), max(y1 - y0, 1e-9)
    user = el.get("gradientUnits") == "userSpaceOnUse"

    def fx(key, default):
        v = el.get(key)
        if v is None:
            return default
        n = _length(v, default) / (100.0 if "%" in v else 1.0)
        return (n - x0) / w if user else n

    def fy(key, default):
        v = el.get(key)
        if v is None:
            return default
        n = _length(v, default) / (100.0 if "%" in v else 1.0)
        return (n - y0) / h if user else n
    if tag == "linearGradient":
        raw = {"type": "linear", "stops": stops, "x1": fx("x1", 0.0), "y1": fy("y1", 0.0), "x2": fx("x2", 1.0),
               "y2": fy("y2", 0.0)}
    else:
        r = _length(el.get("r"), 0.5)
        if user:
            r = r / (math.hypot(w, h) / math.sqrt(2))
        raw = {"type": "radial", "stops": stops, "cx": fx("cx", 0.5), "cy": fy("cy", 0.5), "r": r}
    return paint.valid_gradient(raw)


def import_svg(text: str) -> list[dict]:
    """Valeurs d'éléments `ill_path` (coordonnées du SVG, origine 0) depuis un document SVG ; un `<g>` qui contient
    plusieurs objets devient un groupe."""
    root = ET.fromstring(text)
    out: list[dict] = []
    counter = [0]
    gradients = _gradients(root)

    def tag_of(el):
        return el.tag.split("}", 1)[-1] if isinstance(el.tag, str) else ""

    def walk(el, matrix, inherited, group, masked=False):
        tag = tag_of(el)
        if tag in ("defs", "clipPath", "mask", "symbol", "style", "title", "desc", "metadata", "pattern",
                   "linearGradient", "radialGradient", "marker"):
            return
        style = _styles(el, inherited)
        if style.get("display") == "none":
            return
        m = bz.multiply(parse_transform(el.get("transform", "")), matrix)
        ref = None if masked else _mask_ref(el)
        if ref is not None and ref[1] in masks:          # clip-path / mask : un groupe dont le masque est en haut
            counter[0] += 1
            gid = f"svg{counter[0]}"
            walk(el, matrix, inherited, gid, masked=True)
            entity = _mask_entity(masks[ref[1]], ref[0], m, gid, gradients)
            if entity is not None:
                out.append(entity)
            return
        if tag in ("svg", "g"):
            children = list(el)
            sub_group = group
            if tag == "g" and len(children) > 1:
                counter[0] += 1
                sub_group = group or f"svg{counter[0]}"
            passed = {k: v for k, v in style.items() if k != "opacity"}
            passed["opacity-parent"] = str(_length(style.get("opacity"), 1.0)
                                           * _length(style.get("opacity-parent"), 1.0))
            for child in children:
                walk(child, m, passed, sub_group)
            return
        if tag == "image":
            href = el.get("{http://www.w3.org/1999/xlink}href") or el.get("href") or ""
            w, h = _length(el.get("width")), _length(el.get("height"))
            if href and w > 0 and h > 0:
                matrix = bz.multiply(bz.translate(_length(el.get("x")), _length(el.get("y"))), m)
                entity = model.new_entity(model.IMAGE, w=w, h=h, matrix=list(matrix), group=group,
                                          opacity=_length(style.get("opacity"), 1.0)
                                          * _length(style.get("opacity-parent"), 1.0))
                entity.update({"type": model.IMAGE, "x": 0.0, "y": 0.0, "_href": href})
                out.append(entity)
            return
        if tag == "text":
            entity = _text_entity(el, style, m, group)
            if entity is not None:
                out.append(entity)
            return
        subs = _shape_subpaths(tag, el)
        if not subs:
            return
        box = bz.bounds(subs)
        fill_g = _gradient_of(style.get("fill"), gradients, box)
        stroke_g = _gradient_of(style.get("stroke"), gradients, box)
        bz.transform(subs, m)
        entity = _entity(subs, style, group, m, tag)
        if fill_g:
            entity.update(fill_gradient=fill_g, fill=fill_g["stops"][0][1])
        if stroke_g:
            entity.update(stroke_gradient=stroke_g, stroke=stroke_g["stops"][0][1])
        out.append(entity)

    masks = {el.get("id"): el for el in root.iter()
             if isinstance(el.tag, str) and el.tag.split("}", 1)[-1] in ("clipPath", "mask") and el.get("id")}
    walk(root, bz.IDENTITY, {}, "")
    return out


def _mask_ref(el) -> tuple[str, str] | None:
    """(« clip » / « opacity », id) d'un `clip-path` / `mask` qui vise un élément du document."""
    for attr, kind in (("clip-path", "clip"), ("mask", "opacity")):
        value = el.get(attr)
        if value is None:
            for part in (el.get("style") or "").split(";"):
                if ":" in part and part.split(":", 1)[0].strip() == attr:
                    value = part.split(":", 1)[1]
        m = re.match(r"\s*url\(\s*#([^)\s]+)\s*\)", value or "")
        if m:
            return kind, m.group(1)
    return None


def _mask_entity(el, kind: str, matrix, group: str, gradients) -> dict | None:
    """Objet masque depuis un `<clipPath>` / `<mask>` : ses formes réunies en un tracé (repère de l'élément qui
    l'utilise) ; écrêtage = sans peinture."""
    subs, style, tag = [], {}, "path"
    for child in el.iter():
        t = child.tag.split("}", 1)[-1] if isinstance(child.tag, str) else ""
        shape = _shape_subpaths(t, child)
        if not shape:
            continue
        if not subs:
            style, tag = _styles(child, {}), t
        bz.transform(shape, bz.multiply(parse_transform(child.get("transform", "")), matrix))
        subs += shape
    if not subs:
        return None
    entity = _entity(subs, style, group, matrix, tag)
    entity["mask"] = kind
    if kind == "clip":
        entity.update(fill="", stroke="", fill_gradient=None, stroke_gradient=None)
    return entity


def _text_entity(el, style, matrix, group) -> dict | None:
    """`<text>` -> texte de point : lignes = texte direct puis chaque `<tspan>` (un `<tspan>` avec y ou dy = nouvelle
    ligne) ; position = x, y du texte (ou du 1er `<tspan>`) ; rotation et échelle de la matrice gardées."""
    lines = [(el.text or "")]
    x, y = el.get("x"), el.get("y")
    for span in el:
        if (span.tag.split("}", 1)[-1] if isinstance(span.tag, str) else "") != "tspan":
            continue
        if x is None and span.get("x") is not None:
            x, y = span.get("x"), span.get("y")
        if (span.get("y") is not None or span.get("dy") is not None) and lines[-1].strip():
            lines.append(span.text or "")
        else:
            lines[-1] += span.text or ""
        lines[-1] += span.tail or ""
    text = "\n".join(line.strip("\n") for line in lines).strip("\n")
    if not text.strip():
        return None
    px, py = bz.apply(matrix, _length(x), _length(y))
    scale = math.sqrt(abs(matrix[0] * matrix[3] - matrix[1] * matrix[2])) or 1.0
    fill = parse_color(style.get("fill", "#000000"))
    family = (style.get("font-family") or "").split(",")[0].strip().strip("'\"")
    data = model.new_entity(model.TEXT, text=text, font_size=_length(style.get("font-size"), 16.0) * scale,
                            font_family=family, fill="#000000" if fill is None else fill,
                            bold=str(style.get("font-weight", "")) in ("bold", "700", "800", "900"),
                            italic=style.get("font-style") == "italic", group=group,
                            rotation=math.degrees(math.atan2(matrix[1], matrix[0])),
                            opacity=_length(style.get("opacity"), 1.0) * _length(style.get("opacity-parent"), 1.0))
    data.update({"type": model.TEXT, "x": px, "y": py})
    return model.normalize_entity(data)


def _entity(subs, style, group, matrix, tag) -> dict:
    fill = parse_color(style.get("fill", "#000000"))
    if fill is None:
        fill = "" if str(style.get("fill", "")).startswith("url(") else "#000000"
    if tag in ("line", "polyline") and "fill" not in style:
        fill = "" if tag == "line" else fill
    stroke = parse_color(style.get("stroke", "none"))
    stroke = "" if stroke is None else stroke
    scale = math.sqrt(abs(matrix[0] * matrix[3] - matrix[1] * matrix[2])) or 1.0
    fo = _length(style.get("fill-opacity"), 1.0)
    so = _length(style.get("stroke-opacity"), 1.0)
    if fill and fo < 1.0:
        fill = f"#{max(0, min(255, round(fo * 255))):02x}{fill[1:]}"
    if stroke and so < 1.0:
        stroke = f"#{max(0, min(255, round(so * 255))):02x}{stroke[1:]}"
    dash = [float(v) * scale for v in _NUM.findall(style.get("stroke-dasharray", "") or "")]
    data = model.new_entity(model.PATH, subpaths=subs, fill=fill, stroke=stroke,
                            stroke_width=_length(style.get("stroke-width"), 1.0) * scale,
                            opacity=_length(style.get("opacity"), 1.0) * _length(style.get("opacity-parent"), 1.0),
                            cap=style.get("stroke-linecap", "butt"), join=style.get("stroke-linejoin", "miter"),
                            miter=_length(style.get("stroke-miterlimit"), 4.0), dash=dash,
                            fill_rule=style.get("fill-rule", "nonzero"), group=group)
    data.update({"type": model.PATH, "x": 0.0, "y": 0.0})
    return model.normalize_entity(data)
