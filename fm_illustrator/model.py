"""Données du module Illustrator (SANS Qt) : types d'éléments du `.mro`, valeurs par défaut, formats des plans de
travail, normalisation. Lu par `fm_board.model` (comme `fm_design.design_model`) : les types sont connus dès la
lecture d'un fichier.

Un document Illustrator = les éléments `ill_*` du board :
- `ill_artboard` : plan de travail (zone d'export ; les objets n'en sont PAS enfants, comme dans Illustrator) ;
- `ill_layer` : calque (nom, ordre `index`, couleur, masqué, contenu verrouillé ; voir `layers.py`) ;
- `ill_path` : tracé vectoriel. `subpaths` = liste de sous-tracés {"closed", "nodes"} ; un nœud =
  [ax, ay, ix, iy, ox, oy, lisse] : point d'ancrage, poignée d'ENTRÉE, poignée de SORTIE (coordonnées ABSOLUES
  dans le repère de l'élément, dont l'origine est (x, y) ; poignée = ancrage -> pas de poignée), lisse = 1 si les
  deux poignées restent alignées. Les transformations (échelle, rotation…) sont appliquées aux nœuds (comme
  Illustrator) : `rotation` reste 0 ; un déplacement ne change que (x, y).
`group` = identifiant de groupe (vide = seul) : un clic de l'outil Sélection choisit tout le groupe ; `layer` =
identifiant du calque (vide = le plus bas) ; `fill_gradient` / `stroke_gradient` = dégradé (`paint.py`) ou None ;
`effects` / `extra_strokes` = aspect (effets non destructifs, contours supplémentaires : `appearance.py`) ;
`mask` = « clip » / « opacity » : cet objet est le MASQUE de son groupe (écrêtage : sa forme découpe les autres
objets du groupe, lui-même sans peinture ; opacité : sa luminance règle leur opacité, `mask_invert` = inversée).
- `ill_text` : texte (`text.py`), mêmes attributs de peinture qu'un tracé. `mode` : « point » (origine (x, y) = ligne
  de base du 1er trait, comme Illustrator et SVG), « area » (texte captif : cadre `w` × `h`, origine = son coin haut
  gauche, retour à la ligne automatique), « path » (texte curviligne : `subpaths` = tracé de base, `path_offset` =
  départ en fraction de sa longueur). `font_size` en unités du board (affichée en pt), `leading` = interligne en
  multiple de la taille, `tracking` = approche en millièmes de cadratin, `rotation` en degrés (point et captif).
Un champ inconnu reste dans l'élément (règle du `.mro`)."""
from __future__ import annotations

import copy

ARTBOARD = "ill_artboard"
LAYER = "ill_layer"
PATH = "ill_path"
TEXT = "ill_text"
OBJECT_TYPES = (PATH, TEXT)
ILL_TYPES = (ARTBOARD, LAYER) + OBJECT_TYPES

ACCENT = "#2f7cf6"                     # couleur de sélection du module (bleu d'Illustrator, calque 1)
DEFAULT_FILL = "#ffffff"               # couleurs par défaut d'Illustrator (D) : fond blanc, contour noir 1 pt
DEFAULT_STROKE = "#000000"
PT = 96.0 / 72.0                       # 1 pt = 1,333 unité du board (1 unité = 1 px CSS = 1/96 de pouce)
MM = 96.0 / 25.4

CAPS = ("butt", "round", "square")
TEXT_MODES = ("point", "area", "path")
MASKS = ("", "clip", "opacity")             # objet MASQUE de son groupe : écrêtage / opacité (luminance)
TEXT_ALIGNS = ("left", "center", "right", "justify")
JOINS = ("miter", "round", "bevel")
FILL_RULES = ("nonzero", "evenodd")

# Formats des plans de travail (unités du board) : nom, largeur, hauteur.
ARTBOARD_FORMATS = [
    ("A4", 210 * MM, 297 * MM), ("A3", 297 * MM, 420 * MM), ("A5", 148 * MM, 210 * MM),
    ("Lettre", 8.5 * 96, 11 * 96), ("Tabloïd", 11 * 96, 17 * 96),
    ("Web 1920 × 1080", 1920.0, 1080.0), ("Web 1280 × 800", 1280.0, 800.0), ("Mobile 390 × 844", 390.0, 844.0),
    ("Carré 1080", 1080.0, 1080.0), ("Icône 512", 512.0, 512.0),
]

DEFAULTS = {
    ARTBOARD: {"w": 210 * MM, "h": 297 * MM, "name": "Plan de travail 1", "index": 0, "fill": "#ffffff"},
    LAYER: {"name": "Calque 1", "index": 0.0, "color": ACCENT, "hidden": False, "content_locked": False},
    TEXT: {"text": "", "mode": "point", "font_family": "", "font_size": 16.0, "bold": False, "italic": False,
           "align": "left", "leading": 1.2, "tracking": 0.0, "w": 200.0, "h": 100.0, "path_offset": 0.0,
           "subpaths": [], "fill": "#000000", "stroke": "", "stroke_width": 1.0, "opacity": 1.0,
           "cap": "butt", "join": "miter", "miter": 10.0, "dash": [], "fill_rule": "nonzero",
           "group": "", "name": "", "hidden": False, "layer": "", "fill_gradient": None, "stroke_gradient": None,
           "mask": "", "mask_invert": False, "effects": [], "extra_strokes": []},
    PATH: {"subpaths": [], "fill": DEFAULT_FILL, "stroke": DEFAULT_STROKE, "stroke_width": 1.0, "opacity": 1.0,
           "cap": "butt", "join": "miter", "miter": 10.0, "dash": [], "fill_rule": "nonzero",
           "group": "", "name": "", "hidden": False, "layer": "", "fill_gradient": None, "stroke_gradient": None,
           "mask": "", "mask_invert": False, "effects": [], "extra_strokes": []},
}


