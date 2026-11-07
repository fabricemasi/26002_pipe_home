"""Module CAD du board : OUVERTURE d'un dessin DXF (ezdxf, licence MIT) ou DWG (ezdxf + ODA File Converter) dans
le board (demande de l'utilisateur : un DXF / DWG des colonnes s'ouvre dans le module MRO).

Le dessin est LU puis converti en un board en memoire ; le fichier d'origine n'est JAMAIS reecrit (le modele CAD de
CAD n'a que des lignes, arcs, cercles et polylignes : reecrire le DXF perdrait textes, hachures, cotes...). Le board peut ensuite etre
enregistre en `.mro` a cote (voir `BoardPane.open_import`).

Correspondances :
- espace objet seulement (les presentations sont ignorees) ; blocs (INSERT) et cotes (DIMENSION) eclates ;
- LINE -> ligne ; ARC -> arc ; CIRCLE -> cercle ; LWPOLYLINE -> polyligne (renflements compris) ; POLYLINE, ELLIPSE,
  SPLINE (et les entites hors du plan XY) -> lignes qui suivent la courbe a `TOLERANCE` unites du board pres ;
- calques -> calques (couleur, type de ligne connu sinon continu, epaisseur, eteint / gele = masque, verrou) ;
  couleur 7 (blanc / noir selon le fond dans AutoCAD) -> encre du board ;
- unites ($INSUNITS) -> taille reelle (1 unite du board = 1/96 de pouce) ; sans unite : 1 unite = 1 unite du board ;
- TEXT / MTEXT -> textes (contenu sans codes de mise en forme, hauteur, angle, justification, largeur du cadre ;
  police : celle d'origine du module, la police du fichier n'est pas lue) ;
- HATCH -> hachures (contours, motif d'AutoCAD garde tel quel : familles de traits, tirets, points ; plein ; degrade
  = plein de sa 1re couleur), placees derriere le reste ;
- IGNORE (compte rendu) : points, solides, images, objets 3D...
Lecture faite hors du fil de l'interface par l'appelant (`read_drawing` n'utilise pas Qt)."""
from __future__ import annotations

import math
from pathlib import Path

from . import cad_hatch, cad_image, cad_model, cad_point, cad_shapes
from fm_board import model

EXTENSIONS = (".dxf", ".dwg")
TOLERANCE = 0.25                           # ecart maximal courbe / lignes, en unites du board
MAX_SEGMENTS = 512                         # par courbe
# $INSUNITS -> unites du board par unite du dessin
DRAWING_UNITS = {4: "mm", 5: "cm", 6: "m", 7: "km"}  # $INSUNITS -> unite de mesure du CAD (cad_model.UNITS)
UNIT_SCALE = {0: 1.0, 1: 96.0, 2: 96.0 * 12, 3: 96.0 * 63360, 4: 96.0 / 25.4, 5: 96.0 / 2.54, 6: 96.0 / 0.0254,
              7: 96.0 / 0.0000254, 8: 96.0e-6, 9: 96.0e-3, 10: 96.0 * 36, 14: 96.0 / 0.254}
UNIT_NAMES = {0: "sans unité", 1: "pouces", 2: "pieds", 4: "millimètres", 5: "centimètres", 6: "mètres",
              7: "kilomètres", 10: "yards", 14: "décimètres"}
CURVES = {"LINE", "LWPOLYLINE", "POLYLINE", "ARC", "CIRCLE", "ELLIPSE", "SPLINE"}
TEXTS = {"TEXT", "MTEXT"}
ALIGN_CODES = {"LEFT": "L", "CENTER": "C", "RIGHT": "R", "ALIGNED": "L", "FIT": "L", "MIDDLE": "MC",
               "TOP_LEFT": "TL", "TOP_CENTER": "TC", "TOP_RIGHT": "TR", "MIDDLE_LEFT": "ML", "MIDDLE_CENTER": "MC",
               "MIDDLE_RIGHT": "MR", "BOTTOM_LEFT": "BL", "BOTTOM_CENTER": "BC", "BOTTOM_RIGHT": "BR"}
ATTACH_CODES = {1: "TL", 2: "TC", 3: "TR", 4: "ML", 5: "MC", 6: "MR", 7: "BL", 8: "BC", 9: "BR"}
EXPLODED = {"INSERT", "DIMENSION", "ARC_DIMENSION", "LARGE_RADIAL_DIMENSION", "LEADER", "MULTILEADER", "MLEADER"}
SOLIDS = {"SOLID", "TRACE"}                 # quadrilateres pleins -> hachures pleines
FACES = {"3DFACE"}                          # faces 3D -> leurs aretes visibles (en lignes)
POINTS = {"POINT"}
MASKS = {"WIPEOUT"}                         # masques -> hachures « wipeout » (couleur du fond, sur les traits)
IMAGES = {"IMAGE"}                          # images referencees -> `cad_image` (le fichier reste ou il est)
INFINITE = {"XLINE": "cad_xline", "RAY": "cad_ray"}   # lignes de construction (base + point de direction)
FIT_PX = 1000.0                            # largeur d'ecran supposee pour la limite de zoom d'un grand dessin


class DrawingError(Exception):
    """Lecture impossible (bibliotheque ou outil absent, fichier illisible) : message pour l'utilisateur."""


def is_cad_drawing(path) -> bool:
    return path is not None and Path(path).suffix.lower() in EXTENSIONS


def _ezdxf():
    try:
        import ezdxf
    except ImportError as exc:
        raise DrawingError("Le paquet Python « ezdxf » est nécessaire pour ouvrir un DXF / DWG "
                           "(pip install ezdxf).") from exc
    return ezdxf


def _read(path: Path):
    ezdxf = _ezdxf()
    if path.suffix.lower() == ".dwg":
        from ezdxf.addons import odafc
        from . import cad_export
        exe = cad_export.oda_converter()
        if exe:
            ezdxf.options.set("odafc-addon", "win_exec_path", f'"{exe}"')
        if not odafc.is_installed():
            raise DrawingError("Ouvrir un DWG demande ODA File Converter (gratuit, opendesign.com), introuvable. "
                               "Installez-le ou indiquez son chemin dans la variable ODA_FILE_CONVERTER ; "
                               "les DXF, eux, s'ouvrent sans.")
        try:
            with cad_export.oda_environment():
                return odafc.readfile(str(path))
        except Exception as exc:                            # noqa: BLE001 - conversion refusee par ODA
            raise DrawingError(f"Conversion du DWG impossible : {exc}") from exc
    try:
        return ezdxf.readfile(str(path))
    except IOError as exc:
        raise DrawingError(f"Fichier illisible : {exc}") from exc
    except ezdxf.DXFStructureError:
        try:
            from ezdxf import recover
            doc, _auditor = recover.readfile(str(path))     # DXF abime : lecture tolerante d'ezdxf
            return doc
        except Exception as exc:                            # noqa: BLE001
            raise DrawingError(f"DXF invalide : {exc}") from exc


def _hex(rgb) -> str:
    return "#%02x%02x%02x" % tuple(int(v) for v in rgb)


