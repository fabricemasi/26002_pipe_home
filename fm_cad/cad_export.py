"""Module CAD du board : EXPORT des entites CAD en DXF (ezdxf, licence MIT) et en DWG (ezdxf + ODA File Converter,
outil externe gratuit). Seules les entites CAD (lignes, arcs, cercles, polylignes) et les calques partent ; le reste du board (post-it,
formes, images...) n'a pas d'equivalent CAD et n'est pas exporte.

Correspondances (le modele CAD de la phase 1 n'a que des lignes) :
- ligne -> LINE (coordonnees du DOCUMENT, Y vers le haut comme le DXF), propriete ByLayer gardee ByLayer ;
- calque -> LAYER : nom (caracteres interdits du DXF remplaces), couleur (vraie couleur 24 bits + ACI le plus
  proche pour les lecteurs anciens), type de ligne, epaisseur, visible (calque eteint sinon), verrou ; calque courant
  -> $CLAYER ;
- couleur -> vraie couleur ; epaisseur (unites du document, 1 unite = 1/96 de pouce) -> epaisseur DXF normalisee la
  plus proche (centiemes de mm), 0 (trait fin) -> 0,00 mm ; type de ligne -> LTYPE de meme nom en capitales, motif
  repris en unites du fichier ; echelle globale -> $LTSCALE, echelle propre -> ltscale de l'entite ;
- unites : millimetres (taille reelle, 1 unite = 1/96 de pouce), pouces, ou sans conversion ($INSUNITS) ;
- texte -> TEXT (une entite par ligne, justification gardee) ; texte multiligne -> MTEXT (largeur, point
  d'attache) ; hauteur = hauteur des capitales ; la police n'est pas exportee (style « Standard ») ;
- PERDU : extremites arrondies / border radius (le DXF n'a pas de terminaison par entite).
Fichier ecrit a cote puis renomme (jamais de fichier a moitie ecrit)."""
from __future__ import annotations

import contextlib
import os
import re
import shutil
import tempfile
from pathlib import Path

from . import cad_attrib, cad_block, cad_dims, cad_image, cad_hatch, cad_model, cad_point, cad_shapes, cad_text

UNITS = {                                  # cle -> (libelle, facteur unite du document -> unite du fichier, $INSUNITS)
    "mm": ("Millimètres (taille réelle : 1 unité = 1/96 de pouce)", 25.4 / 96.0, 4),
    "cm": ("Centimètres (taille réelle)", 2.54 / 96.0, 5),
    "m": ("Mètres (taille réelle)", 0.0254 / 96.0, 6),
    "km": ("Kilomètres (taille réelle)", 0.0000254 / 96.0, 7),
    "in": ("Pouces (taille réelle)", 1.0 / 96.0, 1),
    "raw": ("Sans conversion (1 unité du board = 1 unité du fichier)", 1.0, 0),
}
MM_PER_UNIT = 25.4 / 96.0                  # epaisseurs : toujours en mm reels
DXF_VERSION = "R2018"
_BAD_NAME = '<>/\\":;?*|=`'

# Chemin d'ODA File Converter fourni par l'appli (previews._oda_file_converter) ; sinon variable d'environnement,
# PATH, et la recherche d'ezdxf.
ODA_PROVIDER = None


class ExportError(Exception):
    """Export impossible (bibliotheque ou outil absent, ecriture refusee) : message pour l'utilisateur."""


def _ezdxf():
    try:
        import ezdxf
    except ImportError as exc:
        raise ExportError("Le paquet Python « ezdxf » est nécessaire pour exporter en DXF / DWG "
                          "(pip install ezdxf).") from exc
    return ezdxf


def layer_name(name: str) -> str:
    clean = "".join("_" if ch in _BAD_NAME or ord(ch) < 32 else ch for ch in str(name)).strip()
    return clean or "_"


def dxf_lineweight(weight: float) -> int:
    """Epaisseur du document (unites) -> epaisseur DXF normalisee la plus proche (centiemes de mm)."""
    from ezdxf.lldxf.const import VALID_DXF_LINEWEIGHTS
    hundredths = max(0.0, float(weight)) * MM_PER_UNIT * 100.0
    return min(VALID_DXF_LINEWEIGHTS, key=lambda v: abs(v - hundredths))


