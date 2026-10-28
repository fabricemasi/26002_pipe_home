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
- IGNORE (compte rendu) : hachures, points, solides, images, objets 3D...
Lecture faite hors du fil de l'interface par l'appelant (`read_drawing` n'utilise pas Qt)."""
from __future__ import annotations

import math
from pathlib import Path

from . import cad_model, cad_shapes
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
EXPLODED = {"INSERT", "DIMENSION", "ARC_DIMENSION", "LARGE_RADIAL_DIMENSION", "LEADER"}
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
        pts = [(v.x, v.y) for v in entity.flattening(max(tolerance, size / MAX_SEGMENTS / 4.0))]
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


def _text(entity, scale: float):
    """TEXT / MTEXT -> champs d'un `cad_text` (texte sans codes de mise en forme) ; None = texte vide."""
    kind = entity.dxftype()
    if kind == "TEXT":
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
    if not values["text"].strip() or values["height"] <= 0:
        return None
    return values


def _entities(space, depth: int = 0):
    """Entites de l'espace objet, blocs et cotes eclates (calque 0 / couleur PARBLOC -> ceux de l'insertion)."""
    for entity in space:
        kind = entity.dxftype()
        if kind in EXPLODED and depth < 16:
            try:
                parts = list(entity.virtual_entities())
            except Exception:                               # noqa: BLE001 - bloc abime : ignore
                yield entity, None
                continue
            for part, parent in _entities(parts, depth + 1):
                if part.dxf.get("layer", "0") == "0":
                    part.dxf.layer = entity.dxf.get("layer", "0")
                if part.dxf.get("color", 256) == 0:
                    part.dxf.color = entity.dxf.get("color", 256)
                yield part, parent if parent is not None else kind
            continue
        yield entity, None


def read_drawing(path) -> tuple[dict, dict]:
    """(donnees de board, compte rendu) : `{"lines", "layers", "units", "ignored": {type: nombre}, "source"}`."""
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
    items = []
    low = [math.inf, math.inf]
    high = [-math.inf, -math.inf]
    for entity, _parent in _entities(doc.modelspace()):
        kind = entity.dxftype()
        if kind not in CURVES and kind not in TEXTS:
            report["ignored"][kind] = report["ignored"].get(kind, 0) + 1
            continue
        try:
            if kind in TEXTS:
                native = _text(entity, scale)
                if native is None:
                    continue
                native, runs = ("cad_text", native), []
            else:
                native = _native(entity, scale)
                runs = [] if native is not None else _points(entity, tolerance)
        except Exception:                                   # noqa: BLE001 - courbe degeneree
            report["ignored"][kind] = report["ignored"].get(kind, 0) + 1
            continue
        layer = ids.get(str(entity.dxf.get("layer", "0")).lower(), cad_model.LAYER0)
        color = cad_model.BYLAYER
        aci = int(entity.dxf.get("color", 256))
        if entity.rgb is not None:
            color = _hex(entity.rgb)
        elif aci not in (0, 256):
            color = _aci_color(aci)
        weight = _weight(entity.dxf.get("lineweight", -1))
        linetype = str(entity.dxf.get("linetype", "BYLAYER"))
        values = {"layer": layer, "color": color,
                  "lineweight": cad_model.BYLAYER if weight is None else weight,
                  "linetype": cad_model.BYLAYER if linetype.upper() in ("BYLAYER", "BYBLOCK") else _linetype(linetype),
                  "ltscale": float(entity.dxf.get("ltscale", 1.0) or 1.0)}
        if native is not None:
            kind, geometry = native
            items.append(model.new_item(kind, **{**cad_model.new_entity_values(cad, **geometry), **values}))
            if kind == "cad_text":                      # point d'insertion seul : aucune mesure de police hors du fil de l'interface
                x, y = geometry["pos"]
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
                items.append(model.new_item("cad_line", **{**cad_model.new_line_values(cad, p1, p2), **values}))
                for p in (p1, p2):
                    low[0], low[1] = min(low[0], p[0]), min(low[1], p[1])
                    high[0], high[1] = max(high[0], p[0]), max(high[1], p[1])
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


def describe(report: dict) -> str:
    """Compte rendu en une ligne pour la barre d'etat."""
    text = f"{report['source']} : {report['lines']} objet(s), {report['layers']} calques ({report['units']})"
    ignored = report.get("ignored") or {}
    if ignored:
        parts = ", ".join(f"{n} {kind.lower()}" for kind, n in sorted(ignored.items(), key=lambda kv: -kv[1]))
        text += f" ; ignorés (pas encore dans le module CAD) : {parts}"
    return text