def _aci_color(aci: int) -> str:
    from ezdxf.colors import aci2rgb
    if aci in (7, 0, 256) or not 1 <= aci <= 255:
        return cad_model.DEFAULT_COLOR                      # blanc / noir selon le fond dans AutoCAD
    return _hex(aci2rgb(aci))


def _linetype(name) -> str:
    key = str(name or "").lower()
    if key in ("", "continuous", "bylayer", "byblock"):
        return "continuous"
    for known in sorted(cad_model.LINETYPES, key=len, reverse=True):   # « HIDDEN2 », « DASHDOTX2 »...
        if key.startswith(known):
            return known
    return "continuous"


def _int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _weight(value) -> float | None:
    """Epaisseur DXF (centiemes de mm ; -1 calque, -2 bloc, -3 defaut) -> unites du board, None = ByLayer."""
    try:
        value = int(value)
    except (TypeError, ValueError):
        return None
    if value in (-1, -2):
        return None
    return 0.0 if value < 0 else value / 100.0 * model.UNITS_PER_MM


def _layers(doc, report: dict) -> tuple[dict, dict]:
    cad = cad_model.empty_cad_page()
    ids = {}
    used = set()
    for entry in doc.layers:
        name = str(entry.dxf.name)
        if name.lower() in used:
            continue
        used.add(name.lower())
        rgb = entry.rgb
        color = _hex(rgb) if rgb is not None else _aci_color(abs(int(entry.dxf.get("color", 7))))
        weight = _weight(entry.dxf.get("lineweight", -3))
        layer = {"name": name, "visible": not (entry.is_off() or entry.is_frozen()), "locked": entry.is_locked(),
                 "color": color, "linetype": _linetype(entry.dxf.get("linetype")),
                 "lineweight": 0.0 if weight is None else weight}
        if name == "0":
            cad["layers"][0].update(layer, name="0")
            ids[name.lower()] = cad_model.LAYER0
            continue
        layer["id"] = cad_model.new_layer_id(cad)
        cad["layers"].append({**cad_model.LAYER_DEFAULTS, **layer})
        ids[name.lower()] = layer["id"]
    current = str(doc.header.get("$CLAYER", "0")).lower()
    cad["current"] = ids.get(current, cad_model.LAYER0)
    try:
        cad["ltscale"] = max(1e-6, float(doc.header.get("$LTSCALE", 1.0)))
    except (TypeError, ValueError):
        pass
    report["layers"] = len(cad["layers"])
    return cad, ids


def _ellipse(entity):
    """Ellipse a parametres normalises (outil d'ezdxf) : debut / fin au-dela de 2π (1,57 -> 7,85, ellipse complete,
    vu dans des blocs de DWG) ne donnaient AUCUN point a `flattening` ; l'eclatement d'ezdxf les normalisait."""
    from ezdxf.math import ConstructionEllipse
    dxf = entity.dxf
    start, end = float(dxf.start_param), float(dxf.end_param)
    span = (end - start) % math.tau
    if math.isclose(span, 0.0, abs_tol=1e-9) or math.isclose(span, math.tau, abs_tol=1e-9):
        start, end = 0.0, math.tau                          # ellipse complete
    else:
        start %= math.tau
        end = start + span
    return ConstructionEllipse(dxf.center, dxf.major_axis, dxf.get("extrusion", (0.0, 0.0, 1.0)), dxf.ratio,
                               start, end)


def _points(entity, tolerance: float):
    """Polylignes (listes de points 2D du dessin) qui suivent l'entite."""
    kind = entity.dxftype()
    if kind == "LINE":
        a, b = entity.dxf.start, entity.dxf.end
        return [[(a.x, a.y), (b.x, b.y)]]
    if kind in ("ARC", "CIRCLE", "ELLIPSE", "SPLINE"):     # points SUR la courbe (pas sur son approximation)
        if kind in ("ARC", "CIRCLE"):
            size = 2 * math.pi * float(entity.dxf.radius)
        elif kind == "SPLINE":
            cvs = entity.construction_tool().control_points
            size = sum(math.dist((a.x, a.y), (b.x, b.y)) for a, b in zip(cvs, cvs[1:]))
        else:
            size = 2 * math.pi * float(entity.dxf.major_axis.magnitude)
        curve = _ellipse(entity) if kind == "ELLIPSE" else entity
        pts = [(v.x, v.y) for v in curve.flattening(max(tolerance, size / MAX_SEGMENTS / 4.0))]
        return [pts] if len(pts) >= 2 else []
    from ezdxf import path as ezpath
    path = ezpath.make_path(entity)
    out = []
    for sub in path.sub_paths() if path.has_sub_paths else [path]:
        if len(sub) == 0:
            continue
        cvs = sub.control_vertices()
        length = sum(math.dist((a.x, a.y), (b.x, b.y)) for a, b in zip(cvs, cvs[1:]))
        distance = max(tolerance, length / MAX_SEGMENTS / 4.0)      # tres grande courbe : nombre de lignes borne
        pts = [(v.x, v.y) for v in sub.flattening(distance, segments=4)]
        if len(pts) >= 2:
            out.append(pts)
    return out


def _native(entity, scale: float):
    """ARC, CIRCLE, LWPOLYLINE -> la VRAIE entite du module CAD (type, champs geometriques) ; None = approchee par des
    lignes (ellipses, splines, entites hors du plan XY ou retournees : extrusion autre que +Z)."""
    kind = entity.dxftype()
    if kind not in ("ARC", "CIRCLE", "LWPOLYLINE"):
        return None
    extrusion = entity.dxf.get("extrusion", None)
    if extrusion is not None and (abs(extrusion[0]) > 1e-9 or abs(extrusion[1]) > 1e-9 or extrusion[2] < 0):
        return None
    if kind in ("ARC", "CIRCLE"):
        c = entity.dxf.center
        geometry = {"center": [c.x * scale, c.y * scale], "radius": float(entity.dxf.radius) * scale}
        if geometry["radius"] <= 0:
            return None
        if kind == "CIRCLE":
            return "cad_circle", geometry
        geometry.update(start=float(entity.dxf.start_angle), end=float(entity.dxf.end_angle))
        return "cad_arc", geometry
    vertices = [[x * scale, y * scale, float(b)] for x, y, b in entity.get_points("xyb")]
    if len(vertices) < 2:
        return None
    return "cad_pline", {"vertices": vertices, "closed": bool(entity.closed)}


