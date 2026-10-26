"""Export du board entier : PNG (x2, plafonne), SVG, PDF — un RENDU APLATI (pas un aller-retour editable).
Options de la PAGE (`.mro`, Reglages de la page) : fond = couleur de la page ou transparent (PNG / SVG ; le PDF
garde toujours la couleur de la page), grille comprise ou non. Jamais la selection ni les guides ; les
commentaires ne sont pas exportes."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QMarginsF, QRectF, QSize, QSizeF, Qt
from PySide6.QtGui import QColor, QImage, QPageLayout, QPageSize, QPainter, QPdfWriter

MARGIN = 40.0
MAX_SIDE = 16000


def _area(scene) -> QRectF:
    rect = scene.content_rect()
    if rect.isNull() or not rect.isValid():
        rect = QRectF(-400, -300, 800, 600)
    return rect.adjusted(-MARGIN, -MARGIN, MARGIN, MARGIN)


def _render(scene, painter: QPainter, target: QRectF, source: QRectF, transparent: bool):
    from .items import CommentItem
    selected = scene.selectedItems()
    scene.clearSelection()
    hidden = [i for i in scene.board_items() if isinstance(i, CommentItem) and i.isVisible()]
    for item in hidden:
        item.setVisible(False)
    background = QColor(scene.background)
    scene.exporting = True
    hairlines = not getattr(scene, "cad_lineweights", True)
    if hairlines:
        scene.cad_style_changed()                       # export : les VRAIES epaisseurs, quel que soit l'affichage
    if scene.cad_layer is not None:
        scene.cad_layer.exporting(True)                 # rendu GPU : les entites CAD se peignent le temps de l'export
    scene.export_grid = bool(scene.page.get("export_grid", False))
    if transparent:
        scene.background = QColor(Qt.transparent)
    try:
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        scene.render(painter, target, source, Qt.KeepAspectRatio)
    finally:
        scene.exporting = False
        if hairlines:
            scene.cad_style_changed()
        if scene.cad_layer is not None:
            scene.cad_layer.exporting(False)
        scene.background = background
        for item in hidden:
            item.setVisible(True)
        for item in selected:
            item.setSelected(True)


def _transparent(scene) -> bool:
    return scene.page.get("export_background", "page") == "transparent"


def render_items(scene, items, scale: float = 2.0) -> QImage:
    """Image (PNG du presse-papiers) des elements donnes, sur le fond de la page, sans grille."""
    rect = QRectF()
    for item in items:
        rect = rect.united(item.scene_rect())
    source = rect.adjusted(-20, -20, 20, 20)
    scale = min(scale, 8000 / max(1.0, source.width(), source.height()))
    size = QSize(max(1, int(source.width() * scale)), max(1, int(source.height() * scale)))
    image = QImage(size, QImage.Format_ARGB32_Premultiplied)
    image.fill(scene.background)
    hidden = [i for i in scene.board_items() if i not in items and i.isVisible()]
    for item in hidden:
        item.setVisible(False)
    try:
        painter = QPainter(image)
        _render(scene, painter, QRectF(0, 0, size.width(), size.height()), source, False)
        painter.end()
    finally:
        for item in hidden:
            item.setVisible(True)
    return image


def export_png(scene, path, scale: float = 2.0) -> Path:
    source = _area(scene)
    scale = min(scale, MAX_SIDE / max(source.width(), source.height()))
    size = QSize(max(1, int(source.width() * scale)), max(1, int(source.height() * scale)))
    image = QImage(size, QImage.Format_ARGB32_Premultiplied)
    transparent = _transparent(scene)
    image.fill(Qt.transparent if transparent else scene.background)
    painter = QPainter(image)
    _render(scene, painter, QRectF(0, 0, size.width(), size.height()), source, transparent)
    painter.end()
    if not image.save(str(path)):
        raise OSError(f"Impossible d'ecrire {path}")
    return Path(path)


def export_svg(scene, path) -> Path:
    from PySide6.QtSvg import QSvgGenerator
    source = _area(scene)
    generator = QSvgGenerator()
    generator.setFileName(str(path))
    generator.setSize(QSize(int(source.width()), int(source.height())))
    generator.setViewBox(QRectF(0, 0, source.width(), source.height()))
    generator.setTitle(Path(path).stem)
    painter = QPainter(generator)
    _render(scene, painter, QRectF(0, 0, source.width(), source.height()), source, _transparent(scene))
    painter.end()
    return Path(path)


def export_pdf(scene, path) -> Path:
    source = _area(scene)
    writer = QPdfWriter(str(path))
    writer.setResolution(96)
    writer.setPageSize(QPageSize(QSizeF(source.width(), source.height()), QPageSize.Point))
    writer.setPageMargins(QMarginsF(0, 0, 0, 0), QPageLayout.Point)
    painter = QPainter(writer)
    page = QRectF(0, 0, writer.width(), writer.height())
    painter.fillRect(page, scene.background)
    _render(scene, painter, page, source, False)
    painter.end()
    return Path(path)


def export(scene, path) -> Path:
    suffix = Path(path).suffix.lower()
    if suffix == ".svg":
        return export_svg(scene, path)
    if suffix == ".pdf":
        return export_pdf(scene, path)
    return export_png(scene, path)
