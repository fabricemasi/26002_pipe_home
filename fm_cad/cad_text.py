"""Textes du CAD : geometrie PURE (aucun Qt), en coordonnees du DOCUMENT (Y vers le haut, degres, sens
trigonometrique). Un texte (`cad_text`) est UNE entite : une ou plusieurs lignes, posees par un point d'insertion et
une justification (comme TEXT / MTEXT d'AutoCAD) ; le dessin des lettres est fait par l'element
(`cad_items.CadTextItem`).

Champs de l'entite (en plus des proprietes communes des entites CAD) :
- `pos`      : point d'insertion ;
- `rot`      : angle de la ligne de base (degres) ;
- `height`   : hauteur du texte = hauteur des CAPITALES (unites du board), comme AutoCAD ;
- `width`    : largeur du cadre d'un texte multiligne (0 = pas de retour a la ligne automatique) ;
- `text`     : le texte (« \\n » = nouveau paragraphe) ;
- `justify`  : point d'insertion dans le texte (codes d'AutoCAD) : L / C / R = sur la ligne de base de la 1re ligne,
               TL TC TR (haut), ML MC MR (milieu), BL BC BR (bas, sous les jambages) ;
- `spacing`  : interligne (1 = 5/3 de la hauteur, celui d'AutoCAD) ;
- `font`, `bold`, `italic` : police ;
- `mtext`    : texte multiligne (MTEXTE : Entree = nouveau paragraphe dans la meme entite ; export DXF en MTEXT).

La largeur des lignes est mesuree par `MEASURE(ligne, police, gras, italique)` = largeur pour une hauteur de capitales
de 1 ; l'interface la remplace par la vraie mesure de Qt (`cad_items`), une estimation sert sans elle."""
from __future__ import annotations

import math

JUSTIFY = ("L", "C", "R", "TL", "TC", "TR", "ML", "MC", "MR", "BL", "BC", "BR")
JUSTIFY_LABELS = {"L": "Gauche (ligne de base)", "C": "Centre (ligne de base)", "R": "Droite (ligne de base)",
                  "TL": "Haut gauche", "TC": "Haut centre", "TR": "Haut droite",
                  "ML": "Milieu gauche", "MC": "Milieu centre", "MR": "Milieu droite",
                  "BL": "Bas gauche", "BC": "Bas centre", "BR": "Bas droite"}
LINE_SPACING = 5.0 / 3.0            # interligne d'AutoCAD, en hauteurs de texte
DESCENT = 1.0 / 3.0                 # jambages sous la ligne de base, en hauteurs (remplace par la mesure de Qt)
DEFAULT_FONT = "Arial"
MM = 96.0 / 25.4

DEFAULTS = {"text": "", "height": 2.5 * MM, "rot": 0.0, "width": 0.0, "justify": "L", "spacing": 1.0,
            "font": DEFAULT_FONT, "bold": False, "italic": False, "mtext": False}
GEOMETRY_KEYS = ("pos", "rot", "height", "width")


def _estimate(text: str, font: str = "", bold: bool = False, italic: bool = False) -> float:
    return 0.75 * len(text) * (1.08 if bold else 1.0)


MEASURE = _estimate                 # largeur d'une ligne pour une hauteur de capitales de 1 (voir l'entete)


