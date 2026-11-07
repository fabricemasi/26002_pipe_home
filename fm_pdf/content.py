"""Édition RÉELLE du contenu des pages (sans Qt, fil du moteur) : les objets de la page (texte, image, tracé) sont
modifiés dans PDFium puis le flux de contenu de la page est RÉGÉNÉRÉ (`FPDFPage_GenerateContent`) ; les autres
objets restent tels quels. Aucune superposition graphique.

- Texte : remplacement du texte d'un objet (`FPDFText_SetText`) ; PDFium relit le texte posé (`FPDFTextObj_GetText`)
  : si la police INCORPORÉE (souvent un sous-ensemble) n'a pas les glyphes demandés, l'objet est rendu tel quel et le
  remplacement passe EXPLICITEMENT par une police standard (Helvetica / Times / Courier, même taille, couleur et
  position ; signalé à l'utilisateur). Taille, couleur, position, rotation (matrice).
- Image : déplacement, redimensionnement (proportions gardées au choix), rotation, remplacement, suppression, ajout.
- Tracés : couleurs de contour / remplissage, épaisseur, ajout de rectangles, ellipses, lignes.
- Ordre de superposition : l'objet est retiré puis réinséré à l'indice voulu.
Formulaires XFA : refusé (le contenu est produit par le formulaire).

Coordonnées : points « écran » du moteur (origine en haut à gauche) ; converties par `Document.to_page`.
"""
from __future__ import annotations

import ctypes
import math

OBJ_TYPES = {1: "texte", 2: "tracé", 3: "image", 4: "dégradé", 5: "groupe"}
STANDARD_FONTS = {"Helvetica": b"Helvetica", "Times": b"Times-Roman", "Courier": b"Courier",
                  "Helvetica gras": b"Helvetica-Bold", "Times gras": b"Times-Bold"}


class ContentError(ValueError):
    pass


def _check(doc):
    if doc.is_xfa:
        raise ContentError("formulaire XFA : son contenu est produit par le formulaire lui-même")


def _obj(doc, i, index):
    c = doc.c
    page = doc.page(i)
    n = c.FPDFPage_CountObjects(page)
    if not 0 <= index < n:
        raise ContentError("objet introuvable")
    return page, c.FPDFPage_GetObject(page, index)


def _bounds_pdf(c, obj):
    l, b, r, t = (ctypes.c_float() for _ in range(4))
    if not c.FPDFPageObj_GetBounds(obj, ctypes.byref(l), ctypes.byref(b), ctypes.byref(r), ctypes.byref(t)):
        return None
    return l.value, b.value, r.value, t.value


