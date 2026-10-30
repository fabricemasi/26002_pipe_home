"""Rendu d'une page Design hors de l'écran : miniatures (barre des pages, modèles) et EXPORT (PNG, JPEG, PDF
multipage, SVG). La page et ses éléments sont peints DIRECTEMENT (sans `QGraphicsScene.render`) : rien d'autre du
board (post-it, CAD, overlay, sélection) n'y entre et la scène n'est pas touchée."""
from __future__ import annotations

import math
import os
from pathlib import Path

from PySide6.QtCore import QMarginsF, QRectF, QSizeF, Qt
from PySide6.QtGui import QColor, QImage, QPageLayout, QPageSize, QPainter, QPixmap
from PySide6.QtWidgets import QStyleOptionGraphicsItem

from . import design_model as dm
from .items import DesignPageItem

FORMATS = {"png": "PNG", "jpg": "JPEG", "jpeg": "JPEG", "pdf": "PDF", "svg": "SVG"}


def paint_page(painter: QPainter, page: DesignPageItem, transparent: bool = False, bleed: float = 0.0,
               exclude=(), background: bool = True):
    """Peint `page` (fond + éléments visibles, ordre d'empilement) dans `painter`, en coordonnées de la page ;
    `bleed` (unités) = fond perdu : fond et éléments débordants gardés jusqu'à cette distance des bords ;
    `background` False = éléments seuls (couche animée de la présentation)."""
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
    painter.setRenderHint(QPainter.TextAntialiasing, True)
    if background:
        page.paint_background(painter, transparent=transparent, bleed=bleed)
    painter.setClipRect(page.content_rect().adjusted(-bleed, -bleed, bleed, bleed))
    paint_elements(painter, page, [e for e in page.elements() if e not in exclude])
    painter.restore()


def paint_elements(painter: QPainter, page: DesignPageItem, elements):
    """Peint `elements` (de `page`, visibles seulement) dans l'ordre donné, en coordonnées de la page."""
    option = QStyleOptionGraphicsItem()
    page_inverse, _ok = page.sceneTransform().inverted()
    base = painter.transform()
    for element in elements:
        if not element.isVisible():
            continue
        painter.save()
        painter.setTransform(element.sceneTransform() * page_inverse * base)
        painter.setOpacity(float(element.data.get("opacity", 1.0)))
        element.paint(painter, option, None)
        text = element.text_item
        if text is not None and text.isVisible():
            painter.setTransform(text.sceneTransform() * page_inverse * base)
            text.paint(painter, option, None)
        painter.restore()


def render_image(page: DesignPageItem, scale: float = 1.0, transparent: bool = False,
                 background: str | None = None, exclude=()) -> QImage:
    w, h = page.size()
    width, height = max(1, round(w * scale)), max(1, round(h * scale))
    image = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent if transparent else QColor(background or "#ffffff"))
    painter = QPainter(image)
    painter.scale(width / w, height / h)
    paint_page(painter, page, transparent=transparent, exclude=exclude)
    painter.end()
    return image


def render_layers(page: DesignPageItem, scale: float = 1.0) -> tuple[QImage, QImage]:
    """Deux couches de la page pour l'animer : le fond seul (opaque) et les éléments seuls (fond transparent)."""
    back = render_image(page, scale, exclude=set(page.elements()))
    w, h = page.size()
    front = QImage(back.width(), back.height(), QImage.Format_ARGB32_Premultiplied)
    front.fill(Qt.transparent)
    painter = QPainter(front)
    painter.scale(back.width() / w, back.height() / h)
    paint_page(painter, page, background=False)
    painter.end()
    return back, front


def animation_units(page: DesignPageItem) -> list[list]:
    """Éléments visibles de `page` par ordre d'empilement, un groupe = une seule unité (animation « Un par un »)."""
    units, by_group = [], {}
    for element in page.elements():
        if not element.isVisible():
            continue
        group = element.data.get("group") or ""
        if group and group in by_group:
            by_group[group].append(element)
            continue
        unit = [element]
        units.append(unit)
        if group:
            by_group[group] = unit
    return units


