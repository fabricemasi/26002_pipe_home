"""Données du module Design (SANS Qt) : types d'éléments du `.mro`, valeurs par défaut, formats de page, palettes,
normalisation. Lu par `fm_board.model` (comme `fm_cad.cad_model`) : les types sont connus dès la lecture d'un fichier.

Un document Design = les éléments `design_page` du board (plans de travail, ordre `index`) ; chaque élément Design
porte `page` = identifiant de sa page et des coordonnées RELATIVES à la page (il est enfant de la page dans la scène :
découpé par elle, déplacé avec elle). `group` = identifiant de groupe (vide = seul) : un clic choisit tout le groupe.
Un champ inconnu reste dans l'élément (règle du `.mro`)."""
from __future__ import annotations

import copy

PAGE = "design_page"
SHAPE = "design_shape"
TEXT = "design_text"
IMAGE = "design_image"
ELEMENT_TYPES = (SHAPE, TEXT, IMAGE)
DESIGN_TYPES = (PAGE,) + ELEMENT_TYPES

INK = "#1a1a1a"
ACCENT = "#8b3dff"                     # couleur de sélection du module (violet, distinct du bleu de Miro)
PAGE_GAP = 60.0                        # écart vertical entre deux pages (unités du board)
MIN_SIZE = 4.0

# Ombre portée commune (couleur #AARRGGBB, décalage et flou en unités du board).
SHADOW = {"enabled": False, "color": "#59000000", "dx": 0.0, "dy": 8.0, "blur": 18.0}

STYLE_COMMON = {"page": "", "group": "", "opacity": 1.0, "flip_h": False, "flip_v": False, "name": "",
                "shadow": SHADOW}
FILL_TYPES = ("solid", "linear", "radial", "none")

DEFAULTS: dict[str, dict] = {
    # `guides` = repères de la page [{"axis": "v" | "h", "pos": unités de page}] ; `margins` = marges affichées.
    PAGE: {"w": 1080.0, "h": 1080.0, "name": "", "index": 0, "background": "#ffffff", "bg_type": "solid",
           "bg2": "#e8e0ff", "bg_angle": 90.0, "format": "custom", "guides": [], "margins": False},
    # Forme : `shape` = noms de fm_miro (rect, ellipse, triangle…) + « line » (trait horizontal au milieu de la
    # boîte, tourné par `rotation`) ; fill_type solid / linear / radial (fill -> fill2, angle) / none.
    SHAPE: {"w": 240.0, "h": 240.0, "shape": "rect", "fill": "#8b3dff", "fill_type": "solid", "fill2": "#22d3ee",
            "gradient_angle": 90.0, "stroke": INK, "stroke_width": 0.0, "stroke_style": "solid", "radius": 0.0,
            "cap_start": "none", "cap_end": "none", **STYLE_COMMON},
    # Texte : boîte de largeur fixe, hauteur suivie du contenu ; `letter_spacing` en millièmes de la taille
    # (comme Canva), `line_height` = facteur de la hauteur de ligne.
    TEXT: {"w": 520.0, "h": 60.0, "text": "", "font_family": "", "font_size": 48.0, "color": INK, "bold": False,
           "italic": False, "underline": False, "strike": False, "uppercase": False, "align": "left",
           "line_height": 1.2, "letter_spacing": 0.0, "text_bg": "", "text_stroke": INK, "text_stroke_width": 0.0,
           # Style d'une PARTIE du texte (posé pendant l'édition : Ctrl+B / I / U, Ctrl+Maj+> / <) :
           # [{"start", "end" (caractères), "bold"?, "italic"?, "underline"?, "size"? (px)}] par-dessus le style de
           # la boîte.
           "spans": [], **STYLE_COMMON},
    # Image : `crop` = [x0, y0, x1, y1] partie VISIBLE de l'image source (fractions, non destructif) ; réglages
    # -100..100 ; `radius` arrondi des angles ; contour.
    # `mask` = forme du cadre (masque, « » = rectangle) : un nom de SHAPE_KINDS.
    IMAGE: {"w": 400.0, "h": 300.0, "asset": "", "mask": "", "crop": [0.0, 0.0, 1.0, 1.0], "brightness": 0.0,
            "contrast": 0.0,
            "saturation": 0.0, "blur": 0.0, "grayscale": False, "radius": 0.0, "stroke": INK, "stroke_width": 0.0,
            **STYLE_COMMON},
}

