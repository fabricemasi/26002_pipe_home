"""Dégradés et nuancier (SANS Qt) : modèle d'un dégradé, géométrie dans la boîte de l'objet, SVG.

Un dégradé (`fill_gradient` / `stroke_gradient` d'un tracé ; None = couleur unie de `fill` / `stroke`) :
{"type": "linear" | "radial", "stops": [[position 0-1, "#rrggbb" ou "#aarrggbb"], …],
 linéaire : "x1", "y1", "x2", "y2" ; radial : "cx", "cy", "r"} — positions en FRACTIONS de la boîte de l'objet
(comme `objectBoundingBox` de SVG) : le dégradé suit l'objet quand il bouge ou change de taille. L'outil Dégradé (G)
pose ces points ; une rotation de l'objet ne tourne pas le dégradé (limite connue)."""
from __future__ import annotations

import copy
import math

from .model import valid_color

LINEAR = {"type": "linear", "stops": [[0.0, "#ffffff"], [1.0, "#000000"]], "x1": 0.0, "y1": 0.5, "x2": 1.0, "y2": 0.5}
RADIAL = {"type": "radial", "stops": [[0.0, "#ffffff"], [1.0, "#000000"]], "cx": 0.5, "cy": 0.5, "r": 0.5}

# Nuancier par défaut (couleurs de base d'un document RVB : gris, primaires, tons courants ; choix du module).
SWATCHES = ["#ffffff", "#000000", "#e6e6e6", "#b3b3b3", "#808080", "#4d4d4d", "#ff0000", "#ffff00", "#00ff00",
            "#00ffff", "#0000ff", "#ff00ff", "#ed1c24", "#f7931e", "#fcee21", "#8cc63f", "#39b54a", "#22b573",
            "#29abe2", "#0071bc", "#2e3192", "#662d91", "#93278f", "#d4145a", "#c69c6d", "#8c6239", "#603813",
            "#42210b", "#f2a28c", "#fbb03b"]


def _num(value, default: float) -> float:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and value == value \
        else default


def valid_gradient(raw) -> dict | None:
    """Dégradé lu (fichier, collage) : réparé ; None si absent ou inutilisable."""
    if not isinstance(raw, dict) or raw.get("type") not in ("linear", "radial"):
        return None
    base = LINEAR if raw["type"] == "linear" else RADIAL
    out = copy.deepcopy(base)
    for key in base:
        if key not in ("type", "stops"):
            out[key] = _num(raw.get(key), base[key])
    stops = []
    for stop in raw.get("stops") or []:
        if isinstance(stop, (list, tuple)) and len(stop) >= 2:
            color = valid_color(stop[1], "")
            if color:
                stops.append([min(1.0, max(0.0, _num(stop[0], 0.0))), color])
    if len(stops) < 2:
        return None
    stops.sort(key=lambda s: s[0])
    out["stops"] = stops
    if out["type"] == "radial":
        out["r"] = max(1e-4, out["r"])
    return out


def new_gradient(kind: str, first: str = "#ffffff", last: str = "#000000") -> dict:
    g = copy.deepcopy(LINEAR if kind == "linear" else RADIAL)
    g["stops"] = [[0.0, first or "#ffffff"], [1.0, last or "#000000"]]
    return g


def absolute(g: dict, box) -> dict:
    """Points du dégradé dans le repère de l'objet (`box` = x0, y0, x1, y1 de sa géométrie)."""
    x0, y0, x1, y1 = box
    w, h = max(x1 - x0, 1e-9), max(y1 - y0, 1e-9)
    if g["type"] == "linear":
        return {"x1": x0 + g["x1"] * w, "y1": y0 + g["y1"] * h, "x2": x0 + g["x2"] * w, "y2": y0 + g["y2"] * h}
    return {"cx": x0 + g["cx"] * w, "cy": y0 + g["cy"] * h, "r": g["r"] * math.hypot(w, h) / math.sqrt(2)}


def set_from_drag(g: dict, box, start, end) -> dict:
    """Outil Dégradé : glisser de `start` à `end` (repère de l'objet) pose la direction (linéaire) ou le centre et
    le rayon (radial)."""
    x0, y0, x1, y1 = box
    w, h = max(x1 - x0, 1e-9), max(y1 - y0, 1e-9)
    out = copy.deepcopy(g)
    fx = lambda x: (x - x0) / w  # noqa: E731
    fy = lambda y: (y - y0) / h  # noqa: E731
    if g["type"] == "linear":
        out.update(x1=fx(start[0]), y1=fy(start[1]), x2=fx(end[0]), y2=fy(end[1]))
    else:
        out.update(cx=fx(start[0]), cy=fy(start[1]),
                   r=max(1e-4, math.dist(start, end) / (math.hypot(w, h) / math.sqrt(2))))
    return out


def stop_attrs(color: str) -> tuple[str, float]:
    if len(color) == 9:
        return "#" + color[3:], int(color[1:3], 16) / 255.0
    return color, 1.0


def svg_gradient(g: dict, box, gid: str, dx: float = 0.0, dy: float = 0.0) -> str:
    """Élément `<linearGradient>` / `<radialGradient>` (userSpaceOnUse : coordonnées du SVG, décalées de dx, dy)."""
    a = absolute(g, box)
    num = lambda v: (f"{v:.3f}".rstrip("0").rstrip(".") or "0")  # noqa: E731
    if g["type"] == "linear":
        head = (f'<linearGradient id="{gid}" gradientUnits="userSpaceOnUse" x1="{num(a["x1"] + dx)}" '
                f'y1="{num(a["y1"] + dy)}" x2="{num(a["x2"] + dx)}" y2="{num(a["y2"] + dy)}">')
        tail = "</linearGradient>"
    else:
        head = (f'<radialGradient id="{gid}" gradientUnits="userSpaceOnUse" cx="{num(a["cx"] + dx)}" '
                f'cy="{num(a["cy"] + dy)}" r="{num(a["r"])}">')
        tail = "</radialGradient>"
    stops = []
    for offset, color in g["stops"]:
        c, op = stop_attrs(color)
        extra = f' stop-opacity="{num(op)}"' if op < 1 else ""
        stops.append(f'<stop offset="{num(offset)}" stop-color="{c}"{extra}/>')
    return head + "".join(stops) + tail


def interpolate(g: dict, t: float) -> str:
    """Couleur du dégradé à la position t (aperçu des pastilles)."""
    stops = g["stops"]
    if t <= stops[0][0]:
        return stops[0][1]
    for (p0, c0), (p1, c1) in zip(stops, stops[1:]):
        if t <= p1:
            k = 0 if p1 == p0 else (t - p0) / (p1 - p0)
            a, b = _rgba(c0), _rgba(c1)
            mix = [round(a[i] + (b[i] - a[i]) * k) for i in range(4)]
            return "#" + (f"{mix[3]:02x}" if mix[3] < 255 else "") + "".join(f"{v:02x}" for v in mix[:3])
    return stops[-1][1]


def _rgba(color: str) -> tuple[int, int, int, int]:
    if len(color) == 9:
        return int(color[3:5], 16), int(color[5:7], 16), int(color[7:9], 16), int(color[1:3], 16)
    return int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16), 255
