"""Aperçus PDF et Illustrator.

Carte et pièges : docs/agents/apercus.md.
"""

from pathlib import Path
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QImage, QPainter

def pdf_page_count(path: Path) -> int:
    """Nombre de pages d'un PDF (0 si illisible ou QtPdf absent)."""
    try:
        from PySide6.QtPdf import QPdfDocument
    except ImportError:
        return 0
    doc = QPdfDocument()
    try:
        if doc.load(str(path)) != QPdfDocument.Error.None_:
            return 0
        return doc.pageCount()
    finally:
        doc.close()

def _render_pdf_page(path: Path, max_dim: int, page: int = 0) -> QImage | None:
    """Rend la page `page` (0 = premiere) d'un PDF via QtPdf, sur fond blanc,
    avec le grand cote ramene a `max_dim`. Un document par appel : un QPdfDocument (thread de
    worker) partage ne serait pas sûr. None si illisible ou
    protege par mot de passe."""
    try:
        from PySide6.QtPdf import QPdfDocument
    except ImportError:
        return None
    doc = QPdfDocument()
    try:
        if doc.load(str(path)) != QPdfDocument.Error.None_:
            return None
        if not 0 <= page < doc.pageCount():
            return None
        size = doc.pagePointSize(page)
        if size.width() <= 0 or size.height() <= 0:
            return None
        scale = max_dim / max(size.width(), size.height())
        target = QSize(max(1, round(size.width() * scale)), max(1, round(size.height() * scale)))
        image = doc.render(page, target)
        if image.isNull():
            return None
        flat = QImage(image.size(), QImage.Format_RGB32)
        flat.fill(Qt.white)
        painter = QPainter(flat)
        painter.drawImage(0, 0, image)
        painter.end()
        return flat
    finally:
        doc.close()

def ai_has_pdf_content(path: Path) -> bool:
    """Vrai si le .ai porte un vrai contenu PDF. Enregistre sans l'option « Creer un fichier
    compatible PDF », il reste un PDF, mais d'une seule page d'avertissement d'Adobe (« ... saved
    without PDF Content ... ») qu'il ne faut pas montrer comme apercu."""
    try:
        from PySide6.QtPdf import QPdfDocument
    except ImportError:
        return False
    doc = QPdfDocument()
    try:
        if doc.load(str(path)) != QPdfDocument.Error.None_ or doc.pageCount() <= 0:
            return False
        return "without pdf content" not in doc.getAllText(0).text().casefold()
    finally:
        doc.close()

def _decode_ai_xmp_thumbnail(path: Path) -> QImage | None:
    """Vignette JPEG qu'Illustrator range dans les metadonnees XMP (`xmpGImg:image`, base64), pres
    du debut du fichier, qu'il soit PDF ou PostScript. None si absente."""
    import base64
    try:
        with open(path, "rb") as f:
            data = f.read(64 * 1024 * 1024)
    except OSError:
        return None
    start = data.find(b"<xmpGImg:image>")
    end = data.find(b"</xmpGImg:image>", start)
    if start < 0 or end < 0:
        return None
    encoded = data[start + len(b"<xmpGImg:image>"):end].replace(b"&#xA;", b"").replace(b"&#xD;", b"")
    try:
        raw = base64.b64decode(b"".join(encoded.split()), validate=False)
    except ValueError:
        return None
    image = QImage.fromData(raw)
    return None if image.isNull() else image

def _decode_ai_image(path: Path, max_dim: int) -> QImage | None:
    """Illustrator .ai : premiere planche rendue comme un PDF (voir ILLUSTRATOR_EXTENSIONS), sinon
    la vignette XMP."""
    if ai_has_pdf_content(path):
        image = _render_pdf_page(path, max_dim)
        if image is not None:
            return image
    return _decode_ai_xmp_thumbnail(path)