# Formats de page (largeur, hauteur en unités du board = px à 96 ppp ; papier : mm convertis). Noms génériques.
MM = 96.0 / 25.4
PAGE_FORMATS = [
    ("square", "Publication carrée (1080 × 1080)", 1080.0, 1080.0),
    ("portrait_post", "Publication portrait (1080 × 1350)", 1080.0, 1350.0),
    ("story", "Story / vertical (1080 × 1920)", 1080.0, 1920.0),
    ("presentation", "Présentation 16:9 (1920 × 1080)", 1920.0, 1080.0),
    ("video_thumb", "Miniature vidéo (1280 × 720)", 1280.0, 720.0),
    ("banner", "Bannière (1500 × 500)", 1500.0, 500.0),
    ("a4", "A4 portrait (210 × 297 mm)", round(210 * MM, 2), round(297 * MM, 2)),
    ("a4_land", "A4 paysage (297 × 210 mm)", round(297 * MM, 2), round(210 * MM, 2)),
    ("a3", "Affiche A3 (297 × 420 mm)", round(297 * MM, 2), round(420 * MM, 2)),
    ("a5", "Flyer A5 (148 × 210 mm)", round(148 * MM, 2), round(210 * MM, 2)),
    ("letter", "Lettre US (8,5 × 11 in)", 816.0, 1056.0),
    ("card", "Carte de visite (85 × 55 mm)", round(85 * MM, 2), round(55 * MM, 2)),
]
FORMAT_SIZES = {key: (w, h) for key, _label, w, h in PAGE_FORMATS}

PALETTE = ["#000000", "#545454", "#737373", "#a6a6a6", "#d9d9d9", "#ffffff", "#ff3131", "#ff5757", "#ff66c4",
           "#cb6ce6", "#8c52ff", "#5e17eb", "#0097b2", "#0cc0df", "#5ce1e6", "#38b6ff", "#5170ff", "#004aad",
           "#00bf63", "#7ed957", "#c1ff72", "#ffde59", "#ffbd59", "#ff914d"]
SHAPE_KINDS = ("rect", "round", "ellipse", "triangle", "diamond", "pentagon", "hexagon", "octagon", "star", "cross",
               "right_arrow", "left_right_arrow", "callout", "cloud", "parallelogram", "trapezoid", "heart", "ring",
               "line")
MASK_KINDS = ("", "round", "ellipse", "triangle", "diamond", "hexagon", "star", "heart", "cloud")
RADIUS_SHAPES = ("rect", "round", "callout")
CAP_KINDS = ("none", "arrow", "filled", "circle")


def _coerce(value, default):
    if isinstance(default, bool):
        return value if isinstance(value, bool) else default
    if isinstance(default, float):
        return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else default
    if isinstance(default, int):
        return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else default
    if isinstance(default, dict):
        if not isinstance(value, dict):
            return copy.deepcopy(default)
        out = {k: _coerce(value.get(k, d), d) for k, d in default.items()}
        for k, v in value.items():
            out.setdefault(k, v)
        return out
    if isinstance(default, list):
        return copy.deepcopy(value) if isinstance(value, list) else copy.deepcopy(default)
    return value if type(value) is type(default) else copy.deepcopy(default)