def render_units(page: DesignPageItem, scale: float, units) -> list[tuple[QRectF, QImage]]:
    """Chaque unité peinte seule dans une image à sa taille : (rectangle dans la page, image) ; (None, None) pour
    une unité hors de la page."""
    w, h = page.size()
    bounds = QRectF(0, 0, w, h)
    out = []
    for unit in units:
        rect = QRectF()
        for element in unit:
            rect = rect.united(page.mapRectFromScene(element.sceneBoundingRect()))
        rect = rect.intersected(bounds)
        if rect.isEmpty():
            out.append((None, None))                   # hors de la page : place gardée (une unité = une entrée)
            continue
        image = QImage(max(1, math.ceil(rect.width() * scale)), max(1, math.ceil(rect.height() * scale)),
                       QImage.Format_ARGB32_Premultiplied)
        image.fill(Qt.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        painter.scale(scale, scale)
        painter.translate(-rect.topLeft())
        paint_elements(painter, page, unit)
        painter.end()
        out.append((QRectF(rect.topLeft(), QSizeF(image.width() / scale, image.height() / scale)), image))
    return out


def thumbnail(page: DesignPageItem, max_w: int, max_h: int, ratio: float = 1.0) -> QPixmap:
    w, h = page.size()
    k = min(max_w / w, max_h / h) * ratio
    pixmap = QPixmap.fromImage(render_image(page, k))
    pixmap.setDevicePixelRatio(ratio)
    return pixmap


def _replace(tmp: Path, target: Path):
    os.replace(tmp, target)


def export_pages(pages: list, path, fmt: str = "png", scale: float = 1.0, quality: int = 92,
                 transparent: bool = False, bleed_mm: float = 0.0, crop_marks: bool = False) -> list[Path]:
    """Exporte `pages` : PDF = un fichier multipage ; PNG / JPEG / SVG = un fichier par page (« nom_p2.png » à
    partir de la 2e, ou toutes numérotées s'il y en a plusieurs). Écriture par fichier temporaire puis
    remplacement (un export interrompu ne laisse pas de fichier tronqué). Retourne les fichiers écrits."""
    path = Path(path)
    fmt = fmt.lower().lstrip(".")
    if fmt not in FORMATS:
        raise ValueError(f"format inconnu : {fmt}")
    if not pages:
        return []
    if fmt == "pdf":
        return [_export_pdf(pages, path, bleed_mm, crop_marks)]
    out = []
    numbered = len(pages) > 1
    for number, page in enumerate(pages, 1):
        target = path.with_name(f"{path.stem}_p{number}{path.suffix}") if numbered else path
        tmp = target.with_name(target.name + ".part")
        if fmt == "svg":
            _export_svg(page, tmp)
        else:
            image = render_image(page, scale, transparent=transparent and fmt == "png")
            if fmt in ("jpg", "jpeg"):
                image = image.convertToFormat(QImage.Format_RGB32)
            if not image.save(str(tmp), FORMATS[fmt], quality if FORMATS[fmt] == "JPEG" else -1):
                tmp.unlink(missing_ok=True)
                raise OSError(f"écriture impossible : {target}")
        _replace(tmp, target)
        out.append(target)
    return out


MARKS_MM = 5.0          # traits de coupe : marge en plus du fond perdu, traits de 4 mm


def _export_pdf(pages, path: Path, bleed_mm: float = 0.0, crop_marks: bool = False) -> Path:
    """PDF multipage, une page PDF par page du design, à sa taille exacte (1 unité = 1/96 de pouce) ; avec un fond
    perdu, la page PDF est agrandie de `bleed_mm` de chaque côté (fond et éléments prolongés) ; avec les traits de
    coupe, d'une marge de plus où ils sont tracés dans le prolongement des bords."""
    from PySide6.QtGui import QPdfWriter
    bleed = max(0.0, float(bleed_mm)) * dm.MM
    margin = bleed + (MARKS_MM * dm.MM if crop_marks else 0.0)
    tmp = path.with_name(path.name + ".part")
    writer = QPdfWriter(str(tmp))
    writer.setResolution(300)
    writer.setCreator("PIPE FMZ — module Design")

    def layout(page):
        w, h = page.size()
        size = QPageSize(QSizeF((w + 2 * margin) / dm.MM, (h + 2 * margin) / dm.MM), QPageSize.Millimeter, "",
                         QPageSize.ExactMatch)
        return QPageLayout(size, QPageLayout.Portrait, QMarginsF(0, 0, 0, 0))

    writer.setPageLayout(layout(pages[0]))
    painter = QPainter(writer)
    for n, page in enumerate(pages):
        if n:
            writer.setPageLayout(layout(page))
            writer.newPage()
        w, h = page.size()
        painter.save()
        painter.scale(writer.width() / (w + 2 * margin), writer.height() / (h + 2 * margin))
        painter.translate(margin, margin)
        paint_page(painter, page, bleed=bleed)
        if crop_marks:
            _paint_crop_marks(painter, w, h, bleed, margin)
        painter.restore()
    painter.end()
    _replace(tmp, path)
    return path


def _paint_crop_marks(painter, w, h, bleed, margin):
    """Traits de coupe : dans le prolongement des bords de la page, hors du fond perdu."""
    from PySide6.QtCore import QLineF
    from PySide6.QtGui import QPen
    pen = QPen(QColor("#000000"), 0.25 * dm.MM)
    painter.setPen(pen)
    gap = bleed + 1.0 * dm.MM
    end = margin
    for x in (0.0, w):
        for y, sign in ((0.0, -1), (h, 1)):
            painter.drawLine(QLineF(x, y + sign * gap, x, y + sign * end))
    for y in (0.0, h):
        for x, sign in ((0.0, -1), (w, 1)):
            painter.drawLine(QLineF(x + sign * gap, y, x + sign * end, y))


def _export_svg(page, tmp: Path):
    from PySide6.QtSvg import QSvgGenerator
    w, h = page.size()
    generator = QSvgGenerator()
    generator.setFileName(str(tmp))
    generator.setSize(QSizeF(w, h).toSize())
    generator.setViewBox(QRectF(0, 0, w, h))
    generator.setTitle(dm.page_label(page.data, int(page.data.get("index", 0)) + 1))
    painter = QPainter(generator)
    paint_page(painter, page)
    painter.end()
