"""Module CAD du board : DONNEES (aucun Qt). Schema des entites CAD et des calques, valeurs par defaut,
normalisation, resolution DYNAMIQUE des proprietes « ByLayer ».

Ou vivent les donnees dans un `.mro` (aucun fichier a part : une page MRO = un board) :
- chaque entite est un element du board (`items`) : `cad_line`, `cad_arc`, `cad_circle`, `cad_pline` (voir
  `ENTITY_DEFAULTS` ; geometrie : cad_shapes) ;
  sa geometrie de reference est en coordonnees du DOCUMENT (Y vers le haut, voir cad_geometry) ;
- les calques et les proprietes courantes sont dans les reglages de la page : `page["cad"]` (voir
  `empty_cad_page`), versionne (`CAD_VERSION`) ; absent tant que le CAD n'a pas servi (un board sans CAD est
  ecrit exactement comme avant).
Annulation : la page passe par l'etat `__page__` de la scene, les entites par leur etat d'element : tout
changement CAD (calques compris) est une etape d'annulation du board. REGLE : ne jamais modifier sur place un
dictionnaire de `page["cad"]` (les etats d'annulation le partagent) — toujours une copie (`copy_cad`).

Heritage (comme AutoCAD) : couleur, epaisseur et type de ligne valent « ByLayer » par defaut ; la valeur
EFFECTIVE est lue au dessin dans le calque de l'entite (`resolve`), jamais recopiee dans l'entite : changer le
calque met a jour toutes ses entites « ByLayer », une valeur posee sur l'entite (override) reste la sienne.

Epaisseur : en unites du DOCUMENT (largeur geometrique du trait, qui porte les extremites arrondies) ; 0 = trait
fin d'un pixel a tout zoom (comme l'epaisseur 0 d'AutoCAD)."""
from __future__ import annotations

import copy
import math

from . import cad_dims, cad_hatch, cad_text

CAD_VERSION = 4                    # 2 : extremites « selon le type », segments interieurs ; 3 : repartition ; 4 : redimensionner
BYLAYER = "ByLayer"
LAYER0 = "0"                       # calque initial, ni supprimable ni renommable (comme AutoCAD)
DEFAULT_COLOR = "#1a1a1a"          # encre des boards (model.MIRO_INK), lisible sur le canvas clair

# Extremites : coupe franche (perpendiculaire a l'axe, au point de reference), arrondi (demi-cercle du diametre
# de l'epaisseur, AU-DELA du point de reference, comme la terminaison ronde d'AutoCAD / Qt), border radius
# (coins arrondis DANS la coupe franche : 0 % = coins droits, 100 % = rayon de la moitie de l'epaisseur).
END_STYLES = ("flat", "round", "radius")
END_LABELS = {"flat": "Coupe franche", "round": "Arrondi", "radius": "Border radius"}
BYTYPE = "ByType"                  # extremite « selon le type de ligne » (Reglages > Module CAD > Types de ligne)
BYTYPE_LABEL = "Selon le type"

# Unites de mesure (Reglages > Module CAD > Unites, override par dessin : `cad["unit"]`). La geometrie est TOUJOURS
# enregistree en unites du board (1 unite = 1 px CSS = 1/96 de pouce : taille reelle a 100 %) ; l'unite ne change
# que ce qui est SAISI et AFFICHE (coordonnees, longueurs, epaisseurs, motifs des types de ligne, grille) : une
# ligne tracee de « 1 » en cm mesure 1 cm. Valeur = unites du board par unite de mesure. « px » (unite du board)
# n'est pas proposee dans les reglages : compatibilite (tests, valeurs anterieures).
UNITS = {
    "mm": ("Millimètre (mm)", "mm", 96.0 / 25.4),
    "cm": ("Centimètre (cm)", "cm", 96.0 / 2.54),
    "m": ("Mètre (m)", "m", 9600.0 / 2.54),
    "km": ("Kilomètre (km)", "km", 9600000.0 / 2.54),
    "px": ("Unité du board", "u", 1.0),
}
UNIT_CHOICES = ("mm", "cm", "m", "km")
DEFAULT_UNIT = "mm"


def unit_key(value, default: str = DEFAULT_UNIT) -> str:
    return value if value in UNITS else (default if default in UNITS else DEFAULT_UNIT)


