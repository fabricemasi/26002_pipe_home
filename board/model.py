"""Schema d'un board (fichier `.mro`, JSON) :

    {"format": "pipeline-board", "version": 2,
     "page": {"background": null, "grid": true, "export_background": "page", "export_grid": false},
     "view": {"zoom": 1.0, "center": [x, y]},
     "items": [{"id": "...", "type": "sticky", "x": 0, "y": 0, "w": 200, "h": 200, "z": 0, ...}, ...]}

Chaque type d'element a ses champs (voir `DEFAULTS`) ; un champ absent prend sa valeur par defaut. RIEN n'est
perdu d'un fichier plus recent : champs inconnus gardes dans l'element, elements de type inconnu gardes a part
(`foreign`, reecrits tels quels), cles inconnues du fichier gardees (`normalize` / `BoardScene.to_data`).

Couleurs par defaut du CANVAS = celles de Miro, MESUREES sur les captures fournies par l'utilisateur (octobre
2026) : fond #f2f2f2, traits #1a1a1a, selection #3663f7 (anneau de l'outil de dessin choisi), post-it jaune
#fde784 (milieu du degrade). Les autres couleurs des palettes sont celles de Miro connues par son API (noms des
couleurs de post-it), pas des mesures."""
from __future__ import annotations

import copy
import uuid

from . import cad_model

FORMAT = "pipeline-board"
VERSION = 2
EXTENSION = ".mro"

MIRO_BACKGROUND = "#f2f2f2"          # mesure (capture 1 : 142 868 pixels sur 159 185)
MIRO_INK = "#1a1a1a"                 # mesure (trait de la capture 3, contour de la forme de la capture 4)
MIRO_ACCENT = "#3663f7"              # mesure (anneau du preset choisi, capture 3)
MIRO_STICKY = "#fde784"              # mesure (post-it de la capture 2, milieu du degrade)

STICKY_COLORS = [MIRO_STICKY, "#fff9b1", "#f5d128", "#ff9d48", "#d5f692", "#c9df56", "#93d275", "#67c6c0",
                 "#ffcee0", "#ea94bb", "#c6a2d2", "#f0939d", "#a6ccf5", "#6cd8fa", "#9ea9ff", "#e6e6e6"]
COLORS = ["#1a1a1a", "#ffffff", "#808080", "#e6e6e6", "#f24726", "#ee7168", "#ff9d48", "#fac710", "#fef445",
          "#cee741", "#8fd14f", "#62c167", "#12cdd4", "#2d9bf0", "#3663f7", "#9510ac", "#da0063", "#652cb3"]

# Formes (noms internes ; equivalents Miro dans miro_io). « round » = rectangle arrondi des anciens fichiers.
SHAPE_KINDS = ("rect", "round", "ellipse", "triangle", "diamond", "parallelogram", "trapezoid", "pentagon",
               "hexagon", "octagon", "star", "cross", "right_arrow", "left_arrow", "left_right_arrow", "callout",
               "cloud", "can", "predefined_process", "left_brace", "right_brace")
SHAPE_LABELS = {"rect": "Rectangle", "round": "Rectangle arrondi", "ellipse": "Cercle / ellipse",
                "triangle": "Triangle", "diamond": "Losange", "parallelogram": "Parallélogramme",
                "trapezoid": "Trapèze", "pentagon": "Pentagone", "hexagon": "Hexagone", "octagon": "Octogone",
                "star": "Étoile", "cross": "Croix", "right_arrow": "Flèche droite", "left_arrow": "Flèche gauche",
                "left_right_arrow": "Double flèche", "callout": "Bulle", "cloud": "Nuage", "can": "Cylindre",
                "predefined_process": "Processus prédéfini", "left_brace": "Accolade gauche",
                "right_brace": "Accolade droite"}
RADIUS_SHAPES = ("rect", "round", "callout", "predefined_process")   # arrondi des angles reglable
FONT_FAMILIES = ("Noto Sans", "Segoe UI", "Arial", "Calibri", "Verdana", "Tahoma", "Trebuchet MS", "Georgia",
                 "Times New Roman", "Garamond", "Courier New", "Consolas", "Comic Sans MS", "Impact")
