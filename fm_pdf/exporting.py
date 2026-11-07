"""Exports (sans Qt pour le calcul ; menu et dialogues en Qt) : images PNG / JPEG / TIFF à la résolution voulue,
texte, PDF optimisé (qpdf : flux d'objets, recompression ; MuPDF : objets inutilisés et doublons retirés), pages
choisies, PDF APLATI (sur demande explicite seulement : les champs et annotations deviennent du contenu).
DOCX et PDF/A : NON proposés — aucune conversion fiable intégrée ni validateur PDF/A disponible (dit tel quel)."""
from __future__ import annotations

import ctypes
import io
import pathlib

from .worker import PRIO_BACKGROUND


def optimize(data: bytes) -> bytes:
    """Taille réduite SANS perte de contenu : objets inutilisés et doublons retirés, flux recompressés, flux
    d'objets. Formulaires et XFA gardés (aucune image rééchantillonnée)."""
    import pikepdf
    import pymupdf
    doc = pymupdf.open(stream=data, filetype="pdf")
    try:
        if doc.needs_pass:
            raise ValueError("document chiffré")
        out = io.BytesIO()
        doc.save(out, garbage=4, deflate=True, deflate_images=True, deflate_fonts=True, clean=False)
        data2 = out.getvalue()
    finally:
        doc.close()
    with pikepdf.open(io.BytesIO(data2)) as pdf:
        out = io.BytesIO()
        pdf.save(out, compress_streams=True, recompress_flate=True,
                 object_stream_mode=pikepdf.ObjectStreamMode.generate)
    result = out.getvalue()
    return result if len(result) < len(data) else data


def page_text(doc, pages) -> str:
    """Texte des pages (fil du moteur)."""
    parts = []
    for i in pages:
        parts.append("--- Page %d ---\n%s" % (i + 1, doc.text(i)))
    return "\n\n".join(parts)


def render_page_image(doc, i: int, dpi: int):
    from PySide6.QtGui import QImage
    w, h = doc.page_size(i)
    scale = dpi / 72.0
    img = QImage(max(1, int(round(w * scale))), max(1, int(round(h * scale))), QImage.Format_RGB32)
    addr = ctypes.addressof(ctypes.c_char.from_buffer(img.bits()))
    doc.render(i, scale, (0, 0, img.width(), img.height()), into=(addr, img.bytesPerLine()))
    img.setDotsPerMeterX(int(dpi / 0.0254))
    img.setDotsPerMeterY(int(dpi / 0.0254))
    return img


def export_menu(pane, anchor) -> None:
    from . import ui_kit
    m = ui_kit.menu(pane)
    for text, slot in (("Images PNG…", lambda: export_images(pane, "png")),
                       ("Images JPEG…", lambda: export_images(pane, "jpg")),
                       ("Images TIFF…", lambda: export_images(pane, "tif")),
                       ("Texte (.txt)…", lambda: export_text(pane)),
                       ("PDF optimisé (taille réduite, sans perte)…", lambda: export_optimized(pane)),
                       ("Pages choisies (PDF)…", lambda: __import__("fm_pdf.page_actions", fromlist=["x"]).extract(pane)),
                       ("PDF aplati (champs et commentaires figés)…", lambda: export_flattened(pane))):
        m.addAction(text).triggered.connect(slot)
    m.addSeparator()
    na = m.addAction("DOCX, PDF/A : non pris en charge (aucune conversion fiable intégrée)")
    na.setEnabled(False)
    m.exec(anchor.mapToGlobal(anchor.rect().bottomLeft()))


def _stem(pane) -> str:
    return pane.session.path.stem if pane.session.path else "document"


def export_images(pane, fmt: str) -> None:
    from PySide6.QtWidgets import QFileDialog
    from . import pages as P, ui_kit
    n = pane.session.info.get("page_count", 0)
    spec = ui_kit.ask_text(pane, "Exporter en images", "Pages (ex. 1-3, 5 ; vide = toutes) et résolution : "
                           "« pages @ dpi » (ex. 1-2 @ 150)", default="@ 150", action="Exporter")
    if spec is None:
        return
    ranges, _, dpi = spec.partition("@")
    try:
        dpi = max(36, min(1200, int(dpi.strip() or 150)))
    except ValueError:
        dpi = 150
    pages = P.parse_ranges(ranges, n) if ranges.strip() else list(range(n))
    folder = QFileDialog.getExistingDirectory(pane, "Dossier des images",
                                              str(pane.session.path.parent) if pane.session.path else "")
    if not folder:
        return
    stem = _stem(pane)
    quality = {"jpg": 92}.get(fmt, -1)

    def job(doc):
        for i in pages:
            img = render_page_image(doc, i, dpi)
            img.save(str(pathlib.Path(folder) / ("%s_p%03d.%s" % (stem, i + 1, fmt))), None, quality)
        return len(pages)
    pane.session.run(job, PRIO_BACKGROUND, lambda k, err: pane.status(
        "Export impossible : %s" % err if err else "%d image(s) %s à %d dpi dans %s" % (k, fmt.upper(), dpi, folder)))


def export_text(pane) -> None:
    from PySide6.QtWidgets import QFileDialog
    path, _ = QFileDialog.getSaveFileName(pane, "Exporter le texte", _stem(pane) + ".txt", "Texte (*.txt)")
    if not path:
        return
    n = pane.session.info.get("page_count", 0)

    def job(doc):
        text = page_text(doc, range(n))
        pathlib.Path(path).write_text(text, encoding="utf-8")
        return len(text)
    pane.session.run(job, PRIO_BACKGROUND, lambda k, err: pane.status(
        "Export impossible : %s" % err if err else "Texte exporté (%d caractères) : %s" % (k, path)))


def export_optimized(pane) -> None:
    from PySide6.QtWidgets import QFileDialog
    from . import fileio
    path, _ = QFileDialog.getSaveFileName(pane, "PDF optimisé", _stem(pane) + "_optimisé.pdf", "PDF (*.pdf)")
    if not path:
        return
    pages = pane.session.info.get("page_count")

    def job(doc):
        data = doc.save_bytes()[0]
        out = optimize(data)
        fileio.write_atomic(path, out, verify=lambda d: fileio.verify_pdf(d, None if doc.is_xfa else pages))
        return len(data), len(out)
    pane.session.run(job, PRIO_BACKGROUND, lambda r, err: pane.status(
        "Optimisation impossible : %s" % err if err else "PDF optimisé : %d Ko -> %d Ko (%s)" % (
            r[0] // 1024, r[1] // 1024, path)))


def export_flattened(pane) -> None:
    from PySide6.QtWidgets import QFileDialog
    from . import annots, fileio, ui_kit
    if pane.session.info.get("is_xfa"):
        pane.status("Formulaire XFA : l'aplatissement n'est pas pris en charge (il détruirait le formulaire)")
        return
    if not ui_kit.confirm(pane, "PDF aplati", "Les champs de formulaire et les commentaires deviendront du contenu "
                          "FIGÉ dans une COPIE (l'original reste interactif).", "Créer la copie"):
        return
    path, _ = QFileDialog.getSaveFileName(pane, "PDF aplati", _stem(pane) + "_aplati.pdf", "PDF (*.pdf)")
    if not path:
        return

    def job(doc):
        out = annots.flatten_annotations(doc.save_bytes()[0])
        fileio.write_atomic(path, out, verify=lambda d: fileio.verify_pdf(d, doc.page_count()))
        return path
    pane.session.run(job, PRIO_BACKGROUND, lambda p, err: pane.status(
        "Aplatissement impossible : %s" % err if err else "Copie aplatie : %s" % p))
