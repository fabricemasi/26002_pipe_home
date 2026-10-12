"""Apercus des fichiers Illustrator (.ai) : rendu PDF de la 1re planche, sinon vignette XMP
(fichier enregistre sans contenu PDF, ou .ai PostScript)."""
import os as _os, sys as _sys  # jamais les vrais reglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import base64
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if os.path.isdir(r"C:\Windows\Fonts"):          # offscreen sans polices : pas de texte dans le PDF
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QMarginsF, QSizeF, Qt
from PySide6.QtGui import QColor, QImage, QPageSize, QPainter, QPdfWriter
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

import previews


def _write_pdf(path: Path, text: str | None = None, color: str = "#d02020"):
    writer = QPdfWriter(str(path))
    writer.setPageSize(QPageSize(QSizeF(100, 60), QPageSize.Millimeter))
    writer.setPageMargins(QMarginsF(0, 0, 0, 0))
    painter = QPainter(writer)
    if text:
        painter.drawText(writer.width() // 10, writer.height() // 2, text)
    else:
        painter.fillRect(0, 0, writer.width(), writer.height(), QColor(color))
    painter.end()


def _xmp_thumbnail(color: str = "#20a040") -> bytes:
    image = QImage(64, 32, QImage.Format_RGB32)
    image.fill(QColor(color))
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.WriteOnly)
    image.save(buffer, "JPEG")
    encoded = base64.b64encode(bytes(data)).decode()
    encoded = "&#xA;".join(encoded[i:i + 76] for i in range(0, len(encoded), 76))   # comme Illustrator
    return (f"<xmpGImg:width>64</xmpGImg:width><xmpGImg:image>{encoded}</xmpGImg:image>").encode()


class IllustratorPreviewTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)

    def test_pdf_compatible_ai_renders_its_artboard(self):
        path = self.dir / "logo.ai"
        _write_pdf(path, color="#d02020")
        self.assertTrue(previews.ai_has_pdf_content(path))
        image = previews._decode_2d_image(path, 200)
        self.assertIsNotNone(image)
        self.assertEqual(max(image.width(), image.height()), 200)
        center = QColor(image.pixel(image.width() // 2, image.height() // 2))
        self.assertGreater(center.red(), 150)                       # la planche rouge, pas du blanc
        self.assertLess(center.green(), 100)

    def test_ai_saved_without_pdf_content_uses_the_xmp_thumbnail(self):
        path = self.dir / "sans_pdf.ai"
        _write_pdf(path, text="This is an Adobe Illustrator File that was saved without PDF Content.")
        from PySide6.QtPdf import QPdfDocument
        doc = QPdfDocument()
        doc.load(str(path))
        written = doc.getAllText(0).text()
        doc.close()
        if not written:
            self.skipTest("aucune police disponible pour ecrire la page d'avertissement")
        with open(path, "ab") as f:
            f.write(b"\n%" + _xmp_thumbnail("#20a040") + b"\n")
        self.assertFalse(previews.ai_has_pdf_content(path))
        image = previews._decode_2d_image(path, 200)
        self.assertIsNotNone(image)
        self.assertEqual((image.width(), image.height()), (64, 32))  # la vignette, pas la page d'avertissement
        self.assertGreater(QColor(image.pixel(32, 16)).green(), 120)

    def test_postscript_ai_uses_the_xmp_thumbnail(self):
        path = self.dir / "ancien.ai"
        path.write_bytes(b"%!PS-Adobe-3.0\n%%Creator: Adobe Illustrator(R) 8.0\n" + _xmp_thumbnail() + b"\n%%EOF\n")
        self.assertFalse(previews.ai_has_pdf_content(path))
        self.assertIsNotNone(previews._decode_2d_image(path, 200))

    def test_unreadable_ai_has_no_preview(self):
        path = self.dir / "._resource_fork.ai"                     # doublon macOS (AppleDouble)
        path.write_bytes(b"\x00\x05\x16\x07" + b"\x00" * 200)
        self.assertIsNone(previews._decode_2d_image(path, 200))


if __name__ == "__main__":
    unittest.main()
