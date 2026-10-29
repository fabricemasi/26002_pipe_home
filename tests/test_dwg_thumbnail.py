"""Apercu des DWG sans ODA File Converter : vignette integree au fichier par AutoCAD (BMP ou PNG)."""
import os as _os, sys as _sys  # jamais les vrais reglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import os
import shutil
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QBuffer, QByteArray, QIODevice
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

import previews
from preview_services import (
    dwg as preview_dwg,
)


def _encoded(width: int, height: int, color: str, fmt: str) -> bytes:
    image = QImage(width, height, QImage.Format_RGB32)
    image.fill(QColor(color))
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.WriteOnly)
    image.save(buffer, fmt)
    return bytes(data)


def _fake_dwg(entries: list[tuple[int, bytes]], version: bytes = b"AC1032") -> bytes:
    """Entete (version, adresse de la vignette en 0x0D) + section vignette : sentinelle, taille,
    nombre d'entrees, (code, debut, taille) par entree, puis les donnees."""
    section_at = 0x80
    table_size = 16 + 4 + 1 + 9 * len(entries)
    out = bytearray(version + b"\x00" * (section_at - len(version)))
    struct.pack_into("<I", out, 0x0D, section_at)
    out += previews._DWG_THUMBNAIL_SENTINEL + struct.pack("<I", 0) + bytes([len(entries)])
    start = section_at + table_size
    for code, data in entries:
        out += struct.pack("<BII", code, start, len(data))
        start += len(data)
    for _code, data in entries:
        out += data
    return bytes(out)


class DwgThumbnailTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)

    def _write(self, name, data):
        path = self.dir / name
        path.write_bytes(data)
        return path

    def test_png_thumbnail(self):
        path = self._write("plan.dwg", _fake_dwg([(1, b"\x00" * 8), (6, _encoded(220, 140, "#3060c0", "PNG"))]))
        image = previews._decode_dwg_thumbnail(path)
        self.assertEqual((image.width(), image.height()), (220, 140))
        self.assertGreater(QColor(image.pixel(10, 10)).blue(), 150)

    def test_bmp_thumbnail_without_file_header(self):
        dib = _encoded(180, 83, "#c03030", "BMP")[14:]              # AutoCAD stocke le DIB seul
        path = self._write("ancien.dwg", _fake_dwg([(1, b"\x00" * 8), (2, dib)], version=b"AC1018"))
        image = previews._decode_dwg_thumbnail(path)
        self.assertEqual((image.width(), image.height()), (180, 83))
        self.assertGreater(QColor(image.pixel(5, 5)).red(), 150)

    def test_without_oda_the_thumbnail_is_the_preview(self):
        path = self._write("plan.dwg", _fake_dwg([(6, _encoded(64, 40, "#20a040", "PNG"))]))
        with mock.patch.object(preview_dwg, "_oda_file_converter", return_value=None):
            image = previews._decode_2d_image(path, 512)
        self.assertIsNotNone(image)
        self.assertEqual((image.width(), image.height()), (64, 40))

    def test_no_thumbnail_or_not_a_dwg(self):
        self.assertIsNone(previews._decode_dwg_thumbnail(self._write("vide.dwg", _fake_dwg([(1, b"\x00" * 8)]))))
        self.assertIsNone(previews._decode_dwg_thumbnail(self._write("court.dwg", b"AC10")))
        self.assertIsNone(previews._decode_dwg_thumbnail(self._write("faux.dwg", b"\x00" * 300)))


class DxfPreviewTest(unittest.TestCase):
    """DXF : dessin vectoriel par ezdxf, image cadree sur le plan (pas un carre)."""

    def test_dxf_is_drawn_and_framed_on_the_plan(self):
        try:
            import ezdxf
            import matplotlib  # noqa: F401
        except ImportError:
            self.skipTest("ezdxf / matplotlib absents")
        folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, folder, True)
        doc = ezdxf.new()
        msp = doc.modelspace()
        msp.add_lwpolyline([(0, 0), (400, 0), (400, 100), (0, 100)], close=True)
        msp.add_circle((200, 50), 30)
        path = folder / "plan.dxf"
        doc.saveas(path)
        image = previews._decode_2d_image(path, 800)
        self.assertIsNotNone(image)
        self.assertEqual(image.width(), 800)
        self.assertLess(image.height(), image.width() / 2)        # plan 4:1 -> image large, pas carree
        center = QColor(image.pixel(image.width() // 2, image.height() // 2))
        self.assertLess(center.lightness(), 80)                       # fond sombre au centre du cercle
        # un trait clair quelque part sur la ligne mediane (bord du cercle ou du cadre)
        row = [QColor(image.pixel(x, image.height() // 2)).lightness() for x in range(image.width())]
        self.assertGreater(max(row), 100)


if __name__ == "__main__":
    unittest.main()
