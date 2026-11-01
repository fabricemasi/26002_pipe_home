"""Module Photoshop : gestion de la couleur — attribuer ≠ convertir, conversion LittleCMS (valeurs relues indépendamment),
alpha préservé, annulation exacte, profil intégré à l'export PNG / TIFF et relu, profils illisibles refusés."""
import os as _os, sys as _sys  # jamais les vrais réglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image, ImageCms

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fm_photoshop import color, compose as C, container, io_images, model as M
from fm_photoshop.history import History

ADOBE = Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32" / "spool" / "drivers" / "color" / "AdobeRGB1998.icc"


def doc_of(rgba, x=0, y=0):
    doc = M.new_document(8, 8, background=None)
    doc.layers[0].pix.set_all(x, y, np.broadcast_to(np.array(rgba, np.uint8), (8, 8, 4)).copy())
    return doc


@unittest.skipUnless(ADOBE.exists(), "profil AdobeRGB du système absent")
class ProfilesTest(unittest.TestCase):
    def setUp(self):
        self.adobe = ADOBE.read_bytes()

    def test_assign_changes_no_pixel_but_convert_does(self):
        doc = doc_of((200, 60, 30, 255))
        before = C.flatten_u8(doc)
        history = History()
        history.push(color.assign(doc, self.adobe, "Adobe RVB (1998)"))
        self.assertTrue(np.array_equal(C.flatten_u8(doc), before))                                  # AUCUN pixel modifié
        self.assertEqual(doc.icc_profile, self.adobe)
        history.undo()
        self.assertIsNone(doc.icc_profile)
        doc2 = doc_of((200, 60, 30, 255))
        history.push(color.convert(doc2, self.adobe, "Adobe RVB (1998)"))
        after = C.flatten_u8(doc2)
        self.assertFalse(np.array_equal(after, before))                                             # pixels recalculés
        self.assertEqual(int(after[0, 0, 3]), 255)

    def test_conversion_matches_an_independent_littlecms_call(self):
        rgba = np.zeros((4, 4, 4), np.uint8)
        rng = np.random.default_rng(1)
        rgba[..., :3] = rng.integers(20, 235, (4, 4, 3), dtype=np.uint8)
        rgba[..., 3] = 255
        ours = color.convert_array(rgba, color.srgb_bytes(), self.adobe, "relative")
        src = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB"))
        dst = ImageCms.ImageCmsProfile(io.BytesIO(self.adobe))
        reference = ImageCms.profileToProfile(Image.fromarray(rgba[..., :3], "RGB"), src, dst,
                                              renderingIntent=ImageCms.Intent.RELATIVE_COLORIMETRIC,
                                              outputMode="RGB", flags=ImageCms.Flags.BLACKPOINTCOMPENSATION)
        self.assertTrue(np.array_equal(ours[..., :3], np.asarray(reference)))
        # le vert sRVB saturé est MOINS saturé en Adobe RVB (gamut plus large) : valeurs différentes, plausibles
        green = color.convert_array(np.array([[[0, 255, 0, 255]]], np.uint8), color.srgb_bytes(), self.adobe)[0, 0]
        self.assertGreater(int(green[1]), 200)

    def test_round_trip_back_to_srgb_and_alpha_untouched(self):
        rgba = np.zeros((6, 6, 4), np.uint8)
        rgba[..., :3] = np.random.default_rng(3).integers(40, 215, (6, 6, 3), dtype=np.uint8)
        rgba[..., 3] = np.arange(36, dtype=np.uint8).reshape(6, 6) * 7
        there = color.convert_array(rgba, color.srgb_bytes(), self.adobe)
        back = color.convert_array(there, self.adobe, color.srgb_bytes())
        self.assertTrue(np.array_equal(back[..., 3], rgba[..., 3]))
        self.assertLessEqual(int(np.abs(back[..., :3].astype(int) - rgba[..., :3]).max()), 2)

    def test_text_and_shape_colors_follow_and_undo_is_exact(self):
        doc = doc_of((10, 120, 200, 255))
        layer = doc.layers[0]
        layer.source = {"kind": "shape", "shape": "rect", "fill": [10, 120, 200, 255]}
        before_pix = layer.pix.data.copy()
        history = History()
        history.push(color.convert(doc, self.adobe, "Adobe RVB (1998)"))
        self.assertNotEqual(layer.source["fill"][:3], [10, 120, 200])
        self.assertEqual(tuple(layer.pix.data[0, 0, :3]), tuple(layer.source["fill"][:3]))           # source et pixels concordent
        history.undo()
        self.assertEqual(layer.source["fill"], [10, 120, 200, 255])
        self.assertTrue(np.array_equal(layer.pix.data, before_pix))
        self.assertIsNone(doc.icc_profile)

    def test_profile_embedded_in_exports_container_and_unreadable_refused(self):
        doc = doc_of((5, 5, 5, 255))
        color.assign(doc, self.adobe, "Adobe RVB (1998)")
        with tempfile.TemporaryDirectory() as tmp:
            for suffix in (".png", ".tif"):
                target = Path(tmp) / f"x{suffix}"
                io_images.export_document(doc, target)
                with Image.open(target) as image:
                    self.assertEqual(image.info.get("icc_profile"), self.adobe)
                _rgba, _dpi, icc, _notes = io_images.import_image(target)
                self.assertEqual(icc, self.adobe)
        self.assertEqual(container.loads(container.dumps(doc)).icc_profile, self.adobe)
        with self.assertRaises(ValueError):
            color.convert(doc_of((1, 1, 1, 255)), b"pas un profil", "x")
        self.assertEqual(color.describe(b"???"), "Profil illisible")


class SystemProfilesTest(unittest.TestCase):
    def test_listing_contains_srgb_and_only_rgb_profiles(self):
        profiles = color.system_profiles()
        self.assertEqual(profiles[0][0], color.SRGB_NAME)
        self.assertTrue(all(color.is_rgb(data) for _name, data in profiles))
        self.assertEqual(len({name for name, _ in profiles}), len(profiles))


if __name__ == "__main__":
    unittest.main()