def _hatch(entity, tolerance: float):
    """HATCH -> champs d'un `cad_hatch` en unites du DESSIN (None = rien a remplir, ou hachure hors du plan XY) et la
    vraie couleur a lui donner (degrade : sa 1re couleur, le module n'a que le plein). Contours : chemins du HATCH
    (polylignes, aretes droites, arcs, ellipses, splines) decoupes a `tolerance` pres ; motif : ses familles de traits
    telles qu'AutoCAD les ecrit (deja tournees et mises a l'echelle), ramenees au repere de la hachure."""
    from ezdxf import path as ezpath
    extrusion = entity.dxf.get("extrusion", (0.0, 0.0, 1.0))
    if abs(extrusion[0]) > 1e-9 or abs(extrusion[1]) > 1e-9:
        return None
    loops = []
    for sub in ezpath.from_hatch(entity):
        cvs = sub.control_vertices()
        if len(cvs) < 3:
            continue
        length = sum(math.dist((a.x, a.y), (b.x, b.y)) for a, b in zip(cvs, cvs[1:]))
        pts = [[v.x, v.y] for v in sub.flattening(max(tolerance, length / MAX_SEGMENTS / 4.0), segments=4)]
        loops.append(pts)
    loops = cad_hatch.clean_loops(loops)
    if not loops:
        return None
    flip = extrusion[2] < 0                                 # repere objet retourne : X oppose
    rgb = None
    geometry = {"loops": loops, "hatch_angle": 0.0, "hatch_origin": [0.0, 0.0], "hatch_lines": [], "hatch_name": "",
                "hatch_alpha": 100.0}
    lines = entity.pattern.lines if (not entity.dxf.solid_fill and entity.pattern is not None) else []
    if entity.gradient is not None or entity.dxf.solid_fill or not lines:
        geometry.update(hatch_pattern="solid", hatch_spacing=cad_hatch.DEFAULTS["hatch_spacing"])
        gradient = entity.gradient
        if gradient is not None:                            # degrade : ses deux couleurs, sa forme, son angle
            rgb = tuple(gradient.color1)
            if gradient.one_color:                          # une couleur + teinte (0 = noir, 1 = blanc)
                tint = float(gradient.tint)
                target, k = ((255, 255, 255), (tint - 0.5) * 2.0) if tint >= 0.5 else ((0, 0, 0), (0.5 - tint) * 2.0)
                second = tuple(int(round(c + (t - c) * k)) for c, t in zip(rgb, target))
            else:
                second = tuple(gradient.color2)
            name = str(gradient.name or "LINEAR").upper()
            geometry.update(hatch_pattern=cad_hatch.GRADIENT, hatch_color2=_hex(second),
                            hatch_gradient=name if name in cad_hatch.GRADIENTS else "LINEAR",
                            hatch_centered=bool(gradient.centered < 0.5),
                            hatch_angle=float(gradient.rotation) % 360.0)        # ezdxf : en degres
        return geometry, rgb
    sign = -1.0 if flip else 1.0

    def point(p):
        return (sign * p[0], p[1])

    def angle(a):
        return (180.0 - a) % 360.0 if flip else a % 360.0
    world = [(angle(line.angle), point(line.base_point), point(line.offset), list(line.dash_length_items))
             for line in lines]
    a0, _base, offset, _dashes = world[0]
    r = math.radians(a0)
    spacing = abs(-offset[0] * math.sin(r) + offset[1] * math.cos(r))      # ecart des traits de la 1re famille
    if spacing <= 1e-12:
        spacing = math.hypot(*offset) or 1.0
    origin = world[0][1]
    pattern_angle = angle(float(entity.dxf.get("pattern_angle", 0.0)))
    geometry.update(hatch_pattern=cad_hatch.DXF, hatch_angle=pattern_angle, hatch_spacing=spacing,
                    hatch_origin=[origin[0], origin[1]], hatch_name=str(entity.dxf.get("pattern_name", "") or ""),
                    hatch_lines=cad_hatch.families_from_world(world, origin, pattern_angle, spacing))
    return geometry, rgb


def _solid(entity):
    """SOLID / TRACE (quadrilatere plein, sommets 1-2-4-3 dans le repere objet) -> champs d'une hachure PLEINE en
    unites du DESSIN ; None si degenere."""
    ocs = entity.ocs()
    points = []
    for index in (0, 1, 3, 2):
        v = entity.dxf.get(f"vtx{index}", None)
        if v is None:
            continue
        w = ocs.to_wcs(v)
        p = [w.x, w.y]
        if not points or math.dist(p, points[-1]) > 1e-12:
            points.append(p)
    if len(points) > 1 and math.dist(points[0], points[-1]) <= 1e-12:
        points.pop()
    loops = cad_hatch.clean_loops([points])
    if not loops or abs(cad_hatch.signed_area(loops[0])) <= 1e-18:
        return None
    return {"loops": loops, "hatch_pattern": "solid", "hatch_angle": 0.0, "hatch_origin": [0.0, 0.0],
            "hatch_spacing": cad_hatch.DEFAULTS["hatch_spacing"], "hatch_alpha": 100.0, "hatch_lines": [],
            "hatch_name": ""}


def _wipeout(entity) -> dict | None:
    """WIPEOUT -> champs d'une hachure « wipeout » (son contour de decoupe), unites du DESSIN ; None si degenere."""
    points = [[p.x, p.y] for p in entity.boundary_path_wcs()]
    if len(points) > 1 and math.dist(points[0], points[-1]) <= 1e-12:
        points.pop()
    loops = cad_hatch.clean_loops([points])
    if not loops or abs(cad_hatch.signed_area(loops[0])) <= 1e-18:
        return None
    return {"loops": loops, "hatch_pattern": cad_hatch.WIPEOUT, "hatch_angle": 0.0, "hatch_origin": [0.0, 0.0],
            "hatch_spacing": cad_hatch.DEFAULTS["hatch_spacing"], "hatch_alpha": 100.0, "hatch_lines": [],
            "hatch_name": ""}


def _image(entity, folder) -> dict | None:
    """IMAGE -> champs d'un `cad_image` (trois coins, fichier resolu depuis le dossier du dessin), unites du DESSIN."""
    image_def = entity.image_def
    if image_def is None:
        return None
    name = str(image_def.dxf.get("filename", "") or "")
    path = Path(name.replace("\\", "/")) if name else None
    if path is not None and not path.is_absolute() and folder is not None:
        path = (Path(folder) / path).resolve()
    if path is not None and not path.exists() and folder is not None:
        local = Path(folder) / Path(name.replace("\\", "/")).name     # image deplacee a cote du dessin
        if local.exists():
            path = local
    size = entity.dxf.image_size
    insert, u, v = entity.dxf.insert, entity.dxf.u_pixel, entity.dxf.v_pixel
    w, h = float(size[0]), float(size[1])
    if w <= 0 or h <= 0:
        return None
    return {"path": str(path) if path is not None else "", "pos": [insert[0], insert[1]],
            "pu": [insert[0] + u[0] * w, insert[1] + u[1] * w], "pv": [insert[0] + v[0] * h, insert[1] + v[1] * h],
            "fade": float(entity.dxf.get("fade", 0) or 0)}


def _face_edges(entity) -> list:
    """3DFACE -> ses aretes VISIBLES (drapeaux 1, 2, 4, 8 = arete 1..4 invisible), vues de dessus (Z ignore)."""
    pts = [entity.dxf.get(f"vtx{i}", None) for i in range(4)]
    pts = [(p.x, p.y) for p in pts if p is not None]
    flags = int(entity.dxf.get("invisible_edges", 0) or 0)
    runs = []
    for i in range(len(pts)):
        a, b = pts[i], pts[(i + 1) % len(pts)]
        if not flags & (1 << i) and math.dist(a, b) > 1e-12:
            runs.append([a, b])
    return runs