def unit_scale(value) -> float:
    """Unites du board par unite de mesure `value` (inconnue : millimetre)."""
    return UNITS[unit_key(value)][2]


# Reglages generaux qu'un dessin peut remplacer (reglages du dessin, `cad["overrides"]` : {cle de reglage: valeur}) :
# unite, decimales, TOUTE la grille (Reglages > Module MRO > Grille) et le reticule.
# Reticule (Reglages > Module CAD > Reticule) : tout ce qui le regle peut aussi etre remplace par dessin.
CROSSHAIR_KEYS = ("board_cad_crosshair", "board_cad_crosshair_size", "board_cad_crosshair_full",
                  "board_cad_crosshair_auto_color", "board_cad_crosshair_color", "board_cad_pickbox",
                  "board_cad_magnet", "board_cad_crosshair_memory")
OVERRIDABLE = ("board_cad_unit", "board_cad_precision") + CROSSHAIR_KEYS
OVERRIDABLE_PREFIXES = ("board_grid_",)


def overridable(key: str) -> bool:
    return key in OVERRIDABLE or key.startswith(OVERRIDABLE_PREFIXES)


def drawing_overrides(cad) -> dict:
    own = cad.get("overrides") if isinstance(cad, dict) else None
    return own if isinstance(own, dict) else {}


def drawing_unit(cad: dict, general: str = DEFAULT_UNIT) -> str:
    """Unite EFFECTIVE d'un dessin : la sienne (reglages du dessin) sinon la generale."""
    own = drawing_overrides(cad).get("board_cad_unit")
    return own if own in UNITS else unit_key(general)


# Types de ligne : REGLES par l'utilisateur (Reglages > Module CAD > Types de ligne, `board_cad_linetypes`) et
# installes ici (`set_linetypes`). Une definition : sequence alternee trait / espace EN UNITE DE MESURE (« 1 1 » :
# 1 de trait, 1 d'espace ; un trait de 0 = un point ; une sequence impaire est jouee deux fois pour que traits et
# espaces alternent toujours), extremites du debut et de la fin de la ligne, extremite des segments INTERIEURS (les
# bouts des traits qui ne sont pas les extremites de la ligne), et `extra` = segment additionnel pour la
# repartition (longueur du debut du motif ajoutee a la fin, voir `distribution`). `LINETYPES` (cle -> (libelle,
# motif)) reste la vue courte de ces definitions : motif en unite de mesure (> 0 trait, < 0 espace, 0 point),
# multiplie a la resolution par l'unite, l'echelle de la page (`ltscale`) et celle de l'entite.
LINETYPE_DEFAULTS = [
    {"key": "continuous", "name": "Continu", "sequence": []},
    {"key": "dashed", "name": "Tireté", "sequence": [3.0, 1.5], "extra": 3.0},
    {"key": "hidden", "name": "Caché", "sequence": [1.5, 0.75], "extra": 1.5},
    {"key": "center", "name": "Axe", "sequence": [8.0, 1.5, 1.5, 1.5], "extra": 8.0},
    {"key": "dashdot", "name": "Tiret-point", "sequence": [3.0, 1.5, 0.0, 1.5], "extra": 3.0},
    {"key": "dot", "name": "Pointillé", "sequence": [0.0, 1.5], "extra": 0.0},
    {"key": "phantom", "name": "Fantôme", "sequence": [8.0, 1.5, 1.5, 1.5, 1.5, 1.5], "extra": 8.0},
]
LINETYPES: dict = {}               # cle -> (libelle, motif en unite de mesure) ; tenu par set_linetypes
LINETYPE_DEFS: dict = {}           # cle -> definition normalisee

END_DEFAULT = {"style": "flat", "radius": 50.0}
LINE_DEFAULTS = {
    "layer": LAYER0,
    "color": BYLAYER,              # BYLAYER ou « #rrggbb »
    "lineweight": BYLAYER,         # BYLAYER ou nombre >= 0 (unites du board ; 0 = trait fin)
    "linetype": BYLAYER,           # BYLAYER ou une cle de type de ligne (inconnue : dessinee continue, gardee)
    "ltscale": 1.0,                # echelle propre du motif
    "p1": [0.0, 0.0],              # extremite 1, document
    "p2": [0.0, 0.0],              # extremite 2, document
    "end1": BYTYPE,                # BYTYPE ou {"style", "radius"} (override de l'objet)
    "end2": BYTYPE,
    "inner": BYTYPE,               # bouts des segments interieurs d'un motif
    "distribute": BYTYPE,          # repartir (centrer) les segments (BYTYPE = selon le type, ou True / False)
    "resize": BYTYPE,              # redimensionner les segments pour remplir la ligne (avec `distribute` ; `distribution`)
}

