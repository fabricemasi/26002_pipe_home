"""Module Photoshop : export en tâche de fond — l'export part d'un INSTANTANÉ (peindre pendant l'export ne le change
pas), l'erreur est rapportée sans fichier à moitié écrit, écriture atomique, plusieurs formats."""
import os as _os, sys as _sys  # jamais les vrais réglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import unittest
from unittest import mock

import numpy as np

from PIL import Image

from _photoshop_case import PsCase
from fm_photoshop import compose as C, exporter, io_images, model as M


class ExportTest(PsCase):
    def test_snapshot_isolates_the_export_from_later_edits(self):
        _item, std = self.editor(48, 32, background="Transparent")
        s = std.session
        s.layer().pix.write((0, 0, 48, 32), np.full((32, 48, 4), (10, 200, 30, 255), np.uint8))
        expected = C.flatten_u8(s.doc)
        target = self.tmp / "snap.png"
        job = std.export(str(target))                                     # tâche de fond, rendue tout de suite
        s.layer().pix.write((0, 0, 48, 32), np.zeros((32, 48, 4), np.uint8))   # on continue à éditer pendant l'export
        self.assertTrue(job.wait())
        self.assertIsNone(job.error)
        with Image.open(target) as image:
            self.assertTrue(np.array_equal(np.array(image.convert("RGBA")), expected))     # l'état du lancement
        self.assertNotIn(job, exporter._RUNNING)

    def test_errors_are_reported_and_leave_no_partial_file(self):
        _item, std = self.editor(16, 16)
        target = self.tmp / "mauvais.xyz"
        with mock.patch("PySide6.QtWidgets.QMessageBox.warning") as warning:
            job = std.export(str(target), wait=True)
            self.assertTrue(job.done)
            self.assertIsInstance(job.error, io_images.ImageError)
            self.assertTrue(warning.called)
        self.assertFalse(target.exists())
        self.assertEqual([p.name for p in self.tmp.iterdir() if p.name.endswith(".part")], [])

    def test_all_formats_export_and_read_back(self):
        _item, std = self.editor(20, 12, background="Transparent")
        std.session.layer().pix.write((2, 2, 10, 8), np.full((6, 8, 4), (200, 50, 100, 200), np.uint8))
        flat = C.flatten_u8(std.session.doc)
        for suffix in (".png", ".tif"):
            target = self.tmp / f"f{suffix}"
            job = std.export(str(target), wait=True)
            self.assertIsNone(job.error, suffix)
            rgba, _dpi, _icc, _notes = io_images.import_image(target)
            self.assertTrue(np.array_equal(rgba, flat), suffix)
        # WebP : sans perte = exact ; avec perte = alpha exact (qualité réglable)
        lossless = self.tmp / "sans_perte.webp"
        io_images.export_document(std.session.doc, lossless, lossless=True)
        self.assertTrue(np.array_equal(io_images.import_image(lossless)[0], flat))
        lossy = self.tmp / "avec_perte.webp"
        io_images.export_document(std.session.doc, lossy, quality=40)
        self.assertTrue(np.array_equal(io_images.import_image(lossy)[0][..., 3], flat[..., 3]))
        jpeg = self.tmp / "f.jpg"
        job = std.export(str(jpeg), wait=True)
        self.assertTrue(any("JPEG" in n for n in job.notes))


class SnapshotTest(unittest.TestCase):
    def test_snapshot_is_structurally_independent(self):
        doc = M.new_document(8, 8)
        group = M.Layer("g", "group")
        child = M.Layer("c")
        child.pix.set_all(0, 0, np.full((2, 2, 4), 9, np.uint8))
        group.children = [child]
        doc.layers.append(group)
        copy, chosen = exporter.snapshot(doc, child)
        self.assertIsNot(copy.layers[1].children[0], child)
        self.assertIs(chosen, copy.layers[1].children[0])
        child.pix.data[:] = 1
        self.assertEqual(int(chosen.pix.data[0, 0, 0]), 9)
        self.assertEqual([l.uid for l in copy.walk()], [l.uid for l in copy.walk()])


if __name__ == "__main__":
    unittest.main()