FONT_NAMES = {"arial": "Arial", "arialn": "Arial Narrow", "arialbd": "Arial", "times": "Times New Roman",
              "cour": "Courier New", "calibri": "Calibri", "verdana": "Verdana", "tahoma": "Tahoma",
              "swiss": "Swis721 BT", "swisscl": "Swis721 Cn BT", "agencyr": "Agency FB", "isocp": "ISOCPEUR",
              "gost_common": "GOST Common", "simplex": "", "romans": "", "txt": "", "isocp.shx": ""}


def _font_of(entity) -> str:
    """Police du style de texte de l'entite (fichier .ttf -> nom de famille ; police SHX d'AutoCAD : « » = celle du
    module)."""
    doc = getattr(entity, "doc", None)
    if doc is None:
        return ""
    try:
        style = doc.styles.get(entity.dxf.get("style", "Standard"))
        font = str(style.dxf.get("font", "") or "") if style is not None else ""
    except Exception:                                       # noqa: BLE001 - style absent
        return ""
    if not font or font.lower().endswith(".shx") or "." not in font and not font:
        return ""
    stem = font.rsplit(".", 1)[0] if font.lower().endswith((".ttf", ".otf", ".ttc")) else font
    if font.lower().endswith(".shx"):
        return ""
    known = FONT_NAMES.get(stem.lower())
    if known is not None:
        return known
    return stem.replace("_", " ")


def _text(entity, scale: float, allow_empty: bool = False):
    """TEXT / MTEXT -> champs d'un `cad_text` (texte sans codes de mise en forme) ; None = texte vide."""
    kind = entity.dxftype()
    if kind in ("TEXT", "ATTRIB", "ATTDEF"):                # (un attribut de bloc est un TEXT)
        text = entity.plain_text()
        align, p1, p2 = entity.get_placement()
        name = getattr(align, "name", str(align))
        point = p1 if name in ("LEFT", "ALIGNED", "FIT") or p2 is None else p2
        values = {"text": text, "pos": [point.x * scale, point.y * scale], "rot": float(entity.dxf.get("rotation", 0.0)),
                  "height": float(entity.dxf.get("height", 1.0)) * scale, "justify": ALIGN_CODES.get(name, "L"),
                  "mtext": False}
    else:
        text = entity.plain_text(split=False)
        point = entity.dxf.get("insert", (0.0, 0.0, 0.0))
        values = {"text": text.replace("\r\n", "\n"), "pos": [point[0] * scale, point[1] * scale],
                  "rot": float(entity.get_rotation()), "height": float(entity.dxf.get("char_height", 1.0)) * scale,
                  "width": max(0.0, float(entity.dxf.get("width", 0.0) or 0.0)) * scale,
                  "justify": ATTACH_CODES.get(int(entity.dxf.get("attachment_point", 1)), "TL"),
                  "spacing": float(entity.dxf.get("line_spacing_factor", 1.0) or 1.0), "mtext": True}
    if (not values["text"].strip() and not allow_empty) or values["height"] <= 0:
        return None
    font = _font_of(entity)
    if font:
        values["font"] = font
    return values


# -- eclatement des blocs et des cotes ----------------------------------------------------------------------------------
# Une entite convertie = un ENREGISTREMENT (genre, geometrie en unites du DESSIN, proprietes brutes) ; genre « runs » =
# polylignes de points (LINE, courbes approchees), sinon le type d'entite du module (`cad_arc`, `cad_text`...).
# Un bloc est converti UNE fois dans son repere, puis pose a chaque insertion par sa matrice (rotation, echelle
# uniforme, symetrie) : `virtual_entities` d'ezdxf recopiait toutes ses entites a chaque insertion (mesure, DWG de
# 54 000 insertions : 2,3 s sur 4,1 s de conversion). Insertion qui deforme les cercles (echelle non uniforme), hors du
# plan, texte en miroir, bloc absent ou qui s'insere lui-meme : eclatement d'ezdxf, comme avant.
MAX_DEPTH = 16                             # blocs / cotes imbriques au-dela : ignores (comptes)


def _attrs(entity) -> tuple:
    """(calque, couleur ACI, vraie couleur, epaisseur, type de ligne, echelle du type) BRUTS de l'entite."""
    dxf = entity.dxf
    return (str(dxf.get("layer", "0")), int(dxf.get("color", 256)), entity.rgb, dxf.get("lineweight", -1),
            str(dxf.get("linetype", "BYLAYER")), float(dxf.get("ltscale", 1.0) or 1.0))


def _inherit(attrs: tuple, parent: tuple) -> tuple:
    """Entite d'un bloc / d'une cote : calque 0 -> celui de l'insertion, couleur PARBLOC (0) -> celle de l'insertion."""
    if attrs[0] != "0" and attrs[1] != 0:
        return attrs
    return (parent[0] if attrs[0] == "0" else attrs[0], parent[1] if attrs[1] == 0 else attrs[1]) + attrs[2:]


def _similarity(m):
    """Matrice d'insertion (ezdxf : lignes = axes, puis l'origine) -> (a, b, c, d, tx, ty, echelle, miroir), x' = a x +
    b y + tx, y' = c x + d y + ty, quand elle garde le plan XY et la forme des cercles ; sinon None."""
    ux, uy, uz, origin = m.get_row(0), m.get_row(1), m.get_row(2), m.get_row(3)
    a, c, b, d = ux[0], ux[1], uy[0], uy[1]
    lx, ly = math.hypot(a, c), math.hypot(b, d)
    if lx <= 1e-12 or ly <= 1e-12:
        return None
    lz = max(1.0, math.hypot(uz[0], uz[1], uz[2]))
    if (abs(ux[2]) > 1e-9 * lx or abs(uy[2]) > 1e-9 * ly or abs(uz[0]) > 1e-9 * lz or abs(uz[1]) > 1e-9 * lz
            or abs(lx - ly) > 1e-9 * lx or abs(a * b + c * d) > 1e-9 * lx * ly):
        return None
    return a, b, c, d, origin[0], origin[1], lx, a * d - b * c < 0


def _direction(t, degrees: float) -> float:
    """Angle (degres) d'une direction apres la transformation `t`."""
    a, b, c, d = t[:4]
    r = math.radians(degrees)
    x, y = math.cos(r), math.sin(r)
    return math.degrees(math.atan2(c * x + d * y, a * x + b * y)) % 360.0


def _arc_span(start: float, end: float) -> float:
    from ezdxf.math import arc_angle_span_deg          # arc complet : angles gardes (comme `Arc.transform`)
    return arc_angle_span_deg(start, end)


