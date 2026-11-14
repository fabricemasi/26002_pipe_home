"""Mise à l’échelle et cadrage des pixmaps.

Carte et pièges : docs/agents/apercus.md.
"""

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QPainter, QPixmap

def _smooth_scale_down(pix: QPixmap, target: QSize, mode=Qt.KeepAspectRatioByExpanding) -> QPixmap:
    """Reduit `pix` vers `target` par MOITIES SUCCESSIVES (mipmap), PAS en
    un seul saut quand l'ecart est grand — voir _paint_row_image, la
    remarque de l'utilisateur, "je veux que toutes les icones soient
    parfaitement redimensionnables sans pixelisation mais avec un super
    antialiasing dans le cas ou elle serait plus petite que l'originale".
    Un seul Qt.SmoothTransformation directement d'une haute resolution
    (voir SOFTWARE_ICON_SIZE) vers une PETITE taille de ligne (ratio de
    reduction > 2x) reste un filtre bilineaire simple, qui peut aliaser/
    perdre du detail fin (traits, contours nets) — chaque division par 2
    PRE-MOYENNE reellement 4 pixels source en 1 (une vraie supersample),
    avant qu'une derniere passe (SmoothTransformation, ecart <2x
    restant) ajuste la taille EXACTE demandee sur un pas dorenavant fin."""
    while pix.width() > target.width() * 2 and pix.height() > target.height() * 2:
        pix = pix.scaled(
            max(1, pix.width() // 2), max(1, pix.height() // 2),
            Qt.IgnoreAspectRatio, Qt.SmoothTransformation,
        )
    return pix.scaled(target, mode, Qt.SmoothTransformation)

# Marge des icones (Theme > General > « Marge des icônes », `icon_margin`, % du cadre DE CHAQUE COTE) : demande de
# l'utilisateur, 2026-11-12 — chaque icone est ramenee au bord de ses pixels visibles puis recentree avec CETTE marge.
# Valeur et mesure : fm_theme/icon_frame.py (source unique, toutes les icones de l'appli).
from fm_theme import icon_frame as _icon_frame


def _content_rect(pix: QPixmap) -> QRect:
    """Rectangle des pixels VISIBLES (alpha > 8) ; tout le pixmap s'il est opaque ou entierement transparent."""
    if pix.isNull() or not pix.hasAlphaChannel():
        return pix.rect()
    return _icon_frame.content_rect(pix.toImage())


def _contain_square(pix: QPixmap, size: int, margin: float | None = None) -> QPixmap:
    """Redimensionne `pix` pour tenir ENTIEREMENT dans un carre `size`x`size`
    (contrairement aux apercus/vignettes, qui recadrent en "cover") :
    centree, sans rien couper, le reste transparent — voir
    software_icon_pixmap, la remarque de l'utilisateur, "contrairement aux
    apercus, l'icone, si elle n'est pas totalement carree doit apparaitre
    entiere dans l'espace reserve". L'icone est d'abord ramenee au bord de ses
    pixels visibles, puis posee avec la marge `margin` (% de chaque cote ;
    defaut : ICON_MARGIN, reglage du theme)."""
    m = max(0.0, min(_icon_frame.MARGIN_MAX, float(_icon_frame.MARGIN if margin is None else margin)))
    rect = _content_rect(pix)
    if rect != pix.rect():
        pix = pix.copy(rect)
    inner = max(1, round(size * (1 - 2 * m / 100)))
    scaled = _smooth_scale_down(pix, QSize(inner, inner), Qt.KeepAspectRatio)
    canvas = QPixmap(size, size)
    canvas.fill(Qt.transparent)
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
    x = (size - scaled.width()) // 2
    y = (size - scaled.height()) // 2
    painter.drawPixmap(x, y, scaled)
    painter.end()
    return canvas

def _cover_crop_rect(pix: QPixmap, width: int, height: int) -> QPixmap:
    """MEME principe que _cover_crop_square, mais pour un rectangle
    largeur x hauteur QUELCONQUE (pas necessairement carre) — voir
    _SquarePreviewImage.set_rect/Colonnes > Apercu > Image > Ratio, la
    remarque de l'utilisateur, "je veux une section ratio". _smooth_
    scale_down (PAS un .scaled() direct) — voir sa docstring, la remarque
    de l'utilisateur, "les apercus sont tres flous, est-il possible de
    les rendre plus nets ?" : une capture d'ecran/vignette perso est
    souvent BIEN plus haute resolution que le bloc Focus ou elle
    s'affiche, un seul saut de mise a l'echelle y perdait du detail fin."""
    width, height = max(1, width), max(1, height)
    scaled = _smooth_scale_down(pix, QSize(width, height), Qt.KeepAspectRatioByExpanding)
    x = max(0, (scaled.width() - width) // 2)
    y = max(0, (scaled.height() - height) // 2)
    return scaled.copy(x, y, width, height)
