"""IMPRESSION du CAD (TRACEUP) : rendu Qt d'une presentation (`cad_plot.plot_frame`) dans un PDF VECTORIEL
(`QPdfWriter`) ou sur une imprimante (`QPrinter`, boite d'impression du systeme). Meme rendu que l'export du board
(`fm_board.export._render` : vraies epaisseurs, ni selection ni commentaires) ; la zone du dessin est posee a
l'echelle exacte sur la feuille."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QMarginsF, QRectF, QSizeF
from PySide6.QtGui import QPageLayout, QPageSize, QPainter, QPdfWriter

from . import cad_plot

PDF_DPI = 600


def drawing_extents(items) -> list:
    """Etendue (document) des entites CAD visibles, lignes de construction exclues (comme le zoom etendu)."""
    x0 = y0 = float("inf")
    x1 = y1 = float("-inf")
    for item in items:
        if getattr(item, "INFINITE", False) or not item.isVisible():
            continue
        try:
            a, b, c, d = item.doc_bounds()
        except Exception:                                   # noqa: BLE001 - entite sans emprise : ignoree
            continue
        x0, y0, x1, y1 = min(x0, a), min(y0, b), max(x1, c), max(y1, d)
    if x0 == float("inf"):
        return [0.0, 0.0, 100.0, 100.0]
    return [x0, y0, x1, y1]


def _page_layout(frame: dict) -> QPageLayout:
    pw, ph = frame["paper"]
    size = QPageSize(QSizeF(min(pw, ph), max(pw, ph)), QPageSize.Millimeter)
    orientation = QPageLayout.Landscape if pw > ph else QPageLayout.Portrait
    return QPageLayout(size, orientation, QMarginsF(0, 0, 0, 0), QPageLayout.Millimeter)


def _paint(scene, painter: QPainter, frame: dict, dots_per_mm: float):
    from fm_board.export import _render
    x0, y0, x1, y1 = frame["source"]
    source = QRectF(x0, -y1, x1 - x0, y1 - y0)                   # scene : Y vers le bas
    tx, ty, tw, th = frame["target"]
    target = QRectF(tx * dots_per_mm, ty * dots_per_mm, tw * dots_per_mm, th * dots_per_mm)
    from PySide6.QtGui import QColor
    background = scene.background
    scene.background = QColor("#ffffff")                    # papier blanc (les masques WIPEOUT prennent sa couleur)
    painter.save()
    painter.setClipRect(target)
    try:
        _render(scene, painter, target, source, False)
    finally:
        painter.restore()
        scene.background = background


def plot_pdf(scene, layout: dict, extents, path) -> Path:
    """Presentation imprimee dans un PDF (vectoriel) ; rend le chemin ecrit."""
    frame = cad_plot.plot_frame(layout, extents)
    path = Path(path)
    writer = QPdfWriter(str(path))
    writer.setResolution(PDF_DPI)
    writer.setPageLayout(_page_layout(frame))
    writer.setTitle(layout["name"])
    painter = QPainter(writer)
    try:
        _paint(scene, painter, frame, PDF_DPI / 25.4)
    finally:
        painter.end()
    return path


def plot_printer(scene, layout: dict, extents, parent=None) -> bool:
    """Presentation envoyee a une imprimante choisie dans la boite d'impression du systeme ; False = annule."""
    from PySide6.QtPrintSupport import QPrintDialog, QPrinter
    frame = cad_plot.plot_frame(layout, extents)
    printer = QPrinter(QPrinter.HighResolution)
    printer.setFullPage(True)
    printer.setPageLayout(_page_layout(frame))
    printer.setDocName(layout["name"])
    dialog = QPrintDialog(printer, parent)
    if dialog.exec() != QPrintDialog.Accepted:
        return False
    painter = QPainter(printer)
    try:
        _paint(scene, painter, frame, printer.resolution() / 25.4)
    finally:
        painter.end()
    return True