def _transform(record: tuple, t) -> tuple | None:
    """Enregistrement d'un bloc pose par la transformation `t` (`_similarity`) ; None = texte en miroir (ezdxf)."""
    kind, geometry, attrs = record
    a, b, c, d, tx, ty, scale, mirrored = t
    if kind == "runs":
        return kind, [[(a * x + b * y + tx, c * x + d * y + ty) for x, y in run] for run in geometry], attrs
    out = dict(geometry)
    if kind in ("cad_circle", "cad_arc"):
        x, y = geometry["center"]
        out["center"] = [a * x + b * y + tx, c * x + d * y + ty]
        out["radius"] = geometry["radius"] * scale
        if kind == "cad_arc" and not math.isclose(_arc_span(geometry["start"], geometry["end"]), 360.0):
            start, end = _direction(t, geometry["start"]), _direction(t, geometry["end"])
            out["start"], out["end"] = (end, start) if mirrored else (start, end)     # sens trigonometrique garde
    elif kind == "cad_pline":
        sign = -1.0 if mirrored else 1.0
        out["vertices"] = [[a * x + b * y + tx, c * x + d * y + ty, bulge * sign] for x, y, bulge in geometry["vertices"]]
    elif kind == "cad_text":
        if mirrored:
            return None
        x, y = geometry["pos"]
        out["pos"] = [a * x + b * y + tx, c * x + d * y + ty]
        out["rot"] = geometry["rot"] + math.degrees(math.atan2(c, a))
        out["height"] = geometry["height"] * scale
        if "width" in geometry:
            out["width"] = geometry["width"] * scale
    elif kind == "cad_point":
        x, y = geometry["pos"]
        out["pos"] = [a * x + b * y + tx, c * x + d * y + ty]          # figure : taille du dessin (PDSIZE), droite
    elif kind == "cad_image":
        for key in ("pos", "pu", "pv"):
            x, y = geometry[key]
            out[key] = [a * x + b * y + tx, c * x + d * y + ty]
    elif kind in ("cad_xline", "cad_ray"):
        for key in ("p1", "p2"):
            x, y = geometry[key]
            out[key] = [a * x + b * y + tx, c * x + d * y + ty]
    elif kind == "cad_hatch":
        out["loops"] = [[[a * x + b * y + tx, c * x + d * y + ty] for x, y in loop] for loop in geometry["loops"]]
        x, y = geometry["hatch_origin"]
        out["hatch_origin"] = [a * x + b * y + tx, c * x + d * y + ty]
        out["hatch_angle"] = _direction(t, geometry["hatch_angle"])
        out["hatch_spacing"] = geometry["hatch_spacing"] * scale
        if mirrored and geometry["hatch_lines"]:
            out["hatch_lines"] = cad_hatch.flipped_families(geometry["hatch_lines"])
    return kind, out, attrs


def _scaled(kind: str, geometry: dict, scale: float) -> dict:
    """Geometrie en unites du dessin -> unites du board."""
    out = dict(geometry)
    if kind in ("cad_circle", "cad_arc"):
        out["center"] = [geometry["center"][0] * scale, geometry["center"][1] * scale]
        out["radius"] = geometry["radius"] * scale
    elif kind == "cad_pline":
        out["vertices"] = [[x * scale, y * scale, bulge] for x, y, bulge in geometry["vertices"]]
    elif kind == "cad_text":
        out["pos"] = [geometry["pos"][0] * scale, geometry["pos"][1] * scale]
        out["height"] = geometry["height"] * scale
        if "width" in geometry:
            out["width"] = geometry["width"] * scale
    elif kind == "cad_insert":
        out["pos"] = [geometry["pos"][0] * scale, geometry["pos"][1] * scale]
    elif kind == "cad_image":
        for key in ("pos", "pu", "pv"):
            out[key] = [geometry[key][0] * scale, geometry[key][1] * scale]
    elif kind in ("cad_xline", "cad_ray"):
        for key in ("p1", "p2"):
            out[key] = [geometry[key][0] * scale, geometry[key][1] * scale]
    elif kind == "cad_point":
        out["pos"] = [geometry["pos"][0] * scale, geometry["pos"][1] * scale]
        out["pdsize"] = cad_point.DEFAULTS["pdsize"] if geometry.get("pdsize") is None else geometry["pdsize"] * scale
    elif kind == "cad_hatch":
        out["loops"] = [[[x * scale, y * scale] for x, y in loop] for loop in geometry["loops"]]
        out["hatch_origin"] = [geometry["hatch_origin"][0] * scale, geometry["hatch_origin"][1] * scale]
        out["hatch_spacing"] = geometry["hatch_spacing"] * scale
    return out


def _dynamic_source(layout) -> str | None:
    """Bloc anonyme (*U…) d'une reference de bloc DYNAMIQUE : nom du bloc dynamique d'origine (XDATA
    « AcDbBlockRepBTag » de l'enregistrement du bloc : poignee de l'original) ; None = bloc ordinaire."""
    try:
        record = layout.block_record
        for _ in range(8):                                  # chaine de variantes anonymes jusqu'au bloc nomme
            if not record.has_xdata("AcDbBlockRepBTag"):
                return None
            handle = next((v for c, v in record.get_xdata("AcDbBlockRepBTag") if c == 1005), None)
            original = record.doc.entitydb.get(handle) if handle else None
            if original is None or original is record:
                return None
            name = str(original.dxf.name)
            if not name.startswith("*"):
                return name
            record = original
    except Exception:                                       # noqa: BLE001 - donnees abimees : bloc ordinaire
        return None
    return None


