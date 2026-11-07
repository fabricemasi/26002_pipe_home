"""Module Photoshop : qualité d'AFFICHAGE du canevas (voisin / bilinéaire / bicubique) séparée des pixels du document, et
export natif PNG des pixels (sans passer par l'affichage)."""
import os as _os, sys as _sys  # jamais les vrais réglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import os
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtGui import QImage

from fm_photoshop import compose as C, display, model as M
from _photoshop_case import PsCase


def luminance(image, x, y):
    return image.pixelColor(int(x), int(y)).red()


class DisplayModesTest(PsCase):
    def _edge_editor(self, zoom=8.0):
        _item, std = self.editor(20, 12, zoom=zoom, background="Transparent")
        canvas, s = std.canvas, std.session
        layer = s.layer()
        layer.pix.write((0, 0, 20, 12), np.full((12, 20, 4), (255, 255, 255, 255), np.uint8))
        layer.pix.write((0, 0, 10, 12), np.full((12, 10, 4), (0, 0, 0, 255), np.uint8))    # moitié gauche noire
        s.notify("edit", (0, 0, 20, 12))                                          # (écriture directe : on prévient l'affichage)
        canvas._hover = None
        return std, canvas, s

    def _grab(self, std, canvas, mode):
        std.session.display_filter = mode
        canvas._bicubic_key = None
        canvas.update()
        return canvas.grab().toImage()

    def test_three_display_modes_differ_only_on_screen(self):
        std, canvas, s = self._edge_editor()
        before = s.layer().pix.read((0, 0, 20, 12)).copy()
        edge = canvas.to_widget(10.0, 6.0)                                       # frontière noir / blanc au centre
        row = int(edge.y())
        results = {}
        for mode in display.DISPLAY_FILTERS:
            image = self._grab(std, canvas, mode)
            results[mode] = [luminance(image, edge.x() + dx, row) for dx in range(-10, 10)]
        # voisin : marche franche, aucune valeur intermédiaire
        self.assertTrue(set(results["nearest"]) <= {0, 255})
        # bilinéaire et bicubique : transition progressive sur la frontière
        for mode in ("bilinear", "bicubic"):
            inter = [v for v in results[mode] if 10 < v < 245]
            self.assertGreaterEqual(len(inter), 3, mode)
            self.assertEqual(results[mode][0], 0)
            self.assertEqual(results[mode][-1], 255)
        # les pixels du DOCUMENT ne changent jamais
        self.assertTrue(np.array_equal(s.layer().pix.read((0, 0, 20, 12)), before))

    def test_nearest_stays_perfectly_sharp_at_100_percent(self):
        std, canvas, s = self._edge_editor(zoom=1.0)
        canvas.update()
        for mode in ("nearest", "bicubic"):                                       # à 100 % : jamais flouté, quel que soit le mode
            image = self._grab(std, canvas, mode)
            edge = canvas.to_widget(10.0, 6.0)
            values = [luminance(image, edge.x() + dx, edge.y()) for dx in (-2, -1, 0, 1)]
            self.assertEqual(values, [0, 0, 255, 255], mode)

    def test_bicubic_is_cached_until_the_document_or_view_changes(self):
        std, canvas, s = self._edge_editor()
        self._grab(std, canvas, "bicubic")
        key = canvas._bicubic_key
        self.assertIsNotNone(key)
        canvas.grab()
        self.assertEqual(canvas._bicubic_key, key)                                # même vue, même document : pas de recalcul
        s.layer().pix.write((15, 3, 16, 4), np.full((1, 1, 4), (0, 0, 0, 255), np.uint8))
        s.notify("edit", (15, 3, 16, 4))
        canvas.grab()
        self.assertNotEqual(canvas._bicubic_key, key)

    def test_bicubic_function_preserves_flat_colour_and_alpha(self):
        doc = M.new_document(8, 8, background=(40, 90, 200, 255))
        pixels = display.bicubic_view(doc, (2.5, 2.5), 1.0 / 6.0, (36, 36))
        self.assertTrue((pixels[..., 3] == 255).all())
        self.assertLessEqual(int(np.abs(pixels[..., 0].astype(int) - 40).max()), 1)
        self.assertLessEqual(int(np.abs(pixels[..., 2].astype(int) - 200).max()), 1)
        clear = M.new_document(8, 8, background=None)
        empty = display.bicubic_view(clear, (2.5, 2.5), 1.0 / 6.0, (24, 24))
        self.assertEqual(int(empty.max()), 0)                                      # transparent reste transparent (pas de frange)


class NativeExportTest(PsCase):
    def test_native_png_equals_document_pixels(self):
        from fm_photoshop import brush as B
        doc = M.new_document(60, 40, background=None)
        layer = doc.layers[0]
        stroke = B.Stroke(layer, "pixels", B.Brush(size=7, hardness=0.8, spacing=0.2, color=(10, 20, 30)), doc.rect())
        stroke.begin(8, 8)
        for i in range(1, 30):
            stroke.move(8 + i * 1.6, 8 + i * 0.9, 1.0, t=i / 120.0)
        stroke.finish_to(56, 34)
        stroke.end()
        flat = C.flatten_u8(doc)
        image = QImage(flat.data, 60, 40, 60 * 4, QImage.Format.Format_RGBA8888).copy()        # pixels natifs, sans canevas
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "natif.png")
            self.assertTrue(image.save(path))
            back = QImage(path).convertToFormat(QImage.Format.Format_RGBA8888)
        again = np.frombuffer(back.constBits(), np.uint8).reshape(40, 60, 4)
        self.assertTrue(np.array_equal(again, flat))                                # aucun traitement entre le moteur et le fichier
        alpha = flat[..., 3]
        partial = ((alpha > 5) & (alpha < 250)).sum()
        self.assertGreater(int(partial), int((alpha >= 250).sum() * 0.2))            # bord anticrénelé : niveaux intermédiaires nombreux


if __name__ == "__main__":
    unittest.main()