def _rgb(color: str) -> tuple[int, int, int]:
    text = str(color).lstrip("#")
    if len(text) == 8:                      # #aarrggbb : l'opacite n'a pas d'equivalent
        text = text[2:]
    return int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)


def _nearest_aci(rgb) -> int:
    from ezdxf.colors import DXF_DEFAULT_COLORS, int2rgb
    best, best_d = 7, None
    for index in range(1, 256):
        r, g, b = int2rgb(DXF_DEFAULT_COLORS[index])
        d = (r - rgb[0]) ** 2 + (g - rgb[1]) ** 2 + (b - rgb[2]) ** 2
        if best_d is None or d < best_d:
            best, best_d = index, d
    return best


def _linetype_name(key: str) -> str:
    return "CONTINUOUS" if key == "continuous" else key.upper()


def build_document(cad: dict, lines: list, units: str = "mm", unit: float = 1.0):
    """Document ezdxf : `cad` = page["cad"] normalise (cad_model.page_cad), `lines` = entites [(type, champs
    geometriques, donnees)] (lignes -> LINE, arcs -> ARC, cercles -> CIRCLE, polylignes -> LWPOLYLINE avec leurs
    renflements ; une ligne peut aussi etre donnee (p1, p2, donnees)) ; `unit` = unites du board par unite de mesure du dessin (motifs des types de
    ligne, definis dans cette unite)."""
    ezdxf = _ezdxf()
    _label, factor, insunits = UNITS[units]
    doc = ezdxf.new(DXF_VERSION, setup=False)
    doc.header["$INSUNITS"] = insunits
    doc.header["$MEASUREMENT"] = 0 if units == "in" else 1
    doc.header["$LTSCALE"] = float(cad.get("ltscale", 1.0) or 1.0)
    doc.header["$LWDISPLAY"] = 1
    used = {layer["linetype"] for layer in cad["layers"]}
    used |= {data.get("linetype") for _a, _b, data in lines}
    used |= {e.get("linetype") for d in cad_block.blocks(cad).values() for e in d.get("items") or []}
    for key in sorted(k for k in used if k in cad_model.LINETYPES and k != "continuous"):
        label, pattern = cad_model.LINETYPES[key]
        elements = [float(v) * unit * factor for v in pattern]
        doc.linetypes.add(_linetype_name(key), pattern=[sum(abs(v) for v in elements), *elements],
                          description=label)
    names = {}
    for layer in cad["layers"]:
        name = layer_name(layer["name"])
        base, n = name, 2
        while name.upper() in {v.upper() for v in names.values()}:
            name, n = f"{base}_{n}", n + 1
        names[layer["id"]] = name
        entry = doc.layers.get(name) if doc.layers.has_entry(name) else doc.layers.add(name)
        rgb = _rgb(layer["color"])
        entry.color = _nearest_aci(rgb)
        entry.rgb = rgb
        entry.dxf.linetype = _linetype_name(layer["linetype"])
        entry.dxf.lineweight = dxf_lineweight(layer["lineweight"])
        if not layer.get("visible", True):
            entry.off()
        if layer.get("locked"):
            entry.lock()
    current = cad.get("current")
    if current in names:
        doc.header["$CLAYER"] = names[current]
    def write(space, lines):
        """Entites [(type, champs geometriques, donnees)] dans `space` (espace objet ou un bloc)."""
        for entry in lines:
            if isinstance(entry[0], str):
                kind, geometry, data = entry
            else:
                kind, geometry, data = "cad_line", {"p1": entry[0], "p2": entry[1]}, entry[2]
            attribs = {"layer": names.get(data.get("layer"), "0")}
            color = data.get("color", cad_model.BYLAYER)
            weight = data.get("lineweight", cad_model.BYLAYER)
            if color == cad_model.BYBLOCK:          # entite d'un bloc PARBLOC : couleur 0 d'AutoCAD
                attribs["color"] = 0
                color = cad_model.BYLAYER
            if weight == cad_model.BYBLOCK:
                weight = None
            linetype = data.get("linetype", cad_model.BYLAYER)
            attribs["linetype"] = "BYLAYER" if linetype == cad_model.BYLAYER else _linetype_name(linetype)
            attribs["lineweight"] = -2 if weight is None else (
                -1 if weight == cad_model.BYLAYER else dxf_lineweight(weight))
            scale = float(data.get("ltscale", 1.0) or 1.0)
            if scale != 1.0:
                attribs["ltscale"] = scale
            f = factor
            if kind == "cad_line":
                a, b = geometry["p1"], geometry["p2"]
                entity = space.add_line((a[0] * f, a[1] * f), (b[0] * f, b[1] * f), dxfattribs=attribs)
            elif kind in ("cad_arc", "cad_circle"):
                c = geometry["center"]
                if kind == "cad_circle":
                    entity = space.add_circle((c[0] * f, c[1] * f), geometry["radius"] * f, dxfattribs=attribs)
                else:
                    entity = space.add_arc((c[0] * f, c[1] * f), geometry["radius"] * f, geometry["start"],
                                           geometry["end"], dxfattribs=attribs)
            elif kind == "cad_pline":
                points = [(v[0] * f, v[1] * f, 0.0, 0.0, v[2] if len(v) > 2 else 0.0) for v in geometry["vertices"]]
                entity = space.add_lwpolyline(points, format="xyseb", close=bool(geometry.get("closed")),
                                              dxfattribs=attribs)
            elif kind == "cad_hatch":                # hachures : traits du motif en LINE, remplissage plein en HATCH
                merged = {**data, **geometry}
                loops = cad_hatch.clean_loops(merged.get("loops"))
                made = []
                style = cad_hatch.style_of(merged)
                if style["pattern"] == cad_hatch.WIPEOUT:      # masque : un WIPEOUT par contour
                    for loop in loops:
                        space.add_wipeout([(p[0] * f, p[1] * f) for p in loop], dxfattribs=attribs)
                    continue
                if style["pattern"] == cad_hatch.GRADIENT:     # degrade : HATCH a remplissage degrade
                    hatch = space.add_hatch(color=attribs.get("color", 256), dxfattribs=attribs)
                    for loop in loops:
                        hatch.paths.add_polyline_path([(p[0] * f, p[1] * f) for p in loop], is_closed=True)
                    first = _rgb(color) if color not in (cad_model.BYLAYER, cad_model.BYBLOCK) else (0, 0, 0)
                    hatch.set_gradient(color1=first, color2=_rgb(style["color2"]), rotation=style["angle"],
                                       centered=0.0 if style["centered"] else 1.0, name=style["gradient"])
                    continue
                if style["pattern"] in ("solid", cad_hatch.DXF):  # motif d'AutoCAD importe : un vrai HATCH, son motif
                    hatch = space.add_hatch(color=attribs.get("color", 256), dxfattribs=attribs)   # 256 = ByLayer
                    for loop in loops:
                        hatch.paths.add_polyline_path([(p[0] * f, p[1] * f) for p in loop], is_closed=True)
                    if style["pattern"] == cad_hatch.DXF:
                        from ezdxf.entities.pattern import Pattern, PatternLine
                        hatch.dxf.solid_fill = 0
                        hatch.dxf.pattern_name = style["name"] or "_USER"
                        hatch.dxf.pattern_type = 2                  # motif « personnalise » : sa definition est dans le fichier
                        hatch.dxf.pattern_angle = style["angle"]
                        hatch.pattern = Pattern([PatternLine(a, (b[0] * f, b[1] * f), (o[0] * f, o[1] * f),
                                                             [d * f for d in dashes])
                                                 for a, b, o, dashes in cad_hatch.families_to_world(merged)])
                    made.append(hatch)
                else:
                    for a, b in cad_hatch.pattern_segments(loops, style):
                        made.append(space.add_line((a[0] * f, a[1] * f), (b[0] * f, b[1] * f), dxfattribs=attribs))
                if color != cad_model.BYLAYER:
                    rgb = _rgb(color)
                    for entity in made:
                        entity.dxf.color = _nearest_aci(rgb)
                        if hasattr(entity, "rgb"):
                            entity.rgb = rgb
                continue
            elif kind == "cad_text":                 # texte : TEXT par ligne, ou MTEXT ; attribut : ATTDEF
                attdef = cad_attrib.clean_attdef(data.get("attdef"))
                made = (_attdef_entity(space, {**data, **geometry}, attdef, f, attribs) if attdef
                        else _text_entities(space, {**data, **geometry}, f, attribs))
                if color != cad_model.BYLAYER:
                    rgb = _rgb(color)
                    for entity in made:
                        entity.dxf.color = _nearest_aci(rgb)
                        entity.rgb = rgb
                continue
            elif kind == "cad_dim":                  # cotation : traits (lignes, arc de cote) + texte, a plat
                found = cad_dims.geometry({**data, **geometry})
                made = []
                for prim in found["prims"]:
                    if prim[0] == "segment":
                        a, b = prim[1], prim[2]
                        made.append(space.add_line((a[0] * f, a[1] * f), (b[0] * f, b[1] * f), dxfattribs=attribs))
                    else:
                        c = prim[1]
                        end = prim[3] + prim[4]
                        first, last = (prim[3], end) if prim[4] >= 0 else (end, prim[3])
                        made.append(space.add_arc((c[0] * f, c[1] * f), prim[2] * f, first % 360.0, last % 360.0,
                                                  dxfattribs=attribs))
                text = space.add_text(found["text"], dxfattribs={**attribs, "height": found["text_height"] * f,
                                                                 "rotation": found["text_angle"]})
                from ezdxf.enums import TextEntityAlignment
                text.set_placement((found["text_pos"][0] * f, found["text_pos"][1] * f),
                                   align=TextEntityAlignment.BOTTOM_CENTER)
                made.append(text)
                if color != cad_model.BYLAYER:
                    rgb = _rgb(color)
                    for entity in made:
                        entity.dxf.color = _nearest_aci(rgb)
                        entity.rgb = rgb
                continue
            elif kind == "cad_point":                # point : POINT ; sa figure dans $PDMODE / $PDSIZE (du dernier)
                p = geometry["pos"]
                entity = space.add_point((p[0] * f, p[1] * f), dxfattribs=attribs)
                style = cad_point.style_of(data)
                doc.header["$PDMODE"] = style["pdmode"]
                doc.header["$PDSIZE"] = style["pdsize"] * f
            elif kind in ("cad_xline", "cad_ray"):    # ligne de construction : XLINE / RAY (base + vecteur unitaire)
                from . import cad_xline
                a = geometry["p1"]
                d = cad_xline.direction(geometry)
                add = space.add_xline if kind == "cad_xline" else space.add_ray
                entity = add((a[0] * f, a[1] * f), (d[0], d[1]), dxfattribs=attribs)
            elif kind == "cad_image":                # image referencee : IMAGE + IMAGEDEF (une par fichier)
                entity = _image_entity(doc, space, {**data, **geometry}, f, attribs, image_defs)
                if entity is None:
                    continue
            elif kind == "cad_insert":               # reference de bloc : INSERT (miroir = echelle X negative)
                s = cad_block.style_of({**data, **geometry})
                if s["block"] not in block_names:
                    continue
                entity = space.add_blockref(block_names[s["block"]], (s["pos"][0] * f, s["pos"][1] * f),
                                            dxfattribs={**attribs, "xscale": -s["scale"] if s["mirror"] else s["scale"],
                                                        "yscale": s["scale"], "rotation": s["rot"]})
                values = cad_attrib.values_for(blocks.get(s["block"]), data.get("attribs"))
                if values:                           # valeurs des attributs : ATTRIB places par leurs ATTDEF
                    entity.add_auto_attribs(values)
            else:
                continue
            if color != cad_model.BYLAYER:
                rgb = _rgb(color)
                entity.dxf.color = _nearest_aci(rgb)
                entity.rgb = rgb
    blocks = cad_block.blocks(cad)
    image_defs: dict = {}                                   # fichier -> IMAGEDEF (partagee par ses images)
    block_names = {}
    for name in blocks:                                     # definitions d'abord (une reference doit les trouver)
        clean = cad_block.clean_name(name) or "BLOC"
        base, n = clean, 2
        while clean.upper() in {v.upper() for v in block_names.values()} or clean.upper() in ("*MODEL_SPACE",):
            clean, n = f"{base}_{n}", n + 1
        block_names[name] = clean
    for name, definition in blocks.items():
        b = definition.get("base") or [0.0, 0.0]
        layout = doc.blocks.new(block_names[name], base_point=(float(b[0]) * factor, float(b[1]) * factor))
        entries = [(e.get("type"), {k: e[k] for k in cad_shapes.GEOMETRY_KEYS.get(e.get("type"), ()) if k in e}, e)
                   for e in definition.get("items") or [] if e.get("type") in cad_shapes.CAD_TYPES]
        write(layout, entries)
    write(doc.modelspace(), lines)
    return doc