class _Collector:
    """Enregistrements de l'espace objet, blocs et cotes eclates ; blocs convertis une fois (`blocks`)."""

    def __init__(self, point_style: dict | None = None, native_blocks: bool = False, folder=None):
        self.folder = folder                    # dossier du dessin : chemins relatifs des images
        self.point_style = dict(point_style or {"pdmode": 0, "pdsize": None})   # PDMODE / PDSIZE du dessin
        self.native = native_blocks             # insertions gardees en references (`cad_insert`)
        self.definitions: dict = {}             # nom -> (enregistrements du bloc, point de base) des blocs references
        self.blocks: dict = {}          # nom -> [(tolerance, depend de la tolerance, enregistrements, ignores)]
        self.busy: set = set()          # blocs en cours de conversion (bloc qui s'insere lui-meme)
        self.attdef_records: dict = {}  # nom -> definitions d'attributs (blocs gardes en blocs)
        self.dynamic: dict = {}         # nom d'un bloc anonyme (*U…) -> nom du bloc dynamique dont il est une variante

    def collect(self, entities, tol: float, depth: int, out: list, ignored: dict) -> bool:
        """Enregistrements des `entities` ajoutes a `out` (types ignores comptes dans `ignored`) ; vrai si l'un
        depend de la tolerance (courbe approchee par des lignes)."""
        needs = False
        for entity in entities:
            kind = entity.dxftype()
            if kind == "INSERT" and depth < MAX_DEPTH:
                needs |= self.insert(entity, tol, depth, out, ignored)
                continue
            if kind in EXPLODED and depth < MAX_DEPTH:
                try:
                    parts = list(entity.virtual_entities())
                except Exception:                           # noqa: BLE001 - cote abimee : ignoree
                    ignored[kind] = ignored.get(kind, 0) + 1
                    continue
                needs |= self.collect_parts(parts, _attrs(entity), tol, depth, out, ignored)
                continue
            if kind == "POLYLINE" and depth < MAX_DEPTH and entity.get_mode() in ("AcDbPolyFaceMesh",
                                                                                  "AcDbPolygonMesh"):
                try:                                        # maillage : ses faces (3DFACE)
                    parts = list(entity.virtual_entities())
                except Exception:                           # noqa: BLE001 - maillage abime : ignore
                    ignored[kind] = ignored.get(kind, 0) + 1
                    continue
                needs |= self.collect_parts(parts, _attrs(entity), tol, depth, out, ignored)
                continue
            if (kind not in CURVES and kind not in TEXTS and kind not in SOLIDS and kind not in FACES
                    and kind not in POINTS and kind not in MASKS and kind not in IMAGES and kind not in INFINITE
                    and kind != "HATCH"):
                ignored[kind] = ignored.get(kind, 0) + 1
                continue
            attrs = _attrs(entity)
            try:
                if kind in POINTS:
                    p = entity.dxf.location
                    out.append(("cad_point", {"pos": [p.x, p.y], **self.point_style}, attrs))
                    continue
                if kind in INFINITE:
                    s, u = entity.dxf.start, entity.dxf.unit_vector
                    out.append((INFINITE[kind], {"p1": [s.x, s.y], "p2": [s.x + u.x, s.y + u.y]}, attrs))
                    continue
                if kind in MASKS or kind in IMAGES:
                    found = _wipeout(entity) if kind in MASKS else _image(entity, self.folder)
                    if found is None:
                        ignored[kind] = ignored.get(kind, 0) + 1
                    else:
                        out.append(("cad_hatch" if kind in MASKS else "cad_image", found, attrs))
                    continue
                if kind in SOLIDS:
                    found = _solid(entity)
                    if found is None:
                        ignored[kind] = ignored.get(kind, 0) + 1
                    else:
                        out.append(("cad_hatch", found, attrs))
                    continue
                if kind in FACES:
                    runs = _face_edges(entity)
                    if runs:
                        out.append(("runs", runs, attrs))
                    continue
                if kind == "HATCH":
                    found = _hatch(entity, tol)
                    if found is None:
                        ignored[kind] = ignored.get(kind, 0) + 1
                        continue
                    geometry, rgb = found
                    if rgb is not None:                     # degrade : sa 1re couleur
                        attrs = attrs[:2] + (rgb,) + attrs[3:]
                    out.append(("cad_hatch", geometry, attrs))
                    needs = True                            # contours courbes decoupes a la tolerance
                    continue
                if kind in TEXTS:
                    native = _text(entity, 1.0)
                    if native is None:
                        continue
                    record = ("cad_text", native)
                else:
                    native = _native(entity, 1.0)
                    record = native if native is not None else ("runs", _points(entity, tol))
            except Exception:                               # noqa: BLE001 - courbe degeneree
                ignored[kind] = ignored.get(kind, 0) + 1
                continue
            if record[0] == "runs" and kind != "LINE":
                needs = True
            out.append(record + (attrs,))
        return needs

    def collect_parts(self, parts, parent: tuple, tol: float, depth: int, out: list, ignored: dict) -> bool:
        sub: list = []
        needs = self.collect(parts, tol, depth + 1, sub, ignored)
        out.extend((kind, geometry, _inherit(attrs, parent)) for kind, geometry, attrs in sub)
        return needs

    def insert(self, insert, tol: float, depth: int, out: list, ignored: dict) -> bool:
        needs = False
        if int(insert.dxf.get("row_count", 1) or 1) * int(insert.dxf.get("column_count", 1) or 1) > 1:
            try:                                            # MINSERT : chaque case de la grille
                cells = list(insert.multi_insert())
            except Exception:                               # noqa: BLE001 - grille abimee : la 1re case seule
                cells = []
            if cells:
                for cell in cells:
                    needs |= self._insert_one(cell, tol, depth, out, ignored)
                return needs
        return self._insert_one(insert, tol, depth, out, ignored)

    def _insert_one(self, insert, tol: float, depth: int, out: list, ignored: dict) -> bool:
        parent = _attrs(insert)
        try:
            layout = insert.block()
            t = _similarity(insert.matrix44()) if layout is not None else None
        except Exception:                                   # noqa: BLE001 - insertion abimee : eclatement d'ezdxf
            layout = t = None
        if t is not None:
            found = self.block(layout, tol / t[6], depth)
            if found is not None and self.native and not layout.name.upper().startswith("*D"):
                records, block_ignored, needs = found
                name = layout.name
                if name not in self.definitions:
                    try:
                        b = layout.block.dxf.base_point
                        base = (float(b[0]), float(b[1]))
                    except Exception:                       # noqa: BLE001 - point de base absent : l'origine
                        base = (0.0, 0.0)
                    self.definitions[name] = (records + self.attdefs(layout), base)
                    source = _dynamic_source(layout) if name.startswith("*") else None
                    if source:
                        self.dynamic[name] = source
                    for kind, n in block_ignored.items():
                        ignored[kind] = ignored.get(kind, 0) + n
                a, b, c, d, tx, ty, s, mirrored = t
                bx, by = self.definitions[name][1]
                rot = (math.degrees(math.atan2(c, a)) - (180.0 if mirrored else 0.0)) % 360.0
                values = self._attrib_values(insert, self.attdefs(layout), t, out)
                out.append(("cad_insert", {"block": name, "pos": [a * bx + b * by + tx, c * bx + d * by + ty],
                                           "scale": s, "rot": rot, "mirror": bool(mirrored), "attribs": values},
                            parent))
                return needs
        self._attribs(insert, out)
        if t is not None:
            if found is not None:
                records, block_ignored, needs = found
                moved = [_transform(record, t) for record in records]
                if all(record is not None for record in moved):
                    for kind, n in block_ignored.items():
                        ignored[kind] = ignored.get(kind, 0) + n
                    out.extend((kind, geometry, _inherit(attrs, parent)) for kind, geometry, attrs in moved)
                    return needs
        try:
            parts = list(insert.virtual_entities())
        except Exception:                                   # noqa: BLE001 - bloc abime : ignore
            ignored["INSERT"] = ignored.get("INSERT", 0) + 1
            return False
        return self.collect_parts(parts, parent, tol, depth, out, ignored)

    @staticmethod
    def _attribs(insert, out: list):
        """Attributs (ATTRIB) d'une insertion : des textes, deja places (coordonnees de l'insertion), sauf les
        invisibles (drapeau 1)."""
        for attrib in getattr(insert, "attribs", None) or []:
            try:
                if int(attrib.dxf.get("flags", 0)) & 1:
                    continue
                native = _text(attrib, 1.0)
            except Exception:                               # noqa: BLE001 - attribut abime : ignore
                continue
            if native is not None:
                out.append(("cad_text", native, _attrs(attrib)))

    def attdefs(self, layout) -> list:
        """Definitions d'attributs (ATTDEF) d'un bloc garde en bloc : des textes `attdef` (cad_attrib), une fois."""
        name = layout.name
        found = self.attdef_records.get(name)
        if found is not None:
            return found
        found = []
        for entity in layout:
            if entity.dxftype() != "ATTDEF":
                continue
            try:
                native = _text(entity, 1.0, allow_empty=True)
                flags = int(entity.dxf.get("flags", 0))
                tag = str(entity.dxf.get("tag", ""))
                prompt = str(entity.dxf.get("prompt", "") or tag)
            except Exception:                               # noqa: BLE001 - definition abimee : ignoree
                continue
            if native is None or not tag:
                continue
            default = native["text"]
            native["text"] = tag
            native["attdef"] = {"tag": tag, "prompt": prompt, "default": default, "invisible": bool(flags & 1),
                                "constant": bool(flags & 2)}
            found.append(("cad_text", native, _attrs(entity)))
        self.attdef_records[name] = found
        return found

    def _attrib_values(self, insert, attdefs: list, t, out: list) -> dict:
        """Valeurs des attributs (ATTRIB) d'une insertion gardee en reference : {etiquette: valeur} quand l'attribut est
        a la place de sa definition ; deplace (poignee d'AutoCAD), il reste un texte a part (`_attribs`) et la valeur
        de la reference est vide."""
        places = {}
        for record in attdefs:
            moved = _transform(record, t)
            if moved is not None:
                places[record[1]["attdef"]["tag"].upper()] = moved[1]
        values = {}
        for attrib in getattr(insert, "attribs", None) or []:
            try:
                tag = str(attrib.dxf.get("tag", "")).upper()
                native = _text(attrib, 1.0, allow_empty=True)
            except Exception:                               # noqa: BLE001 - attribut abime : ignore
                continue
            if native is None or not tag:
                continue
            place = places.get(tag)
            tol = 1e-3 * max(1.0, native["height"])
            if (place is not None and abs(place["pos"][0] - native["pos"][0]) <= tol
                    and abs(place["pos"][1] - native["pos"][1]) <= tol
                    and abs(place["height"] - native["height"]) <= tol):
                values[tag] = native["text"]
                continue
            values[tag] = ""
            if native["text"].strip() and not int(attrib.dxf.get("flags", 0)) & 1:
                out.append(("cad_text", native, _attrs(attrib)))
        return values

    def block(self, layout, tol: float, depth: int):
        """(enregistrements dans le repere du bloc, ignores, depend de la tolerance) ; None = bloc en cours."""
        name = layout.name
        entries = self.blocks.setdefault(name, [])
        for entry_tol, needs, records, ignored in entries:
            if not needs or abs(entry_tol - tol) <= 0.01 * tol:         # meme finesse a 1 % pres
                return records, ignored, needs
        if name in self.busy:
            return None
        self.busy.add(name)
        try:
            records, ignored = [], {}
            # ATTDEF : definitions d'attributs, jamais dessinees (comme `virtual_entities`)
            needs = self.collect((e for e in layout if e.dxftype() != "ATTDEF"), tol, depth + 1, records, ignored)
        finally:
            self.busy.discard(name)
        entries.append((tol, needs, records, ignored))
        return records, ignored, needs


