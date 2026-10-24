import _isolate  # noqa: F401 — ne jamais modifier les réglages réels
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QApplication, QListWidgetItem

APP = QApplication.instance() or QApplication([])
import previews
import column
from browser_core import ROLE_PATH, ROLE_ISDIR


class ManualFilePreviewTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "video.MKV"
        self.path.touch()

    def test_mkv_selection_never_decodes_but_keeps_existing_preview(self):
        with mock.patch.object(previews, "_read_preview_pixmap", return_value=(None, False)), \
                mock.patch.object(previews, "_decode_video_frame") as decode:
            self.assertIsNone(previews.file_image_pixmap(self.path))
            decode.assert_not_called()
        pix = QPixmap(8, 8)
        with mock.patch.object(previews, "_read_preview_pixmap", return_value=(pix, False)):
            self.assertIs(previews.file_image_pixmap(self.path), pix)

    def test_mkv_background_requests_only_read_cache(self):
        manager = previews._PreviewDecodeManager()
        with mock.patch.object(previews._IMAGE_DECODE_POOL, "start"):
            manager.request(self.path, 1, quiet=True)
        task = manager.active[str(self.path)]
        self.assertTrue(task.cache_only)
        with mock.patch.object(previews, "_decode_video_frame") as decode, \
                mock.patch.object(previews, "_find_stale_preview_cache", return_value=None):
            task.run()
        decode.assert_not_called()

    def test_explicit_mkv_request_decodes_in_worker(self):
        manager = previews._PreviewDecodeManager()
        with mock.patch.object(previews._IMAGE_DECODE_POOL, "start") as start:
            manager.request(self.path, 1, force_render=True)
        task = manager.active[str(self.path)]
        start.assert_called_once()
        self.assertFalse(task.cache_only)
        with mock.patch.object(previews, "_decode_video_frame", return_value=None) as decode:
            task.run()
        decode.assert_called_once()

    def test_other_videos_remain_automatic(self):
        manager = previews._PreviewDecodeManager()
        path = self.path.with_suffix(".mp4")
        with mock.patch.object(previews._IMAGE_DECODE_POOL, "start"):
            manager.request(path, 1, quiet=True)
        self.assertFalse(manager.active[str(path)].cache_only)

    def test_manual_request_is_kept_while_cache_is_loading(self):
        manager = previews._PreviewDecodeManager()
        with mock.patch.object(previews._IMAGE_DECODE_POOL, "start") as start:
            manager.request(self.path, 1, quiet=True)
            cached_task = manager.active[str(self.path)]
            manager.request(self.path, 1, force_render=True)
            manager._on_finished(cached_task, str(self.path), 1, None)
        self.assertEqual(start.call_count, 2)
        self.assertFalse(manager.active[str(self.path)].cache_only)

    def test_file_menu_launches_explicit_request(self):
        widget = column.Column(Path(self.tmp.name), "Test")
        self.addCleanup(widget.deleteLater)
        widget._load_timer.stop()
        widget.list.clear()
        item = QListWidgetItem("video.MKV", widget.list)
        item.setData(ROLE_PATH, str(self.path))
        item.setData(ROLE_ISDIR, False)
        pos = widget.list.visualItemRect(item).center()

        def choose(menu, *args):
            action = next(a for a in menu.actions() if a.text() == "Créer un aperçu automatique")
            self.assertTrue(action.isEnabled())
            return action

        with mock.patch.object(column.Menu, "exec", choose), \
                mock.patch.object(column._PREVIEW_DECODE_MANAGER, "request") as request:
            widget._on_context_menu(pos)
            APP.processEvents()
        request.assert_called_once_with(self.path, self.path.stat().st_mtime, force_render=True)


if __name__ == "__main__":
    unittest.main()