ATTACHMENT = {"TL": 1, "TC": 2, "TR": 3, "ML": 4, "MC": 5, "MR": 6, "BL": 7, "BC": 8, "BR": 9,
              "L": 1, "C": 2, "R": 3}           # MTEXT : point d'attache (ligne de base -> haut)
ALIGNMENT = {"L": "LEFT", "C": "CENTER", "R": "RIGHT", "TL": "TOP_LEFT", "TC": "TOP_CENTER", "TR": "TOP_RIGHT",
             "ML": "MIDDLE_LEFT", "MC": "MIDDLE_CENTER", "MR": "MIDDLE_RIGHT", "BL": "BOTTOM_LEFT",
             "BC": "BOTTOM_CENTER", "BR": "BOTTOM_RIGHT"}


def _image_entity(doc, space, data: dict, f: float, attribs: dict, image_defs: dict):
    """Image -> IMAGE (vecteurs de pixel = ses coins, cisaillement compris) ; taille en pixels lue du fichier (sinon
    1000 x 1000)."""
    s = cad_image.style_of(data)
    path = s["path"]
    found = image_defs.get(path)
    if found is None:
        width, height = 1000, 1000
        try:
            from PySide6.QtGui import QImageReader
            size = QImageReader(path).size()
            if size.isValid():
                width, height = size.width(), size.height()
        except Exception:                                   # noqa: BLE001 - lecteur indisponible : taille par defaut
            pass
        found = image_defs[path] = (doc.add_image_def(path or "image.png", (width, height)), (width, height))
    image_def, (width, height) = found
    p, u, v = s["pos"], s["pu"], s["pv"]
    entity = space.add_image(image_def, (p[0] * f, p[1] * f), (1.0, 1.0), dxfattribs=attribs)
    entity.dxf.u_pixel = ((u[0] - p[0]) * f / width, (u[1] - p[1]) * f / width, 0.0)
    entity.dxf.v_pixel = ((v[0] - p[0]) * f / height, (v[1] - p[1]) * f / height, 0.0)
    entity.dxf.image_size = (width, height)
    if s["fade"]:
        entity.dxf.fade = int(round(s["fade"]))
    return entity