# Proprietes communes a toutes les entites (les autres champs sont la geometrie, voir cad_shapes).
PROP_DEFAULTS = {k: v for k, v in LINE_DEFAULTS.items() if k not in ("p1", "p2")}
ENTITY_DEFAULTS = {
    "cad_line": LINE_DEFAULTS,
    "cad_arc": {**PROP_DEFAULTS, "center": [0.0, 0.0], "radius": 1.0, "start": 0.0, "end": 90.0},
    "cad_circle": {**PROP_DEFAULTS, "center": [0.0, 0.0], "radius": 1.0},
    "cad_pline": {**PROP_DEFAULTS, "vertices": [], "closed": False},
    # Cotation : geometrie et style, voir cad_dims
    "cad_dim": {**PROP_DEFAULTS, "dim_type": "linear", "p1": [0.0, 0.0], "p2": [0.0, 0.0], "pos": [0.0, 0.0],
                "center": [0.0, 0.0], "rot": 0.0, **cad_dims.STYLE_DEFAULTS},
    # Hachures : contours + motif, voir cad_hatch
    "cad_hatch": {**PROP_DEFAULTS, "loops": [], "hatch_pattern": cad_hatch.DEFAULTS["hatch_pattern"],
                  "hatch_angle": cad_hatch.DEFAULTS["hatch_angle"], "hatch_spacing": cad_hatch.DEFAULTS["hatch_spacing"],
                  "hatch_origin": [0.0, 0.0], "hatch_alpha": cad_hatch.DEFAULTS["hatch_alpha"]},
    # Texte (TEXTE / MTEXTE) : point d'insertion, contenu, style, voir cad_text
    "cad_text": {**PROP_DEFAULTS, "pos": [0.0, 0.0], **cad_text.DEFAULTS},
}
CAD_TYPES = tuple(ENTITY_DEFAULTS)

# Proprietes d'une ligne qui suivent un reglage (calque ou type de ligne) tant qu'elles ne sont pas remplacees :
# cle de l'entite -> (cle de la propriete COURANTE du dessin ou None, valeur « par defaut »). Une autre valeur = un
# override (point orange du panneau Proprietes ; un clic le retire).
FOLLOWING = {"color": ("cecolor", BYLAYER), "lineweight": ("celweight", BYLAYER), "linetype": ("celtype", BYLAYER),
             "ltscale": (None, 1.0), "distribute": ("distribute", BYTYPE), "resize": ("resize", BYTYPE), "end1": ("end1", BYTYPE),
             "end2": ("end2", BYTYPE), "inner": ("inner", BYTYPE)}

LAYER_DEFAULTS = {"id": LAYER0, "name": "0", "visible": True, "locked": False, "color": DEFAULT_COLOR,
                  "linetype": "continuous", "lineweight": 0.0}


def empty_cad_page() -> dict:
    return {"version": CAD_VERSION, "current": LAYER0, "layers": [dict(LAYER_DEFAULTS)], "ltscale": 1.0,
            # proprietes des objets crees (comme CECOLOR / CELWEIGHT / CELTYPE d'AutoCAD) et extremites
            "cecolor": BYLAYER, "celweight": BYLAYER, "celtype": BYLAYER,
            "end1": BYTYPE, "end2": BYTYPE, "inner": BYTYPE, "distribute": BYTYPE, "resize": BYTYPE}


def copy_cad(cad: dict) -> dict:
    return copy.deepcopy(cad)


# -- validation --
def _color(value, default=BYLAYER):
    if value == BYLAYER:
        return BYLAYER
    if isinstance(value, str) and value.startswith("#") and len(value) in (7, 9):
        try:
            int(value[1:], 16)
            return value.lower()
        except ValueError:
            pass
    return default


def _weight(value, default=BYLAYER):
    if value == BYLAYER:
        return BYLAYER
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
        return float(value)
    return default


def _linetype(value, default=BYLAYER):
    """BYLAYER ou une cle de type de ligne. Une cle INCONNUE (type supprime des reglages, autre machine) est gardee :
    l'entite est dessinee en continu et retrouve son motif si le type revient."""
    if value == BYLAYER or (isinstance(value, str) and value):
        return value
    return default


