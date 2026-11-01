"""Module Photoshop : import PSD (psd-tools, lecture seule). Fichiers PSD construits par psd-tools (écriture
indépendante de notre lecture) : calques, positions, opacité, modes de fusion, groupes, visibilité, composition comparée
à celle de psd-tools ; fichier invalide, non repris signalé ; import par le VRAI chemin du Board."""
import os as _os, sys as _sys  # jamais les vrais réglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from _photoshop_case import PsCase  # noqa: E402
from fm_photoshop import compose as C, io_images, io_psd  # noqa: E402

try:
    from PIL import Image
    from psd_tools import PSDImage
    from psd_tools.api.layers import PixelLayer
    from psd_tools.constants import BlendMode
    HAVE = True
except ImportError:                                                  # pragma: no cover
    HAVE = False


def build_psd(path: Path):
    psd = PSDImage.new("RGB", (60, 40), color=(255, 255, 255))
    base = PixelLayer.frompil(Image.new("RGBA", (60, 40), (200, 200, 60, 255)), psd, "Fond", top=0, left=0)
    red = PixelLayer.frompil(Image.new("RGBA", (30, 20), (255, 0, 0, 255)), psd, "Rouge", top=5, left=10)
    red.opacity = 128
    blue = PixelLayer.frompil(Image.new("RGBA", (30, 20), (40, 90, 200, 255)), psd, "Bleu produit", top=15, left=25)
    blue.blend_mode = BlendMode.MULTIPLY
    ghost = PixelLayer.frompil(Image.new("RGBA", (10, 10), (0, 255, 0, 255)), psd, "Caché", top=0, left=0)
    ghost.visible = False
    odd = PixelLayer.frompil(Image.new("RGBA", (8, 8), (255, 255, 0, 255)), psd, "Bizarre", top=30, left=2)
    odd.blend_mode = BlendMode.HUE
    for layer in (base, red, blue, ghost, odd):
        psd.append(layer)
    group = psd.create_group(name="Groupe", layer_list=[])
    inner = PixelLayer.frompil(Image.new("RGBA", (12, 12), (0, 0, 0, 255)), psd, "Dedans", top=2, left=44)
    group.append(inner)
    psd.save(str(path))
    return psd


@unittest.skipUnless(HAVE, "psd-tools absent")
class ReadPsdTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="psd_test_"))
        self.path = self.tmp / "essai.psd"
        build_psd(self.path)

    def test_layers_properties_and_notes(self):
        doc, notes = io_psd.read_psd(self.path)
        self.assertEqual((doc.width, doc.height), (60, 40))
        names = [l.name for l in doc.layers]
        self.assertEqual(names[:5], ["Fond", "Rouge", "Bleu produit", "Caché", "Bizarre"])
        by = {l.name: l for l in doc.layers}
        self.assertEqual((by["Rouge"].pix.x, by["Rouge"].pix.y), (10, 5))
        self.assertAlmostEqual(by["Rouge"].opacity, 128 / 255, places=3)
        self.assertEqual(by["Bleu produit"].blend, "multiply")
        self.assertFalse(by["Caché"].visible)
        self.assertEqual(by["Bizarre"].blend, "normal")
        self.assertTrue(any("HUE" in n or "Hue" in n.title().upper() or "fusion" in n for n in notes))   # mode inconnu signalé
        group = next(l for l in doc.layers if l.is_group())
        self.assertEqual(group.name, "Groupe")
        self.assertEqual([c.name for c in group.children], ["Dedans"])

    def test_composition_matches_psd_tools_composite(self):
        doc, _notes = io_psd.read_psd(self.path)
        ours = C.flatten_u8(doc)[..., :3].astype(int)
        theirs = np.array(PSDImage.open(str(self.path)).composite().convert("RGB"), int)
        diff = np.abs(ours - theirs)
        # le calque « Bizarre » (mode sans équivalent) est la seule différence permise : zone (2..10, 30..38)
        mask = np.ones(diff.shape[:2], bool)
        mask[30:38, 2:10] = False
        self.assertLessEqual(int(diff[mask].max()), 3)

    def test_invalid_files_and_missing_library(self):
        bad = self.tmp / "faux.psd"
        bad.write_bytes(b"8BPS pas vraiment")
        with self.assertRaises(io_images.ImageError):
            io_psd.read_psd(bad)
        with self.assertRaises(io_images.ImageError):
            io_psd.read_psd(self.tmp / "absent.psd")
        with mock.patch.dict(sys.modules, {"psd_tools": None}):
            with self.assertRaisesRegex(io_images.ImageError, "psd-tools"):
                io_psd.read_psd(self.path)
        self.assertTrue(io_psd.available())


@unittest.skipUnless(HAVE, "psd-tools absent")
class BoardPsdTest(PsCase):
    def test_import_through_the_board_toolbar(self):
        path = self.tmp / "board.psd"
        build_psd(path)
        self.pane.set_module("photoshop")
        with mock.patch("PySide6.QtWidgets.QMessageBox.information") as info:
            item = self.pane.photoshop.import_file(str(path))
        self.assertIsNotNone(item)
        self.assertTrue(info.called)                                                  # les non repris sont annoncés
        doc = item.session.doc
        self.assertEqual((doc.width, doc.height), (60, 40))
        self.assertEqual(len(doc.layers), 6)
        # enregistrement / réouverture du Board : les calques PSD sont devenus des calques natifs
        self.pane.save()
        self.pane._autosave.stop()
        from fm_photoshop import session as S
        S._REGISTRY.clear()
        pane2 = self.make_pane(self.path)
        from fm_photoshop.board_item import PsItem
        loaded = [i for i in pane2.scene.board_items() if isinstance(i, PsItem)][0].session.doc
        self.assertEqual([l.name for l in loaded.layers], [l.name for l in doc.layers])
        self.assertTrue(np.array_equal(C.flatten_u8(loaded), C.flatten_u8(doc)))


if __name__ == "__main__":
    unittest.main()
