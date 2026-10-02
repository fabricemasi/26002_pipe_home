"""Integration Blender/Qt : python -m unittest discover -s tests -p test_turntable.py."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import json
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QWidget, QLineEdit
from PySide6.QtGui import QImage

APP = QApplication.instance() or QApplication([])
import detail_panel as dp
import time
import previews as pv


class TurntableIntegrationTest(unittest.TestCase):
    def test_legacy_alembic_is_not_retried_as_transient_failure(self):
        with tempfile.TemporaryDirectory(prefix="turntable_legacy_") as work:
            source = Path(work) / "old.abc"
            source.write_bytes(b"\x89HDF\r\n\x1a\n")
            self.assertTrue(pv._is_legacy_alembic(source))
            identity = (str(source), source.stat().st_mtime)
            browser = QWidget()
            browser.root_field = QLineEdit(work)
            scheduler = pv._IdlePreviewScheduler(browser)
            scheduler.timer.stop()
            scheduler.active_key = str(source)
            scheduler.active_identity = identity
            scheduler._on_preview_progress(str(source), 100, "Alembic HDF5 obsolète : réexport en Ogawa requis")
            scheduler._on_preview_ready(str(source), identity[1], None)
            self.assertIn(identity, scheduler.failed)
            self.assertNotIn(identity, scheduler.done)
            self.assertFalse(scheduler.queue)
            browser.deleteLater()

    def test_publication_retries_transient_windows_lock(self):
        with tempfile.TemporaryDirectory(prefix="turntable_publish_") as work:
            source = Path(work) / "frames"
            source.mkdir()
            (source / "frame_000.png").write_bytes(b"saved frame")
            destination = Path(work) / "published"
            original = Path.rename
            attempts = []
            def rename(path, target):
                attempts.append(target)
                if len(attempts) <= 2:
                    raise PermissionError("Windows file lock")
                return original(path, target)
            with patch.object(Path, "rename", autospec=True, side_effect=rename), \
                    patch.object(time, "sleep") as sleep:
                pv._rename_render_directory(source, destination)
            self.assertEqual(len(attempts), 3)
            self.assertEqual(sleep.call_count, 2)
            self.assertEqual((destination / "frame_000.png").read_bytes(), b"saved frame")

    def test_failed_turntable_gets_one_deferred_retry_not_marked_done(self):
        with tempfile.TemporaryDirectory(prefix="turntable_retry_") as work:
            source = Path(work) / "model.blend"
            source.touch()
            mtime = source.stat().st_mtime
            identity = (str(source), mtime)
            browser = QWidget()
            browser.root_field = QLineEdit(work)
            browser.detail = SimpleNamespace(prepare_auto_preview_log=lambda path: None)
            manager = pv._PreviewDecodeManager()
            requests = []
            def request(path, mtime, **kwargs):
                requests.append(kwargs["media_type"])
                manager.active[str(path)] = SimpleNamespace()
            with patch.object(pv, "FILE_IMAGE_DISK_CACHE_DIR", Path(work) / "cache"), \
                    patch.object(pv, "_PREVIEW_DECODE_MANAGER", manager), \
                    patch.object(manager, "request", request), \
                    patch.object(pv, "_is_preview_protected", return_value=False):
                cache = pv._file_image_cache_path(source, mtime, profiles_snapshot=pv._AUTOMATIC_RENDER_PROFILES)
                cache.parent.mkdir(parents=True)
                image = QImage(4, 4, QImage.Format_ARGB32)
                image.fill(0xff777777)
                image.save(str(cache), "PNG")
                scheduler = pv._IdlePreviewScheduler(browser)
                scheduler.timer.stop()
                scheduler.is_idle = True
                scheduler._user_is_idle = lambda: True
                scheduler.queue.append((source, mtime))
                scheduler._start_next()
                manager.active.clear()
                scheduler._on_preview_ready(str(source), mtime, QImage())
                self.assertNotIn(identity, scheduler.done)
                self.assertEqual(requests, ["turntable"])
                self.assertEqual(scheduler.queue, [(source, mtime)])
                scheduler.retry_after[identity] = 0.0
                scheduler._start_next()
                manager.active.clear()
                scheduler._on_preview_ready(str(source), mtime, None)
                self.assertNotIn(identity, scheduler.done)
                self.assertIn(identity, scheduler.failed)
                self.assertEqual(requests, ["turntable", "turntable"])
                self.assertFalse(scheduler.queue)
            browser.deleteLater()

    def test_cancellation_preserves_cache_and_settings_make_it_stale(self):
        with tempfile.TemporaryDirectory(prefix="turntable_cancel_test_") as work:
            root = Path(work)
            source = root / "model.blend"
            source.touch()
            mtime = source.stat().st_mtime
            profiles = {"LOW POLY": {"subdivisions": 0}}
            with patch.object(pv, "FILE_IMAGE_DISK_CACHE_DIR", root / "cache"):
                directory = pv._turntable_cache_path(source, mtime, profiles)
                directory.mkdir(parents=True)
                image = QImage(4, 4, QImage.Format_ARGB32)
                image.fill(0xff777777)
                for index in range(72):
                    image.save(str(directory / f"frame_{index:03d}.png"), "PNG")
                (directory / "complete.json").write_text(json.dumps({"frames": 72}))
                pv._turntable_metadata_path(source).write_text(json.dumps({"cache": str(directory)}))
                canceled = threading.Event()
                canceled.set()
                task = pv._PreviewDecodeTask(source, mtime, cancel_event=canceled,
                                           media_type="turntable", profiles_snapshot=profiles)
                with patch.object(task, "_decode", side_effect=AssertionError("Ne pas lancer Blender")):
                    self.assertIsNone(task._decode_turntable())
                self.assertEqual(len(pv._turntable_frames(source, mtime, profiles)), 72)
                changed_profiles = {"LOW POLY": {"subdivisions": 1}}
                self.assertFalse(pv._turntable_frames(source, mtime, changed_profiles))
                self.assertEqual(len(pv._turntable_frames(source, mtime, changed_profiles, allow_stale=True)), 72)

    def test_automatic_image_then_turntable_and_protection(self):
        with tempfile.TemporaryDirectory(prefix="turntable_queue_test_") as work:
            root = Path(work)
            source = root / "model.blend"
            source.touch()
            mtime = source.stat().st_mtime
            browser = QWidget()
            browser.root_field = QLineEdit(str(root))
            browser.detail = SimpleNamespace(prepare_auto_preview_log=lambda path: None)
            manager = pv._PreviewDecodeManager()
            requests = []
            def request(path, mtime, **kwargs):
                requests.append(kwargs["media_type"])
                manager.active[str(path)] = SimpleNamespace()
            with patch.object(pv, "FILE_IMAGE_DISK_CACHE_DIR", root / "cache"), \
                 patch.object(pv, "_PREVIEW_DECODE_MANAGER", manager), \
                 patch.object(manager, "request", request), \
                 patch.object(pv, "_is_preview_protected", lambda path: False):
                scheduler = pv._IdlePreviewScheduler(browser)
                scheduler.timer.stop()
                scheduler.is_idle = True
                scheduler._user_is_idle = lambda: True
                scheduler.queue.append((source, mtime))
                scheduler._start_next()
                self.assertEqual(requests, ["image"])
                cache = pv._file_image_cache_path(source, mtime, profiles_snapshot=pv._AUTOMATIC_RENDER_PROFILES)
                cache.parent.mkdir(parents=True, exist_ok=True)
                image = QImage(8, 8, QImage.Format_ARGB32)
                image.fill(0xff777777)
                image.save(str(cache), "PNG")
                manager.active.clear()
                scheduler._on_preview_ready(str(source), mtime, image)
                self.assertEqual(requests, ["image", "turntable"])
                manager.active.clear()
                scheduler._on_preview_ready(str(source), mtime, image)
                self.assertIn((str(source), mtime), scheduler.done)
                scheduler.done.clear()
                scheduler.queue.append((source, mtime))
                with patch.object(pv, "_is_preview_protected", lambda path: True):
                    scheduler._start_next()
                self.assertEqual(requests, ["image", "turntable"])
            browser.deleteLater()

    def test_complete_sequence_cache_and_inspector(self):
        blender = pv._blender_executable()
        if not blender:
            self.skipTest("Blender non installe")
        with tempfile.TemporaryDirectory(prefix="turntable_test_") as work:
            root = Path(work)
            source = root / "asymmetric.blend"
            expression = ("import bpy; bpy.context.object.scale=(2.0,0.6,0.8); "
                          "bpy.ops.wm.save_as_mainfile(filepath=" + repr(str(source)) + ")")
            subprocess.run([blender, "--background", "--factory-startup", "--python-expr", expression],
                           check=True, capture_output=True, timeout=60)
            mtime = source.stat().st_mtime
            profile = pv._render_profile("low")
            profile.update(resolution=(96, 96), lighting_hdri_enabled=False,
                           lighting_hdri="", lighting="", subdivisions=0)
            profiles = {"LOW POLY": profile}
            with patch.object(pv, "FILE_IMAGE_DISK_CACHE_DIR", root / "cache"), \
                 patch.object(pv, "_RENDER_PROFILES", profiles), \
                 patch.object(pv, "_reload_render_profiles", lambda: None):
                task = pv._PreviewDecodeTask(source, mtime, force_render=True,
                                           profile_override=profile, profiles_snapshot=profiles,
                                           media_type="turntable")
                results = []
                task.signals.finished.connect(lambda *args: results.append(args[-1]))
                task.signals.progress.connect(lambda path, percent, message: print(percent, message, flush=True))
                task.run()
                self.assertEqual(len(results), 1)
                self.assertIsNotNone(results[0])
                frames = pv._turntable_frames(source, mtime, profiles)
                self.assertEqual(len(frames), 72)
                self.assertTrue(all(QImage(str(frame)).size() == results[0].size() for frame in frames))
                self.assertNotEqual(QImage(str(frames[0])), QImage(str(frames[18])))
                self.assertEqual(source.stat().st_mtime, mtime)
                self.assertFalse(pv._file_image_cache_path(source, mtime, profiles_snapshot=profiles).exists())
                self.assertEqual(json.loads((frames[0].parent / "complete.json").read_text())["frames"], 72)

                manager = pv._PreviewDecodeManager()
                image_ready, turntable_ready = [], []
                manager.ready.connect(lambda *args: image_ready.append(args))
                manager.turntable_ready.connect(lambda *args: turntable_ready.append(args))
                manager._on_finished(task, str(source), mtime, results[0])
                self.assertEqual(len(turntable_ready), 1)
                self.assertFalse(image_ready)

                panel = dp.DetailPanel()
                panel.show_path(source)
                panel.preview_media_combo.setCurrentIndex(1)
                self.assertEqual(len(panel._turntable_frame_paths), 72)
                self.assertTrue(panel._turntable_timer.isActive())
                panel._advance_turntable()
                self.assertEqual(panel._turntable_frame_index, 1)
                panel._toggle_turntable_playback()
                self.assertFalse(panel._turntable_timer.isActive())
                panel.preview_media_combo.setCurrentIndex(0)
                self.assertFalse(panel._turntable_timer.isActive())
                panel.clear()
                panel.deleteLater()

                # Une sequence incomplete n'est jamais presentee comme valide.
                frames[-1].unlink()
                self.assertFalse(pv._turntable_frames(source, mtime, profiles))


if __name__ == "__main__":
    unittest.main()
