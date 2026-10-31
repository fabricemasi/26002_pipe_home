"""Aspect et effets (SANS Qt) : effets non destructifs d'un objet (`effects`), contours supplémentaires
(`extra_strokes`), géométrie des effets vectoriels, marges, filtres SVG.

Un effet = {"type", "on", …paramètres} ; un seul effet de chaque type par objet, appliqués dans l'ordre fixe
`ORDER` (géométrie d'abord, comme le menu Effet > Distorsion d'Illustrator, puis les effets tramés) :
- vectoriels (`VECTOR`) : « offset » (décalage du tracé, `distance` > 0 = vers l'extérieur), « round » (arrondis des
  angles entre segments droits, `radius`) — calculés ici, sur les nœuds ;
- tramés (`RASTER`) : « blur » (flou gaussien, `radius`), « feather » (contour progressif, `radius`), « shadow »
  (ombre portée : `dx`, `dy`, `blur`, `color`, `opacity`), « glow » (lueur externe : `blur`, `color`, `opacity`) —
  peints par `effects.py` dans l'image gardée de l'élément.
Valeurs par défaut d'Illustrator pour l'ombre portée (opacité 75 %, X 7 pt, Y 7 pt, flou 5 pt) : connaissance
générale, NON vérifiée cette session ; les autres : choix du module.
Contours supplémentaires (panneau Aspect : plusieurs contours sur un objet) : [{"color", "width", "opacity"}], peints
SOUS le contour principal, le premier le plus bas."""
from __future__ import annotations

import copy

from . import bezier as bz
from .model import PT, valid_color

ORDER = ("offset", "round", "blur", "feather", "shadow", "glow")
VECTOR = ("offset", "round")
RASTER = ("blur", "feather", "shadow", "glow")
LABELS = {"offset": "Décalage du tracé", "round": "Arrondis", "blur": "Flou gaussien",
          "feather": "Contour progressif", "shadow": "Ombre portée", "glow": "Lueur externe"}
DEFAULTS = {
    "offset": {"distance": 10.0},
    "round": {"radius": 10.0},
    "blur": {"radius": 5.0},
    "feather": {"radius": 10.0},
    "shadow": {"dx": round(7 * PT, 3), "dy": round(7 * PT, 3), "blur": round(5 * PT, 3), "color": "#000000",
               "opacity": 0.75},
    "glow": {"blur": round(7 * PT, 3), "color": "#ffcc00", "opacity": 0.75},
}
# Curseurs du menu Effets : (clé, libellé, minimum, maximum, unité affichée).
PARAMS = {
    "offset": [("distance", "Décalage", -100, 100, "px")],
    "round": [("radius", "Rayon", 0, 200, "px")],
    "blur": [("radius", "Rayon", 0, 100, "px")],
    "feather": [("radius", "Rayon", 0, 100, "px")],
    "shadow": [("dx", "Décalage X", -100, 100, "px"), ("dy", "Décalage Y", -100, 100, "px"),
               ("blur", "Flou", 0, 100, "px"), ("opacity", "Opacité", 0, 100, "%")],
    "glow": [("blur", "Flou", 0, 100, "px"), ("opacity", "Opacité", 0, 100, "%")],
}
STROKE_DEFAULT = {"color": "#000000", "width": 6.0, "opacity": 1.0}
MAX_STROKES = 4


def _num(value, default: float) -> float:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and value == value \
        else default


def valid_effects(raw) -> list:
    """Effets lus : un par type, ordre `ORDER`, valeurs bornées ; types inconnus écartés."""
    found = {}
    for effect in raw if isinstance(raw, list) else []:
        if not isinstance(effect, dict) or effect.get("type") not in DEFAULTS or effect["type"] in found:
            continue
        kind = effect["type"]
        out = {"type": kind, "on": effect.get("on", True) is not False}
        for key, default in DEFAULTS[kind].items():
            if key == "color":
                out[key] = valid_color(effect.get(key), default) or default
            else:
                out[key] = _num(effect.get(key), default)
        for key, _label, low, high, unit in PARAMS[kind]:
            value = out[key] * (100 if unit == "%" else 1)
            value = min(float(high) * (1 if unit != "px" else 10), max(float(low) * (1 if unit != "px" else 10),
                                                                      value))
            out[key] = value / (100 if unit == "%" else 1)
        found[kind] = out
    return [found[k] for k in ORDER if k in found]