def _point(value, default):
    try:
        x, y = float(value[0]), float(value[1])
    except (TypeError, ValueError, IndexError):
        return list(default)
    if x != x or y != y or abs(x) == float("inf") or abs(y) == float("inf"):
        return list(default)
    return [x, y]


def normalize_end(value, allow_bytype: bool = True):
    """Extremite : BYTYPE (selon le type de ligne) ou {"style", "radius"} valide (champs inconnus gardes)."""
    if allow_bytype and (value == BYTYPE or value is None):
        return BYTYPE
    out = dict(END_DEFAULT)
    if isinstance(value, dict):
        if value.get("style") in END_STYLES:
            out["style"] = value["style"]
        try:
            out["radius"] = max(0.0, min(100.0, float(value.get("radius", out["radius"]))))
        except (TypeError, ValueError):
            pass
        for key, extra in value.items():          # champs d'une version plus recente : gardes
            out.setdefault(key, extra)
    return out


def _number(value, default: float) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if math.isfinite(out) else default


def normalize_entity(item: dict) -> dict:
    """Champs CAD d'une entite lue dans un fichier (ligne, arc, cercle, polyligne ; inconnus gardes)."""
    kind = item.get("type", "cad_line")
    if kind == "cad_line":
        return normalize_line(item)
    _normalize_props(item)
    if kind in ("cad_arc", "cad_circle"):
        item["center"] = _point(item.get("center"), (0.0, 0.0))
        item["radius"] = max(0.0, _number(item.get("radius"), 1.0))
    if kind == "cad_arc":
        item["start"] = _number(item.get("start"), 0.0)
        item["end"] = _number(item.get("end"), 90.0)
    if kind == "cad_dim":
        item["dim_type"] = item.get("dim_type") if item.get("dim_type") in cad_dims.TYPES else "linear"
        for key in ("p1", "p2", "pos", "center"):
            item[key] = _point(item.get(key), (0.0, 0.0))
        item["rot"] = _number(item.get("rot"), 0.0)
        style = cad_dims.style_of(item)
        for key in cad_dims.STYLE_DEFAULTS:
            item[key] = style[key] if key != "dim_str" else str(item.get("dim_str") or "")
    if kind == "cad_hatch":
        item["loops"] = cad_hatch.clean_loops(item.get("loops"))
        style = cad_hatch.style_of(item)
        item["hatch_pattern"], item["hatch_angle"] = style["pattern"], style["angle"]
        item["hatch_spacing"], item["hatch_alpha"] = style["spacing"], style["alpha"]
        item["hatch_origin"] = list(style["origin"])
    if kind == "cad_text":
        item["pos"] = _point(item.get("pos"), (0.0, 0.0))
        style = cad_text.style_of(item)
        for key in cad_text.DEFAULTS:
            item[key] = style[key]
    if kind == "cad_pline":
        vertices = []
        for v in item.get("vertices") or []:
            if isinstance(v, (list, tuple)) and len(v) >= 2:
                x, y = _number(v[0], math.nan), _number(v[1], math.nan)
                if math.isfinite(x) and math.isfinite(y):
                    vertices.append([x, y, _number(v[2], 0.0) if len(v) > 2 else 0.0])
        item["vertices"] = vertices
        item["closed"] = bool(item.get("closed", False))
    return item


def normalize_line(item: dict) -> dict:
    """Champs CAD d'un element `cad_line` lu dans un fichier (complete, valide ; inconnus gardes)."""
    _normalize_props(item)
    item["p1"] = _point(item.get("p1"), (0.0, 0.0))
    item["p2"] = _point(item.get("p2"), (0.0, 0.0))
    return item


def _normalize_props(item: dict):
    item["layer"] = str(item.get("layer") or LAYER0)
    item["color"] = _color(item.get("color"))
    item["lineweight"] = _weight(item.get("lineweight"))
    item["linetype"] = _linetype(item.get("linetype"))
    try:
        item["ltscale"] = max(1e-6, float(item.get("ltscale", 1.0)))
    except (TypeError, ValueError):
        item["ltscale"] = 1.0
    item["end1"] = normalize_end(item.get("end1"))
    item["end2"] = normalize_end(item.get("end2"))
    item["inner"] = normalize_end(item.get("inner"))
    distribute = item.get("distribute", BYTYPE)
    item["distribute"] = distribute if isinstance(distribute, bool) else BYTYPE
    resize = item.get("resize", BYTYPE)
    item["resize"] = resize if isinstance(resize, bool) else BYTYPE