def normalize_entity(item: dict) -> dict:
    """Élément Design lu (déjà complété par `fm_board.model.normalize_item`) : valeurs bornées, structures
    réparées. Les champs inconnus restent."""
    kind = item.get("type")
    defaults = DEFAULTS.get(kind)
    if defaults is None:
        return item
    for key, default in defaults.items():
        item[key] = _coerce(item.get(key, default), default)
    item["w"] = max(MIN_SIZE, item["w"])
    item["h"] = max(MIN_SIZE if kind != SHAPE or item.get("shape") != "line" else 1.0, item["h"])
    if kind != PAGE:
        item["opacity"] = min(1.0, max(0.0, item["opacity"]))
    if kind == IMAGE:
        item["crop"] = valid_crop(item.get("crop"))
        for key in ("brightness", "contrast", "saturation"):
            item[key] = min(100.0, max(-100.0, item[key]))
        item["blur"] = min(100.0, max(0.0, item["blur"]))
    if kind == TEXT:
        item["spans"] = valid_spans(item.get("spans"))
        item["font_size"] = min(1600.0, max(1.0, item["font_size"]))
        item["line_height"] = min(5.0, max(0.5, item["line_height"]))
        if item["align"] not in ("left", "center", "right", "justify"):
            item["align"] = "left"
    if kind == PAGE:
        item["guides"] = valid_guides(item.get("guides"))
    if kind == SHAPE and item["fill_type"] not in FILL_TYPES:
        item["fill_type"] = "solid"
    return item


def valid_spans(value) -> list[dict]:
    out = []
    for span in value if isinstance(value, list) else []:
        try:
            start, end = int(span["start"]), int(span["end"])
        except (KeyError, TypeError, ValueError):
            continue
        if end <= start or start < 0:
            continue
        clean = {"start": start, "end": end}
        for key in ("bold", "italic", "underline"):
            if isinstance(span.get(key), bool):
                clean[key] = span[key]
        if isinstance(span.get("size"), (int, float)) and not isinstance(span.get("size"), bool) and span["size"] > 0:
            clean["size"] = round(float(span["size"]), 2)
        if len(clean) > 2:
            out.append(clean)
    return out


def scale_spans(spans: list, k: float) -> list:
    """Tailles des parties stylées multipliées (texte agrandi / réduit par une poignée de coin)."""
    return [dict(span, size=round(span["size"] * k, 2)) if "size" in span else dict(span) for span in spans or []]


def valid_guides(value) -> list[dict]:
    out = []
    for guide in value if isinstance(value, list) else []:
        try:
            axis, pos = guide["axis"], float(guide["pos"])
        except (KeyError, TypeError, ValueError):
            continue
        if axis in ("v", "h"):
            out.append({"axis": axis, "pos": round(pos, 2)})
    return out


def margin_size(w: float, h: float) -> float:
    """Marge affichée d'une page : 5 % du plus petit côté (repère visuel, rien n'est déplacé)."""
    return round(min(w, h) * 0.05, 2)


def valid_crop(value) -> list[float]:
    """[x0, y0, x1, y1] dans [0, 1], x0 < x1, y0 < y1 (sinon l'image entière)."""
    try:
        x0, y0, x1, y1 = (float(v) for v in value)
    except (TypeError, ValueError):
        return [0.0, 0.0, 1.0, 1.0]
    x0, x1 = max(0.0, min(1.0, x0)), max(0.0, min(1.0, x1))
    y0, y1 = max(0.0, min(1.0, y0)), max(0.0, min(1.0, y1))
    if x1 - x0 < 1e-4 or y1 - y0 < 1e-4:
        return [0.0, 0.0, 1.0, 1.0]
    return [x0, y0, x1, y1]


def page_label(page: dict, number: int) -> str:
    name = str(page.get("name") or "").strip()
    return f"Page {number}" + (f" — {name}" if name else "")


def layout_positions(sizes: list[tuple[float, float]], origin: tuple[float, float], gap: float = PAGE_GAP):
    """Pages empilées verticalement (comme Canva), centrées sur l'axe de la première : liste de (x, y)."""
    if not sizes:
        return []
    ox, oy = origin
    axis = ox + sizes[0][0] / 2
    out, y = [], oy
    for w, h in sizes:
        out.append((round(axis - w / 2, 2), round(y, 2)))
        y += h + gap
    return out
