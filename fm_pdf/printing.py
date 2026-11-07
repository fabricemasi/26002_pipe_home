"""Impression (Qt) : boîte d'impression de Windows (plage, copies, imprimante), puis rendu de chaque page À LA
RÉSOLUTION choisie dans le FIL DU MOTEUR, peint sur le QPrinter dans ce même fil (QPainter sur QPrinter est permis
hors du fil de l'interface) : l'interface reste libre, l'avancement s'affiche dans la barre d'état."""
from __future__ import annotations

from PySide6.QtCore import QRectF
from PySide6.QtGui import QImage, QPainter
from PySide6.QtPrintSupport import QPrintDialog, QPrinter

from .worker import PRIO_BACKGROUND


def print_dialog(pane) -> None:
    info = pane.session.info
    if not info.get("page_count"):
        return
    if not info.get("security", {}).get("can_print", True):
        pane.status("Impression interdite par les permissions du document")
        return
    printer = QPrinter(QPrinter.HighResolution)
    printer.setDocName(pane.session.path.name if pane.session.path else "Document PDF")
    printer.setFromTo(1, info["page_count"])
    dialog = QPrintDialog(printer, pane)
    dialog.setMinMax(1, info["page_count"])
    if dialog.exec() != QPrintDialog.Accepted:
        return
    first, last = printer.fromPage(), printer.toPage()
    if first == 0:
        first, last = 1, info["page_count"]
    if printer.printRange() == QPrinter.CurrentPage:
        first = last = pane.view.current + 1
    dpi = int(pane.settings.get("pdf_print_dpi", 300))
    annots = bool(pane.settings.get("pdf_print_annotations", True))
    pages = list(range(first - 1, last))
    pane.status("Impression de %d page(s)…" % len(pages))
    session = pane.session

    def job(doc):
        c = doc.c
        flags = c.FPDF_PRINTING | (c.FPDF_ANNOT if annots else 0)
        painter = QPainter()
        if not painter.begin(printer):
            raise RuntimeError("imprimante indisponible")
        try:
            for k, i in enumerate(pages):
                if k:
                    printer.newPage()
                w, h = doc.page_size(i)
                area = printer.pageRect(QPrinter.DevicePixel)
                scale = dpi / 72.0
                img = QImage(max(1, int(round(w * scale))), max(1, int(round(h * scale))), QImage.Format_RGB32)
                import ctypes
                addr = ctypes.addressof(ctypes.c_char.from_buffer(img.bits()))
                doc.render(i, scale, (0, 0, img.width(), img.height()), flags=flags, into=(addr, img.bytesPerLine()))
                target = QRectF(0, 0, area.width(), area.height())
                ratio = min(target.width() / img.width(), target.height() / img.height())
                tw, th = img.width() * ratio, img.height() * ratio
                painter.drawImage(QRectF((target.width() - tw) / 2, (target.height() - th) / 2, tw, th), img)
        finally:
            painter.end()
        return len(pages)
    session.run(job, PRIO_BACKGROUND, lambda n, err: pane.status(
        "Impression impossible : %s" % err if err else "%d page(s) envoyées à l'imprimante" % n))