def normalize_layer(raw, index: int) -> dict | None:
    if not isinstance(raw, dict):
        return None
    layer = dict(LAYER_DEFAULTS)
    layer["id"] = str(raw.get("id") or (LAYER0 if index == 0 else f"layer{index}"))
    layer["name"] = str(raw.get("name") or layer["id"])
    layer["visible"] = bool(raw.get("visible", True))
    layer["locked"] = bool(raw.get("locked", False))
    layer["color"] = _color(raw.get("color"), DEFAULT_COLOR)
    if layer["color"] == BYLAYER:
        layer["color"] = DEFAULT_COLOR
    layer["linetype"] = _linetype(raw.get("linetype"), "continuous")
    if layer["linetype"] == BYLAYER:
        layer["linetype"] = "continuous"
    weight = _weight(raw.get("lineweight"), 0.0)
    layer["lineweight"] = 0.0 if weight == BYLAYER else weight
    for key, value in raw.items():
        layer.setdefault(key, value)
    return layer


def normalize_cad_page(raw) -> dict:
    """`page["cad"]` lu dans un fichier (ou absent) : schema complet, calque 0 toujours present (en tete),
    identifiants et noms uniques, calque courant valide. Champs inconnus gardes."""
    cad = empty_cad_page()
    if not isinstance(raw, dict):
        return cad
    layers, seen_ids, seen_names = [], set(), set()
    for index, value in enumerate(raw.get("layers") or []):
        layer = normalize_layer(value, index)
        if layer is None or layer["id"] in seen_ids:
            continue
        if layer["id"] == LAYER0:
            layer["name"] = "0"
        name = layer["name"]
        n = 2
        while name.lower() in seen_names:
            name = f"{layer['name']} ({n})"
            n += 1
        layer["name"] = name
        seen_ids.add(layer["id"])
        seen_names.add(name.lower())
        layers.append(layer)
    if LAYER0 not in seen_ids:
        layers.insert(0, dict(LAYER_DEFAULTS))
    cad["layers"] = layers
    current = str(raw.get("current") or LAYER0)
    cad["current"] = current if current in {l["id"] for l in layers} else LAYER0
    try:
        cad["ltscale"] = max(1e-6, float(raw.get("ltscale", 1.0)))
    except (TypeError, ValueError):
        pass
    cad["cecolor"] = _color(raw.get("cecolor"))
    cad["celweight"] = _weight(raw.get("celweight"))
    cad["celtype"] = _linetype(raw.get("celtype"))
    try:
        version = int(raw.get("version", CAD_VERSION))
    except (TypeError, ValueError):
        version = CAD_VERSION
    for key in ("end1", "end2", "inner"):
        value = raw.get(key)
        if version < 2 and value == END_DEFAULT:
            value = BYTYPE              # version 1 : terminaison courante d'origine = « selon le type » desormais
        cad[key] = normalize_end(value)
    distribute = raw.get("distribute", BYTYPE)
    cad["distribute"] = BYTYPE if version < 3 and distribute is False else (
        distribute if isinstance(distribute, bool) else BYTYPE)
    resize = raw.get("resize", BYTYPE)
    cad["resize"] = resize if isinstance(resize, bool) else BYTYPE
    if version < 4 and cad["distribute"] is True and "resize" not in raw:
        cad["resize"] = True                # avant la version 4, repartir allongeait / raccourcissait le motif
    overrides = {k: v for k, v in drawing_overrides(raw).items() if isinstance(k, str) and overridable(k)}
    if raw.get("unit") in UNITS:                      # premiers essais (non publies) : cles a part
        overrides.setdefault("board_cad_unit", raw["unit"])
    if isinstance(raw.get("precision"), int) and not isinstance(raw.get("precision"), bool):
        overrides.setdefault("board_cad_precision", max(0, min(8, raw["precision"])))
    if overrides:
        cad["overrides"] = overrides
    raw = {k: v for k, v in raw.items() if k not in ("unit", "precision", "grid_step")}   # repris ci-dessus
    cad["version"] = max(CAD_VERSION, version)
    for key, value in raw.items():
        cad.setdefault(key, value)
    return cad


