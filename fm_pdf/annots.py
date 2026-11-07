"""Annotations standard (sans Qt) : création, liste, modification, suppression, par PyMuPDF (apparences /AP
générées : visibles dans tout lecteur conforme, Acrobat compris). Coordonnées = points de la page NON tournée par
la vue, origine en haut à gauche (repère du moteur du module) ; converties dans le repère de PyMuPDF par la
matrice de rotation de la page (/Rotate).

Chaque fonction prend les octets du document et rend les nouveaux (+ le xref de l'annotation créée)."""
from __future__ import annotations

import datetime as _dt
import io

KINDS = {"highlight": "Surlignage", "underline": "Soulignement", "strikeout": "Barré", "squiggly": "Ondulé",
         "note": "Note", "freetext": "Zone de texte", "ink": "Dessin à main levée", "line": "Ligne",
         "arrow": "Flèche", "rect": "Rectangle", "circle": "Ellipse", "stamp": "Tampon", "check": "Coche",
         "cross": "Croix"}
STAMPS = {"Approuvé": 0, "Confidentiel": 2, "Brouillon": 5, "Final": 7, "Pour commentaire": 11,
          "Pour information": 10, "Expérimental": 4, "Non approuvé": 8, "Expiré": 6, "Public": 12}
SUBTYPE_KIND = {"Highlight": "highlight", "Underline": "underline", "StrikeOut": "strikeout",
                "Squiggly": "squiggly", "Text": "note", "FreeText": "freetext", "Ink": "ink", "Line": "line",
                "Square": "rect", "Circle": "circle", "Stamp": "stamp", "PolyLine": "line", "Polygon": "rect"}


class AnnotError(ValueError):
    pass


def _open(data: bytes):
    import pymupdf
    doc = pymupdf.open(stream=data, filetype="pdf")
    if doc.is_encrypted:
        doc.close()
        raise AnnotError("document chiffré : impossible d'y ajouter des commentaires sans l'enregistrer déchiffré")
    return doc


def _save(doc) -> bytes:
    out = io.BytesIO()
    doc.save(out, garbage=1, deflate=True)
    doc.close()
    return out.getvalue()


def _rect(page, r):
    import pymupdf
    rect = pymupdf.Rect(r) * page.derotation_matrix
    rect.normalize()
    return rect


def _point(page, p):
    import pymupdf
    return pymupdf.Point(p) * page.derotation_matrix