def _attdef_entity(space, data: dict, attdef: dict, f: float, attribs: dict) -> list:
    """Definition d'attribut -> ATTDEF (etiquette, question, valeur par defaut, invisible / constant)."""
    from ezdxf.enums import TextEntityAlignment
    s = cad_text.style_of(data)
    pos = data.get("pos") or (0.0, 0.0)
    flags = (1 if attdef["invisible"] else 0) | (2 if attdef["constant"] else 0)
    entity = space.add_attdef(attdef["tag"], (float(pos[0]) * f, float(pos[1]) * f), attdef["default"],
                              dxfattribs={**attribs, "height": s["height"] * f, "rotation": s["rot"],
                                          "prompt": attdef["prompt"], "flags": flags})
    entity.set_placement((float(pos[0]) * f, float(pos[1]) * f),
                         align=TextEntityAlignment[ALIGNMENT.get(s["justify"], "LEFT")])
    return [entity]


def _text_entities(space, data: dict, f: float, attribs: dict) -> list:
    """Texte -> MTEXT (texte multiligne) ou un TEXT par ligne (meme justification, lignes empilees)."""
    from ezdxf.enums import TextEntityAlignment
    s = cad_text.style_of(data)
    pos = data.get("pos") or (0.0, 0.0)
    if s["mtext"]:
        entity = space.add_mtext(s["text"].replace("\n", "\\P"), dxfattribs={
            **attribs, "char_height": s["height"] * f, "rotation": s["rot"], "width": s["width"] * f,
            "attachment_point": ATTACHMENT[s["justify"]], "insert": (pos[0] * f, pos[1] * f),
            "line_spacing_factor": s["spacing"]})
        return [entity]
    made = []
    point = (float(pos[0]), float(pos[1]))
    for line in s["text"].split("\n"):
        if line:
            entity = space.add_text(line, dxfattribs={**attribs, "height": s["height"] * f, "rotation": s["rot"]})
            entity.set_placement((point[0] * f, point[1] * f), align=TextEntityAlignment[ALIGNMENT[s["justify"]]])
            made.append(entity)
        point = cad_text.next_line({**data, "pos": list(point)})
    return made