def migrate_lines(page: dict, items: list):
    """Fichier d'avant la version 2 : les terminaisons d'origine des lignes (coupe franche, rayon 50 %) n'avaient
    jamais ete choisies — elles deviennent « selon le type » et suivent les reglages ; une autre valeur reste un
    override."""
    raw = page.get("cad") if isinstance(page, dict) else None
    try:
        version = int(raw.get("version", 1)) if isinstance(raw, dict) else 1
    except (TypeError, ValueError):
        version = 1
    if version >= 4:
        return
    for item in items:
        if item.get("type") in CAD_TYPES:
            if version < 3 and item.get("distribute") is False:          # version 2 : False = jamais choisi
                item["distribute"] = BYTYPE
            if item.get("distribute") is True and "resize" not in item:
                item["resize"] = True                    # avant la version 4, repartir redimensionnait le motif
            for key in ("end1", "end2"):
                if version < 2 and item.get(key) == END_DEFAULT:
                    item[key] = BYTYPE


def page_cad(page: dict) -> dict:
    """Donnees CAD d'une page (normalisees ; page sans CAD = calque 0 seul). Ne modifie pas la page."""
    raw = page.get("cad") if isinstance(page, dict) else None
    cached = _NORMALIZED.get(id(raw))
    if cached is not None and cached[0] is raw:
        return cached[1]
    cad = normalize_cad_page(raw)
    if raw is not None:
        if len(_NORMALIZED) > 64:
            _NORMALIZED.clear()
        _NORMALIZED[id(raw)] = (raw, cad)
    return cad


_NORMALIZED: dict = {}             # id(dict brut) -> (dict brut, normalise) : lecture au dessin sans recopie


# -- calques --
def layer_by_id(cad: dict, layer_id: str) -> dict | None:
    for layer in cad["layers"]:
        if layer["id"] == layer_id:
            return layer
    return None


def layer_by_name(cad: dict, name: str) -> dict | None:
    key = (name or "").strip().lower()
    for layer in cad["layers"]:
        if layer["name"].lower() == key:
            return layer
    return None


def effective_layer(cad: dict, layer_id: str) -> dict:
    """Calque d'une entite ; identifiant inconnu (entite collee d'un autre board, fichier modifie) : calque 0
    (l'entite garde son identifiant)."""
    return layer_by_id(cad, layer_id) or layer_by_id(cad, LAYER0) or dict(LAYER_DEFAULTS)


def unique_layer_name(cad: dict, base: str = "Calque") -> str:
    names = {l["name"].lower() for l in cad["layers"]}
    n = 1
    while f"{base}{n}".lower() in names:
        n += 1
    return f"{base}{n}"


def new_layer_id(cad: dict) -> str:
    ids = {l["id"] for l in cad["layers"]}
    n = len(ids)
    while f"L{n}" in ids:
        n += 1
    return f"L{n}"


def valid_layer_name(cad: dict, name: str, layer_id: str | None = None) -> str | None:
    """Message d'erreur si `name` ne convient pas (vide, caracteres interdits par AutoCAD, deja pris)."""
    name = (name or "").strip()
    if not name:
        return "Le nom d'un calque ne peut pas être vide."
    if any(c in name for c in '<>/\\":;?*|=`'):
        return "Caractères interdits dans un nom de calque : < > / \\ \" : ; ? * | = `"
    other = layer_by_name(cad, name)
    if other is not None and other["id"] != layer_id:
        return f"Le calque « {name} » existe déjà."
    return None


# -- types de ligne --
def parse_sequence(text) -> list | None:
    """« 1 0.5 0.5 0.5 » -> [1.0, 0.5, 0.5, 0.5] ; separateurs : espaces (ou points-virgules) ; valeurs >= 0.
    Texte invalide : None. Vide = continu."""
    if isinstance(text, (list, tuple)):
        values = list(text)
    else:
        values = (text or "").replace(";", " ").split()
    out = []
    for value in values:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(number) or number < 0:
            return None
        out.append(number)
    if out and sum(out) <= 0:
        return None
    return out


def format_sequence(sequence) -> str:
    return " ".join(f"{v:g}" for v in sequence or ())