FONT_SIZES = (10, 12, 14, 18, 24, 36, 48, 64, 80, 144, 288)
STROKE_STYLES = ("solid", "dashed", "dotted")

TEXT_STYLE = {"font_family": "", "bold": False, "italic": False, "underline": False, "strike": False,
              "align": "center", "valign": "middle", "text_bg": ""}
DEFAULTS: dict[str, dict] = {
    # font_size 0 = automatique (la plus grande qui tient), comme les post-it de Miro.
    "sticky": {"w": 200.0, "h": 200.0, "color": MIRO_STICKY, "text": "", "font_size": 0,
               "text_color": MIRO_INK, **TEXT_STYLE},
    "text": {"w": 280.0, "h": 40.0, "text": "", "font_size": 24, "text_color": MIRO_INK,
             **TEXT_STYLE, "align": "left", "valign": "top"},
    "shape": {"w": 220.0, "h": 140.0, "shape": "rect", "fill": "#ffffff", "fill_opacity": 0.0,
              "stroke": MIRO_INK, "stroke_width": 2.0, "stroke_style": "solid", "stroke_opacity": 1.0,
              "radius": 0.0, "text": "", "font_size": 14, "text_color": MIRO_INK, **TEXT_STYLE},
    "image": {"w": 320.0, "h": 240.0, "asset": ""},
    # tool : « pen » (stylo) ou « highlighter » (surligneur : trait large et transparent, sous l'encre)
    "ink": {"points": [], "color": MIRO_INK, "width": 2.0, "tool": "pen", "opacity": 1.0},
    # Format du cadre : « free » (libre), papier (FRAME_PAPERS), « square », « custom » (`ratio` [l, h]) ;
    # `orientation` portrait / landscape ; `ratio_locked` = le redimensionnement garde les proportions.
    "frame": {"w": 800.0, "h": 600.0, "title": "Cadre", "fill": "#ffffff", "fill_opacity": 1.0,
              "format": "free", "orientation": "landscape", "ratio": [16.0, 9.0], "ratio_locked": False},
    # Pointes : start_cap / end_cap (board.items.CAP_KINDS), cap_size = taille commune en unites du board
    # (distincte de l'epaisseur). arrow_start / arrow_end gardes a jour pour les anciennes versions.
    "connector": {"src": {}, "dst": {}, "color": MIRO_INK, "width": 2.0, "arrow_end": True,
                  "arrow_start": False, "style": "straight", "stroke_style": "solid",
                  "start_cap": "none", "end_cap": "filled", "cap_size": 12.0},
    # Commentaire LOCAL : marqueur sur le canvas, fil de messages ; `target` = element auquel il est accroche
    # (il le suit ; `dx` / `dy` = sa place par rapport au coin haut gauche de l'element).
    "comment": {"target": "", "dx": 0.0, "dy": 0.0, "resolved": False, "messages": []},
    # Ligne du module CAD (board/cad*.py) : geometrie en coordonnees du DOCUMENT (Y vers le haut), proprietes
    # « ByLayer » resolues dans le calque (page["cad"]) ; champs valides par cad_model.normalize_line.
    "cad_line": {k: None for k in cad_model.LINE_DEFAULTS},
    # Arc, cercle, polyligne du CAD (memes proprietes ; geometrie : board/cad_shapes.py) ; cad_model.normalize_entity.
    "cad_arc": {k: None for k in cad_model.ENTITY_DEFAULTS["cad_arc"]},
    "cad_circle": {k: None for k in cad_model.ENTITY_DEFAULTS["cad_circle"]},
    "cad_pline": {k: None for k in cad_model.ENTITY_DEFAULTS["cad_pline"]},
    "cad_dim": {k: None for k in cad_model.ENTITY_DEFAULTS["cad_dim"]},
    "cad_hatch": {k: None for k in cad_model.ENTITY_DEFAULTS["cad_hatch"]},
    "cad_text": {k: None for k in cad_model.ENTITY_DEFAULTS["cad_text"]},
}
COMMON = {"x": 0.0, "y": 0.0, "z": 0.0, "rotation": 0.0, "locked": False, "link": ""}
ROTATABLE = ("shape", "text", "image")
PAGE_DEFAULTS = {"background": None, "grid": True, "export_background": "page", "export_grid": False,
                 "show_resolved": False, "zoom_min": 0.1, "zoom_max": 4.0}