def _paper_layouts(doc, scale: float) -> list:
    """Presentations (espace papier) du dessin -> `cad_plot` : papier, orientation, marge, et la plus grande fenetre
    (VIEWPORT) : sa zone du dessin et son echelle 1:N. Les objets de l'espace papier (cartouche...) ne sont pas
    importes."""
    from . import cad_plot
    out = []
    for layout in doc.layouts:
        if layout.name.upper() == "MODEL":
            continue
        try:
            dxf = layout.dxf_layout.dxf
            pw, ph = float(dxf.get("paper_width", 0) or 0), float(dxf.get("paper_height", 0) or 0)
            rotation = int(dxf.get("plot_rotation", 0) or 0)
            margin = min(float(dxf.get(k, 0) or 0) for k in ("left_margin", "right_margin", "top_margin",
                                                             "bottom_margin"))
            paper_mm = 1.0 if int(dxf.get("plot_paper_units", 1)) == 1 else 25.4
            viewports = [v for v in layout.viewports() if int(v.dxf.get("id", 0)) != 1]
        except Exception:                                   # noqa: BLE001 - presentation abimee : ignoree
            continue
        if pw <= 0 or ph <= 0:
            continue
        short, long_ = min(pw, ph), max(pw, ph)
        paper = next((k for k, (a, b) in cad_plot.PAPERS.items() if abs(a - short) < 1.0 and abs(b - long_) < 1.0),
                     f"{short:g}x{long_:g}")
        landscape = (pw > ph) != (rotation in (1, 3))
        entry = {"name": layout.name, "paper": paper, "landscape": landscape, "margin": max(0.0, margin),
                 "scale": 0.0, "area": None, "center": True}
        best = None
        for vp in viewports:
            w, h = float(vp.dxf.get("width", 0) or 0), float(vp.dxf.get("height", 0) or 0)
            vh = float(vp.dxf.get("view_height", 0) or 0)
            if w > 0 and h > 0 and vh > 0 and (best is None or w * h > best[0]):
                best = (w * h, w, h, vh, vp.dxf.get("view_center_point", (0.0, 0.0)))
        if best is not None:
            _a, w, h, vh, c = best
            vw = vh * w / h
            entry["area"] = [(c[0] - vw / 2) * scale, (c[1] - vh / 2) * scale, (c[0] + vw / 2) * scale,
                             (c[1] + vh / 2) * scale]
            real_mm = scale * cad_plot.MM_PER_UNIT              # mm reels par unite du dessin
            entry["scale"] = round(real_mm / (h * paper_mm / vh), 6)
        out.append(entry)
    return out


NATIVE_BLOCKS = True           # blocs gardes en BLOCS (references `cad_insert` + definitions) ; pose par l'appli
                               # d'apres le reglage `board_cad_import_blocks` (sinon : eclates, comme avant)