def sequence_pattern(sequence) -> tuple:
    """Sequence alternee trait / espace -> motif signe (> 0 trait, < 0 espace, 0 point ; un espace nul est saute).
    Sequence impaire : jouee deux fois (traits et espaces alternent toujours)."""
    values = list(sequence or ())
    if len(values) % 2:
        values = values * 2
    out = []
    for index, value in enumerate(values):
        if index % 2 == 0:
            out.append(float(value))
        elif value > 0:
            out.append(-float(value))
    return tuple(out)


def pattern_period(pattern) -> float:
    return sum(abs(v) for v in pattern or ())


def normalize_linetype(raw, index: int = 0) -> dict | None:
    if not isinstance(raw, dict):
        return None
    key = str(raw.get("key") or f"type{index}")
    sequence = parse_sequence(raw.get("sequence", []))
    out = {"key": key, "name": str(raw.get("name") or key), "sequence": sequence if sequence is not None else [],
           "distribute": bool(raw.get("distribute", False)),
           "resize": bool(raw["resize"]) if "resize" in raw else bool(raw.get("distribute", False))}
    for end in ("end1", "end2", "inner"):
        out[end] = normalize_end(raw.get(end), allow_bytype=False)
    try:
        out["extra"] = max(0.0, float(raw.get("extra", 0.0)))
    except (TypeError, ValueError):
        out["extra"] = 0.0
    period = pattern_period(sequence_pattern(out["sequence"]))
    out["extra"] = min(out["extra"], 4 * period) if period > 0 else 0.0
    return out


def normalize_linetypes(raw) -> list:
    """Liste des definitions (reglages) : cles uniques, « continuous » toujours present (en tete)."""
    out, seen = [], set()
    for index, value in enumerate(raw if isinstance(raw, list) else []):
        entry = normalize_linetype(value, index)
        if entry is None or entry["key"] in seen:
            continue
        seen.add(entry["key"])
        out.append(entry)
    if "continuous" not in seen:
        out.insert(0, normalize_linetype(LINETYPE_DEFAULTS[0]))
    return out


def set_linetypes(raw) -> bool:
    """Installe les definitions des reglages (`board_cad_linetypes`, vide = celles d'origine) ; True si elles ont
    change (les lignes doivent alors relire leurs proprietes)."""
    defs = normalize_linetypes(raw if raw else LINETYPE_DEFAULTS)
    new = {d["key"]: d for d in defs}
    if new == LINETYPE_DEFS:
        return False
    LINETYPE_DEFS.clear()
    LINETYPE_DEFS.update(new)
    LINETYPES.clear()
    LINETYPES.update({d["key"]: (d["name"], sequence_pattern(d["sequence"])) for d in defs})
    return True


def new_linetype_key(defs) -> str:
    keys = {d.get("key") for d in defs}
    n = 1
    while f"user{n}" in keys:
        n += 1
    return f"user{n}"


def linetype_def(key) -> dict:
    return LINETYPE_DEFS.get(key) or LINETYPE_DEFS.get("continuous") or normalize_linetype(LINETYPE_DEFAULTS[0])


def centered_span(length: float, period: float, extra: float) -> tuple:
    """Repartition SANS redimensionner (le motif garde sa taille) : (decalage, longueur) du groupe de cycles ENTIERS
    plus le segment additionnel qui tient dans la ligne, centre sur elle ; le reste est partage a parts egales de
    chaque cote. Pas de motif, ligne nulle ou rien qui tienne : (0, length)."""
    if period <= 0 or length <= 0:
        return 0.0, length
    extra = max(0.0, extra)
    cycles = max(0, math.floor((length - extra) / period + 1e-9))
    total = cycles * period + extra
    if total <= 0 or total > length + 1e-9:
        return 0.0, length
    return (length - total) / 2.0, total


def distribution(length: float, period: float, extra: float) -> float:
    """Redimensionnement des segments : facteur applique au motif pour que la ligne compte un nombre ENTIER de cycles plus
    le segment additionnel (`extra` : debut du motif, repete a la fin) — cycles au plus proche, motif allonge ou
    raccourci d'autant ; la ligne garde sa longueur. 1.0 = rien a faire (pas de motif, ligne nulle)."""
    if period <= 0 or length <= 0:
        return 1.0
    extra = max(0.0, extra)
    cycles = max(0, round((length - extra) / period))
    if cycles == 0 and extra <= 0:
        cycles = 1
    total = cycles * period + extra
    return length / total if total > 0 else 1.0


