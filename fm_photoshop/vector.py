"""Calques de TEXTE et de FORME éditables (Qt pour le rendu).

Un calque porte `source` (dictionnaire, enregistré dans le manifeste) = ce qui se modifie : contenu, police, taille,
couleur, alignement ; ou géométrie, remplissage, contour. Ses `pix` sont le RENDU de cette source (enregistrés aussi : une
machine sans la police revoit le même calque, et seule la modification refait le rendu). Peindre, remplir, appliquer
un filtre sur un tel calque est REFUSÉ tant qu'il n'a pas été converti en pixels (`Actions.rasterize`, menu Calque :
conversion explicite, annulable).

Texte : {kind:"text", content, font, size (px), bold, italic, color [r,g,b,a], align (left|center|right), width (0 =
au fil de la ligne, sinon retour à la ligne dans cette largeur), line_height (%), x, y (coin haut gauche)}.
Forme : {kind:"shape", shape:"rect"|"ellipse"|"line", x, y, w, h (ou x1, y1 pour une ligne), fill [r,g,b,a] ou None,
stroke [r,g,b,a] ou None, stroke_width (px), radius (rectangle)}."""
from __future__ import annotations

import math

import numpy as np

TEXT_DEFAULTS = {"kind": "text", "content": "Texte", "font": "Segoe UI", "size": 48, "bold": False, "italic": False,
                 "color": [0, 0, 0, 255], "align": "left", "width": 0, "line_height": 100, "x": 0, "y": 0}
SHAPE_DEFAULTS = {"kind": "shape", "shape": "rect", "x": 0, "y": 0, "w": 100, "h": 100, "x1": 100, "y1": 100,
                  "fill": [0, 0, 0, 255], "stroke": None, "stroke_width": 4, "radius": 0}
PAD = 2


def _color(value, default):
    if value is None:
        return None
    try:
        r, g, b, a = (max(0, min(255, int(v))) for v in (list(value) + [255])[:4])
        return [r, g, b, a]
    except (TypeError, ValueError):
        return default


def normalize(source: dict | None) -> dict | None:
    """Source validée (valeurs invalides = défauts) ; None si ce n'est pas une source connue."""
    if not isinstance(source, dict):
        return None
    if source.get("kind") == "text":
        out = dict(TEXT_DEFAULTS)
        out.update(source)
        out["content"] = str(out["content"])
        out["font"] = str(out["font"] or TEXT_DEFAULTS["font"])
        try:
            out["size"] = max(1, min(2000, int(float(out["size"]))))
        except (TypeError, ValueError):
            out["size"] = TEXT_DEFAULTS["size"]
        out["align"] = out["align"] if out["align"] in ("left", "center", "right") else "left"
        out["color"] = _color(out["color"], [0, 0, 0, 255]) or [0, 0, 0, 255]
        out["bold"], out["italic"] = bool(out["bold"]), bool(out["italic"])
        for key in ("width", "line_height", "x", "y"):
            try:
                out[key] = float(out[key])
            except (TypeError, ValueError):
                out[key] = TEXT_DEFAULTS[key]
        out["line_height"] = max(50.0, min(300.0, out["line_height"]))
        return out
    if source.get("kind") == "shape":
        out = dict(SHAPE_DEFAULTS)
        out.update(source)
        out["shape"] = out["shape"] if out["shape"] in ("rect", "ellipse", "line") else "rect"
        out["fill"] = _color(out["fill"], None)
        out["stroke"] = _color(out["stroke"], None)
        for key in ("x", "y", "w", "h", "x1", "y1", "stroke_width", "radius"):
            try:
                out[key] = float(out[key])
            except (TypeError, ValueError):
                out[key] = SHAPE_DEFAULTS[key]
        out["stroke_width"] = max(0.0, min(500.0, out["stroke_width"]))
        return out
    return None


def _to_rgba(image) -> np.ndarray:
    from PySide6.QtGui import QImage
    image = image.convertToFormat(QImage.Format_RGBA8888)
    ptr = image.constBits()
    array = np.frombuffer(ptr, np.uint8, image.height() * image.bytesPerLine()).reshape(image.height(),
                                                                                      image.bytesPerLine())
    return array[:, :image.width() * 4].reshape(image.height(), image.width(), 4).copy()   # COPIE : le tampon appartient a QImage


