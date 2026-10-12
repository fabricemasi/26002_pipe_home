"""Apercu des brosses Photoshop (.abr, previews._decode_abr_image) : fichiers fabriques en memoire
(ancienne version 2 et version 6 avec section "desc"), jamais de fichier de l'utilisateur."""
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

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

import previews


def _sample(width: int, height: int, value: int, rle: bool) -> bytes:
    """Bornes + profondeur 8 + pixels (tous a `value`), bruts ou en PackBits."""
    head = struct.pack(">4iHB", 0, 0, height, width, 8, 1 if rle else 0)
    if not rle:
        return head + bytes([value]) * (width * height)
    row = bytes([257 - width, value])                 # une repetition par ligne (width <= 128)
    return head + struct.pack(f">{height}H", *([len(row)] * height)) + row * height


def _v2_file(path: Path):
    computed = struct.pack(">IHHHhH", 0, 25, 40, 100, 0, 100)
    name = "x\0".encode("utf-16-be")
    sampled = struct.pack(">IH", 0, 25) + struct.pack(">I", 2) + name + b"\1" + b"\0" * 8 + _sample(12, 6, 255, True)
    body = struct.pack(">HI", 1, len(computed)) + computed + struct.pack(">HI", 2, len(sampled)) + sampled
    path.write_bytes(struct.pack(">HH", 2, 2) + body)


def _v6_file(path: Path):
    uuid = "5deeee77-dad9-1175-913f-a4bfcac45329"
    brush = b"$" + uuid.encode() + b"\0" * 264 + _sample(20, 10, 200, False)
    samp = struct.pack(">I", len(brush)) + brush + b"\0" * (-len(brush) % 4)
    text = (uuid + "\0").encode("utf-16-be")
    desc = (b"BrshObjc\0\0\0\1\0\0\0\0\0\x0dcomputedBrush\0\0\0\x08\0\0\0\0"
            + b"DmtrUntF#Pxl" + struct.pack(">d", 30) + b"\0\0\0\0HrdnUntF#Prc" + struct.pack(">d", 100)
            + b"BrshObjc\0\0\0\1\0\0\0\0\0\x0csampledBrush\0\0\0\x09"
            + b"\0\0\0\x0bsampledDataTEXT" + struct.pack(">I", len(text) // 2) + text)
    sections = b"".join(b"8BIM" + key + struct.pack(">I", len(data)) + data
                        for key, data in ((b"samp", samp), (b"patt", b""), (b"desc", desc)))
    path.write_bytes(struct.pack(">HH", 6, 2) + sections)


class AbrPreviewTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)

    def test_v2_computed_and_rle_sampled_brushes(self):
        path = self.dir / "old.abr"
        _v2_file(path)
        brushes = previews._abr_brushes(path)
        self.assertEqual(brushes[0][:3], ("round", 40, 100))
        self.assertEqual((brushes[1].width(), brushes[1].height()), (12, 6))
        self.assertEqual(brushes[1].pixelColor(5, 3).value(), 255)

    def test_v6_follows_the_description_order(self):
        path = self.dir / "new.abr"
        _v6_file(path)
        brushes = previews._abr_brushes(path)
        self.assertEqual(brushes[0][:3], ("round", 30.0, 100.0))
        self.assertEqual((brushes[1].width(), brushes[1].height()), (20, 10))
        self.assertEqual(brushes[1].pixelColor(3, 3).value(), 200)

    def test_contact_sheet_is_drawn(self):
        path = self.dir / "new.abr"
        _v6_file(path)
        image = previews._decode_2d_image(path, 600)
        self.assertIsNotNone(image)
        self.assertEqual(image.width(), 600)
        # Peinture sombre sur fond clair : il y a des pixels presque noirs.
        darkest = min(image.pixelColor(x, y).value() for x in range(0, 600, 4) for y in range(0, image.height(), 4))
        self.assertLess(darkest, 60)

    def test_not_a_brush_file_has_no_preview(self):
        path = self.dir / "._apple.abr"                  # double AppleDouble de macOS
        path.write_bytes(b"\x00\x05\x16\x07" + b"\0" * 60)
        self.assertIsNone(previews._decode_abr_image(path, 600))
        path.write_bytes(b"")
        self.assertIsNone(previews._decode_abr_image(path, 600))


if __name__ == "__main__":
    unittest.main()
