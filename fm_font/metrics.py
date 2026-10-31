"""Métriques (sans Qt) : approches gauche / droite, chasse, métriques verticales de la famille, chaînes de
contrôle. Les approches d'un glyphe composé se mesurent sur son dessin complet (composants compris)."""
from __future__ import annotations

from fontTools.pens.boundsPen import BoundsPen

# Chaînes de contrôle classiques (espacement des minuscules / capitales / chiffres).
CONTROL_STRINGS = {
    "Minuscules": "nnannbnncnndnnennfnngnnhnninnjnnknnlnnmnnonnpnnqnnrnnsnntnnunnvnnwnnxnnynnzn",
    "Capitales": "HHAHHBHHCHHDHHEHHFHHGHHIHHJHHKHHLHHMHHNHHOHHPHHQHHRHHSHHTHHUHHVHHWHHXHHYHHZH",
    "Chiffres": "00102030405060708090",
    "Rondes": "oonoodoopooqoobooeooco",
    "Pangramme": "Portez ce vieux whisky au juge blond qui fume",
}


def bounds(glyph, layer=None):
    pen = BoundsPen(layer)
    glyph.draw(pen)
    return pen.bounds


def left_margin(glyph, layer=None) -> float | None:
    b = bounds(glyph, layer)
    return None if b is None else b[0]


def right_margin(glyph, layer=None) -> float | None:
    b = bounds(glyph, layer)
    return None if b is None else glyph.width - b[2]


def set_left_margin(glyph, value: float, layer=None) -> None:
    """Déplace le dessin (contours, composants, ancres) et garde l'approche droite."""
    b = bounds(glyph, layer)
    if b is None:
        return
    dx = value - b[0]
    _shift(glyph, dx)
    glyph.width += dx


def set_right_margin(glyph, value: float, layer=None) -> None:
    b = bounds(glyph, layer)
    if b is None:
        return
    glyph.width = b[2] + value


def set_width(glyph, value: float, center: bool = False, layer=None) -> None:
    """Nouvelle chasse ; `center` : le dessin reste centré (approches égales)."""
    if center:
        b = bounds(glyph, layer)
        if b is not None:
            room = value - (b[2] - b[0])
            _shift(glyph, room / 2 - b[0])
    glyph.width = value


def center(glyph, layer=None) -> None:
    set_width(glyph, glyph.width, center=True, layer=layer)


def _shift(glyph, dx: float) -> None:
    if not dx:
        return
    for contour in glyph.contours:
        for p in contour:
            p.x += dx
    for comp in glyph.components:
        t = comp.transformation
        comp.transformation = type(t)(t[0], t[1], t[2], t[3], t[4] + dx, t[5])
    for anchor in glyph.anchors:
        anchor.x += dx


def vertical_metrics(info) -> dict:
    return {"unitsPerEm": info.unitsPerEm, "ascender": info.ascender, "descender": info.descender,
            "capHeight": info.capHeight, "xHeight": info.xHeight, "italicAngle": info.italicAngle or 0}
