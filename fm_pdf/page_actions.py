"""Actions de l'outil « Pages » (Qt) : demandent ce qu'il faut (fichier, plage, texte) puis lancent l'opération de
pages.py comme UNE édition annulable de la session. Pages concernées : celles choisies dans le panneau des
miniatures (sinon la page courante)."""
from __future__ import annotations

import pathlib

from PySide6.QtWidgets import QFileDialog

from . import pages as P
from . import ui_kit

FILTER = "Documents PDF (*.pdf)"


def _pages(pane, pages=None) -> list[int]:
    return list(pages) if pages else pane.thumbs.selected_pages()


def _edit(pane, label, fn) -> None:
    def done(_extra, error):
        if error is None:
            pane.status(label + " : fait")
            pane.thumbs.invalidate()
    pane.session.edit(label, fn, done)


def move(pane, pages, to) -> None:
    _edit(pane, "Déplacer %d page(s)" % len(pages), lambda d: P.move_pages(d, pages, to))


def delete(pane, pages=None) -> None:
    pages = _pages(pane, pages)
    if ui_kit.confirm(pane, "Supprimer des pages", "Supprimer %d page(s) ? (Annuler la rétablit)" % len(pages),
                      "Supprimer", items=["page %d" % (p + 1) for p in pages]):
        _edit(pane, "Supprimer %d page(s)" % len(pages), lambda d: P.delete_pages(d, pages))


def rotate(pane, quarter, pages=None) -> None:
    pages = _pages(pane, pages)
    _edit(pane, "Pivoter %d page(s)" % len(pages), lambda d: P.rotate_pages(d, pages, quarter))


def duplicate(pane, pages=None) -> None:
    pages = _pages(pane, pages)
    _edit(pane, "Dupliquer %d page(s)" % len(pages), lambda d: P.duplicate_pages(d, pages))


def insert_blank(pane, at=None) -> None:
    at = (pane.view.current + 1) if at is None else at
    _edit(pane, "Insérer une page vierge", lambda d: P.insert_blank(d, at))


def insert_file(pane, at=None) -> None:
    at = (pane.view.current + 1) if at is None else at
    path, _ = QFileDialog.getOpenFileName(pane, "Insérer les pages d'un PDF", "", FILTER)
    if not path:
        return
    other = pathlib.Path(path).read_bytes()
    _edit(pane, "Insérer « %s »" % pathlib.Path(path).name, lambda d: P.insert_from(d, other, at))


def merge(pane) -> None:
    paths, _ = QFileDialog.getOpenFileNames(pane, "Fusionner : PDF à ajouter à la fin", "", FILTER)
    if not paths:
        return
    blobs = [pathlib.Path(p).read_bytes() for p in paths]
    _edit(pane, "Fusionner %d document(s)" % len(blobs), lambda d: P.merge([d] + blobs))


def _ask_save(pane, title, name):
    start = str(pane.session.path.with_name(name)) if pane.session.path else name
    path, _ = QFileDialog.getSaveFileName(pane, title, start, FILTER)
    return path


def extract(pane, pages=None) -> None:
    pages = _pages(pane, pages)
    stem = pane.session.path.stem if pane.session.path else "document"
    path = _ask_save(pane, "Extraire les pages", "%s_pages.pdf" % stem)
    if not path:
        return
    from . import fileio

    def job(doc):
        data = P.extract(doc.save_bytes()[0], pages)
        fileio.write_atomic(path, data, verify=lambda d: fileio.verify_pdf(d, len(pages)))
        return len(pages)
    pane.session.run(job, 5, lambda n, err: pane.status("Extraction impossible : %s" % err if err else
                                                        "%d page(s) extraites dans %s" % (n, path)))


def split(pane) -> None:
    text = ui_kit.ask_text(pane, "Diviser le document", "Pages par document (ex. 1), ou plages séparées par « ; » "
                           "(ex. 1-3; 4-10) :", default="1", action="Diviser")
    if not text:
        return
    folder = QFileDialog.getExistingDirectory(pane, "Dossier des documents produits",
                                              str(pane.session.path.parent) if pane.session.path else "")
    if not folder:
        return
    stem = pane.session.path.stem if pane.session.path else "document"
    from . import fileio

    def job(doc):
        data = doc.save_bytes()[0]
        n = doc.page_count()
        if ";" in text or "-" in text:
            ranges = []
            for part in text.split(";"):
                idx = P.parse_ranges(part, n)
                if idx:
                    ranges.append((idx[0], idx[-1]))
            parts = P.split(data, ranges=ranges)
        else:
            parts = P.split(data, every=int(text))
        for k, blob in enumerate(parts, 1):
            fileio.write_atomic(pathlib.Path(folder) / ("%s_%02d.pdf" % (stem, k)), blob)
        return len(parts)
    pane.session.run(job, 5, lambda n, err: pane.status("Division impossible : %s" % err if err else
                                                        "%d document(s) écrits dans %s" % (n, folder)))


def crop(pane, pages=None) -> None:
    pages = _pages(pane, pages)
    text = ui_kit.ask_text(pane, "Recadrer", "Marges à retirer en points : gauche, haut, droite, bas "
                           "(ex. 36, 36, 36, 36) :", default="36, 36, 36, 36", action="Recadrer")
    if not text:
        return
    try:
        l, t, r, b = (float(v.replace(",", ".")) for v in text.replace(";", ",").split(","))
    except ValueError:
        pane.status("Quatre nombres attendus")
        return
    sizes = pane.session.info.get("sizes", [])

    def fn(data):
        import pymupdf
        doc = pymupdf.open(stream=data, filetype="pdf")
        boxes = {p: doc[p].mediabox for p in pages}
        doc.close()
        for p in pages:
            m = boxes[p]
            data = P.crop(data, [p], (m.x0 + l, m.y0 + t, m.x1 - r, m.y1 - b))
        return data
    _edit(pane, "Recadrer %d page(s)" % len(pages), fn)


def numbers(pane) -> None:
    fmt = ui_kit.ask_text(pane, "Numéros de page", "Modèle ({n} = numéro, {total} = nombre de pages) ; position : "
                          "bas-centre par défaut", default="{n} / {total}", action="Numéroter")
    if fmt:
        _edit(pane, "Numéroter les pages", lambda d: P.add_page_numbers(d, fmt))


def header_footer(pane) -> None:
    header = ui_kit.ask_text(pane, "En-tête", "Texte de l'en-tête (vide : aucun)", action="Suivant")
    if header is None:
        return
    footer = ui_kit.ask_text(pane, "Pied de page", "Texte du pied de page (vide : aucun)", action="Ajouter")
    if footer is None or not (header or footer):
        return
    _edit(pane, "En-tête et pied de page", lambda d: P.header_footer(d, header, footer))


def watermark(pane) -> None:
    text = ui_kit.ask_text(pane, "Filigrane", "Texte du filigrane", default="CONFIDENTIEL", action="Ajouter")
    if text:
        _edit(pane, "Filigrane", lambda d: P.watermark(d, text))