def _coerce(value, default):
    if isinstance(default, bool):
        return value if isinstance(value, bool) else default
    if isinstance(default, float):
        return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else default
    if isinstance(default, int):
        return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else default
    return value if type(value) is type(default) else copy.deepcopy(default)


def valid_color(value, default: str = "") -> str:
    """« #rrggbb » ou « #aarrggbb » ; vide = aucun (pas de fond / de contour)."""
    if value == "":
        return ""
    if isinstance(value, str) and value.startswith("#") and len(value) in (7, 9):
        try:
            int(value[1:], 16)
            return value.lower()
        except ValueError:
            pass
    return default


def valid_node(raw) -> list | None:
    try:
        values = [float(v) for v in raw[:6]]
    except (TypeError, ValueError, IndexError):
        return None
    if len(values) != 6 or any(v != v or abs(v) > 1e9 for v in values):      # NaN, valeurs absurdes
        return None
    smooth = 1 if len(raw) > 6 and raw[6] else 0
    return values + [smooth]


def valid_subpaths(raw) -> list:
    out = []
    for sub in raw if isinstance(raw, list) else []:
        if not isinstance(sub, dict):
            continue
        nodes = [n for n in (valid_node(x) for x in sub.get("nodes") or []) if n is not None]
        if nodes:
            out.append({"closed": bool(sub.get("closed")) and len(nodes) > 1, "nodes": nodes})
    return out


def normalize_entity(item: dict) -> dict:
    """Élément Illustrator lu (déjà complété par `fm_board.model.normalize_item`) : valeurs bornées, structures
    réparées. Les champs inconnus restent."""
    kind = item.get("type")
    defaults = DEFAULTS.get(kind)
    if defaults is None:
        return item
    for key, default in defaults.items():
        if default is not None:                         # dégradés (None par défaut) : vérifiés plus bas
            item[key] = _coerce(item.get(key, default), default)
    if kind == LAYER:
        item["color"] = valid_color(item["color"], ACCENT) or ACCENT
        return item
    if kind == ARTBOARD:
        item["w"] = max(1.0, item["w"])
        item["h"] = max(1.0, item["h"])
        item["fill"] = valid_color(item["fill"], "#ffffff")
        return item
    if kind == TEXT:
        item["mode"] = item["mode"] if item["mode"] in TEXT_MODES else "point"
        item["align"] = item["align"] if item["align"] in TEXT_ALIGNS else "left"
        item["font_size"] = min(5000.0, max(0.5, item["font_size"]))
        item["leading"] = min(10.0, max(0.3, item["leading"]))
        item["tracking"] = min(5000.0, max(-1000.0, item["tracking"]))
        item["w"] = max(1.0, item["w"])
        item["h"] = max(1.0, item["h"])
        item["path_offset"] = min(1.0, max(0.0, item["path_offset"]))
    if item["mask"] not in MASKS or not item.get("group"):
        item["mask"] = ""
    from .appearance import valid_effects, valid_strokes
    item["effects"] = valid_effects(item["effects"])
    item["extra_strokes"] = valid_strokes(item["extra_strokes"])
    item["subpaths"] = valid_subpaths(item["subpaths"])
    item["fill"] = valid_color(item["fill"], DEFAULT_FILL)
    item["stroke"] = valid_color(item["stroke"], DEFAULT_STROKE)
    item["stroke_width"] = min(1000.0, max(0.0, item["stroke_width"]))
    item["opacity"] = min(1.0, max(0.0, item["opacity"]))
    item["miter"] = min(500.0, max(1.0, item["miter"]))
    for key, allowed in (("cap", CAPS), ("join", JOINS), ("fill_rule", FILL_RULES)):
        if item[key] not in allowed:
            item[key] = allowed[0]
    item["dash"] = [max(0.0, float(v)) for v in item["dash"]
                    if isinstance(v, (int, float)) and not isinstance(v, bool)][:6]
    from .paint import valid_gradient
    item["fill_gradient"] = valid_gradient(item.get("fill_gradient"))
    item["stroke_gradient"] = valid_gradient(item.get("stroke_gradient"))
    return item


def new_entity(kind: str, **values) -> dict:
    """Valeurs d'un élément neuf (sans identifiant : `fm_board.model.new_item` le pose)."""
    data = copy.deepcopy(DEFAULTS[kind])
    data.update(values)
    return data


def style_of(data: dict) -> dict:
    """Attributs de peinture d'un tracé (pipette, styles par défaut des nouveaux objets)."""
    return {k: copy.deepcopy(data[k]) for k in ("fill", "stroke", "stroke_width", "opacity", "cap", "join", "miter",
                                                "dash", "fill_rule", "fill_gradient", "stroke_gradient", "effects",
                                                "extra_strokes")
            if k in data}


DEFAULT_STYLE = style_of(DEFAULTS[PATH])