def _blank(w, h):
    from PySide6.QtGui import QImage
    image = QImage(max(1, w), max(1, h), QImage.Format_ARGB32_Premultiplied)
    image.fill(0)
    return image


def render_text(source: dict):
    from PySide6.QtGui import QColor, QFont, QPainter, QTextBlockFormat, QTextCharFormat, QTextCursor, QTextDocument, \
        QTextOption
    from PySide6.QtCore import Qt
    if not source["content"].strip():
        return None
    font = QFont(source["font"])
    font.setPixelSize(int(source["size"]))
    font.setBold(source["bold"])
    font.setItalic(source["italic"])
    doc = QTextDocument()
    doc.setDocumentMargin(0)
    doc.setDefaultFont(font)
    option = QTextOption({"left": Qt.AlignLeft, "center": Qt.AlignHCenter, "right": Qt.AlignRight}[source["align"]])
    doc.setDefaultTextOption(option)
    if source["width"] > 0:
        doc.setTextWidth(source["width"])
    doc.setPlainText(source["content"])
    cursor = QTextCursor(doc)
    cursor.select(QTextCursor.Document)
    char = QTextCharFormat()
    char.setForeground(QColor(*source["color"]))
    cursor.mergeCharFormat(char)
    block = QTextBlockFormat()
    block.setAlignment(option.alignment())
    block.setLineHeight(source["line_height"], QTextBlockFormat.LineHeightTypes.ProportionalHeight.value)
    cursor.mergeBlockFormat(block)
    size = doc.size()
    w, h = int(math.ceil(size.width())) + 2 * PAD, int(math.ceil(size.height())) + 2 * PAD
    image = _blank(w, h)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setRenderHint(QPainter.TextAntialiasing, True)
    painter.translate(PAD, PAD)
    doc.drawContents(painter)
    painter.end()
    return int(round(source["x"])) - PAD, int(round(source["y"])) - PAD, _to_rgba(image)


def render_shape(source: dict):
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtGui import QBrush, QColor, QPainter, QPen
    stroke = source["stroke"] if source["stroke_width"] > 0 else None
    half = (source["stroke_width"] / 2.0 if stroke else 0.0) + 2
    if source["shape"] == "line":
        x0, y0, x1, y1 = source["x"], source["y"], source["x1"], source["y1"]
        box = (min(x0, x1) - half, min(y0, y1) - half, max(x0, x1) + half, max(y0, y1) + half)
    else:
        box = (source["x"] - half, source["y"] - half, source["x"] + source["w"] + half, source["y"] + source["h"] + half)
    ox, oy = int(math.floor(box[0])), int(math.floor(box[1]))
    w, h = int(math.ceil(box[2])) - ox, int(math.ceil(box[3])) - oy
    if w <= 0 or h <= 0 or w * h > 400_000_000:
        return None
    image = _blank(w, h)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.translate(-ox, -oy)
    fill = source["fill"]
    painter.setBrush(QBrush(QColor(*fill)) if fill and source["shape"] != "line" else Qt.NoBrush)
    if stroke:
        pen = QPen(QColor(*stroke), source["stroke_width"])
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
    else:
        painter.setPen(Qt.NoPen)
    if source["shape"] == "line":
        if not stroke:
            painter.end()
            return None
        painter.drawLine(QPointF(source["x"], source["y"]), QPointF(source["x1"], source["y1"]))
    else:
        rect = QRectF(source["x"], source["y"], source["w"], source["h"])
        if source["shape"] == "ellipse":
            painter.drawEllipse(rect)
        elif source["radius"] > 0:
            painter.drawRoundedRect(rect, source["radius"], source["radius"])
        else:
            painter.drawRect(rect)
    painter.end()
    return ox, oy, _to_rgba(image)


def render(source: dict):
    """(x, y, RGBA uint8 droit) du rendu de la source normalisée, ou None si rien n'est visible."""
    source = normalize(source)
    if source is None:
        return None
    return render_text(source) if source["kind"] == "text" else render_shape(source)


def apply_source(layer, source: dict | None):
    """Pose `source` sur le calque et refait ses pixels (SANS historique : l'appelant l'enveloppe)."""
    layer.source = normalize(source)
    got = render(layer.source) if layer.source else None
    if got is None:
        layer.pix.clear()
    else:
        layer.pix.set_all(got[0], got[1], got[2])
