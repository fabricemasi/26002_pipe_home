"""BLOCS du CAD (BLOC / INSERER / DECOMPOSER, comme AutoCAD) : logique PURE (aucun Qt), coordonnees du DOCUMENT.

- Definitions : `page["cad"]["blocks"]` = {nom: {"base": [x, y], "items": [entites]}} ; les entites sont des
  entites CAD ordinaires (memes champs que sur le board : `cad_line`, `cad_arc`, `cad_circle`, `cad_pline`,
  `cad_hatch`, `cad_text`, `cad_point`, `cad_dim`, et `cad_insert` pour un bloc dans un bloc) dans le repere du bloc.
- Reference : entite `cad_insert` = `block` (nom), `pos` (point d'insertion), `scale` (echelle uniforme > 0),
  `rot` (degres), `mirror` (symetrie selon l'axe Y du bloc avant la rotation, comme une echelle X negative),
  `state` (etat de visibilite, voir ci-dessous) + les proprietes ordinaires (calque, couleur…).
- BLOC DYNAMIQUE (etats de visibilite, comme AutoCAD) : `definition["states"]` = {nom: [rangs des entites du bloc
  MASQUEES dans cet etat]} ; la reference montre l'etat `state` (vide ou inconnu = le premier etat, aucun etat = tout).
  `definition["dynamic"]` = nom du bloc dynamique d'AutoCAD dont la definition anonyme (*U…) est une variante (import).

La reference se dessine avec les PRIMITIVES de ses entites transformees (`parts`) ; textes et remplissages pleins a
part (peints par QPainter comme ceux des entites). Couleur et epaisseur de CHAQUE entite du bloc, comme AutoCAD
(`inherit`) : calque 0 -> calque de la reference ; PARBLOC (`BYBLOCK`) -> celle de la reference ; ByLayer -> celle
de son calque ; sinon la sienne. Entite sur un calque masque : non dessinee. Les traits sont groupes par (couleur,
epaisseur) (`strokes`)."""
from __future__ import annotations

import copy
import math

from . import cad_attrib, cad_hatch, cad_point, cad_shapes

MAX_DEPTH = 8                       # blocs imbriques au-dela : ignores
BYBLOCK = "ByBlock"                 # couleur / epaisseur PARBLOC d'une entite de bloc (celle de la reference)
BYLAYER = "ByLayer"                 # = cad_model.BYLAYER (cad_model importe ce module)
LAYER0 = "0"
INSERT_KEYS = ("pos", "scale", "rot", "mirror")
DRAWN_KEYS = ("block", "attribs", "state") + INSERT_KEYS     # champs d'une reference dont depend son dessin
DEFAULTS = {"block": "", "pos": [0.0, 0.0], "scale": 1.0, "rot": 0.0, "mirror": False}


def blocks(cad: dict) -> dict:
    found = (cad or {}).get("blocks")
    return found if isinstance(found, dict) else {}


def states(definition: dict | None) -> dict:
    """Etats de visibilite d'un bloc : {nom: ensemble des rangs masques}, dans l'ordre."""
    raw = (definition or {}).get("states")
    if not isinstance(raw, dict):
        return {}
    out = {}
    for name, hidden in raw.items():
        try:
            out[str(name)] = {int(i) for i in hidden or ()}
        except (TypeError, ValueError):
            out[str(name)] = set()
    return out


def state_of(definition: dict | None, insert: dict) -> str:
    """Etat montre par la reference (le premier si le sien est vide ou inconnu ; "" = bloc sans etats)."""
    found = states(definition)
    if not found:
        return ""
    name = str(insert.get("state") or "")
    return name if name in found else next(iter(found))


def hidden_of(definition: dict | None, insert: dict) -> set:
    found = states(definition)
    return found.get(state_of(definition, insert), set()) if found else set()


def with_states(definition: dict, new_states: dict) -> dict:
    """Definition NEUVE avec ces etats (les definitions ne sont jamais modifiees sur place, cad_model.copy_cad)."""
    out = dict(definition)
    count = len(definition.get("items") or [])
    out["states"] = {str(k): sorted(i for i in set(v) if 0 <= i < count) for k, v in new_states.items()}
    if not out["states"]:
        del out["states"]
    return out