# -- resolution des proprietes --
def resolve(data: dict, cad: dict, unit: float = 1.0) -> dict:
    """Proprietes EFFECTIVES d'une entite : couleur, epaisseur, type de ligne (motif en unites du board = motif du
    type x `unit`), extremites (celles de l'objet, sinon celles du type), calque, visibilite, verrou. Rien n'est
    recopie dans l'entite. `unit` : unites du board par unite de mesure du dessin."""
    layer = effective_layer(cad, data.get("layer", LAYER0))
    color = data.get("color", BYLAYER)
    weight = data.get("lineweight", BYLAYER)
    linetype = data.get("linetype", BYLAYER)
    linetype = layer["linetype"] if linetype == BYLAYER else linetype
    definition = LINETYPE_DEFS.get(linetype) or linetype_def("continuous")
    pattern = LINETYPES.get(linetype, ("", ()))[1]
    ends = {}
    for key in ("end1", "end2", "inner"):
        own = data.get(key, BYTYPE)
        ends[key] = dict(own) if isinstance(own, dict) else dict(definition.get(key) or END_DEFAULT)
    return {
        "layer": layer,
        "color": layer["color"] if color == BYLAYER else color,
        "lineweight": float(layer["lineweight"] if weight == BYLAYER else weight),
        "linetype": linetype,
        "pattern": tuple(v * unit for v in pattern),
        "extra": float(definition.get("extra", 0.0)) * unit if pattern else 0.0,
        "ltscale": float(cad.get("ltscale", 1.0)) * float(data.get("ltscale", 1.0) or 1.0),
        "distribute": own_distribute if isinstance(own_distribute := data.get("distribute", BYTYPE), bool)
        else bool(definition.get("distribute", False)),
        "resize": own_resize if isinstance(own_resize := data.get("resize", BYTYPE), bool)
        else bool(definition.get("resize", False)),
        **ends,
        "visible": bool(layer["visible"]),
        "locked": bool(layer["locked"]),
    }


def new_entity_values(cad: dict, **geometry) -> dict:
    """Valeurs d'une entite creee maintenant (arc, cercle, polyligne…) : proprietes COURANTES + sa geometrie."""
    values = new_line_values(cad, (0.0, 0.0), (0.0, 0.0))
    del values["p1"], values["p2"]
    values.update(copy.deepcopy(geometry))
    return values


def new_line_values(cad: dict, p1, p2) -> dict:
    """Valeurs d'une ligne creee maintenant : calque et proprietes COURANTS (ByLayer / selon le type par defaut)."""
    def end(key):
        value = cad.get(key, BYTYPE)
        return dict(value) if isinstance(value, dict) else BYTYPE
    return {"layer": cad.get("current", LAYER0), "color": cad.get("cecolor", BYLAYER),
            "lineweight": cad.get("celweight", BYLAYER), "linetype": cad.get("celtype", BYLAYER),
            "ltscale": 1.0, "p1": [float(p1[0]), float(p1[1])], "p2": [float(p2[0]), float(p2[1])],
            "end1": end("end1"), "end2": end("end2"), "inner": end("inner"),
            "distribute": cad["distribute"] if isinstance(cad.get("distribute"), bool) else BYTYPE,
            "resize": cad["resize"] if isinstance(cad.get("resize"), bool) else BYTYPE}


def overridden(data: dict, key: str) -> bool:
    """Propriete `key` d'une entite remplacee (autre chose que ce que donnent le calque / le type de ligne) ?"""
    default = FOLLOWING[key][1]
    return data.get(key, default) != default


def describe_weight(value, unit: float = 1.0) -> str:
    """Epaisseur affichee dans l'unite de mesure (`unit` = unites du board par unite)."""
    if value == BYLAYER:
        return BYLAYER
    return "fin (0)" if float(value) == 0 else f"{round(float(value) / unit, 6):g}"


def describe_color(value) -> str:
    return BYLAYER if value == BYLAYER else str(value)


def describe_linetype(value) -> str:
    return BYLAYER if value == BYLAYER else LINETYPES.get(value, (f"{value} (absent)",))[0]


def describe_end(value) -> str:
    return BYTYPE_LABEL if not isinstance(value, dict) else END_LABELS.get(value.get("style"), "?")


set_linetypes(LINETYPE_DEFAULTS)