def scene_lines(scene) -> list:
    """Entites CAD de la page : [(type, champs geometriques, donnees)]."""
    from .cad_items import CadLineItem
    return [(item.kind, item.geometry(), item.data) for item in scene.board_items() if isinstance(item, CadLineItem)]


def _write(target: Path, writer):
    """Ecrit dans un fichier temporaire du meme dossier puis remplace la cible."""
    target = Path(target)
    fd, temp = tempfile.mkstemp(prefix=f".{target.stem}.part.", suffix=target.suffix, dir=str(target.parent))
    os.close(fd)
    try:
        writer(Path(temp))
        os.replace(temp, target)
    except BaseException:
        try:
            os.unlink(temp)
        except OSError:
            pass
        raise
    return target


def _document(scene, units: str):
    from .cad_items import unit_of
    cad = cad_model.page_cad(scene.page)
    return build_document(cad, scene_lines(scene), units, unit_of(scene, cad))


def export_dxf(scene, path, units: str = "mm") -> Path:
    doc = _document(scene, units)
    return _write(Path(path), lambda temp: doc.saveas(temp))


def oda_converter() -> str | None:
    """Chemin d'ODA File Converter, ou None : `ODA_PROVIDER` (posé par la fenêtre principale), variable
    ODA_FILE_CONVERTER, PATH, puis l'installation standard (`Program Files/ODA/ODAFileConverter <version>`, la plus
    récente). Bug corrigé (2026-10-31) : sans cette dernière recherche, le 1er DWG ouvert, lu AVANT que le board ne pose
    `ODA_PROVIDER`, disait ODA « introuvable » alors qu'il était installé."""
    if ODA_PROVIDER is not None:
        try:
            found = ODA_PROVIDER()
        except Exception:                                   # noqa: BLE001 - recherche de l'appli en echec
            found = None
        if found:
            return found
    configured = os.environ.get("ODA_FILE_CONVERTER")
    if configured and Path(configured).is_file():
        return configured
    found = shutil.which("ODAFileConverter") or shutil.which("ODAFileConverter.exe")
    if found:
        return found
    roots = dict.fromkeys((Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "ODA",
                           Path(r"C:\Program Files\ODA")))
    for root in roots:
        try:
            candidates = list(root.glob("*/ODAFileConverter.exe"))
        except OSError:
            continue
        if candidates:                                      # version la plus récente (27.10 après 27.9)
            version = lambda exe: [int(n) for n in re.findall(r"\d+", exe.parent.name)]
            return str(max(candidates, key=version))
    return None


