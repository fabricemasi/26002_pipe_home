import _isolate  # noqa: F401 -- ne touche pas aux reglages utilisateur
import json
import os
import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtGui import QImage, QImageIOHandler, QPixmap
from PySide6.QtCore import QSize
from PySide6.QtWidgets import QApplication

import lightroom_bridge
import focus
import previews

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_app = QApplication.instance() or QApplication([])


class LightroomPreviewFallbackTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.photo = self.base / "photos" / "test.jpg"
        self.photo.parent.mkdir()
        image = QImage(12, 8, QImage.Format_RGB32)
        image.fill(0xFF336699)
        self.assertTrue(image.save(str(self.photo), "JPEG"))
        self.catalog = self.base / "catalogue.lrcat"
        (self.photo.parent / lightroom_bridge.MARKER).write_text(
            json.dumps({"catalog": str(self.catalog)}), encoding="utf-8")
        self.cache = self.base / "cache"
        (self.cache / "images").mkdir(parents=True)
        self.photo_info = {"uuid": "12345678-1234-1234-1234-123456789abc",
                           "local_id": 1, "revision": "1:1"}
        self.key = (os.path.normcase(str(self.photo.resolve())),
                    os.path.normcase(str(self.catalog)))
        self.origin_before = lightroom_bridge._preview_origins.get(str(self.photo))
        self.displayed_before = str(self.photo) in lightroom_bridge._displayed_from

    def tearDown(self):
        lightroom_bridge._automatic_requests.pop(self.key, None)
        lightroom_bridge._preview_origins.pop(str(self.photo), None)
        lightroom_bridge._displayed_from.discard(str(self.photo))
        previews._file_image_cache.pop(str(self.photo), None)
        previews._file_image_column_cache.pop(str(self.photo), None)
        if self.origin_before is not None:
            lightroom_bridge._preview_origins[str(self.photo)] = self.origin_before
        if self.displayed_before:
            lightroom_bridge._displayed_from.add(str(self.photo))

    def _fetch(self, entry=None):
        with (patch.object(lightroom_bridge, "_catalog_photo", return_value=self.photo_info),
              patch.object(lightroom_bridge, "_lightroom_preview_path", return_value=entry),
              patch.object(lightroom_bridge, "_cache_root", return_value=self.cache),
              patch.object(lightroom_bridge, "_plugin_is_live", return_value=False),
              patch.object(lightroom_bridge, "_ensure_preview_monitor"),
              patch("previews._decode_2d_image", return_value=QImage(str(self.photo)))):
            lightroom_bridge._fetch(self.photo, self.photo.stat().st_mtime,
                                    self.catalog, self.key)

    def _fetch_unindexed(self):
        with (patch.object(lightroom_bridge, "_catalog_photo", return_value=None),
              patch.object(lightroom_bridge, "_cache_root", return_value=self.cache),
              patch.object(lightroom_bridge, "_ensure_preview_monitor"),
              patch("previews._decode_2d_image", return_value=QImage(str(self.photo)))):
            lightroom_bridge._fetch(self.photo, self.photo.stat().st_mtime,
                                    self.catalog, self.key)

    def _application_preview(self):
        with patch.object(lightroom_bridge, "_cache_root", return_value=self.cache):
            return lightroom_bridge._application_preview_path(
                self.photo, self.photo.stat().st_mtime, self.catalog)

    def test_missing_lightroom_preview_uses_and_marks_local_fallback(self):
        self._fetch()
        app_preview = self._application_preview()
        self.assertTrue(app_preview.is_file())
        self.assertEqual(lightroom_bridge.preview_origin(self.photo), "application")

    def test_photo_not_in_lightroom_catalog_still_gets_local_preview(self):
        self._fetch_unindexed()
        self.assertTrue(self._application_preview().is_file())
        self.assertEqual(lightroom_bridge.preview_origin(self.photo), "application")

    def test_fallback_does_not_wait_when_plugin_is_stopped(self):
        with (patch.object(lightroom_bridge, "_catalog_photo", return_value=self.photo_info),
              patch.object(lightroom_bridge, "_lightroom_preview_path", return_value=None),
              patch.object(lightroom_bridge, "_cache_root", return_value=self.cache),
              patch.object(lightroom_bridge, "_plugin_is_live", return_value=False),
              patch.object(lightroom_bridge, "_ensure_preview_monitor"),
              patch("previews._decode_2d_image", return_value=QImage(str(self.photo)))):
            lightroom_bridge._fetch(self.photo, self.photo.stat().st_mtime, self.catalog, self.key)
        self.assertFalse((self.cache / "requests").exists())
        self.assertEqual(lightroom_bridge.preview_origin(self.photo), "application")

    def test_new_lightroom_preview_removes_local_fallback(self):
        self._fetch()
        app_preview = self._application_preview()
        lightroom_preview = self.base / "lightroom.jpg"
        image = QImage(16, 10, QImage.Format_RGB32)
        image.fill(0xFFAA5500)
        self.assertTrue(image.save(str(lightroom_preview), "JPEG"))
        entry = (lightroom_preview, "AB", self.photo_info["uuid"], "a" * 32)
        self._fetch(entry)
        self.assertFalse(app_preview.exists())
        self.assertEqual(lightroom_bridge.preview_origin(self.photo), "lightroom")

    def test_cached_sdk_render_is_displayed_without_pyramid(self):
        self._fetch()
        app_preview = self._application_preview()
        with patch.object(lightroom_bridge, "_cache_root", return_value=self.cache):
            rendered = lightroom_bridge._lightroom_request_path(self.photo, self.photo_info, self.catalog)
        image = QImage(1200, 800, QImage.Format_RGB32)
        image.fill(0xFFAA5500)
        self.assertTrue(image.save(str(rendered), "JPEG"))
        self._fetch()
        self.assertEqual(lightroom_bridge.preview_origin(self.photo), "lightroom")
        self.assertFalse(app_preview.exists())
        shown = previews._file_image_cache[str(self.photo)][1]
        self.assertLessEqual(max(shown.width(), shown.height()), previews.FILE_IMAGE_CACHE_MAX_DIM)
        self.assertEqual(QImage(str(rendered)).size(), image.size())

    def test_live_plugin_receives_automatic_preview_request(self):
        requests = self.cache / "requests"
        replies = self.cache / "replies"
        requests.mkdir()
        replies.mkdir()
        with (patch.object(lightroom_bridge, "_catalog_photo", return_value=self.photo_info),
              patch.object(lightroom_bridge, "_lightroom_preview_path", return_value=None),
              patch.object(lightroom_bridge, "_cache_root", return_value=self.cache),
              patch.object(lightroom_bridge, "_plugin_is_live", return_value=True),
              patch.object(lightroom_bridge, "_write_connection"),
              patch.object(lightroom_bridge.os, "replace", side_effect=shutil.copyfile),
              patch.object(lightroom_bridge, "_ensure_preview_monitor")):
            rendered = lightroom_bridge._lightroom_request_path(self.photo, self.photo_info, self.catalog)
            def respond():
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    pending = list(requests.glob("*.req"))
                    if pending:
                        image = QImage(16, 10, QImage.Format_RGB32)
                        image.fill(0xFFAA5500)
                        image.save(str(rendered), "JPEG")
                        (replies / (pending[0].stem + ".json")).write_text('{"ok": true}', encoding="utf-8")
                        return
                    time.sleep(.01)
            worker = threading.Thread(target=respond, daemon=True)
            worker.start()
            lightroom_bridge._fetch(self.photo, self.photo.stat().st_mtime, self.catalog, self.key)
            worker.join(1)
            lightroom_bridge._poll_automatic_requests()
        self.assertTrue(rendered.is_file(),
                        f"requests={list(requests.iterdir())}, replies={list(replies.iterdir())}, "
                        f"cache={list((self.cache / 'images').iterdir())}")
        self.assertEqual(lightroom_bridge.preview_origin(self.photo), "lightroom")
        self.assertFalse(self._application_preview().exists())

    def test_focus_prefers_large_sdk_render_over_catalog_thumbnail(self):
        small = self.base / "lightroom-small.jpg"
        image = QImage(242, 162, QImage.Format_RGB32)
        image.fill(0xFF336699)
        self.assertTrue(image.save(str(small), "JPEG"))
        with (patch.object(lightroom_bridge, "_catalog_photo", return_value=self.photo_info),
              patch.object(lightroom_bridge, "_lightroom_preview_path",
                           return_value=(small, "AB", self.photo_info["uuid"], "a" * 32)),
              patch.object(lightroom_bridge, "_cache_root", return_value=self.cache)):
            rendered = lightroom_bridge._lightroom_request_path(self.photo, self.photo_info, self.catalog)
            large = QImage(1600, 1067, QImage.Format_RGB32)
            large.fill(0xFFAA5500)
            self.assertTrue(large.save(str(rendered), "JPEG"))
            # Vignette de la pyramide trop petite (< 640 px) : le proxy est le rendu SDK...
            self.assertEqual(lightroom_bridge.proxy_path(self.photo), rendered)
            self.assertEqual(lightroom_bridge.proxy_path(self.photo, max_dimension=640), rendered)
            # ... et l'image en focus aussi (jamais la vignette).
            self.assertEqual(lightroom_bridge.large_file(self.photo)[0], rendered)

    def test_focus_requests_large_render_when_only_thumbnail_exists(self):
        small = self.base / "lightroom-small.jpg"
        image = QImage(242, 162, QImage.Format_RGB32)
        image.fill(0xFF336699)
        self.assertTrue(image.save(str(small), "JPEG"))
        key = os.path.normcase(os.path.abspath(str(self.photo)))
        with (patch.object(lightroom_bridge, "managed_folder", return_value=(self.photo.parent, self.catalog)),
              patch.object(lightroom_bridge, "_plugin_is_live", return_value=True),
              patch.object(lightroom_bridge, "_catalog_photo", return_value=self.photo_info),
              patch.object(lightroom_bridge, "_cache_root", return_value=self.cache),
              patch.object(lightroom_bridge, "proxy_path", return_value=small),
              patch.object(lightroom_bridge, "create_preview") as create):
            lightroom_bridge._check_large_preview(self.photo, 1600, 1000, key)
        create.assert_called_once_with(self.photo)
        lightroom_bridge._large_preview_retry_after.pop((key, self.photo_info["revision"]), None)

    def test_cached_film_thumbnail_does_not_requery_lightroom_during_paint(self):
        mtime = previews.cached_mtime(self.photo)
        pixmap = QPixmap(40, 30)
        key = (str(self.photo), 80)
        focus._THUMBS[key] = (mtime, pixmap)
        self.addCleanup(focus._THUMBS.pop, key, None)
        with patch.object(lightroom_bridge, "is_managed", side_effect=AssertionError("disk lookup")):
            self.assertIs(focus.thumbnail(self.photo, 80), pixmap)

    def test_lightroom_film_task_reduces_thumbnail_without_disk_copy(self):
        large = self.base / "large.jpg"
        image = QImage(900, 600, QImage.Format_RGB32)
        image.fill(0xFF336699)
        self.assertTrue(image.save(str(large), "JPEG"))
        key = str(large)
        self.addCleanup(focus._FILM.pop, key, None)
        with (patch.object(lightroom_bridge, "is_managed", return_value=True),
              patch.object(lightroom_bridge, "proxy_path", return_value=large),
              patch.object(focus._FilmTask, "_store", side_effect=AssertionError("disk write"))):
            focus._FilmTask(key, large.stat().st_mtime, None).run()
        self.assertLessEqual(max(focus._FILM[key][1].width(), focus._FILM[key][1].height()),
                             focus.FILM_THUMB_MAX)

    def test_gallery_reads_small_lightroom_proxy(self):
        small = self.base / "small.jpg"
        image = QImage(160, 100, QImage.Format_RGB32)
        image.fill(0xFF336699)
        self.assertTrue(image.save(str(small), "JPEG"))
        signals = focus._ProxySignals()
        received = []
        signals.done.connect(lambda _key, _mtime, _side, image, _full: received.append(image))
        with (patch.object(lightroom_bridge, "is_managed", return_value=True),
              patch.object(lightroom_bridge, "proxy_path", return_value=small) as proxy):
            focus._ProxyTask(signals, str(self.photo), self.photo.stat().st_mtime, 480).run()
        proxy.assert_called_once_with(self.photo)
        self.assertEqual(received[0].size(), QSize(160, 100))

    def test_oriented_small_and_large_proxies_have_distinct_cache_files(self):
        source_files = []
        for side in (160, 800):
            source = self.base / f"preview_{side}"
            image = QImage(side, side // 2, QImage.Format_RGB32)
            image.fill(0xFF336699)
            self.assertTrue(image.save(str(source), "JPEG"))
            source_files.append(source)
        with (patch.object(lightroom_bridge, "_cache_root", return_value=self.cache),
              patch.object(lightroom_bridge.os, "replace", side_effect=shutil.copyfile)):
            small = lightroom_bridge._oriented_preview_path(source_files[0], "BC", "uuid", "digest", self.catalog)
            large = lightroom_bridge._oriented_preview_path(source_files[1], "BC", "uuid", "digest", self.catalog)
        self.assertNotEqual(small, large)
        self.assertEqual(QImage(str(small)).size(), QSize(80, 160))
        self.assertEqual(QImage(str(large)).size(), QSize(400, 800))

    def test_focus_uses_full_image_when_lightroom_proxy_is_tiny(self):
        original = self.base / "full.jpg"
        large = QImage(1200, 800, QImage.Format_RGB32)
        large.fill(0xFF336699)
        self.assertTrue(large.save(str(original), "JPEG"))
        small = self.base / "small.jpg"
        self.assertTrue(large.scaled(160, 107).save(str(small), "JPEG"))
        signals = focus._DecodeSignals()
        received = []
        signals.done.connect(lambda *_args: received.append(_args))
        with (patch.object(lightroom_bridge, "is_managed", return_value=True),
              patch.object(lightroom_bridge, "large_file", return_value=None),
              patch.object(lightroom_bridge, "proxy_path", return_value=small)):
            focus._DecodeTask(signals, str(original), original.stat().st_mtime, QSize(600, 400), 8192).run()
        self.assertEqual(received[0][2].size(), QSize(1200, 800))
        self.assertEqual(received[0][5], "Image originale")

    def test_focus_keeps_large_lightroom_preview_with_edits(self):
        proxy_image = QImage(1200, 800, QImage.Format_RGB32)
        proxy_image.fill(0xFFAA5500)
        proxy = self.base / "large-lightroom.jpg"
        self.assertTrue(proxy_image.save(str(proxy), "JPEG"))
        signals = focus._DecodeSignals()
        received = []
        signals.done.connect(lambda *_args: received.append(_args))
        source = "Lightroom · aperçu développé 1200 px (Previews.lrdata)"
        with (patch.object(lightroom_bridge, "is_managed", return_value=True),
              patch.object(lightroom_bridge, "large_file", return_value=(proxy, source))):
            # Zone de focus plus GRANDE que l'aperçu : il reste montré (jamais l'original non développé).
            focus._DecodeTask(signals, str(self.photo), self.photo.stat().st_mtime, QSize(2400, 1600), 8192).run()
        self.assertEqual(received[0][2].size(), QSize(1200, 800))
        self.assertEqual(received[0][5], source)

    def test_focus_applies_lightroom_orientation_to_unrotated_original(self):
        original = self.base / "landscape.jpg"
        image = QImage(1200, 800, QImage.Format_RGB32)
        image.fill(0xFF336699)
        self.assertTrue(image.save(str(original), "JPEG"))
        proxy = self.base / "portrait-proxy.jpg"
        self.assertTrue(image.scaled(160, 240).save(str(proxy), "JPEG"))
        signals = focus._DecodeSignals()
        received = []
        signals.done.connect(lambda *_args: received.append(_args))
        with (patch.object(lightroom_bridge, "is_managed", return_value=True),
              patch.object(lightroom_bridge, "proxy_path", return_value=proxy),
              patch.object(lightroom_bridge, "orientation", return_value="DA")):
            focus._DecodeTask(signals, str(original), original.stat().st_mtime, QSize(600, 400), 8192).run()
        self.assertEqual(received[0][2].size(), QSize(800, 1200))

    def test_focus_does_not_double_rotate_raw_with_exif_orientation(self):
        raw = self.base / "portrait.RAF"
        raw.touch()
        proxy = self.base / "portrait-proxy.jpg"
        image = QImage(160, 240, QImage.Format_RGB32)
        image.fill(0xFF336699)
        self.assertTrue(image.save(str(proxy), "JPEG"))
        oriented = QImage(800, 1200, QImage.Format_RGB32)
        oriented.fill(0xFF336699)
        signals = focus._DecodeSignals()
        received = []
        signals.done.connect(lambda *_args: received.append(_args))
        with (patch.object(lightroom_bridge, "is_managed", return_value=True),
              patch.object(lightroom_bridge, "proxy_path", return_value=proxy),
              patch.object(lightroom_bridge, "orientation", return_value="DA"),
              patch.object(previews, "_decode_embedded_jpeg",
                           return_value=(oriented, QImageIOHandler.Transformation.TransformationRotate270))):
            focus._DecodeTask(signals, str(raw), raw.stat().st_mtime, QSize(600, 400), 8192).run()
        self.assertEqual(received[0][2].size(), QSize(800, 1200))

    def test_initial_prefetch_is_bounded(self):
        photos = [self.photo.parent / f"image-{index}.jpg" for index in range(100)]
        with patch.object(lightroom_bridge._pool, "submit") as submit:
            lightroom_bridge.request_previews(photos)
        self.assertEqual(len(submit.call_args.args[1]), 36)


if __name__ == "__main__":
    unittest.main()