def index_at(cad: dict, insert: dict, p, tol: float):
    """Rang (dans la definition) de l'entite du bloc la plus proche du point `p` (document) a moins de `tol`, parmi
    TOUTES les entites (etat ignore) ; None = aucune."""
    from . import cad_text
    s = style_of(insert)
    definition = blocks(cad).get(s["block"])
    if definition is None:
        return None
    base = definition.get("base") or [0.0, 0.0]
    best, found = tol, None
    for index, entity in enumerate(definition.get("items") or []):
        kind = entity.get("type")
        if kind == "cad_insert":
            prims = parts(cad, nested(entity, base, insert))["prims"]
        elif kind == "cad_text":
            box = cad_text.layout(placed(kind, entity, base, insert))["corners"]
            prims = [("segment", tuple(box[i]), tuple(box[(i + 1) % 4])) for i in range(4)]
        elif kind in cad_shapes.CAD_TYPES:
            data = placed(kind, entity, base, insert)
            prims = cad_point.prims(data) if kind == "cad_point" else cad_shapes.prims(kind, data)
        else:
            continue
        if not prims:
            continue
        d = cad_shapes.distance_to(prims, p)
        if d < best:
            best, found = d, index
    return found


def clean_name(name) -> str:
    """Nom de bloc valide (comme AutoCAD : pas de < > / \\ " : ; ? * | , = `), sans espaces autour."""
    text = str(name or "").strip()
    for ch in '<>/\\":;?*|,=`':
        text = text.replace(ch, "")
    return text[:255]


def style_of(data: dict) -> dict:
    try:
        scale = float(data.get("scale", 1.0))
    except (TypeError, ValueError):
        scale = 1.0
    try:
        rot = float(data.get("rot", 0.0)) % 360.0
    except (TypeError, ValueError):
        rot = 0.0
    pos = data.get("pos") or [0.0, 0.0]
    return {"block": str(data.get("block") or ""), "pos": [float(pos[0]), float(pos[1])],
            "scale": scale if math.isfinite(scale) and scale > 0 else 1.0, "rot": rot,
            "mirror": bool(data.get("mirror", False))}


def placed(kind: str, data: dict, base, insert: dict) -> dict:
    """Entite du bloc (repere du bloc) posee par la reference `insert` (repere du document). Champs geometriques
    NEUFS (les transformations les recopient) ; les autres PARTAGES avec la definition : ne pas les modifier sur place
    (une copie profonde coutait 80 % du calcul d'une reference ; `exploded_insert` copie ce qu'il garde)."""
    s = style_of(insert)
    out = dict(data)
    out.update(cad_shapes.translated(kind, out, (-float(base[0]), -float(base[1]))))
    if s["mirror"]:
        out.update(cad_shapes.mirrored(kind, out, (0.0, 0.0), (0.0, 1.0)))
    if abs(s["scale"] - 1.0) > 1e-12:
        out.update(cad_shapes.scaled(kind, out, (0.0, 0.0), s["scale"]))
    if s["rot"]:
        out.update(cad_shapes.rotated(kind, out, (0.0, 0.0), s["rot"]))
    out.update(cad_shapes.translated(kind, out, tuple(s["pos"])))
    return out


def nested(entity: dict, base, insert: dict) -> dict:
    """Reference de bloc DANS un bloc (repere du bloc) -> reference equivalente dans le document : position posee,
    echelles multipliees, rotations composees (F R(a) = R(-a) F : sous un parent retourne, l'angle change de signe),
    miroirs combines."""
    parent, child = style_of(insert), style_of(entity)
    out = dict(entity)
    out["pos"] = placed("cad_point", {"pos": child["pos"]}, base, insert)["pos"]
    out["scale"] = child["scale"] * parent["scale"]
    out["rot"] = (parent["rot"] + (-child["rot"] if parent["mirror"] else child["rot"])) % 360.0
    out["mirror"] = child["mirror"] != parent["mirror"]
    return out


_LAYERS: dict = {}                  # id(page CAD) -> (page, {identifiant: calque}) : jamais modifiee sur place


def _layer(cad: dict, layer_id) -> dict:
    found = _LAYERS.get(id(cad))
    if found is None or found[0] is not cad:
        if len(_LAYERS) > 32:
            _LAYERS.clear()
        found = _LAYERS[id(cad)] = (cad, {layer.get("id"): layer for layer in (cad or {}).get("layers") or []})
    layer = found[1].get(LAYER0 if layer_id is None else layer_id) or found[1].get(LAYER0)
    if layer is None:
        from .cad_model import LAYER_DEFAULTS
        layer = LAYER_DEFAULTS
    return layer