def _wide(text: str):
    raw = text.encode("utf-16-le") + b"\0\0"
    return (ctypes.c_ushort * (len(raw) // 2)).from_buffer_copy(raw)


def obj_text(doc, i, obj) -> str:
    c = doc.c
    tp = doc.text_page(i)
    n = c.FPDFTextObj_GetText(obj, tp, None, 0)
    if n <= 2:
        return ""
    buf = (ctypes.c_ushort * (n // 2 + 1))()
    c.FPDFTextObj_GetText(obj, tp, buf, n)
    return bytes(buf)[: n - 2].decode("utf-16-le", "replace")


def _color(c, getter, obj):
    r, g, b, a = (ctypes.c_uint() for _ in range(4))
    if getter(obj, ctypes.byref(r), ctypes.byref(g), ctypes.byref(b), ctypes.byref(a)):
        return (r.value, g.value, b.value, a.value)
    return None


def objects(doc, i) -> list[dict]:
    """Objets de la page : indice, type, rectangle (points écran), texte, taille, couleurs."""
    c = doc.c
    page = doc.page(i)
    out = []
    for k in range(c.FPDFPage_CountObjects(page)):
        obj = c.FPDFPage_GetObject(page, k)
        kind = int(c.FPDFPageObj_GetType(obj))
        b = _bounds_pdf(c, obj)
        if b is None:
            continue
        rect = doc.rect_to_device(i, b[0], b[3], b[2], b[1])
        item = {"index": k, "type": kind, "type_name": OBJ_TYPES.get(kind, "?"), "rect": rect}
        if kind == 1:
            size = ctypes.c_float()
            c.FPDFTextObj_GetFontSize(obj, ctypes.byref(size))
            item["text"] = obj_text(doc, i, obj)
            item["size"] = float(size.value)
            item["fill"] = _color(c, c.FPDFPageObj_GetFillColor, obj)
        elif kind == 2:
            item["fill"] = _color(c, c.FPDFPageObj_GetFillColor, obj)
            item["stroke"] = _color(c, c.FPDFPageObj_GetStrokeColor, obj)
            w = ctypes.c_float()
            item["width"] = float(w.value) if c.FPDFPageObj_GetStrokeWidth(obj, ctypes.byref(w)) else 0.0
        out.append(item)
    return out


def object_at(doc, i, x, y, tolerance: float = 2.0) -> dict | None:
    """Objet le plus HAUT sous le point ; un tracé qui couvre presque toute la page (fond) ne gagne qu'en dernier."""
    w, h = doc.page_size(i)
    hits = []
    for item in objects(doc, i):
        x0, y0, x1, y1 = item["rect"]
        if x0 - tolerance <= x <= x1 + tolerance and y0 - tolerance <= y <= y1 + tolerance:
            area = (x1 - x0) * (y1 - y0)
            background = item["type"] == 2 and area > 0.6 * w * h
            hits.append((background, -item["index"], item))
    if not hits:
        return None
    hits.sort(key=lambda t: (t[0], t[1]))
    return hits[0][2]


def _commit(doc, i) -> None:
    if not doc.c.FPDFPage_GenerateContent(doc.page(i)):
        raise ContentError("PDFium n'a pas pu régénérer le contenu de la page")
    doc._text.pop(i, None) and doc.c.FPDFText_ClosePage(doc._text.pop(i, None)) if False else None
    tp = doc._text.pop(i, None)
    if tp:
        doc.c.FPDFText_ClosePage(tp)
    doc.revision += 1


def _delta_pdf(doc, i, dx, dy):
    ax, ay = doc.to_page(i, 0.0, 0.0)
    bx, by = doc.to_page(i, dx, dy)
    return bx - ax, by - ay


def move(doc, i, index, dx, dy) -> None:
    _check(doc)
    _page, obj = _obj(doc, i, index)
    px, py = _delta_pdf(doc, i, dx, dy)
    doc.c.FPDFPageObj_Transform(obj, 1, 0, 0, 1, px, py)
    _commit(doc, i)


def resize(doc, i, index, rect, keep_ratio: bool = False) -> None:
    """Amène le rectangle de l'objet sur `rect` (points écran)."""
    _check(doc)
    c = doc.c
    _page, obj = _obj(doc, i, index)
    b = _bounds_pdf(c, obj)
    if b is None:
        raise ContentError("objet sans étendue")
    l, bo, r, t = b
    x0, y0 = doc.to_page(i, rect[0], rect[3])
    x1, y1 = doc.to_page(i, rect[2], rect[1])
    nl, nb, nr, nt = min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)
    sx = (nr - nl) / max(1e-6, r - l)
    sy = (nt - nb) / max(1e-6, t - bo)
    if keep_ratio:
        sx = sy = min(sx, sy)
    if sx <= 0 or sy <= 0:
        raise ContentError("taille nulle")
    c.FPDFPageObj_Transform(obj, 1, 0, 0, 1, -l, -bo)
    c.FPDFPageObj_Transform(obj, sx, 0, 0, sy, 0, 0)
    c.FPDFPageObj_Transform(obj, 1, 0, 0, 1, nl, nb)
    _commit(doc, i)


def rotate(doc, i, index, degrees: float) -> None:
    _check(doc)
    c = doc.c
    _page, obj = _obj(doc, i, index)
    l, b, r, t = _bounds_pdf(c, obj)
    cx, cy = (l + r) / 2, (b + t) / 2
    a = math.radians(degrees)
    cos, sin = math.cos(a), math.sin(a)
    c.FPDFPageObj_Transform(obj, 1, 0, 0, 1, -cx, -cy)
    c.FPDFPageObj_Transform(obj, cos, sin, -sin, cos, 0, 0)
    c.FPDFPageObj_Transform(obj, 1, 0, 0, 1, cx, cy)
    _commit(doc, i)


def delete(doc, i, index) -> None:
    _check(doc)
    page, obj = _obj(doc, i, index)
    if not doc.c.FPDFPage_RemoveObject(page, obj):
        raise ContentError("suppression refusée")
    doc.c.FPDFPageObj_Destroy(obj)
    _commit(doc, i)


def restack(doc, i, index, to: int) -> int:
    """Ordre de superposition : l'objet passe à l'indice `to` (0 = tout en dessous) ; renvoie le nouvel indice."""
    _check(doc)
    c = doc.c
    page, obj = _obj(doc, i, index)
    n = c.FPDFPage_CountObjects(page)
    to = max(0, min(n - 1, int(to)))
    if not c.FPDFPage_RemoveObject(page, obj):
        raise ContentError("déplacement refusé")
    if not c.FPDFPage_InsertObjectAtIndex(page, obj, to):
        c.FPDFPage_InsertObject(page, obj)
        to = n - 1
    _commit(doc, i)
    return to


def set_colors(doc, i, index, fill=None, stroke=None, width=None, opacity=None) -> None:
    """Couleurs 0-255 (r, g, b) ; `opacity` 0-1 (alpha des couleurs)."""
    _check(doc)
    c = doc.c
    _page, obj = _obj(doc, i, index)
    alpha = None if opacity is None else int(round(max(0.0, min(1.0, opacity)) * 255))
    if fill is not None or alpha is not None:
        cur = _color(c, c.FPDFPageObj_GetFillColor, obj) or (0, 0, 0, 255)
        r, g, b = fill if fill is not None else cur[:3]
        c.FPDFPageObj_SetFillColor(obj, r, g, b, alpha if alpha is not None else cur[3])
    if stroke is not None or (alpha is not None and c.FPDFPageObj_GetType(obj) == 2):
        cur = _color(c, c.FPDFPageObj_GetStrokeColor, obj) or (0, 0, 0, 255)
        r, g, b = stroke if stroke is not None else cur[:3]
        c.FPDFPageObj_SetStrokeColor(obj, r, g, b, alpha if alpha is not None else cur[3])
    if width is not None:
        c.FPDFPageObj_SetStrokeWidth(obj, float(width))
    _commit(doc, i)


def set_text(doc, i, index, text: str, font: str = "Helvetica") -> dict:
    """Remplace le texte d'un objet texte. Renvoie {'fallback': police standard utilisée ou None}."""
    _check(doc)
    c = doc.c
    page, obj = _obj(doc, i, index)
    if c.FPDFPageObj_GetType(obj) != 1:
        raise ContentError("cet objet n'est pas du texte")
    old = obj_text(doc, i, obj)
    c.FPDFText_SetText(obj, _wide(text))
    tp = doc._text.pop(i, None)                       # texte relu après le changement
    if tp:
        c.FPDFText_ClosePage(tp)
    if obj_text(doc, i, obj).replace("\r", "").replace("\n", "") == text.replace("\n", ""):
        _commit(doc, i)
        return {"fallback": None}
    c.FPDFText_SetText(obj, _wide(old))               # glyphes absents de la police incorporée : remplacement
    size = ctypes.c_float()
    c.FPDFTextObj_GetFontSize(obj, ctypes.byref(size))
    matrix = c.FS_MATRIX()
    c.FPDFPageObj_GetMatrix(obj, ctypes.byref(matrix))
    fill = _color(c, c.FPDFPageObj_GetFillColor, obj) or (0, 0, 0, 255)
    new = c.FPDFPageObj_NewTextObj(doc.handle, STANDARD_FONTS.get(font, b"Helvetica"), size.value or 12.0)
    if not new:
        raise ContentError("police standard indisponible")
    c.FPDFText_SetText(new, _wide(text))
    c.FPDFPageObj_SetMatrix(new, ctypes.byref(matrix))
    c.FPDFPageObj_SetFillColor(new, *fill)
    c.FPDFPage_RemoveObject(page, obj)
    c.FPDFPageObj_Destroy(obj)
    c.FPDFPage_InsertObjectAtIndex(page, new, index) or c.FPDFPage_InsertObject(page, new)
    _commit(doc, i)
    return {"fallback": font}


def set_font_size(doc, i, index, size: float) -> None:
    _check(doc)
    c = doc.c
    _page, obj = _obj(doc, i, index)
    if not c.FPDFTextObj_SetFontSize(obj, float(size)):
        raise ContentError("taille refusée")
    _commit(doc, i)


def add_text(doc, i, x, y, text: str, size: float = 12.0, color=(0, 0, 0), font: str = "Helvetica") -> int:
    """Nouveau texte (police standard) dont la LIGNE DE BASE commence au point (x, y) (points écran)."""
    _check(doc)
    c = doc.c
    page = doc.page(i)
    obj = c.FPDFPageObj_NewTextObj(doc.handle, STANDARD_FONTS.get(font, b"Helvetica"), float(size))
    lines = text.split("\n")
    c.FPDFText_SetText(obj, _wide(lines[0]))
    px, py = doc.to_page(i, x, y)
    c.FPDFPageObj_Transform(obj, 1, 0, 0, 1, px, py)
    c.FPDFPageObj_SetFillColor(obj, *color, 255)
    c.FPDFPage_InsertObject(page, obj)
    for k, line in enumerate(lines[1:], 1):           # lignes suivantes : un objet par ligne, interligne 1,2
        o = c.FPDFPageObj_NewTextObj(doc.handle, STANDARD_FONTS.get(font, b"Helvetica"), float(size))
        c.FPDFText_SetText(o, _wide(line))
        qx, qy = doc.to_page(i, x, y + k * size * 1.2)
        c.FPDFPageObj_Transform(o, 1, 0, 0, 1, qx, qy)
        c.FPDFPageObj_SetFillColor(o, *color, 255)
        c.FPDFPage_InsertObject(page, o)
    _commit(doc, i)
    return c.FPDFPage_CountObjects(page) - 1


def add_image(doc, i, rect, bgra: bytes, width: int, height: int, stride: int | None = None) -> int:
    """Image BGRA 8 bits posée dans `rect` (points écran)."""
    _check(doc)
    c = doc.c
    page = doc.page(i)
    obj = c.FPDFPageObj_NewImageObj(doc.handle)
    stride = stride or width * 4
    buf = ctypes.create_string_buffer(bytes(bgra), len(bgra))
    bmp = c.FPDFBitmap_CreateEx(width, height, c.FPDFBitmap_BGRA, buf, stride)
    try:
        if not c.FPDFImageObj_SetBitmap(None, 0, obj, bmp):
            raise ContentError("image refusée par PDFium")
    finally:
        c.FPDFBitmap_Destroy(bmp)
    x0, y0 = doc.to_page(i, rect[0], rect[3])
    x1, y1 = doc.to_page(i, rect[2], rect[1])
    l, b = min(x0, x1), min(y0, y1)
    c.FPDFImageObj_SetMatrix(obj, abs(x1 - x0), 0, 0, abs(y1 - y0), l, b)
    c.FPDFPage_InsertObject(page, obj)
    _commit(doc, i)
    return c.FPDFPage_CountObjects(page) - 1


def replace_image(doc, i, index, bgra: bytes, width: int, height: int) -> None:
    _check(doc)
    c = doc.c
    _page, obj = _obj(doc, i, index)
    if c.FPDFPageObj_GetType(obj) != 3:
        raise ContentError("cet objet n'est pas une image")
    buf = ctypes.create_string_buffer(bytes(bgra), len(bgra))
    bmp = c.FPDFBitmap_CreateEx(width, height, c.FPDFBitmap_BGRA, buf, width * 4)
    try:
        if not c.FPDFImageObj_SetBitmap(None, 0, obj, bmp):
            raise ContentError("image refusée par PDFium")
    finally:
        c.FPDFBitmap_Destroy(bmp)
    _commit(doc, i)


def add_shape(doc, i, kind: str, rect, stroke=(0, 0, 0), fill=None, width: float = 1.0) -> int:
    """Rectangle, ellipse (4 Bézier) ou ligne (diagonale du rectangle, de son 1er point au 2e)."""
    _check(doc)
    c = doc.c
    page = doc.page(i)
    x0, y0 = doc.to_page(i, rect[0], rect[1])
    x1, y1 = doc.to_page(i, rect[2], rect[3])
    if kind == "rect":
        obj = c.FPDFPageObj_CreateNewRect(min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0))
    elif kind == "line":
        obj = c.FPDFPageObj_CreateNewPath(x0, y0)
        c.FPDFPath_LineTo(obj, x1, y1)
        fill = None
    elif kind == "ellipse":
        cx, cy, rx, ry = (x0 + x1) / 2, (y0 + y1) / 2, abs(x1 - x0) / 2, abs(y1 - y0) / 2
        k = 0.5522847498
        obj = c.FPDFPageObj_CreateNewPath(cx + rx, cy)
        c.FPDFPath_BezierTo(obj, cx + rx, cy + k * ry, cx + k * rx, cy + ry, cx, cy + ry)
        c.FPDFPath_BezierTo(obj, cx - k * rx, cy + ry, cx - rx, cy + k * ry, cx - rx, cy)
        c.FPDFPath_BezierTo(obj, cx - rx, cy - k * ry, cx - k * rx, cy - ry, cx, cy - ry)
        c.FPDFPath_BezierTo(obj, cx + k * rx, cy - ry, cx + rx, cy - k * ry, cx + rx, cy)
        c.FPDFPath_Close(obj)
    else:
        raise ContentError("forme inconnue : %s" % kind)
    c.FPDFPageObj_SetStrokeColor(obj, *stroke, 255)
    c.FPDFPageObj_SetStrokeWidth(obj, float(width))
    if fill is not None:
        c.FPDFPageObj_SetFillColor(obj, *fill, 255)
    c.FPDFPath_SetDrawMode(obj, 2 if fill is not None else 0, 1)       # 2 = remplissage « non nul », 0 = aucun
    c.FPDFPage_InsertObject(page, obj)
    _commit(doc, i)
    return c.FPDFPage_CountObjects(page) - 1