ZOOM_RANGE = (0.001, 20.0)            # limites de zoom reglables par page : 0,1 % a 2 000 %


def zoom_limits(page: dict) -> tuple[float, float]:
    """(min, max) valides d'une page : dans `ZOOM_RANGE`, min < max ; sinon les valeurs par defaut."""
    try:
        low, high = float(page.get("zoom_min", 0.1)), float(page.get("zoom_max", 4.0))
    except (TypeError, ValueError):
        return 0.1, 4.0
    low = max(ZOOM_RANGE[0], min(ZOOM_RANGE[1], low))
    high = max(ZOOM_RANGE[0], min(ZOOM_RANGE[1], high))
    if not (0 < low < high):
        return 0.1, 4.0
    return low, high


# Formats papier : dimensions EXACTES en mm (portrait). Correspondance avec le board : 1 unite = 1 pixel CSS =
# 1/96 de pouce (un A4 en « taille reelle » mesure 793,7 x 1 122,5 unites). Ce n'est pas une garantie de taille
# imprimee : l'export d'image / PDF couvre tout le board (avec ses marges), pas un cadre seul.
FRAME_PAPERS = {"A6": (105.0, 148.0), "A5": (148.0, 210.0), "A4": (210.0, 297.0), "A3": (297.0, 420.0),
                "A2": (420.0, 594.0), "A1": (594.0, 841.0), "letter": (215.9, 279.4)}
FRAME_FORMATS = ("free", "A6", "A5", "A4", "A3", "A2", "A1", "letter", "square", "custom")
FRAME_LABELS = {"free": "Libre", "letter": "Lettre (US)", "square": "Carré 1:1", "custom": "Ratio personnalisé…",
                **{k: k for k in ("A6", "A5", "A4", "A3", "A2", "A1")}}
UNITS_PER_MM = 96.0 / 25.4


def frame_ratio(data: dict) -> float | None:
    """Largeur / hauteur imposee par le format d'un cadre (orientation comprise) ; None = libre."""
    fmt = data.get("format", "free")
    if fmt in FRAME_PAPERS:
        w, h = FRAME_PAPERS[fmt]
    elif fmt == "square":
        return 1.0
    elif fmt == "custom":
        w, h = parse_ratio(data.get("ratio")) or (16.0, 9.0)
        w, h = min(w, h), max(w, h)                    # l'orientation choisit le sens du ratio personnalise
    else:
        return None
    portrait = data.get("orientation", "landscape") == "portrait"
    return (w / h) if portrait else (h / w)


def parse_ratio(value) -> tuple[float, float] | None:
    """[16, 9], « 16:9 », « 16/9 », « 1,5 » -> (l, h) strictement positifs ; None sinon."""
    try:
        if isinstance(value, (list, tuple)) and len(value) == 2:
            w, h = float(value[0]), float(value[1])
        elif isinstance(value, str):
            text = value.strip().replace(",", ".")
            for sep in (":", "/", "x", "×"):
                if sep in text:
                    a, b = text.split(sep, 1)
                    w, h = float(a), float(b)
                    break
            else:
                w, h = float(text), 1.0
        else:
            return None
    except (TypeError, ValueError):
        return None
    if not (w > 0 and h > 0) or w / h > 1000 or h / w > 1000:
        return None
    return w, h


def paper_size(data: dict) -> tuple[float, float] | None:
    """Taille « reelle » (1 unite = 1/96 de pouce) d'un format papier, orientation comprise."""
    fmt = data.get("format")
    if fmt not in FRAME_PAPERS:
        return None
    w, h = (v * UNITS_PER_MM for v in FRAME_PAPERS[fmt])
    return (w, h) if data.get("orientation") == "portrait" else (h, w)