_USED: dict = {}                    # id(definition) -> (definition, calques cites par le bloc et ses blocs imbriques)


def used_layers(cad: dict, name: str, stack: tuple = ()) -> frozenset:
    """Calques cites par les entites du bloc `name` (blocs imbriques compris ; calque 0 non compte : c'est celui de
    la reference)."""
    definition = blocks(cad).get(name)
    if definition is None or name in stack or len(stack) > MAX_DEPTH:
        return frozenset()
    found = _USED.get(id(definition))
    if found is not None and found[0] is definition:
        return found[1]
    out = set()
    for entity in definition.get("items") or []:
        layer = entity.get("layer")
        if layer not in (None, LAYER0):
            out.add(layer)
        if entity.get("type") == "cad_insert":
            out |= used_layers(cad, str(entity.get("block") or ""), stack + (name,))
    if len(_USED) > 8192:
        _USED.clear()
    result = frozenset(out)
    _USED[id(definition)] = (definition, result)
    return result


def signature(cad: dict, insert: dict) -> tuple:
    """Tout ce dont depend le dessin d'une reference hors de sa geometrie : son encre concrete et celle des calques
    cites par son bloc (une page changee ailleurs ne la refait pas)."""
    name = str(insert.get("block") or "")
    layers = tuple(sorted((lid, layer.get("color"), layer.get("lineweight"), layer.get("visible"))
                          for lid in used_layers(cad, name) for layer in (_layer(cad, lid),)))
    return concrete(cad, insert), layers


def concrete(cad: dict, data: dict) -> tuple:
    """(calque, couleur, epaisseur) EFFECTIFS d'une entite (ou d'une reference) du document : couleur / epaisseur
    explicites, sinon celles de son calque."""
    layer = str(data.get("layer") or LAYER0)
    found = _layer(cad, layer)
    color = data.get("color", BYLAYER)
    weight = data.get("lineweight", BYLAYER)
    color = found["color"] if color in (None, BYLAYER, BYBLOCK) or not isinstance(color, str) else color
    weight = float(found["lineweight"] if weight in (None, BYLAYER, BYBLOCK) else weight)
    return layer, color, weight


def inherit(cad: dict, entity: dict, insert: dict) -> dict:
    """Entite d'un bloc posee par `insert` (deja concrete : `concrete`) : calque 0 -> celui de la reference ; PARBLOC
    -> couleur / epaisseur de la reference ; ByLayer -> celles du calque (apres l'heritage) ; resultat CONCRET."""
    layer = entity.get("layer")
    if layer in (None, LAYER0):
        layer = insert.get("layer", LAYER0)
    found = _layer(cad, layer)
    color = entity.get("color", BYLAYER)
    weight = entity.get("lineweight", BYLAYER)
    if color == BYBLOCK:
        color = insert.get("color")
    elif color in (None, BYLAYER) or not isinstance(color, str):
        color = found["color"]
    if weight == BYBLOCK:
        weight = insert.get("lineweight")
    elif weight in (None, BYLAYER) or isinstance(weight, str):
        weight = found["lineweight"]
    linetype = entity.get("linetype", BYLAYER)
    if linetype == BYBLOCK:
        linetype = insert.get("linetype", BYLAYER)
    if linetype in (None, BYLAYER):
        linetype = found.get("linetype", "continuous")
    out = dict(entity)
    out.update(layer=layer, color=color, lineweight=float(weight), linetype=linetype,
               _visible=bool(found.get("visible", True)))
    return out


MAX_DASHES = 4000                   # tirets au plus par entite d'un bloc (au-dela : trait continu)


def dashed(prims: list, data: dict, cad: dict, unit: float, scale: float) -> list:
    """Traits d'une entite de bloc a type de ligne (tirets) : les morceaux VISIBLES (motif a l'echelle de la
    reference, comme AutoCAD) ; continu : tels quels."""
    from . import cad_model
    from . import cad_geometry as geo
    props = cad_model.resolve(data, cad, unit)
    pattern = props["pattern"]
    length = cad_shapes.total_length(prims)
    if not pattern or length <= geo.EPS:
        return prims
    intervals = geo.dash_intervals(length, pattern, props["ltscale"] * scale, limit=MAX_DASHES)
    if intervals is None:
        return prims
    out = []
    for u0, u1 in intervals:
        out.extend(cad_shapes.sub_prims(prims, u0, max(u1, u0 + geo.EPS)))
    return out


