"""Cadre des icônes (demande de l'utilisateur, 2026-11-12) : TOUTE icône (dessinée par le code, SVG, PNG, image
choisie dans les réglages) est ramenée au bord de ses pixels visibles puis recentrée dans son cadre avec la marge
« Marge des icônes » (Thème > Général, `icon_margin`, % du cadre DE CHAQUE CÔTÉ, défaut 20).

- `paint_framed(painter, rect, draw, key)` : icône dessinée par le code. Le dessin est fait hors écran, mesuré, puis
  REFAIT à la bonne échelle (les traits gardent leur épaisseur, rien n'est agrandi en image) ; résultat gardé par
  `key` (None = pas de cache : l'appelant garde déjà l'image). Imbriqué (un peintre cadré qui en appelle un autre) :
  l'intérieur peint tel quel.
- `framed(nom)` : décorateur des peintres `(painter, kind, rect, color, ...)`.
- `frame_image` / `frame_pixmap` : image déjà rendue (SVG rendu 4x, PNG, image importée), même toile.
- `framed_icon(chemin)` : QIcon d'un fichier (menus).
- `set_margin(valeur)` : appliqué par l'appli et l'éditeur de thème ; les caches inscrits par `on_change` sont vidés.
N'importe RIEN de l'appli (règle de fm_theme)."""
from __future__ import annotations

import functools
import math
from pathlib import Path

from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPixmap

MARGIN = 20.0
MARGIN_MAX = 40.0
CACHE_MAX = 3000
_PAD = 0.5                    # toile hors écran : le cadre + 50 % de chaque côté (un dessin qui déborde reste entier)
_CACHE: dict = {}
_ICON_CACHE: dict = {}
_LISTENERS: list = []
_DEPTH = 0


def margin() -> float:
    return MARGIN


def set_margin(value) -> bool:
    """Marge (% de chaque côté, 0 à MARGIN_MAX) ; vrai si elle a changé (caches vidés, icônes refaites à leur
    prochaine peinture)."""
    global MARGIN
    try:
        value = max(0.0, min(MARGIN_MAX, float(value)))
    except (TypeError, ValueError):
        value = 20.0
    if value == MARGIN:
        return False
    MARGIN = value
    _CACHE.clear()
    _ICON_CACHE.clear()
    for listener in list(_LISTENERS):
        try:
            listener()
        except Exception:                               # noqa: BLE001 - un cache d'un module ne bloque pas les autres
            pass
    return True


def on_change(listener) -> None:
    """`listener()` appelé quand la marge change (vider un cache d'icônes)."""
    if listener not in _LISTENERS:
        _LISTENERS.append(listener)


# -- Mesure ------------------------------------------------------------------------------------------------------------

def content_rect(image: QImage) -> QRect:
    """Rectangle des pixels VISIBLES (alpha > 8) ; toute l'image si elle est opaque ou entièrement transparente."""
    if image.isNull() or not image.hasAlphaChannel():
        return image.rect()
    import numpy as np
    if image.format() not in (QImage.Format_ARGB32, QImage.Format_ARGB32_Premultiplied):
        image = image.convertToFormat(QImage.Format_ARGB32_Premultiplied)
    w, h = image.width(), image.height()
    data = np.frombuffer(image.constBits(), dtype=np.uint8, count=image.sizeInBytes()).reshape(h, image.bytesPerLine())
    alpha = data[:, 3:w * 4:4] > 8                      # ARGB32 en mémoire (petit-boutiste) : B, G, R, A
    rows, cols = np.flatnonzero(alpha.any(axis=1)), np.flatnonzero(alpha.any(axis=0))
    if not rows.size:
        return image.rect()
    return QRect(int(cols[0]), int(rows[0]), int(cols[-1] - cols[0] + 1), int(rows[-1] - rows[0] + 1))


def inner_rect(rect: QRectF, value: float | None = None) -> QRectF:
    """Le cadre moins la marge (% du plus petit côté, de chaque côté)."""
    rect = QRectF(rect)
    m = min(rect.width(), rect.height()) * (MARGIN if value is None else value) / 100
    return rect.adjusted(m, m, -m, -m)