# Boutons du board dont l'icone se regle (Reglages > Module MRO > Icones ; cle d'icone `ui_board_<genre>`).
ICON_ROWS = [
    ("select", "Outil Sélection"), ("hand", "Outil Main"), ("sticky", "Outil Post-it"), ("text", "Outil Texte"),
    ("shape", "Outil Formes"), ("connector", "Outil Connecteur"), ("draw", "Outil Dessin"),
    ("comment", "Commentaire"), ("frame", "Outil Cadre"), ("image", "Image depuis un fichier"),
    ("page", "Réglages de la page"), ("grid", "Grille"), ("invert", "Icônes et textes en négatif"),
    ("pen", "Dessin : stylo"), ("highlighter", "Dessin : surligneur"), ("smart", "Dessin : dessin intelligent"),
    ("eraser", "Dessin : gomme"), ("precision_eraser", "Dessin : gomme de précision"), ("lasso", "Dessin : lasso"),
    ("text_style", "Barre : style du texte"), ("align", "Barre : alignement"),
    ("text_color", "Barre : couleur du texte"), ("highlight", "Barre : surlignage"), ("link", "Barre : lien"),
    ("border", "Barre : contour"), ("fill", "Barre : fond"), ("arrow", "Barre : flèche"),
    ("frame_format", "Barre : format du cadre"), ("lock", "Barre : verrou"), ("more", "Barre : plus"),
    ("minus", "Zoom : dézoomer"), ("plus", "Zoom : zoomer"), ("fit", "Zoom : tout voir"),
    ("close", "Fermer le fil de commentaire"),
]

# Icones du module CAD (Reglages > Module CAD > Icones ; meme cle d'icone `ui_board_<genre>`) : barre d'outils CAD,
# bouton « Mode CAD » du board, gestion, historique de la barre de commande. Les menus du CAD n'ont pas d'icone.
CAD_ICON_ROWS = [
    ("cad", "Mode CAD (barre d'outils du board)"),
    ("cad_line", "Dessin : ligne"), ("cad_pline", "Dessin : polyligne"), ("cad_circle", "Dessin : cercle"),
    ("cad_arc", "Dessin : arc"), ("cad_rect", "Dessin : rectangle"), ("cad_hatch", "Dessin : hachures"),
    ("cad_move", "Modification : déplacer"), ("cad_copy", "Modification : copier"),
    ("cad_erase", "Modification : effacer"), ("cad_match", "Modification : pipette"), ("cad_rotate", "Modification : rotation"), ("cad_scale", "Modification : échelle"),
    ("cad_mirror", "Modification : miroir"), ("cad_trim", "Modification : ajuster"), ("cad_offset", "Modification : décalage"),
    ("cad_chamfer", "Modification : chanfrein"), ("cad_fillet", "Modification : raccord"),
    ("cad_text", "Annotations : texte"), ("cad_mtext", "Annotations : texte multiligne"),
    ("cad_explode", "Modification : décomposer"), ("cad_dim", "Annotations : cotation linéaire"),
    ("cad_dim_aligned", "Annotations : cotation alignée"), ("cad_dim_radius", "Annotations : cotation de rayon"),
    ("cad_dim_diameter", "Annotations : cotation de diamètre"), ("cad_dim_angular", "Annotations : cotation angulaire"),
    ("cad_settings", "Précision : accrochages et suivi"), ("cad_drawing", "Réglages : réglages du dessin"),
    ("cad_layers", "Gestion : calques"), ("cad_properties", "Gestion : propriétés"),
    ("cad_history", "Barre de commande : historique"),
]


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def empty_board() -> dict:
    return {"format": FORMAT, "version": VERSION, "page": dict(PAGE_DEFAULTS),
            "view": {"zoom": 1.0, "center": [0.0, 0.0]}, "items": []}


def new_item(kind: str, **values) -> dict:
    """Element neuf de type `kind` (valeurs par defaut + `values`), avec un identifiant."""
    item = {"id": new_id(), "type": kind, **copy.deepcopy(COMMON), **copy.deepcopy(DEFAULTS[kind])}
    item.update(values)
    return item