def _num(value, default=0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if math.isfinite(out) else default


def _pt(value, default=(0.0, 0.0)):
    try:
        return (float(value[0]), float(value[1]))
    except (TypeError, ValueError, IndexError, KeyError):
        return default


def style_of(data: dict) -> dict:
    out = dict(DEFAULTS)
    out["text"] = str(data.get("text") or "").replace("\r\n", "\n").replace("\r", "\n")
    out["height"] = max(1e-6, _num(data.get("height"), DEFAULTS["height"]))
    out["rot"] = _num(data.get("rot"), 0.0) % 360.0
    out["width"] = max(0.0, _num(data.get("width"), 0.0))
    out["justify"] = data.get("justify") if data.get("justify") in JUSTIFY else "L"
    out["spacing"] = max(0.1, _num(data.get("spacing"), 1.0))
    out["font"] = str(data.get("font") or DEFAULT_FONT)
    out["bold"] = bool(data.get("bold", False))
    out["italic"] = bool(data.get("italic", False))
    out["mtext"] = bool(data.get("mtext", False))
    return out


def _measure(line: str, s: dict) -> float:
    try:
        return max(0.0, float(MEASURE(line, s["font"], s["bold"], s["italic"])))
    except Exception:                                   # noqa: BLE001 - mesure indisponible : estimation
        return _estimate(line, s["font"], s["bold"], s["italic"])


def wrap(paragraph: str, width: float, s: dict) -> list:
    """Paragraphe coupe aux espaces pour tenir dans `width` (hauteurs de texte ; 0 = jamais coupe). Un mot plus long
    que la largeur reste entier sur sa ligne (comme AutoCAD)."""
    if width <= 0 or _measure(paragraph, s) <= width:
        return [paragraph]
    lines, current = [], ""
    for word in paragraph.split(" "):
        candidate = word if not current else current + " " + word
        if current and _measure(candidate, s) > width:
            lines.append(current)
            current = word
        else:
            current = candidate
    lines.append(current)
    return lines


def layout(data: dict, offset=(0.0, 0.0)) -> dict:
    """Lignes [(texte, x, y de la ligne de base)] dans le repere LOCAL du texte (origine = point d'insertion, x le long
    de la ligne de base, unites du board), cadre local (x0, y0, x1, y1), ses 4 coins dans le document, hauteur, angle."""
    s = style_of(data)
    h = s["height"]
    lines = []
    for paragraph in s["text"].split("\n"):
        lines += wrap(paragraph, s["width"] / h if s["width"] > 0 else 0.0, s)
    widths = [_measure(line, s) * h for line in lines]
    step = s["spacing"] * LINE_SPACING * h
    top, bottom = h, -(len(lines) - 1) * step - DESCENT * h
    code = s["justify"]
    vertical, horizontal = (code[0], code[1]) if len(code) == 2 else ("", code)
    dy = {"T": -top, "M": -(top + bottom) / 2.0, "B": -bottom}.get(vertical, 0.0)
    if s["width"] > 0:
        span = s["width"]
    else:
        span = max(widths) if widths else 0.0
    box_x0 = {"L": 0.0, "C": -span / 2.0, "R": -span}[horizontal]
    placed = []
    for i, (line, w) in enumerate(zip(lines, widths)):
        x = {"L": 0.0, "C": -w / 2.0, "R": -w}[horizontal]
        placed.append((line, x, -i * step + dy))
    minimum = 0.5 * h                                   # texte vide : un cadre quand meme (choix, apercu)
    x0, x1 = box_x0, box_x0 + max(span, minimum)
    if span < minimum and horizontal != "L":
        x0, x1 = -minimum / 2.0 if horizontal == "C" else -minimum, minimum / 2.0 if horizontal == "C" else 0.0
    box = (x0, bottom + dy, x1, top + dy)
    pos = _pt(data.get("pos"))
    origin = (pos[0] + offset[0], pos[1] + offset[1])
    corners = [to_doc(origin, s["rot"], (x, y)) for x, y in ((box[0], box[1]), (box[2], box[1]),
                                                             (box[2], box[3]), (box[0], box[3]))]
    return {"lines": placed, "box": box, "corners": corners, "height": h, "rot": s["rot"], "origin": origin,
            "style": s}


def to_doc(origin, rot: float, local):
    c, s = math.cos(math.radians(rot)), math.sin(math.radians(rot))
    return (origin[0] + local[0] * c - local[1] * s, origin[1] + local[0] * s + local[1] * c)


def to_local(origin, rot: float, point):
    c, s = math.cos(math.radians(rot)), math.sin(math.radians(rot))
    x, y = point[0] - origin[0], point[1] - origin[1]
    return (x * c + y * s, -x * s + y * c)


def box_segments(corners) -> list:
    return [(corners[i], corners[(i + 1) % 4]) for i in range(4)]


def distance(found: dict, point) -> float:
    """Distance de `point` au cadre du texte (0 dedans)."""
    x, y = to_local(found["origin"], found["rot"], point)
    x0, y0, x1, y1 = found["box"]
    dx = max(x0 - x, 0.0, x - x1)
    dy = max(y0 - y, 0.0, y - y1)
    return math.hypot(dx, dy)


def bounds(found: dict) -> tuple:
    xs = [p[0] for p in found["corners"]]
    ys = [p[1] for p in found["corners"]]
    return (min(xs), min(ys), max(xs), max(ys))


def next_line(data: dict) -> tuple:
    """Point d'insertion de la ligne suivante d'un texte une ligne (TEXTE : Entree = ligne suivante, dessous)."""
    s = style_of(data)
    p = _pt(data.get("pos"))
    step = s["spacing"] * LINE_SPACING * s["height"]
    return to_doc(p, s["rot"], (0.0, -step))


def readable(angle: float) -> float:
    """Angle ramene dans ]-90, 90] (un texte miroir reste lisible, comme MIRRTEXT = 0 d'AutoCAD)."""
    angle = (angle + 180.0) % 360.0 - 180.0
    if angle > 90.0:
        angle -= 180.0
    elif angle <= -90.0:
        angle += 180.0
    return angle % 360.0


def translate(data: dict, delta) -> dict:
    p = _pt(data.get("pos"))
    return {"pos": [p[0] + delta[0], p[1] + delta[1]]}


def transform(data: dict, fn, rot_fn, flips: bool = False) -> dict:
    p = fn(_pt(data.get("pos")))
    rot = rot_fn(_num(data.get("rot"), 0.0))
    return {"pos": [p[0], p[1]], "rot": readable(rot) if flips else rot % 360.0}


def scale(data: dict, factor: float) -> dict:
    return {"height": max(1e-6, _num(data.get("height"), DEFAULTS["height"]) * factor),
            "width": max(0.0, _num(data.get("width"), 0.0) * factor)}


def from_dim(found: dict) -> dict:
    """Texte d'une cotation decomposee (`cad_dims.geometry`) : meme place, angle et hauteur."""
    return {"text": found["text"], "pos": list(found["text_pos"]), "rot": found["text_angle"] % 360.0,
            "height": found["text_height"], "justify": "C", "font": "Segoe UI"}