def _fit(size_w: float, size_h: float, box: QRectF) -> QRectF:
    """`size` à l'échelle pour tenir dans `box` (proportions gardées), centré."""
    if size_w <= 0 or size_h <= 0:
        return QRectF(box)
    k = min(box.width() / size_w, box.height() / size_h)
    out = QRectF(0, 0, size_w * k, size_h * k)
    out.moveCenter(box.center())
    return out


# -- Images déjà rendues ----------------------------------------------------------------------------------------------

def frame_image(image: QImage, value: float | None = None) -> QImage:
    """Même toile ; contenu ramené au bord de ses pixels visibles puis recentré avec la marge."""
    if image.isNull():
        return image
    r = content_rect(image)
    target = _fit(r.width(), r.height(), inner_rect(QRectF(image.rect()), value))
    out = QImage(image.size(), QImage.Format_ARGB32_Premultiplied)
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.SmoothPixmapTransform, True)
    p.drawImage(target, image, QRectF(r))
    p.end()
    out.setDevicePixelRatio(image.devicePixelRatio())
    return out


def frame_into(image: QImage, width: int, height: int, value: float | None = None) -> QImage:
    """Nouvelle toile `width` x `height` (px) : contenu visible de `image` posé dans le cadre moins la marge."""
    out = QImage(max(1, int(width)), max(1, int(height)), QImage.Format_ARGB32_Premultiplied)
    out.fill(Qt.transparent)
    if image.isNull():
        return out
    r = content_rect(image)
    p = QPainter(out)
    p.setRenderHint(QPainter.SmoothPixmapTransform, True)
    p.drawImage(_fit(r.width(), r.height(), inner_rect(QRectF(out.rect()), value)), image, QRectF(r))
    p.end()
    return out


def frame_pixmap(pix: QPixmap, value: float | None = None) -> QPixmap:
    if pix is None or pix.isNull():
        return pix
    out = QPixmap.fromImage(frame_image(pix.toImage(), value))
    out.setDevicePixelRatio(pix.devicePixelRatio())
    return out


def framed_icon(path, size: int = 128) -> QIcon:
    """QIcon d'un fichier image / SVG, cadré (menus). Cache par (chemin, date, marge)."""
    path = Path(path)
    try:
        key = (str(path), path.stat().st_mtime, size)
    except OSError:
        return QIcon(str(path))
    icon = _ICON_CACHE.get(key)
    if icon is None:
        source = QIcon(str(path)).pixmap(size, size)
        if source.isNull():
            return QIcon(str(path))
        image = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
        image.fill(Qt.transparent)
        p = QPainter(image)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        p.drawPixmap(_fit(source.width(), source.height(), QRectF(0, 0, size, size)), source, QRectF(source.rect()))
        p.end()
        icon = QIcon(QPixmap.fromImage(frame_image(image)))
        if len(_ICON_CACHE) > 400:
            _ICON_CACHE.clear()
        _ICON_CACHE[key] = icon
    return icon


# -- Icônes dessinées par le code -----------------------------------------------------------------------------------

def _device_scale(painter: QPainter) -> float:
    device = painter.device()
    dpr = device.devicePixelRatioF() if device is not None else 1.0
    t = painter.worldTransform()
    return max(0.1, dpr * math.sqrt(abs(t.determinant()) or 1.0))


def _render(painter: QPainter, w: float, h: float, draw, scale: float, zoom: float = 1.0):
    """`draw(p, rect)` dans un cadre w x h au milieu d'une toile hors écran (px de l'écran), le tout agrandi `zoom`
    fois en vectoriel ; (image, contenu)."""
    pad_w, pad_h = w * _PAD, h * _PAD
    image = QImage(max(1, math.ceil((w + 2 * pad_w) * scale * zoom)), max(1, math.ceil((h + 2 * pad_h) * scale * zoom)),
                   QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)
    p = QPainter(image)
    p.setRenderHints(painter.renderHints())
    p.setFont(painter.font())
    p.setPen(painter.pen())
    p.setBrush(painter.brush())
    p.scale(scale * zoom, scale * zoom)
    global _DEPTH
    _DEPTH += 1
    try:
        draw(p, QRectF(pad_w, pad_h, w, h))
    finally:
        _DEPTH -= 1
        p.end()
    bbox = content_rect(image)
    empty = bbox == image.rect() and not _has_ink(image)
    return image, (None if empty else bbox)