def expand(cad: dict, insert: dict, depth: int = 0, stack: tuple = ()) -> list:
    """[(type, donnees)] des entites d'une reference, en coordonnees du DOCUMENT (blocs imbriques compris, sans
    boucle : un bloc qui s'insere lui-meme est ignore). Calque, couleur et epaisseur de chaque entite : CONCRETS
    (`inherit`) ; `_visible` faux = sur un calque masque."""
    if depth == 0:
        layer, color, weight = concrete(cad, insert)
        insert = dict(insert, layer=layer, color=color, lineweight=weight)
    name = style_of(insert)["block"]
    definition = blocks(cad).get(name)
    if definition is None or depth > MAX_DEPTH or name in stack:
        return []
    base = definition.get("base") or [0.0, 0.0]
    hidden = hidden_of(definition, insert)
    out = []
    for index, entity in enumerate(definition.get("items") or []):
        if index in hidden:                             # etat de visibilite : masquee
            continue
        kind = entity.get("type")
        if kind == "cad_insert":
            child = inherit(cad, nested(entity, base, insert), insert)
            if child["_visible"]:
                out.extend(expand(cad, child, depth + 1, stack + (name,)))
        elif kind in cad_shapes.CAD_TYPES:
            if kind == "cad_text" and entity.get("attdef"):     # attribut : la valeur de la reference
                entity = cad_attrib.shown(entity, insert)
                if entity is None:
                    continue
            out.append((kind, placed(kind, inherit(cad, entity, insert), base, insert)))
    return out


def parts(cad: dict, insert: dict, unit: float = 1.0) -> dict:
    """Ce qu'il faut pour dessiner la reference : `prims` (traits de toutes ses entites visibles, sauf textes),
    `strokes` ({(couleur, epaisseur): primitives} : les memes, par encre), `texts` (donnees des textes, couleur
    concrete), `fills` ([(contours, opacite, couleur)] des hachures pleines), `masks` (contours des masques WIPEOUT),
    `count`."""
    prims, texts, fills, masks = [], [], [], []
    strokes: dict = {}
    entities = expand(cad, insert)
    scale = style_of(insert)["scale"]
    for kind, data in entities:
        if not data.get("_visible", True):
            continue
        if kind == "cad_text":
            texts.append(data)
            continue
        if kind == "cad_hatch":
            style = cad_hatch.style_of(data)
            if style["pattern"] == cad_hatch.WIPEOUT:
                masks.append(cad_hatch.clean_loops(data.get("loops")))
                continue
            if style["pattern"] in ("solid", cad_hatch.GRADIENT):
                fills.append((cad_hatch.clean_loops(data.get("loops")), style["alpha"], data.get("color"),
                              style if style["pattern"] == cad_hatch.GRADIENT else None))
                continue
        if kind == "cad_point":
            found = cad_point.prims(data)
        else:
            found = cad_shapes.prims(kind, data)
            if data.get("linetype") not in (None, BYLAYER, "continuous"):
                found = dashed(found, data, cad, unit, scale)
        prims.extend(found)
        strokes.setdefault((data.get("color"), float(data.get("lineweight", 0.0))), []).extend(found)
    return {"prims": prims, "strokes": strokes, "texts": texts, "fills": fills, "masks": masks,
            "count": len(entities)}


def definition_from(entities, base) -> dict:
    """Definition d'un bloc a partir d'entites du document (copiees telles quelles : le bloc garde leur repere,
    `base` = point de base)."""
    return {"base": [float(base[0]), float(base[1])],
            "items": [copy.deepcopy(e) for e in entities]}


def uses(cad: dict, name: str, inside: str) -> bool:
    """Le bloc `inside` contient-il (meme indirectement) une reference a `name` ? (eviter un bloc qui s'insere lui-meme)"""
    seen = set()
    todo = [inside]
    while todo:
        current = todo.pop()
        if current == name:
            return True
        if current in seen:
            continue
        seen.add(current)
        for entity in (blocks(cad).get(current) or {}).get("items") or []:
            if entity.get("type") == "cad_insert":
                todo.append(str(entity.get("block") or ""))
    return False
