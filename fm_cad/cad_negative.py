"""Reticule en NEGATIF sur les zones de sa couleur (demande de l'utilisateur, 2026-11-05) : la ou le fond est proche
de la couleur du reticule (ecart <= tolerance sur chaque canal), ses pixels prennent la couleur inverse ; ailleurs,
sa couleur. Meme regle pour le curseur du systeme (image refaite seulement quand le motif change) et pour le
reticule peint par l'overlay. Le fond est l'image du viewport relevee par l'overlay (`CadOverlay.backdrop`) : sans
elle (rendu GPU, releve impossible), le reticule reste d'une couleur.

Tout est en PIXELS PHYSIQUES (rectangles de `cad_overlay.crosshair_rects`).
"""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPoint, QRect
from PySide6.QtGui import QColor, QCursor, QImage, QPainter, QPixmap

_ARRAYS: dict = {}            # id(fond) -> (fond, image gardee, tableau BGR) : un seul a la fois
_CURSORS: dict = {}           # signature -> QCursor
MAX_CURSORS = 256


def negative_of(color: str) -> QColor:
    c = QColor(color)
    return QColor(255 - c.red(), 255 - c.green(), 255 - c.blue())


def backdrop_array(backdrop):
    """Tableau (h, w, 3) BGR du fond (QImage ou QPixmap), garde tant que le fond ne change pas."""
    if backdrop is None:
        return None
    key = id(backdrop)
    found = _ARRAYS.get(key)
    if found is not None and found[0] is backdrop:
        return found[2]
    image = backdrop.toImage() if isinstance(backdrop, QPixmap) else backdrop
    if image.isNull():
        return None
    image = image.convertToFormat(QImage.Format_RGB32)
    h, w, line = image.height(), image.width(), image.bytesPerLine()
    array = np.frombuffer(image.constBits(), dtype=np.uint8, count=h * line).reshape(h, line // 4, 4)[:, :w, :3]
    _ARRAYS.clear()
    _ARRAYS[key] = (backdrop, image, array)
    return array


def split(rects, color: str, tol: int, array, dx: int, dy: int) -> list:
    """[(x, y, w, h, QColor)] : chaque rectangle d'UN pixel de large / haut coupe en morceaux de la couleur du
    reticule ou de son negatif selon le fond ; (dx, dy) : pixel du fond qui correspond au pixel (0, 0) des
    rectangles. Les autres rectangles et ceux hors du fond gardent la couleur."""
    ink, neg = QColor(color), negative_of(color)
    if array is None or tol <= 0:
        return [(x, y, w, h, ink) for x, y, w, h in rects]
    target = np.array([ink.blue(), ink.green(), ink.red()], dtype=np.int16)
    height, width = array.shape[0], array.shape[1]
    out = []
    for x, y, w, h in rects:
        if w <= 0 or h <= 0:
            continue
        horizontal = h == 1
        if not horizontal and w != 1:
            out.append((x, y, w, h, ink))
            continue
        bx, by = x + dx, y + dy
        if horizontal:
            lo, hi = max(0, bx), min(width, bx + w)
            if by < 0 or by >= height or lo >= hi:
                out.append((x, y, w, h, ink))
                continue
            run = array[by, lo:hi]
        else:
            lo, hi = max(0, by), min(height, by + h)
            if bx < 0 or bx >= width or lo >= hi:
                out.append((x, y, w, h, ink))
                continue
            run = array[lo:hi, bx]
        near = (np.abs(run.astype(np.int16) - target).max(axis=1) <= tol)
        flags = np.zeros(w if horizontal else h, dtype=bool)
        start = (lo - bx) if horizontal else (lo - by)
        flags[start:start + len(near)] = near
        if not flags.any():
            out.append((x, y, w, h, ink))
            continue
        edges = np.flatnonzero(np.diff(flags.astype(np.int8))) + 1
        bounds = [0, *edges.tolist(), len(flags)]
        for a, b in zip(bounds[:-1], bounds[1:]):
            c = neg if flags[a] else ink
            out.append((x + a, y, b - a, 1, c) if horizontal else (x, y + a, 1, b - a, c))
    return out


def cross_array(row, col, reach: int, background=None):
    """Image (2r+1, 2r+1, 3) faite d'une seule ligne et d'une seule colonne (pixels BGRA premultiplies lus sous le
    reticule, rendu GPU), composes sur `background` (QColor : le fond du board, peint sous la couche) ; le reste et
    les pixels illisibles (-1) ne ressemblent a aucune couleur (jamais en negatif)."""
    size = 2 * reach + 1
    bg = QColor(background) if background is not None else QColor(0, 0, 0)
    under = np.array([bg.blue(), bg.green(), bg.red()], dtype=np.float32)
    array = np.full((size, size, 3), -1000, dtype=np.int16)
    for strip, place in ((row, (reach, slice(None))), (col, (slice(None), reach))):
        strip = np.asarray(strip, dtype=np.float32)
        ok = strip[:, 3] >= 0
        shown = strip[:, :3] + under * (1.0 - strip[:, 3:4] / 255.0)
        array[place] = np.where(ok[:, None], np.clip(np.rint(shown), 0, 255), -1000).astype(np.int16)
    return array


def adapted_cursor(args: tuple, array, view_px: tuple):
    """Curseur du systeme du reticule (`args` = arguments de `cad_overlay.native_cursor`) avec ses pixels en negatif
    sur les zones de sa couleur ; None si aucun pixel n'est concerne (le curseur ordinaire convient). `view_px` :
    pixel du fond sous le point chaud."""
    from .cad_overlay import BADGE_ROOM, crosshair_rects, paint_memory_badge
    reach, pickbox, color, ratio, badge, tol = args
    room = max(reach, pickbox, BADGE_ROOM if badge else 0)
    size = 2 * room + 1
    device = max(1, round(size * ratio))
    centre = round(room * ratio)
    rects = crosshair_rects(centre, centre, round(reach * ratio), round(pickbox * ratio) if pickbox > 0 else 0)
    pieces = split(rects, color, tol, array, view_px[0] - centre, view_px[1] - centre)
    negative = [p for p in pieces if p[4] != QColor(color)]
    if not negative:
        return None
    key = (args, tuple((x, y, w, h) for x, y, w, h, _c in negative))
    cursor = _CURSORS.get(key)
    if cursor is not None:
        return cursor
    pixmap = QPixmap(device, device)
    pixmap.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pixmap)
    for x, y, w, h, c in pieces:
        painter.fillRect(QRect(x, y, w, h), c)
    if badge:
        painter.scale(ratio, ratio)
        paint_memory_badge(painter, room + 0.5 / ratio, room + 0.5 / ratio, badge, color)
    painter.end()
    pixmap.setDevicePixelRatio(ratio)
    if len(_CURSORS) >= MAX_CURSORS:
        _CURSORS.clear()
    cursor = _CURSORS[key] = QCursor(pixmap, room, room)
    return cursor