@contextlib.contextmanager
def oda_environment():
    """ODA File Converter est une application Qt : les variables Qt de NOTRE processus (`QT_QPA_PLATFORM=offscreen` des
    tests, `QT_PLUGIN_PATH`…) l'empechent de demarrer (« no Qt platform plugin could be initialized », signale). Retirees
    le temps de la conversion (ezdxf lance le programme avec l'environnement du processus), puis remises."""
    saved = {k: os.environ.pop(k) for k in list(os.environ) if k.upper().startswith("QT_")}
    try:
        yield
    finally:
        os.environ.update(saved)


def export_dwg(scene, path, units: str = "mm") -> Path:
    """DWG : DXF fait par ezdxf, converti par ODA File Converter (format proprietaire : aucune bibliotheque libre ne
    l'ecrit de facon fiable)."""
    ezdxf = _ezdxf()
    from ezdxf.addons import odafc
    exe = oda_converter()
    if exe:
        ezdxf.options.set("odafc-addon", "win_exec_path", f'"{exe}"')
    if not odafc.is_installed():
        raise ExportError("L'export DWG demande ODA File Converter (gratuit, opendesign.com), introuvable. "
                          "Installez-le ou indiquez son chemin dans la variable ODA_FILE_CONVERTER ; "
                          "l'export DXF, lui, fonctionne sans.")
    doc = _document(scene, units)
    def convert(temp):
        with oda_environment():
            return odafc.export_dwg(doc, str(temp), version=DXF_VERSION, replace=True)
    return _write(Path(path), convert)