def valid_strokes(raw) -> list:
    out = []
    for stroke in raw if isinstance(raw, list) else []:
        if isinstance(stroke, dict) and len(out) < MAX_STROKES:
            out.append({"color": valid_color(stroke.get("color"), "#000000") or "#000000",
                        "width": min(1000.0, max(0.0, _num(stroke.get("width"), 6.0))),
                        "opacity": min(1.0, max(0.0, _num(stroke.get("opacity"), 1.0)))})
    return out


def new_effect(kind: str) -> dict:
    return {"type": kind, "on": True, **copy.deepcopy(DEFAULTS[kind])}


def active(data: dict, kinds=ORDER) -> list:
    return [e for e in data.get("effects") or [] if e.get("on", True) and e.get("type") in kinds]


def has_raster(data: dict) -> bool:
    return bool(active(data, RASTER))


def effect(data: dict, kind: str) -> dict | None:
    for e in data.get("effects") or []:
        if e.get("type") == kind:
            return e
    return None


# ---------------------------------------------------------------- géométrie
def render_subpaths(data: dict) -> list:
    """Géométrie DESSINÉE (effets vectoriels appliqués) ; la géométrie de l'objet reste `subpaths`."""
    subs = data.get("subpaths") or []
    vector = active(data, VECTOR)
    if not vector or not subs:
        return subs
    out = bz.copy_subpaths(subs)
    for e in vector:
        if e["type"] == "round" and e["radius"] > 0:
            out = bz.round_corners(out, e["radius"])
        elif e["type"] == "offset" and abs(e["distance"]) > 1e-6:
            from .pathfinder import offset_subpaths
            out = offset_subpaths(out, e["distance"], data.get("fill_rule", "nonzero"))
    return out


def margin(data: dict) -> float:
    """Débord de la peinture au-delà de la géométrie dessinée (effets tramés, contours supplémentaires)."""
    m = 0.0
    for e in active(data, RASTER):
        if e["type"] == "shadow":
            m = max(m, max(abs(e["dx"]), abs(e["dy"])) + 2.5 * e["blur"])
        elif e["type"] == "glow":
            m = max(m, 2.5 * e["blur"])
        elif e["type"] == "blur":
            m = max(m, 2.5 * e["radius"])
    for stroke in data.get("extra_strokes") or []:
        m = max(m, stroke["width"] / 2)
    return m


# ---------------------------------------------------------------- SVG
def _rgb(color: str) -> tuple[str, float]:
    if len(color) == 9:
        return "#" + color[3:], int(color[1:3], 16) / 255.0
    return color, 1.0


def svg_filter(data: dict, fid: str) -> str:
    """`<filter>` des effets tramés actifs (vide s'il n'y en a pas) ; flou SVG = écart type ≈ rayon / 2."""
    effects = active(data, RASTER)
    if not effects:
        return ""
    num = bz._num
    parts, under = [], []
    source = "SourceGraphic"
    for e in effects:
        if e["type"] == "blur":
            parts.append(f'<feGaussianBlur in="{source}" stdDeviation="{num(e["radius"] / 2)}" result="flou"/>')
            source = "flou"
        elif e["type"] == "feather":
            parts.append(f'<feGaussianBlur in="SourceAlpha" stdDeviation="{num(e["radius"] / 2)}" result="bords"/>'
                         f'<feComposite in="{source}" in2="bords" operator="in" result="progressif"/>')
            source = "progressif"
    for n, e in enumerate(e for e in effects if e["type"] in ("shadow", "glow")):
        color, op = _rgb(e["color"])
        dx, dy = (e["dx"], e["dy"]) if e["type"] == "shadow" else (0.0, 0.0)
        name = f"dessous{n}"
        parts.append(f'<feGaussianBlur in="SourceAlpha" stdDeviation="{num(e["blur"] / 2)}" result="{name}a"/>'
                     f'<feOffset in="{name}a" dx="{num(dx)}" dy="{num(dy)}" result="{name}b"/>'
                     f'<feFlood flood-color="{color}" flood-opacity="{num(op * e["opacity"])}" result="{name}c"/>'
                     f'<feComposite in="{name}c" in2="{name}b" operator="in" result="{name}"/>')
        under.append(name)
    merge = "".join(f'<feMergeNode in="{n}"/>' for n in under) + f'<feMergeNode in="{source}"/>'
    return (f'<filter id="{fid}" x="-50%" y="-50%" width="200%" height="200%" color-interpolation-filters="sRGB">'
            f'{"".join(parts)}<feMerge>{merge}</feMerge></filter>')