def _has_ink(image: QImage) -> bool:
    import numpy as np
    data = np.frombuffer(image.constBits(), dtype=np.uint8, count=image.sizeInBytes())
    return bool(data.reshape(image.height(), image.bytesPerLine())[:, 3:image.width() * 4:4].max(initial=0) > 8)


def _framed(painter: QPainter, w: float, h: float, draw, scale: float):
    """(pixmap aux px de l'écran, place dans le cadre en px logiques) ; (None, None) si rien n'est dessiné."""
    box = inner_rect(QRectF(0, 0, w, h))
    image, bbox = _render(painter, w, h, draw, scale)
    if bbox is None or box.width() <= 0 or box.height() <= 0:
        return None, None
    def ratio(b):
        return max(0.25, min(8.0, min(box.width() * scale / b.width(), box.height() * scale / b.height())))
    k = ratio(bbox)
    cw, ch = w, h
    if abs(k - 1.0) > 0.02:     # 1) refait dans un cadre a la bonne echelle : traits nets, epaisseurs gardees
        image2, bbox2 = _render(painter, w * k, h * k, draw, scale)
        if bbox2 is not None:
            image, bbox, cw, ch = image2, bbox2, w * k, h * k
    z = ratio(bbox)
    if abs(z - 1.0) > 0.03:     # 2) dessin de taille FIXE (insensible au cadre) : agrandi en vectoriel (net)
        image3, bbox3 = _render(painter, cw, ch, draw, scale, zoom=z)
        if bbox3 is not None:
            image, bbox = image3, bbox3
    crop = QPixmap.fromImage(image.copy(bbox))
    lw, lh = bbox.width() / scale, bbox.height() / scale
    place = _fit(lw, lh, box) if (lw > box.width() + 0.5 or lh > box.height() + 0.5) else QRectF(0, 0, lw, lh)
    place.moveCenter(box.center())
    # Coin posé sur un pixel de l'écran (aucun flou de rééchantillonnage) quand l'image est gardée telle quelle.
    if place.width() == lw and place.height() == lh:
        place.moveTopLeft(QPointF(round(place.x() * scale) / scale, round(place.y() * scale) / scale))
    return crop, place


def paint_framed(painter: QPainter, rect, draw, key=None) -> None:
    """Peint `draw(painter, rect)` ramené au bord de son dessin puis recentré dans `rect` avec la marge."""
    rect = QRectF(rect)
    if _DEPTH or rect.width() < 2 or rect.height() < 2:
        draw(painter, rect)
        return
    scale = _device_scale(painter)
    cache_key = None
    if key is not None:
        cache_key = (key, round(rect.width(), 2), round(rect.height(), 2), round(scale, 3), MARGIN,
                     painter.font().key(), painter.renderHints().value)
        hit = _CACHE.get(cache_key)
        if hit is not None:
            pix, place = hit
            if pix is not None:
                _draw(painter, pix, place.translated(rect.topLeft()))
            return
    pix, place = _framed(painter, rect.width(), rect.height(), draw, scale)
    if cache_key is not None:
        if len(_CACHE) > CACHE_MAX:
            _CACHE.clear()
        _CACHE[cache_key] = (pix, place)
    if pix is not None:
        _draw(painter, pix, place.translated(rect.topLeft()))


def _draw(painter: QPainter, pix: QPixmap, target: QRectF) -> None:
    hint = painter.testRenderHint(QPainter.SmoothPixmapTransform)
    painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
    painter.drawPixmap(target, pix, QRectF(pix.rect()))
    painter.setRenderHint(QPainter.SmoothPixmapTransform, hint)


def _color_key(color):
    try:
        return QColor(color).rgba()
    except TypeError:
        return repr(color)


def framed(name: str):
    """Décorateur d'un peintre d'icônes `(painter, kind, rect, color, *args, **kw)` : cadré, gardé en cache par
    (nom, kind, couleur, autres arguments). `fonction.raw` = le peintre d'origine."""
    def decorate(fn):
        @functools.wraps(fn)
        def wrapper(painter, kind, rect, color, *args, **kw):
            try:
                key = (name, kind, _color_key(color), args, tuple(sorted(kw.items())))
                hash(key)
            except TypeError:
                key = None
            paint_framed(painter, rect, lambda p, r: fn(p, kind, r, color, *args, **kw), key)
        wrapper.raw = fn
        return wrapper
    return decorate
