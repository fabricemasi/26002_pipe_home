"""Rendu des effets TRAMÉS (Qt) : flou gaussien, contour progressif, ombre portée, lueur externe (`appearance.py`).

L'objet est peint dans une image à la résolution de l'écran (transformation du peintre), les effets y sont appliqués,
puis l'image est posée. Comme pour le masque d'opacité, ce travail n'est fait qu'à la (re)création de l'image gardée de
l'élément (`DeviceCoordinateCache` : zoom, changement de l'objet), jamais à chaque image du board.
Flou = réduction / agrandissement lissés successifs (approximation rapide d'un flou gaussien : ~0,3 ms pour 400 ×
400 px au lieu d'une convolution) ; rayon en unités du board, converti en pixels par l'échelle du peintre."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QTransform

from . import appearance

MAX_PIXELS = 4096 * 4096


def soften(image: QImage, radius_px: float) -> QImage:
    """Flou approché de rayon `radius_px` (pixels) : deux passes réduction / agrandissement lissés."""
    if radius_px < 0.6:
        return image
    w, h = image.width(), image.height()
    factor = max(1.0, radius_px / 1.6)
    sw, sh = max(1, round(w / factor)), max(1, round(h / factor))
    out = image
    for _ in range(2):
        small = out.scaled(sw, sh, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        out = small.scaled(w, h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    return out


def tinted(silhouette: QImage, color: str, opacity: float) -> QImage:
    """Même forme (alpha), d'une seule couleur."""
    out = QImage(silhouette)
    p = QPainter(out)
    p.setCompositionMode(QPainter.CompositionMode_SourceIn)
    c = QColor(color)
    c.setAlphaF(c.alphaF() * max(0.0, min(1.0, opacity)))
    p.fillRect(out.rect(), c)
    p.end()
    return out


def _zooming(item) -> bool:
    scene = item.scene()
    views = scene.views() if scene is not None else []
    return bool(views) and hasattr(views[0], "zooming") and views[0].zooming()


def paint_with_effects(item, painter: QPainter, paint_vector) -> None:
    """Peint `item` (fonction `paint_vector(painter)`) avec ses effets tramés actifs. Pendant un ZOOM CONTINU, la
    dernière image composée est reposée à la nouvelle échelle (refaire les effets de 200 objets coûtait ~180 ms par
    cran) ; elle est refaite nette à l'arrêt du zoom (la vue remet les images gardées, `BoardView._zoom_settled`)."""
    data = item.data
    effects = appearance.active(data, appearance.RASTER)
    world = painter.worldTransform()
    local = item.paint_margin()
    kept = getattr(item, "_fx_image", None)
    if kept is not None and kept[0] == item._fx_generation and _zooming(item):
        painter.save()
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.drawImage(kept[1], kept[2], QRectF(kept[2].rect()))
        painter.restore()
        return
    device = world.mapRect(local).toAlignedRect()
    if device.isEmpty() or device.width() * device.height() > MAX_PIXELS:
        paint_vector(painter)
        return
    scale = math.sqrt(abs(world.determinant())) or 1.0
    shift = QTransform.fromTranslate(-device.x(), -device.y())
    art = QImage(device.size(), QImage.Format_ARGB32_Premultiplied)
    art.fill(Qt.transparent)
    p = QPainter(art)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setTransform(world * shift)
    paint_vector(p)
    p.end()
    for e in effects:
        if e["type"] == "blur" and e["radius"] > 0:
            art = soften(art, e["radius"] * scale)
        elif e["type"] == "feather" and e["radius"] > 0:
            edges = soften(art, e["radius"] * scale)            # bords adoucis vers l'intérieur
            p = QPainter(art)
            p.setCompositionMode(QPainter.CompositionMode_DestinationIn)
            p.drawImage(0, 0, edges)
            p.end()
    result = QImage(device.size(), QImage.Format_ARGB32_Premultiplied)
    result.fill(Qt.transparent)
    p = QPainter(result)
    for e in effects:                                           # dessous : ombre, lueur (dans l'ordre)
        if e["type"] not in ("shadow", "glow"):
            continue
        under = soften(tinted(art, e["color"], e["opacity"]), e["blur"] * scale)
        offset = QPointF(0.0, 0.0)
        if e["type"] == "shadow":                               # décalage en unités, porté à l'écran
            o = world.map(QPointF(e["dx"], e["dy"])) - world.map(QPointF(0.0, 0.0))
            offset = QPointF(o.x(), o.y())
        p.drawImage(offset, under)
    p.drawImage(0, 0, art)
    p.end()
    painter.save()
    painter.resetTransform()
    painter.drawImage(device.topLeft(), result)
    painter.restore()
    inverse, ok = world.inverted()                              # place de l'image dans le repère de l'élément
    if ok:
        item._fx_image = (item._fx_generation, inverse.mapRect(QRectF(device)), result)