def _pdf_date(when: _dt.datetime | None = None) -> str:
    when = when or _dt.datetime.now().astimezone()
    off = when.utcoffset() or _dt.timedelta(0)
    minutes = int(off.total_seconds() // 60)
    sign = "+" if minutes >= 0 else "-"
    return when.strftime("D:%Y%m%d%H%M%S") + "%s%02d'%02d'" % (sign, abs(minutes) // 60, abs(minutes) % 60)


def _finish(annot, props: dict) -> None:
    color = props.get("color")
    fill = props.get("fill")
    if color is not None or fill is not None:
        kw = {}
        if color is not None:
            kw["stroke"] = tuple(color)
        if fill is not None and annot.type[1] in ("Square", "Circle", "FreeText", "Polygon"):
            kw["fill"] = tuple(fill) if fill else None
        try:
            annot.set_colors(**kw)
        except Exception:                                   # noqa: BLE001 - type sans couleur de fond
            if color is not None:
                annot.set_colors(stroke=tuple(color))
    if props.get("width") is not None and annot.type[1] not in ("Highlight", "Underline", "StrikeOut", "Text",
                                                                   "Stamp"):
        annot.set_border(width=float(props["width"]))
    if props.get("opacity") is not None:
        annot.set_opacity(float(props["opacity"]))
    info = {"title": props.get("author", "") or "", "content": props.get("contents", "") or "",
            "subject": props.get("subject", "") or KINDS.get(props.get("kind", ""), "")}
    annot.set_info(info)
    annot.update()
    doc = annot.parent.parent
    doc.xref_set_key(annot.xref, "M", "(%s)" % _pdf_date())
    if doc.xref_get_key(annot.xref, "CreationDate")[0] == "null":
        doc.xref_set_key(annot.xref, "CreationDate", "(%s)" % _pdf_date())


def add(data: bytes, page_index: int, kind: str, props: dict) -> tuple[bytes, int]:
    """Ajoute une annotation. props : rects (balisage), rect, points, strokes, text, color, fill, width,
    opacity, author, contents, stamp."""
    import pymupdf
    doc = _open(data)
    page = doc[page_index]
    props = dict(props, kind=kind)
    if kind in ("highlight", "underline", "strikeout", "squiggly"):
        quads = [_rect(page, r).quad for r in props.get("rects", [])]
        if not quads:
            doc.close()
            raise AnnotError("aucun texte choisi")
        fn = {"highlight": page.add_highlight_annot, "underline": page.add_underline_annot,
              "strikeout": page.add_strikeout_annot, "squiggly": page.add_squiggly_annot}[kind]
        annot = fn(quads)
    elif kind == "note":
        annot = page.add_text_annot(_point(page, props["point"]), props.get("contents", ""), icon="Comment")
    elif kind == "freetext":
        annot = page.add_freetext_annot(_rect(page, props["rect"]), props.get("text", ""),
                                        fontsize=float(props.get("font_size", 11)), fontname="helv",
                                        text_color=tuple(props.get("text_color", props.get("color") or (0, 0, 0))),
                                        fill_color=tuple(props["fill"]) if props.get("fill") else None,
                                        rotate=page.rotation)
        props = dict(props, color=None)
        props["contents"] = props.get("contents") or props.get("text", "")
    elif kind == "ink":
        strokes = [[_point(page, p) for p in stroke] for stroke in props.get("strokes", []) if len(stroke) > 1]
        if not strokes:
            doc.close()
            raise AnnotError("tracé vide")
        annot = page.add_ink_annot([[(p.x, p.y) for p in s] for s in strokes])
    elif kind in ("line", "arrow"):
        a, b = (_point(page, p) for p in props["points"])
        annot = page.add_line_annot(a, b)
        if kind == "arrow":
            annot.set_line_ends(pymupdf.PDF_ANNOT_LE_NONE, pymupdf.PDF_ANNOT_LE_OPEN_ARROW)
    elif kind == "rect":
        annot = page.add_rect_annot(_rect(page, props["rect"]))
    elif kind == "circle":
        annot = page.add_circle_annot(_rect(page, props["rect"]))
    elif kind == "stamp":
        annot = page.add_stamp_annot(_rect(page, props["rect"]), stamp=int(STAMPS.get(props.get("stamp"), 0)))
    elif kind in ("check", "cross"):
        r = _rect(page, props["rect"])
        if kind == "check":
            pts = [(r.x0, r.y0 + r.height * 0.55), (r.x0 + r.width * 0.4, r.y1), (r.x1, r.y0)]
            annot = page.add_ink_annot([pts])
        else:
            annot = page.add_ink_annot([[(r.x0, r.y0), (r.x1, r.y1)], [(r.x0, r.y1), (r.x1, r.y0)]])
        props.setdefault("subject", KINDS[kind])
    else:
        doc.close()
        raise AnnotError("type d'annotation inconnu : %s" % kind)
    _finish(annot, props)
    xref = annot.xref
    return _save(doc), xref


def list_all(data: bytes) -> list[dict]:
    """Annotations de commentaire (pas les champs de formulaire ni les liens)."""
    import pymupdf
    doc = pymupdf.open(stream=data, filetype="pdf")
    try:
        out = []
        for page in doc:
            for annot in page.annots() or []:
                subtype = annot.type[1]
                if subtype in ("Widget", "Link", "Popup"):
                    continue
                info = annot.info
                r = annot.rect * page.rotation_matrix
                r.normalize()
                out.append({"page": page.number, "xref": annot.xref, "subtype": subtype,
                            "kind": SUBTYPE_KIND.get(subtype, subtype.lower()),
                            "label": KINDS.get(SUBTYPE_KIND.get(subtype, ""), subtype),
                            "author": info.get("title", ""), "contents": info.get("content", ""),
                            "date": info.get("modDate") or info.get("creationDate", ""),
                            "rect": (r.x0, r.y0, r.x1, r.y1), "color": (annot.colors or {}).get("stroke"),
                            "opacity": annot.opacity})
        return out
    finally:
        doc.close()


def update(data: bytes, page_index: int, xref: int, props: dict) -> bytes:
    doc = _open(data)
    page = doc[page_index]
    annot = page.load_annot(xref)
    if annot is None:
        doc.close()
        raise AnnotError("annotation introuvable")
    if props.get("rect") is not None and annot.type[1] in ("Square", "Circle", "FreeText", "Stamp", "Text"):
        annot.set_rect(_rect(page, props["rect"]))
    if "contents" in props or "author" in props:
        info = annot.info
        if "contents" in props:
            info["content"] = props["contents"]
        if "author" in props:
            info["title"] = props["author"]
        annot.set_info(info)
    if props.get("color") is not None:
        try:
            annot.set_colors(stroke=tuple(props["color"]))
        except Exception:                                   # noqa: BLE001
            pass
    if props.get("width") is not None:
        annot.set_border(width=float(props["width"]))
    if props.get("opacity") is not None:
        annot.set_opacity(float(props["opacity"]))
    annot.update()
    doc.xref_set_key(annot.xref, "M", "(%s)" % _pdf_date())
    return _save(doc)


def delete(data: bytes, items: list[tuple[int, int]]) -> bytes:
    """Supprime les annotations [(page, xref)]."""
    doc = _open(data)
    for page_index, xref in items:
        page = doc[page_index]
        annot = page.load_annot(xref)
        if annot is not None:
            page.delete_annot(annot)
    return _save(doc)


def flatten_annotations(data: bytes) -> bytes:
    """APLATIT les annotations ET les champs dans le contenu (sur demande explicite seulement : export « aplati »)."""
    import pymupdf
    doc = _open(data)
    try:
        doc.bake(annots=True, widgets=True)
    except AttributeError:                                  # PyMuPDF ancien : conversion page par page
        out = pymupdf.open()
        for page in doc:
            out.new_page(width=page.rect.width, height=page.rect.height).show_pdf_page(page.rect, doc, page.number)
        doc.close()
        return _save(out)
    return _save(doc)