def _coerce(value, default):
    if default is None:
        return value
    if isinstance(default, bool):
        return value if isinstance(value, bool) else default
    if isinstance(default, float):
        return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else default
    if isinstance(default, int):
        return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else default
    return value if type(value) is type(default) else copy.deepcopy(default)


def normalize_item(raw) -> dict | None:
    """Element lu dans un fichier : complete par les valeurs par defaut ; None si son type est inconnu
    (l'appelant le garde alors tel quel, voir `normalize`)."""
    if not isinstance(raw, dict) or raw.get("type") not in DEFAULTS:
        return None
    kind = raw["type"]
    item = {"id": str(raw.get("id") or new_id()), "type": kind}
    for key, default in {**COMMON, **DEFAULTS[kind]}.items():
        item[key] = _coerce(raw.get(key, default), default)
    if kind == "connector":
        for end, legacy in (("start", "arrow_start"), ("end", "arrow_end")):
            if f"{end}_cap" not in raw:                 # anciennes fleches : leur pointe pleine d'avant
                item[f"{end}_cap"] = "filled" if item[legacy] else "none"
        if "cap_size" not in raw:                       # ancienne taille, calculee sur l'epaisseur
            item["cap_size"] = round(8 + item["width"] * 2.2, 2)
    if kind in cad_model.CAD_TYPES:
        cad_model.normalize_entity(item)
    if kind == "shape" and item["shape"] == "round" and "radius" not in raw:
        item["radius"] = round(min(item["w"], item["h"]) * 0.18, 2)        # anciens fichiers (version 1)
    if kind == "shape" and item["shape"] not in SHAPE_KINDS:
        item["shape_unknown"] = item["shape"]                               # forme d'une version plus recente
        item["shape"] = "rect"
    for key, value in raw.items():                     # champs inconnus gardes tels quels (version plus recente)
        item.setdefault(key, value)
    return item


def normalize(data) -> dict:
    """Board lu dans un fichier : schema complete, identifiants uniques ; elements de type inconnu dans
    `foreign` (reecrits tels quels a l'enregistrement)."""
    board = empty_board()
    board["foreign"] = []
    if not isinstance(data, dict):
        return board
    view = data.get("view")
    if isinstance(view, dict):
        try:
            zoom = float(view.get("zoom", 1.0))          # jamais borne ici : la vue applique les limites de la page
            board["view"]["zoom"] = zoom if zoom > 0 else 1.0
            cx, cy = view.get("center", [0.0, 0.0])
            board["view"]["center"] = [float(cx), float(cy)]
        except (TypeError, ValueError):
            pass
    page = data.get("page")
    if isinstance(page, dict):
        for key, default in PAGE_DEFAULTS.items():
            value = page.get(key, default)
            if key == "background":
                board["page"][key] = value if isinstance(value, str) and value.startswith("#") else None
            else:
                board["page"][key] = _coerce(value, default)
        for key, value in page.items():
            board["page"].setdefault(key, value)
        board["page"]["zoom_min"], board["page"]["zoom_max"] = zoom_limits(board["page"])
    seen = set()
    for raw in data.get("items") or []:
        item = normalize_item(raw)
        if item is None:
            if isinstance(raw, dict):
                board["foreign"].append(copy.deepcopy(raw))
            continue
        while item["id"] in seen:
            item["id"] = new_id()
        seen.add(item["id"])
        board["items"].append(item)
    cad_model.migrate_lines(board["page"], board["items"])
    try:
        board["version"] = max(VERSION, int(data.get("version", VERSION)))
    except (TypeError, ValueError):
        pass
    for key, value in data.items():
        board.setdefault(key, value)
    return board


def referenced_assets(data: dict) -> set[str]:
    """Noms des fichiers du dossier assets references par un board (elements connus et inconnus)."""
    names = set()
    for item in list(data.get("items") or []) + list(data.get("foreign") or []):
        if isinstance(item, dict) and isinstance(item.get("asset"), str) and item["asset"]:
            names.add(item["asset"])
    return names
