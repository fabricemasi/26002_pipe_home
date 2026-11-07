"""Organisation des pages (sans Qt) : chaque fonction prend les OCTETS du document et rend les nouveaux octets
(PyMuPDF : liens, annotations, champs et signets suivent leurs pages ; les signets vers une page supprimée
disparaissent). Appelées par `PdfSession.edit` (fil du moteur, instantané pour annuler).

Document XFA dynamique : refusé (`PageError`) — ses pages sont produites par la mise en page du formulaire
(Acrobat refuse aussi) ; un XFA statique garde ses pages PDF mais ses champs XFA ne suivraient pas : refusé aussi.
"""
from __future__ import annotations

import io

POSITIONS = ("bas-centre", "bas-droite", "bas-gauche", "haut-centre", "haut-droite", "haut-gauche")


class PageError(ValueError):
    pass


def _open(data: bytes):
    import pymupdf
    doc = pymupdf.open(stream=data, filetype="pdf")
    if doc.is_encrypted:
        doc.close()
        raise PageError("document chiffré : enregistrez-le d'abord sans chiffrement (Protéger > Retirer)")
    if _has_xfa(doc):
        doc.close()
        raise PageError("formulaire XFA : ses pages sont produites par le formulaire lui-même, elles ne se "
                        "réorganisent pas (comme dans Acrobat)")
    return doc


def _has_xfa(doc) -> bool:
    """/AcroForm /XFA présent (que MuPDF voie ou non le document comme un formulaire)."""
    cat = doc.pdf_catalog()
    return doc.xref_get_key(cat, "AcroForm/XFA")[0] not in ("null", "")


def _save(doc) -> bytes:
    out = io.BytesIO()
    doc.save(out, garbage=1, deflate=True)
    doc.close()
    return out.getvalue()


def _check(doc, pages):
    pages = sorted(set(int(p) for p in pages))
    if not pages:
        raise PageError("aucune page choisie")
    if pages[0] < 0 or pages[-1] >= doc.page_count:
        raise PageError("page hors du document")
    return pages


def move_pages(data: bytes, pages, to: int) -> bytes:
    """Déplace les pages (indices, dans leur ordre) AVANT la page `to` (indice dans le document d'origine ;
    `to` = nombre de pages : à la fin)."""
    doc = _open(data)
    pages = _check(doc, pages)
    order = [i for i in range(doc.page_count) if i not in pages]
    insert_at = sum(1 for i in order if i < to)
    order[insert_at:insert_at] = pages
    doc.select(order)
    return _save(doc)


def delete_pages(data: bytes, pages) -> bytes:
    doc = _open(data)
    pages = _check(doc, pages)
    if len(pages) >= doc.page_count:
        raise PageError("un document garde au moins une page")
    doc.delete_pages(pages)
    return _save(doc)


def rotate_pages(data: bytes, pages, quarter: int = 1) -> bytes:
    doc = _open(data)
    for i in _check(doc, pages):
        page = doc[i]
        page.set_rotation((page.rotation + 90 * quarter) % 360)
    return _save(doc)


def duplicate_pages(data: bytes, pages) -> bytes:
    doc = _open(data)
    pages = _check(doc, pages)
    for offset, i in enumerate(pages):
        doc.fullcopy_page(i + offset, i + offset + 1)
    return _save(doc)


def insert_blank(data: bytes, at: int, width: float | None = None, height: float | None = None,
                 count: int = 1) -> bytes:
    doc = _open(data)
    ref = doc[min(max(0, at - 1), doc.page_count - 1)].rect if doc.page_count else None
    w = width or (ref.width if ref else 595.28)
    h = height or (ref.height if ref else 841.89)
    for k in range(max(1, count)):
        doc.new_page(pno=at + k, width=w, height=h)
    return _save(doc)


def insert_from(data: bytes, other: bytes, at: int, pages=None) -> bytes:
    """Insère les pages `pages` (toutes si None) d'un autre PDF avant la page `at`."""
    import pymupdf
    doc = _open(data)
    src = pymupdf.open(stream=other, filetype="pdf")
    try:
        if src.is_encrypted:
            raise PageError("le document à insérer est chiffré")
        chosen = list(range(src.page_count)) if pages is None else _check(src, pages)
        for k, p in enumerate(chosen):
            doc.insert_pdf(src, from_page=p, to_page=p, start_at=at + k, links=True, annots=True, widgets=True)
    finally:
        src.close()
    return _save(doc)


def merge(documents: list[bytes]) -> bytes:
    import pymupdf
    if not documents:
        raise PageError("aucun document")
    out = pymupdf.open()
    toc = []
    for data in documents:
        src = _open(data)
        offset = out.page_count
        toc += [[lvl, title, page + offset] for lvl, title, page in src.get_toc(simple=True)]
        out.insert_pdf(src, links=True, annots=True, widgets=True)
        src.close()
    if toc:
        try:
            out.set_toc(toc)
        except Exception:                                   # noqa: BLE001 - signets incohérents : pages gardées
            pass
    return _save(out)


