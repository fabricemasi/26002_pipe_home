"""Rendu d'une page Design hors de l'écran : miniatures (barre des pages, modèles) et EXPORT (PNG, JPEG, PDF
multipage, SVG). La page et ses éléments sont peints DIRECTEMENT (sans `QGraphicsScene.render`) : rien d'autre du
board (post-it, CAD, overlay, sélection) n'y entre et la scène n'est pas touchée."""
from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QMarginsF, QRectF, QSizeF, Qt
from PySide6.QtGui import QColor, QImage, QPageLayout, QPageSize, QPainter, QPixmap
from PySide6.QtWidgets import QStyleOptionGraphicsItem

from . import design_model as dm
from .items import DesignPageItem

FORMATS = {"png": "PNG", "jpg": "JPEG", "jpeg": "JPEG", "pdf": "PDF", "svg": "SVG"}


def paint_page(painter: QPainter, page: DesignPageItem, transparent: bool = False):
    """Peint `page` (fond + éléments visibles, ordre d'empilement) dans `painter`, en coordonnées de la page."""
    option = QStyleOptionGraphicsItem()
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
    painter.setRenderHint(QPainter.TextAntialiasing, True)
    page.paint_background(painter, transparent=transparent)
    painter.setClipRect(page.content_rect())
    page_inverse, _ok = page.sceneTransform().inverted()
    base = painter.transform()
    for element in page.elements():
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
    painter.restore()


def render_image(page: DesignPageItem, scale: float = 1.0, transparent: bool = False,
                 background: str | None = None) -> QImage:
    w, h = page.size()
    width, height = max(1, round(w * scale)), max(1, round(h * scale))
    image = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent if transparent else QColor(background or "#ffffff"))
    painter = QPainter(image)
    painter.scale(width / w, height / h)
    paint_page(painter, page, transparent=transparent)
    painter.end()
    return image


def thumbnail(page: DesignPageItem, max_w: int, max_h: int, ratio: float = 1.0) -> QPixmap:
    w, h = page.size()
    k = min(max_w / w, max_h / h) * ratio
    pixmap = QPixmap.fromImage(render_image(page, k))
    pixmap.setDevicePixelRatio(ratio)
    return pixmap


def _replace(tmp: Path, target: Path):
    os.replace(tmp, target)


def export_pages(pages: list, path, fmt: str = "png", scale: float = 1.0, quality: int = 92,
                 transparent: bool = False) -> list[Path]:
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
        return [_export_pdf(pages, path)]
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


def _export_pdf(pages, path: Path) -> Path:
    from PySide6.QtGui import QPdfWriter
    tmp = path.with_name(path.name + ".part")
    writer = QPdfWriter(str(tmp))
    writer.setResolution(300)
    writer.setCreator("PIPE FMZ — module Design")

    def layout(page):
        w, h = page.size()
        size = QPageSize(QSizeF(w / dm.MM, h / dm.MM), QPageSize.Millimeter, "", QPageSize.ExactMatch)
        return QPageLayout(size, QPageLayout.Portrait, QMarginsF(0, 0, 0, 0))

    writer.setPageLayout(layout(pages[0]))
    painter = QPainter(writer)
    for n, page in enumerate(pages):
        if n:
            writer.setPageLayout(layout(page))
            writer.newPage()
        w, h = page.size()
        painter.save()
        painter.scale(writer.width() / w, writer.height() / h)
        paint_page(painter, page)
        painter.restore()
    painter.end()
    _replace(tmp, path)
    return path


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