def read_drawing(path, native_blocks: bool | None = None) -> tuple[dict, dict]:
    """(donnees de board, compte rendu) : `{"lines", "layers", "units", "ignored": {type: nombre}, "source"}` ;
    `native_blocks` (defaut : `NATIVE_BLOCKS`) : insertions gardees en references de blocs."""
    if native_blocks is None:
        native_blocks = NATIVE_BLOCKS
    path = Path(path)
    doc = _read(path)
    report = {"source": path.name, "lines": 0, "ignored": {}}
    cad, ids = _layers(doc, report)
    try:
        insunits = int(doc.header.get("$INSUNITS", 0))
    except (TypeError, ValueError):
        insunits = 0
    scale = UNIT_SCALE.get(insunits, 1.0)
    report["units"] = UNIT_NAMES.get(insunits, f"unités ({insunits})")
    if insunits in DRAWING_UNITS:                       # le dessin s'affiche et se saisit dans l'unite du fichier
        cad["overrides"] = {"board_cad_unit": DRAWING_UNITS[insunits]}
    tolerance = TOLERANCE / scale
    items, hatches = [], []
    low = [math.inf, math.inf]
    high = [-math.inf, -math.inf]
    records: list = []
    try:
        pdsize = float(doc.header.get("$PDSIZE", 0.0) or 0.0)
    except (TypeError, ValueError):
        pdsize = 0.0
    point_style = {"pdmode": cad_point.clean_mode(doc.header.get("$PDMODE", 0)),
                   "pdsize": pdsize if pdsize > 0 else None}          # 0 / negatif (relatif a l'ecran) : taille du module
    collector = _Collector(point_style, native_blocks, path.parent)
    collector.collect(doc.modelspace(), tolerance, 0, records, report["ignored"])
    styles: dict = {}                                       # proprietes brutes -> valeurs des entites (memes calques)

    def convert(found_records, out_items, out_hatches, bounds: bool, in_block: bool = False):
        for kind, geometry, attrs in found_records:
            values = styles.get((attrs, in_block))
            if values is None:
                layer_name, aci, rgb, weight, linetype, ltscale = attrs
                color = cad_model.BYLAYER
                if rgb is not None:
                    color = _hex(rgb)
                elif aci == 0 and in_block:                 # PARBLOC dans un bloc garde : celle de la reference
                    color = cad_model.BYBLOCK
                elif aci not in (0, 256):
                    color = _aci_color(aci)
                raw_weight = weight
                weight = _weight(weight)
                if weight is None and in_block and _int(raw_weight) == -2:
                    weight = cad_model.BYBLOCK
                values = styles[(attrs, in_block)] = {
                    "layer": ids.get(layer_name.lower(), cad_model.LAYER0), "color": color,
                    "lineweight": cad_model.BYLAYER if weight is None else weight,
                    "linetype": cad_model.BYLAYER if linetype.upper() in ("BYLAYER", "BYBLOCK") else _linetype(linetype),
                    "ltscale": ltscale}
            native, runs = (None, geometry) if kind == "runs" else ((kind, _scaled(kind, geometry, scale)), ())
            if native is not None:
                kind, geometry = native
                item = model.new_item(kind, **{**cad_model.new_entity_values(cad, **geometry), **values})
                (out_hatches if kind == "cad_hatch" and geometry.get("hatch_pattern") != cad_hatch.WIPEOUT
                 else out_items).append(item)                # masque : a sa place dans l ordre du dessin
                if not bounds:
                    continue
                if kind in ("cad_text", "cad_point", "cad_insert"):   # point d'insertion seul (aucune mesure de police
                    x, y = geometry["pos"]                            # hors du fil de l'interface)
                    box = (x, y, x, y)
                elif kind == "cad_hatch":                   # ses contours (pas les milliers de traits du motif)
                    box = cad_hatch.bounds(geometry["loops"])
                elif kind == "cad_image":
                    box = cad_shapes.bounds(cad_image.prims(geometry))
                elif kind in ("cad_xline", "cad_ray"):          # infinie : son point de base seul (zoom etendu)
                    x, y = geometry["p1"]
                    box = (x, y, x, y)
                else:
                    box = cad_shapes.bounds(cad_shapes.prims(kind, geometry))
                low[0], low[1] = min(low[0], box[0]), min(low[1], box[1])
                high[0], high[1] = max(high[0], box[2]), max(high[1], box[3])
            for run in runs:
                for a, b in zip(run, run[1:]):
                    p1 = (a[0] * scale, a[1] * scale)
                    p2 = (b[0] * scale, b[1] * scale)
                    if p1 == p2:
                        continue
                    out_items.append(model.new_item("cad_line", **{**cad_model.new_line_values(cad, p1, p2), **values}))
                    if bounds:
                        for p in (p1, p2):
                            low[0], low[1] = min(low[0], p[0]), min(low[1], p[1])
                            high[0], high[1] = max(high[0], p[0]), max(high[1], p[1])

    convert(records, items, hatches, True)
    if collector.definitions:                               # blocs gardes en blocs (reglage) : leurs definitions
        definitions = {}
        for name, (block_records, base) in collector.definitions.items():
            own, own_hatches = [], []
            convert(block_records, own, own_hatches, False, in_block=True)
            entities = []
            for entity in own_hatches + own:
                entity = {k: v for k, v in entity.items() if k not in ("id", "x", "y", "z", "locked", "link")}
                entities.append(entity)
            definitions[name] = {"base": [base[0] * scale, base[1] * scale], "items": entities}
            if name in collector.dynamic:
                definitions[name]["dynamic"] = collector.dynamic[name]
        cad["blocks"] = definitions
        report["blocks"] = len(definitions)
    try:
        layouts = _paper_layouts(doc, scale)
    except Exception:                                       # noqa: BLE001 - presentations illisibles : ignorees
        layouts = []
    if layouts:
        cad["layouts"] = layouts
        cad["layout"] = layouts[0]["name"]
        report["layouts"] = len(layouts)
    items = hatches + items                                 # hachures DERRIERE le reste (remplissages pleins)
    report["lines"] = len(items)
    data = model.empty_board()
    data["page"]["cad"] = cad
    data["view"] = {}                                       # vue d'ensemble a l'ouverture
    if items:
        extent = max(high[0] - low[0], high[1] - low[1], 1.0)
        fit = FIT_PX / extent                               # grand dessin : le zoom doit pouvoir tout montrer
        low_zoom, _high = model.zoom_limits(data["page"])
        if fit / 2.0 < low_zoom:
            data["page"]["zoom_min"] = max(model.ZOOM_RANGE[0], fit / 2.0)
    data["items"] = items
    data["foreign"] = []
    return data, report


def open_drawing(path, native_blocks: bool | None = None) -> tuple[dict, dict]:
    """(donnees de board NORMALISEES, compte rendu) : pretes pour `BoardPane.open_import(normalized=True)`. Copie du
    cache disque si le dessin n'a pas change (`cad_cache` : ni ODA, ni ezdxf, ni conversion ; compte rendu
    `cached` vrai), sinon lecture puis copie gardee. Hors du fil de l'interface (aucun Qt)."""
    from . import cad_cache
    if native_blocks is None:
        native_blocks = NATIVE_BLOCKS
    key = cad_cache.entry(path)                     # avant la lecture : dessin modifie pendant = copie perimee
    if key is not None and native_blocks:
        key = (key[0], key[1].replace(cad_cache.SUFFIX, "-blocs" + cad_cache.SUFFIX))
    found = cad_cache.load(key)
    if found is not None:
        data, report = found
        report["cached"] = True
        return data, report
    data, report = read_drawing(path, native_blocks)
    data = model.normalize(data)                    # ici, pas sur le fil de l'interface (~1 s a 40 000 lignes)
    cad_cache.store(key, data, report)
    return data, report


def describe(report: dict) -> str:
    """Compte rendu en une ligne pour la barre d'etat."""
    text = f"{report['source']} : {report['lines']} objet(s), {report['layers']} calques ({report['units']})"
    if report.get("cached"):
        text += ", copie convertie gardée"
    ignored = report.get("ignored") or {}
    if ignored:
        parts = ", ".join(f"{n} {kind.lower()}" for kind, n in sorted(ignored.items(), key=lambda kv: -kv[1]))
        text += f" ; ignorés (pas encore dans le module CAD) : {parts}"
    return text