def extract(data: bytes, pages) -> bytes:
    doc = _open(data)
    doc.select(_check(doc, pages))
    return _save(doc)


def split(data: bytes, every: int = 1, ranges=None) -> list[bytes]:
    """Découpe en documents de `every` pages, ou selon `ranges` = [(début, fin incluse)]."""
    import pymupdf
    doc = _open(data)
    n = doc.page_count
    if ranges is None:
        every = max(1, int(every))
        ranges = [(k, min(n, k + every) - 1) for k in range(0, n, every)]
    out = []
    for a, b in ranges:
        part = pymupdf.open()
        part.insert_pdf(doc, from_page=a, to_page=b, links=True, annots=True, widgets=True)
        out.append(_save(part))
    doc.close()
    return out


def crop(data: bytes, pages, box) -> bytes:
    """Recadre (CropBox) : `box` = (gauche, haut, droite, bas) en points dans la page non tournée."""
    import pymupdf
    doc = _open(data)
    for i in _check(doc, pages):
        page = doc[i]
        r = pymupdf.Rect(box) & page.mediabox
        if r.is_empty or r.width < 10 or r.height < 10:
            raise PageError("zone de recadrage trop petite")
        page.set_cropbox(r)
    return _save(doc)


def resize(data: bytes, pages, width: float, height: float) -> bytes:
    """Nouvelle taille de page (MediaBox) : le contenu garde sa place en haut à gauche, rien n'est déformé."""
    import pymupdf
    doc = _open(data)
    for i in _check(doc, pages):
        page = doc[i]
        page.set_mediabox(pymupdf.Rect(0, 0, width, height))
    return _save(doc)


def _place(page, text, position, size, margin=24.0):
    import pymupdf
    r = page.rect
    width = pymupdf.get_text_length(text, fontname="helv", fontsize=size)
    vertical, horizontal = position.split("-")
    x = {"gauche": margin, "centre": (r.width - width) / 2, "droite": r.width - margin - width}[horizontal]
    y = margin + size if vertical == "haut" else r.height - margin
    return pymupdf.Point(x, y)


def add_page_numbers(data: bytes, fmt: str = "{n} / {total}", position: str = "bas-centre", size: float = 10,
                     start: int = 1, pages=None, color=(0, 0, 0)) -> bytes:
    doc = _open(data)
    chosen = range(doc.page_count) if pages is None else _check(doc, pages)
    total = doc.page_count
    for k, i in enumerate(chosen):
        page = doc[i]
        text = fmt.format(n=start + k, total=total, page=i + 1)
        page.insert_text(_place(page, text, position, size), text, fontsize=size, fontname="helv", color=color,
                         rotate=0)
    return _save(doc)


def header_footer(data: bytes, header: str = "", footer: str = "", size: float = 9, pages=None,
                  color=(0.25, 0.25, 0.25)) -> bytes:
    doc = _open(data)
    chosen = range(doc.page_count) if pages is None else _check(doc, pages)
    for i in chosen:
        page = doc[i]
        if header:
            page.insert_text(_place(page, header, "haut-centre", size), header, fontsize=size, fontname="helv",
                             color=color)
        if footer:
            page.insert_text(_place(page, footer, "bas-centre", size), footer, fontsize=size, fontname="helv",
                             color=color)
    return _save(doc)


def watermark(data: bytes, text: str, opacity: float = 0.15, size: float = 60, angle: float = 45,
              color=(0.6, 0.0, 0.0), pages=None) -> bytes:
    """Filigrane texte au centre de chaque page (contenu ajouté par-dessus, transparence réelle)."""
    import pymupdf
    doc = _open(data)
    chosen = range(doc.page_count) if pages is None else _check(doc, pages)
    for i in chosen:
        page = doc[i]
        r = page.rect
        length = pymupdf.get_text_length(text, fontname="helv", fontsize=size)
        center = pymupdf.Point(r.width / 2, r.height / 2)
        start = pymupdf.Point(center.x - length / 2, center.y + size / 3)
        morph = (center, pymupdf.Matrix(-angle))
        page.insert_text(start, text, fontsize=size, fontname="helv", color=color, fill_opacity=opacity,
                         stroke_opacity=opacity, morph=morph, overlay=True)
    return _save(doc)


def parse_ranges(text: str, count: int) -> list[int]:
    """« 1-3, 5, 8- » -> indices 0, 1, 2, 4, 7… (1 = première page)."""
    out = []
    for part in (text or "").replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            a = int(a) if a.strip() else 1
            b = int(b) if b.strip() else count
        else:
            a = b = int(part)
        if a > b:
            a, b = b, a
        out.extend(range(max(1, a) - 1, min(count, b)))
    seen = set()
    return [i for i in out if not (i in seen or seen.add(i))]
