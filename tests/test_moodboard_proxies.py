import _isolate  # noqa: F401
import os
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import numpy as np
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication
from fm_video.thumbs import MoodboardProxyCache

APP = QApplication.instance() or QApplication([])


class MoodboardProxiesTest(unittest.TestCase):
    def setUp(self):
        # Le répertoire temporaire du bac à sable Windows refuse certains renommages.
        self.tmp = tempfile.TemporaryDirectory(prefix="mood_proxy_test_", dir=Path(__file__).resolve().parents[1])
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "film.mkv"
        self.path.write_bytes(b"video originale")
        self.source = SimpleNamespace(width=1920, height=1080)
        self.cache = MoodboardProxyCache(self.path)

    def test_proxy_is_1200_wide_in_film_moodboards_folder_and_reused(self):
        pixels = np.full((675, 1200, 3), 128, np.uint8)
        with mock.patch("fm_video.thumbs.video_thumbnail", return_value=pixels) as decode:
            small = self.cache.pixels(self.source, 12, 100)
            decode.assert_called_once_with(self.source, 12, 675)
        target = self.cache.filename(12)
        self.assertEqual(target.parent, self.path.parent / "Moodboards" /
                         f"{self.path.stem} - {self.cache.identity}")
        self.assertEqual(QImage(str(target)).size().toTuple(), (1200, 675))
        self.assertEqual(small.shape[0], 100)
        with mock.patch("fm_video.thumbs.video_thumbnail") as decode:
            # Nouvelle ouverture et zoom : le JPEG suffit, sans décoder la vidéo.
            large = MoodboardProxyCache(self.path).pixels(self.source, 12, 2000)
            decode.assert_not_called()
        self.assertEqual(large.shape, (675, 1200, 3))
        self.assertEqual(self.path.read_bytes(), b"video originale")

    def test_old_proxy_without_manifest_is_removed_before_regeneration(self):
        target = self.cache.filename(12)
        previous = self.path.parent / f'{self.path.name}.moodboard_old.jpg'
        image = QImage(1200, 675, QImage.Format_RGB888)
        image.fill(0)
        self.assertTrue(image.save(str(previous), "JPEG"))
        self.assertFalse(self.cache.prepare([12]))
        self.assertFalse(target.is_file())
        self.assertFalse(previous.exists())

    def _make_board(self, indices=(0, 7), layout=(2, 1)):
        self.cache.prepare(indices, layout)
        with mock.patch("fm_video.thumbs.video_thumbnail", return_value=np.zeros((675, 1200, 3), np.uint8)):
            for index in indices:
                self.cache.pixels(self.source, index, 100)

    def test_matching_board_reuses_all_files_without_rewriting(self):
        self._make_board()
        before = {p: p.stat().st_mtime_ns for p in self.cache.filename(0).parent.iterdir()}
        self.assertTrue(MoodboardProxyCache(self.path).prepare([0, 7], (2, 1)))
        self.assertEqual(before, {p: p.stat().st_mtime_ns for p in before})

    def test_new_width_removes_entire_previous_board(self):
        self._make_board()
        old = [self.cache.filename(i) for i in (0, 7)]
        new = MoodboardProxyCache(self.path, 640)
        self.assertFalse(new.prepare([0, 7], (2, 1)))
        self.assertTrue(all(not path.exists() for path in old))
        with mock.patch("fm_video.thumbs.video_thumbnail", return_value=np.zeros((360, 640, 3), np.uint8)):
            for index in (0, 7):
                new.pixels(self.source, index, 100)
        self.assertEqual(set(new.filename(0).parent.glob("*.jpg")), {new.filename(i) for i in (0, 7)})

    def test_changed_frames_layout_and_incomplete_board_remove_all_proxies(self):
        for indices, layout in (([0, 3, 7], (3, 1)), ([0, 7], (1, 2)), ([0, 7], (2, 1))):
            self._make_board()
            if layout == (2, 1):
                self.cache.filename(7).unlink()
            self.assertFalse(self.cache.prepare(indices, layout))
            self.assertEqual(list(self.cache.filename(0).parent.glob("*.jpg")), [])

    def test_small_sources_still_produce_exactly_1200_pixels(self):
        source = SimpleNamespace(width=160, height=96)
        with mock.patch("fm_video.thumbs.video_thumbnail", return_value=np.zeros((96, 160, 3), np.uint8)):
            self.cache.pixels(source, 0, 100)
        self.assertEqual(QImage(str(self.cache.filename(0))).size().toTuple(), (1200, 720))

    def test_modified_video_has_distinct_proxies(self):
        before = self.cache.filename(0)
        self.path.write_bytes(b"nouvelle version de la video")
        self.assertNotEqual(before, MoodboardProxyCache(self.path).filename(0))
        other = self.path.with_suffix(".mp4")
        other.write_bytes(self.path.read_bytes())
        # Deux copies de contenu identique partagent la même identité.
        copied = MoodboardProxyCache(other)
        self.assertEqual(MoodboardProxyCache(self.path).identity, copied.identity)

    def test_old_hash_only_folder_is_renamed_with_the_film_name(self):
        self._make_board()
        old = self.cache.directory.parent / self.cache.identity
        self.cache.directory.rename(old)
        migrated = MoodboardProxyCache(self.path)
        self.assertEqual(migrated.directory.name, f"film - {self.cache.identity}")
        self.assertTrue(migrated.prepare([0, 7], (2, 1)))
        self.assertFalse(old.exists())

    def test_full_png_and_rename_keep_existing_proxies(self):
        self._make_board()
        self.cache.export([0, 7], (2, 1))
        output = self.cache.directory / '.moodboard - film.png'
        self.assertEqual(QImage(str(output)).size().toTuple(), (2400, 675))
        before = {p.name: p.stat().st_mtime_ns for p in self.cache.directory.glob('*.jpg')}
        renamed = self.path.with_name('nouveau nom.mkv')
        self.path.rename(renamed)
        cache = MoodboardProxyCache(renamed)
        self.assertEqual(cache.identity, self.cache.identity)
        self.assertEqual(cache.directory.name, f"nouveau nom - {self.cache.identity}")
        self.assertTrue(cache.prepare([0, 7], (2, 1)))
        cache.export([0, 7], (2, 1))
        self.assertFalse(output.exists())
        self.assertTrue((cache.directory / '.moodboard - nouveau nom.png').exists())
        self.assertEqual(before, {p.name: p.stat().st_mtime_ns for p in cache.directory.glob('*.jpg')})

    def test_full_png_has_no_gap_between_proxies(self):
        self._make_board(layout=(2, 1, 1200, 675, 40))
        self.cache.export([0, 7], (2, 1, 1200, 675, 40))
        output = self.cache.directory / '.moodboard - film.png'
        self.assertEqual(QImage(str(output)).size().toTuple(), (2400, 675))

    def test_new_board_replaces_png(self):
        self._make_board()
        self.cache.export([0, 7], (2, 1))
        self.cache.prepare([0], (1, 1))
        with mock.patch('fm_video.thumbs.video_thumbnail', return_value=np.zeros((675, 1200, 3), np.uint8)):
            self.cache.pixels(self.source, 0, 100)
        self.cache.export([0], (1, 1))
        outputs = list(self.cache.directory.glob('.moodboard - *.png'))
        self.assertEqual(len(outputs), 1)
        self.assertEqual(QImage(str(outputs[0])).size().toTuple(), (1200, 675))

    def test_configured_width_preserves_ratio_and_default_proxies(self):
        cache = MoodboardProxyCache(self.path, 640)
        with mock.patch("fm_video.thumbs.video_thumbnail", return_value=np.zeros((360, 640, 3), np.uint8)):
            cache.pixels(self.source, 0, 100)
        self.assertEqual(QImage(str(cache.filename(0))).size().toTuple(), (640, 360))
        self.assertNotEqual(cache.filename(0), self.cache.filename(0))

    def test_read_only_directory_keeps_moodboard_working(self):
        with mock.patch("fm_video.thumbs.video_thumbnail", return_value=np.zeros((675, 1200, 3), np.uint8)), \
                mock.patch("fm_video.thumbs.tempfile.mkstemp", side_effect=PermissionError):
            pixels = self.cache.pixels(self.source, 0, 100)
        self.assertEqual(pixels.shape[0], 100)
        self.assertFalse(self.cache.filename(0).exists())

    def test_fast_board_change_does_not_publish_old_images(self):
        from test_video_module import wait
        from fm_video.thumbs import ThumbnailLoader
        started, release = threading.Event(), threading.Event()
        source = SimpleNamespace(kind="video", width=1920, height=1080, close=lambda: None)

        def decode(source, index, height):
            if index == 0:
                started.set()
                release.wait(5)
            return np.zeros((height, round(height * 16 / 9), 3), np.uint8)

        with mock.patch("fm_video.media.open_media", return_value=source), \
                mock.patch("fm_video.thumbs.video_thumbnail", side_effect=decode):
            loader = ThumbnailLoader(self.path, moodboard_proxies=True)
            images = {}
            loader.ready.connect(lambda index, image: images.update({index: image}))
            try:
                loader.set_moodboard([0, 1], (2, 1))
                loader.request([0, 1])
                self.assertTrue(started.wait(5))
                loader.set_proxy_width(640)
                loader.set_moodboard([3, 7], (1, 2))
                loader.request([3])                           # zoom : le reste du moodboard doit aussi être produit
                release.set()
                self.assertTrue(wait(lambda: len(images) == 2, 5))
                self.assertEqual(set(images), {3, 7})
                cache = MoodboardProxyCache(self.path, 640)
                self.assertEqual(set(cache.filename(3).parent.glob("*.jpg")),
                                 {cache.filename(i) for i in (3, 7)})
            finally:
                release.set()
                loader.stop()
                for thread in loader._threads:
                    thread.join(5)

    def test_real_video_worker_writes_and_reuses_proxies(self):
        from test_video_module import HAS_AV, FFMPEG, make_video, wait
        from fm_video.thumbs import ThumbnailLoader
        if not HAS_AV or not FFMPEG:
            self.skipTest("PyAV et FFmpeg requis")
        video = self.path.with_suffix(".mp4")
        make_video(video, count=8)
        for reopening in (False, True):
            loader = ThumbnailLoader(video, moodboard_proxies=True)
            images = {}
            loader.ready.connect(lambda index, image: images.update({index: image}))
            try:
                if reopening:
                    with mock.patch("fm_video.thumbs.video_thumbnail", side_effect=AssertionError("redécodage")):
                        loader.request([0, 7])
                        self.assertTrue(wait(lambda: len(images) == 2, 5))
                else:
                    loader.request([0, 7])
                    self.assertTrue(wait(lambda: len(images) == 2, 5))
                cache = MoodboardProxyCache(video)
                for index in (0, 7):
                    self.assertEqual(QImage(str(cache.filename(index))).width(), 1200)
                if reopening:
                    self.assertTrue(loader.set_proxy_width(640))
                    self.assertFalse(loader.set_proxy_width(640))
                    images.clear()
                    loader.request([0, 7])
                    self.assertTrue(wait(lambda: len(images) == 2, 5))
                    for index in (0, 7):
                        self.assertEqual(QImage(str(MoodboardProxyCache(video, 640).filename(index))).width(), 640)
                        self.assertFalse(cache.filename(index).exists())
            finally:
                loader.stop()
                for thread in loader._threads:
                    thread.join(5)


if __name__ == "__main__":
    unittest.main()
