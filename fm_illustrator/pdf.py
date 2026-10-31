"""Export PDF du module Illustrator (Qt, `QPdfWriter`) : une PAGE PAR PLAN DE TRAVAIL, à sa taille exacte
(1 unité du board = 1/96 de pouce = 0,75 pt), ou le cadre de tout le dessin.

Seuls les objets du module sont peints, un par un, par leur propre peinture (`paint_content`) : tracés, textes (en
contours vectoriels : pas de police incorporée, texte non sélectionnable dans le PDF), dégradés, masques
d'écrêtage restent VECTORIELS ; les effets tramés et les masques d'opacité sont des images (à `DPI`) ; les images
placées sont incorporées en PLEINE résolution (pas l'image réduite à 2 400 px de l'affichage). Ni sélection, ni
repères, ni autres modules du board. Mode Tracés et texte en édition : ignorés le temps de l'export. Écriture
atomique (`.part` puis renommage)."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QMarginsF, QRectF, QSizeF
from PySide6.QtGui import QColor, QPageLayout, QPageSize, QPainter, QPdfWriter

from .items import IllImageItem

DPI = 300                               # résolution des parties tramées (effets, masques d'opacité)
POINTS_PER_UNIT = 72.0 / 96.0


def _page_size(rect: QRectF) -> QPageSize:
    return QPageSize(QSizeF(rect.width() * POINTS_PER_UNIT, rect.height() * POINTS_PER_UNIT), QPageSize.Point,
                     "", QPageSize.ExactMatch)


def export_pdf(ctl, path, pages: list[tuple[QRectF, str]], title: str = "") -> Path:
    """`pages` = [(zone de la scène, couleur du fond ou "")] ; une page par zone."""
    target = Path(path)
    part = target.with_name(target.name + ".part")
    scene = ctl.scene
    ctl.end_text_edit()
    outline = getattr(scene, "ill_outline", False)
    scene.ill_outline = False
    IllImageItem.export_images = {}                     # images en pleine résolution (le temps de l'export)
    writer = QPdfWriter(str(part))
    writer.setResolution(DPI)
    writer.setTitle(title)
    writer.setCreator("PIPE FMZ — module Illustrator")
    writer.setPageMargins(QMarginsF(0, 0, 0, 0), QPageLayout.Point)
    writer.setPageSize(_page_size(pages[0][0]))
    objects = ctl.objects()
    painter = QPainter(writer)
    try:
        for n, (rect, background) in enumerate(pages):
            if n:
                writer.setPageSize(_page_size(rect))
                writer.newPage()
            k = DPI / 96.0
            painter.save()
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.scale(k, k)
            painter.translate(-rect.topLeft())
            painter.setClipRect(rect)
            if background:
                painter.fillRect(rect, QColor(background))
            for item in objects:
                if not item.isVisible() or not item.sceneBoundingRect().intersects(rect):
                    continue
                painter.save()
                painter.setTransform(item.sceneTransform(), True)
                painter.setOpacity(float(item.data.get("opacity", 1.0)))
                item.paint_content(painter)
                painter.restore()
            painter.restore()
    finally:
        painter.end()
        IllImageItem.export_images = None
        scene.ill_outline = outline
    part.replace(target)
    return target
