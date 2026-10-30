"""Texte COURBÉ (effet « Courbe » de Canva) : champ `curve` d'un texte, de -100 (creux, en sourire) à 100 (arche) ;
0 = droit. Le texte est posé sur UNE ligne le long d'un arc (100 = presque un cercle entier), chaque lettre avec sa
police, sa couleur et son contour (parties stylées comprises). La boîte prend la taille de l'arc ; pendant l'édition
le texte redevient droit (comme Canva). Calculé une fois par changement (`curve_layout`, gardé par l'élément)."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFontMetricsF, QPainterPath, QPen, QTransform

MAX_TURN = 0.95                # |curve| = 100 : 95 % d'un tour


def _characters(document, base_font, base_color):
    """(caractère, police, couleur, contour) de tout le texte ; paragraphes joints par une espace."""
    out = []
    block = document.begin()
    while block.isValid():
        if out:
            out.append((" ", base_font, base_color, None))
        it = block.begin()
        while not it.atEnd():
            fragment = it.fragment()
            if fragment.isValid():
                fmt = fragment.charFormat()
                font = fmt.font().resolve(base_font)
                brush = fmt.foreground()
                color = brush.color() if brush.style() != Qt.NoBrush else base_color
                outline = fmt.textOutline()
                outline = outline if outline.style() != Qt.NoPen and outline.widthF() > 0 else None
                for ch in fragment.text():
                    out.append((ch, font, color, outline))
            it += 1
        block = block.next()
    return out


def curve_layout(document, base_font, base_color, curve: float):
    """-> (lettres [(chemin, couleur, contour, transformation)], rectangle englobant) ; centre de l'arc en (0, 0)
    pour le milieu du texte, à recaler par l'appelant (`-rect.topLeft()`)."""
    chars = _characters(document, base_font, base_color)
    advances = [QFontMetricsF(font).horizontalAdvance(ch) for ch, font, _c, _o in chars]
    total = sum(advances)
    turn = max(-1.0, min(1.0, curve / 100.0)) * MAX_TURN * 2 * math.pi
    radius = total / abs(turn) if abs(turn) > 1e-6 and total > 0 else 0.0
    glyphs, bounds = [], QRectF()
    s = -total / 2
    for (ch, font, color, outline), advance in zip(chars, advances):
        metrics = QFontMetricsF(font)
        middle = s + advance / 2
        s += advance
        if ch.isspace():
            continue
        path = QPainterPath()
        path.addText(QPointF(-advance / 2, 0), font, ch)
        if radius > 0:
            phi = middle / radius
            if turn > 0:                       # arche : lettres à l'extérieur du cercle, centre dessous
                point = QPointF(radius * math.sin(phi), radius - radius * math.cos(phi))
                angle = math.degrees(phi)
            else:                              # creux : lettres à l'intérieur, centre dessus
                point = QPointF(radius * math.sin(phi), -radius + radius * math.cos(phi))
                angle = -math.degrees(phi)
        else:
            point, angle = QPointF(middle, 0), 0.0
        transform = QTransform()
        transform.translate(point.x(), point.y())
        transform.rotate(angle)
        box = QRectF(-advance / 2, -metrics.ascent(), advance, metrics.ascent() + metrics.descent())
        bounds = bounds.united(transform.mapRect(box))
        glyphs.append((path, color, outline, transform))
    return glyphs, bounds


def paint_curve(painter, glyphs, offset: QPointF, shadow: dict | None = None):
    """Peint les lettres (décalées de `offset`) ; ombre = mêmes lettres teintées et décalées (sans flou)."""
    painter.save()
    painter.translate(offset)
    if shadow and shadow.get("enabled"):
        tint = QColor(shadow.get("color", "#59000000"))
        shift = QPointF(float(shadow.get("dx", 0.0)), float(shadow.get("dy", 0.0)))
        for path, _color, _outline, transform in glyphs:
            painter.save()
            painter.translate(shift)
            painter.setTransform(transform, True)
            painter.fillPath(path, tint)
            painter.restore()
    for path, color, outline, transform in glyphs:
        painter.save()
        painter.setTransform(transform, True)
        painter.fillPath(path, QBrush(color))
        if outline is not None:
            painter.strokePath(path, QPen(outline))
        painter.restore()
    painter.restore()
