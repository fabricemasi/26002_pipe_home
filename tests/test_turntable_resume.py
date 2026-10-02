"""Images durables, reprise des trous et isolation des processus Blender."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage

APP = QApplication.instance() or QApplication([])
import previews as pv


class TurntableResumeTest(unittest.TestCase):
    def test_pause_at_37_resumes_missing_frames_after_new_task(self):
        with tempfile.TemporaryDirectory(prefix="turntable_resume_") as work:
            root = Path(work)
            source = root / "model.blend"
            source.touch()
            mtime = source.stat().st_mtime
            profile = pv._render_profile("low")
            profiles = {"LOW POLY": profile}
            canceled = threading.Event()
            rendered = []
            prepared_paths = []
            image = QImage(4, 4, QImage.Format_ARGB32)
            image.fill(0xff777777)
            def prepare(task):
                scene = Path(task.profile_override["_turntable_prepared_scene"])
                prepared_paths.append(scene)
                scene.write_bytes(b"test snapshot")
                return image
            def frame(scene, target, index, cancel, report):
                if cancel is not None and cancel.is_set():
                    return False
                rendered.append(index)
                image.save(str(target), "PNG")
                if index == 36 and cancel is canceled:
                    canceled.set()
                return True
            with patch.object(pv, "FILE_IMAGE_DISK_CACHE_DIR", root / "cache"), \
                    patch.object(pv._PreviewDecodeTask, "_decode", prepare), \
                    patch.object(pv, "_render_turntable_frame", frame):
                first = pv._PreviewDecodeTask(source, mtime, media_type="turntable", cancel_event=canceled,
                    profile_override=profile, profiles_snapshot=profiles)
                self.assertIsNone(first._decode_turntable())
                self.assertEqual(rendered, list(range(37)))
                partial = prepared_paths[0].parent
                self.assertEqual(len(list(partial.glob("frame_???.png"))), 37)
                self.assertFalse(pv._turntable_frames(source, mtime, profiles))
                # Une image endommagee doit etre refaite, pas les autres.
                (partial / "frame_010.png").write_bytes(b"broken png")
                rendered.clear()
                resumed = pv._PreviewDecodeTask(source, mtime, media_type="turntable",
                    profile_override=profile, profiles_snapshot=profiles)
                self.assertIsNotNone(resumed._decode_turntable())
                self.assertEqual(rendered, [10] + list(range(37, 72)))
                self.assertEqual(len(prepared_paths), 1, "Ne pas refaire la preparation")
                frames = pv._turntable_frames(source, mtime, profiles)
                self.assertEqual(len(frames), 72)
                self.assertFalse((frames[0].parent / "prepared.blend").exists())
                self.assertFalse(partial.exists())

    def test_profile_or_source_change_never_reuses_old_images(self):
        with tempfile.TemporaryDirectory(prefix="turntable_resume_keys_") as work:
            root = Path(work)
            source = root / "model.blend"
            source.touch()
            profile = pv._render_profile("low")
            profiles = {"LOW POLY": profile}
            with patch.object(pv, "FILE_IMAGE_DISK_CACHE_DIR", root / "cache"):
                old = pv._turntable_cache_path(source, 1.0, profiles)
                same = pv._turntable_work_path(old, profile, "low")
                self.assertEqual(same, pv._turntable_work_path(old, profile, "low"))
                changed = dict(profile, wireframe_thickness=2.0)
                self.assertNotEqual(same, pv._turntable_work_path(old, changed, "low"))
                newer = pv._turntable_cache_path(source, 2.0, profiles)
                self.assertNotEqual(same, pv._turntable_work_path(newer, profile, "low"))

    def test_real_frames_use_distinct_finished_blender_processes(self):
        blender = pv._blender_executable()
        if not blender:
            self.skipTest("Blender absent")
        with tempfile.TemporaryDirectory(prefix="turntable_processes_") as work:
            root = Path(work)
            source = root / "model.blend"
            subprocess.run([blender, "-b", "--factory-startup", "--python-expr",
                f"import bpy; bpy.context.object.scale=(2,.6,.8); bpy.ops.wm.save_as_mainfile(filepath={str(source)!r})"],
                check=True, capture_output=True, timeout=60)
            profile = pv._render_profile("low")
            profile.update(resolution=(48, 48), samples=1, lighting_hdri_enabled=False,
                           lighting_hdri="", lighting="", subdivisions=0)
            profiles = {"LOW POLY": profile}
            processes = []
            original_popen = subprocess.Popen
            original_frame = pv._render_turntable_frame
            def popen(*args, **kwargs):
                process = original_popen(*args, **kwargs)
                processes.append(process)
                return process
            def frame(scene, target, index, cancel, report):
                if index in (0, 18):
                    self.assertTrue(all(process.poll() is not None for process in processes))
                    return original_frame(scene, target, index, cancel, report)
                image = QImage(48, 48, QImage.Format_ARGB32)
                image.fill(0xff777777)
                return image.save(str(target), "PNG")
            with patch.object(pv, "FILE_IMAGE_DISK_CACHE_DIR", root / "cache"), \
                    patch.object(subprocess, "Popen", popen), \
                    patch.object(pv, "_render_turntable_frame", frame):
                task = pv._PreviewDecodeTask(source, source.stat().st_mtime, media_type="turntable",
                    profile_override=profile, profiles_snapshot=profiles)
                result = task._decode_turntable()
                self.assertIsNotNone(result)
                frames = pv._turntable_frames(source, source.stat().st_mtime, profiles)
                self.assertEqual(len(frames), 72)
                self.assertNotEqual(QImage(str(frames[0])), QImage(str(frames[18])))
                self.assertEqual(len(processes), 3, "Une preparation puis deux renders reels")
                self.assertEqual(len({process.pid for process in processes}), 3)
                self.assertTrue(all(process.poll() is not None for process in processes))


if __name__ == "__main__":
    unittest.main()
