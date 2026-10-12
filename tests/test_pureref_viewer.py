"""Planches PureRef dans la visionneuse : les images embarquees d'un .pur (1.x) deviennent des
fichiers du cache (recopie sans decodage, une fois) et remplacent la planche dans la liste de la
visionneuse, a sa place, avec un nom « planche.pur · n/N » ; l'image en cours suit celle de
l'inspecteur."""
import os as _os, sys as _sys  # jamais les vrais reglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QBuffer, QByteArray, QIODevice
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

import focus
import pipeline_browser as pb
import preview_column as pc


def encoded(color: str, fmt: str) -> bytes:
    image = QImage(40, 30, QImage.Format_RGB32)
    image.fill(QColor(color))
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.WriteOnly)
    image.save(buffer, fmt)
    return bytes(data)


class _Viewer:
    """Juste ce que _expand_viewer_pureref utilise de PipelineBrowser."""
    _expand_viewer_pureref = pb.PipelineBrowser._expand_viewer_pureref
    _pur_files = pb.PipelineBrowser._pur_files
    _remember_pur = pb.PipelineBrowser._remember_pur

    def __init__(self):
        self._pur_expansions, self._pur_sources, self._pur_tasks = {}, {}, {}
        self.detail = mock.Mock(_pur_image_path=None, _pur_image_index=0)
        self.started = []

    def _start_pur_images(self, pur, mtime):
        self.started.append(pur)


class PureRefViewerTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.cache = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.addCleanup(shutil.rmtree, self.cache, True)
        patcher = mock.patch.object(pc, "FILE_IMAGE_DISK_CACHE_DIR", self.cache)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.pur = self.dir / "planche.pur"
        header = b"\x00\x00\x00\x08" + "1.10".encode("utf-16-be") + b"\x00" * 40
        self.pur.write_bytes(header + encoded("#ff0000", "PNG") + b"\x00junk\x00" + encoded("#00ff00", "JPG")
                             + b"\x00" * 16)
        self.mtime = self.pur.stat().st_mtime

    def test_embedded_images_become_files(self):
        self.assertIsNone(pc.pur_image_files(self.pur, self.mtime))        # pas encore extraites
        files = pc.extract_pur_embedded_images(self.pur, self.mtime)
        self.assertEqual(len(files), 2)
        self.assertEqual([f.suffix for f in files], [".png", ".jpg"])
        self.assertFalse(QImage(str(files[0])).isNull())
        self.assertEqual(pc.pur_image_files(self.pur, self.mtime), files)  # ensuite : directement

    def test_task_reports_the_files(self):
        task = pc.PureRefImagesTask(self.pur, self.mtime)
        got = []
        task.signals.finished.connect(lambda *args: got.append(args))
        task.run()
        self.assertEqual(len(got[0][2]), 2)
        self.assertEqual(got[0][3], "")

    def test_viewer_list_replaces_the_board_by_its_images(self):
        before, after = self.dir / "a.jpg", self.dir / "z.jpg"
        viewer = _Viewer()
        paths, index = viewer._expand_viewer_pureref([before, self.pur, after], str(self.pur))
        self.assertEqual(paths, [before, self.pur, after])               # extraction lancee en fond
        self.assertEqual(viewer.started, [self.pur])
        pc.extract_pur_embedded_images(self.pur, self.mtime)
        viewer = _Viewer()
        viewer.detail._pur_image_path, viewer.detail._pur_image_index = str(self.pur), 1
        paths, index = viewer._expand_viewer_pureref([before, self.pur, after], str(self.pur))
        self.assertEqual(len(paths), 4)
        self.assertEqual((paths[0], paths[-1]), (before, after))
        self.assertEqual(index, 2)                                      # l'image montree par l'inspecteur
        self.assertEqual(focus.display_name(paths[1]), "planche.pur · 1/2")
        self.assertEqual(viewer._pur_sources[str(paths[2])], (self.pur, 1))


class InspectorWantedImageTest(unittest.TestCase):
    """Retour de la visionneuse : l'inspecteur montre l'image REGARDEE de la planche, meme si ses images
    ne sont pas encore listees (extraction en fond) — pas la premiere."""

    def fake(self):
        import detail_panel
        panel = mock.Mock()
        panel._pur_wanted, panel._pur_exported_images, panel._pur_image_ranges = None, [], []
        panel._pur_image_index, panel._pur_image_path = 0, "x.pur"
        panel._apply_pur_wanted = lambda p: detail_panel.DetailPanel._apply_pur_wanted(panel, p)
        panel.select_pur_image = lambda p, i: detail_panel.DetailPanel.select_pur_image(panel, p, i)
        return panel

    def test_rank_waits_for_the_images_then_applies(self):
        panel = self.fake()
        panel.select_pur_image("x.pur", 2)
        self.assertEqual(panel._pur_image_index, 0)                      # pas encore d'images
        self.assertEqual(panel._pur_wanted, ("x.pur", 2))
        panel._pur_exported_images = ["a", "b"]                            # extraction partielle
        self.assertFalse(panel._apply_pur_wanted("x.pur"))
        panel._pur_exported_images = ["a", "b", "c"]
        self.assertTrue(panel._apply_pur_wanted("x.pur"))
        self.assertEqual(panel._pur_image_index, 2)
        self.assertIsNone(panel._pur_wanted)

    def test_known_images_navigate_at_once(self):
        panel = self.fake()
        panel._pur_image_ranges = [(0, 1, "PNG")] * 3
        panel.select_pur_image("x.pur", 1)
        self.assertEqual(panel._pur_image_index, 1)
        panel._navigate_pur_image.assert_called_with(0)

    def test_other_board_is_ignored(self):
        panel = self.fake()
        panel.select_pur_image("autre.pur", 1)
        panel._pur_exported_images = ["a", "b"]
        self.assertFalse(panel._apply_pur_wanted("x.pur"))
        self.assertEqual(panel._pur_image_index, 0)


if __name__ == "__main__":
    unittest.main()
