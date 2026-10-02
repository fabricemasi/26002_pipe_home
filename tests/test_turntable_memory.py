"""Validation opt-in sur un vrai modele lourd, avec limite de memoire."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import ctypes
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from PySide6.QtWidgets import QApplication

APP = QApplication.instance() or QApplication([])
import previews as pv


class MemoryCounters(ctypes.Structure):
    _fields_ = [("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong)] + [
        (name, ctypes.c_size_t) for name in (
            "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage",
            "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage", "PrivateUsage")]


class TurntableMemoryTest(unittest.TestCase):
    @unittest.skipUnless(os.environ.get("PIPE_TURNTABLE_TEST_SOURCE"), "Test lourd opt-in")
    def test_heavy_sequence(self):
        source = Path(os.environ["PIPE_TURNTABLE_TEST_SOURCE"])
        mtime = source.stat().st_mtime
        profile = pv._render_profile("low")
        profile["resolution"] = (96, 96)
        # Le nombre de faces et les buffers geometriques restent identiques.
        # Inutile de refaire 512 passes anti-aliasing par image pour ce test.
        profile["samples"] = 16
        canceled = threading.Event()
        memory_samples = []
        memory_limit = float(os.environ.get("PIPE_TURNTABLE_TEST_MEMORY_GIB", "16")) * 1024**3
        duration_limit = float(os.environ.get("PIPE_TURNTABLE_TEST_MAX_SECONDS", "7200"))
        monitors = []
        original_popen = subprocess.Popen
        started = time.monotonic()
        memory_info = ctypes.windll.psapi.GetProcessMemoryInfo
        memory_info.argtypes = [ctypes.c_void_p, ctypes.POINTER(MemoryCounters), ctypes.c_ulong]
        memory_info.restype = ctypes.c_int

        def popen(*args, **kwargs):
            process = original_popen(*args, **kwargs)
            def monitor():
                last_report = 0.0
                while process.poll() is None:
                    counters = MemoryCounters()
                    counters.cb = ctypes.sizeof(counters)
                    if memory_info(int(process._handle), ctypes.byref(counters), counters.cb):
                        memory_samples.append(counters.PrivateUsage)
                        if counters.PrivateUsage > memory_limit:
                            canceled.set()
                    elapsed = time.monotonic() - started
                    if elapsed - last_report >= 30:
                        print("MEMORY", round(elapsed), "s", round(counters.PrivateUsage / 1024**3, 2), "GiB", flush=True)
                        last_report = elapsed
                    if elapsed > duration_limit:
                        canceled.set()
                    time.sleep(0.5)
            thread = threading.Thread(target=monitor, daemon=True)
            thread.start()
            monitors.append(thread)
            return process

        with tempfile.TemporaryDirectory(prefix="turntable_memory_") as work:
            root = Path(work)
            profiles = {"LOW POLY": profile}
            original_log = pv._write_render_log
            with patch.object(pv, "FILE_IMAGE_DISK_CACHE_DIR", root / "cache"), \
                    patch.object(pv, "_write_render_log", lambda directory, *args, **kwargs:
                                 original_log(root, *args, **kwargs)), \
                    patch.object(subprocess, "Popen", popen):
                task = pv._PreviewDecodeTask(source, mtime, force_render=True, cancel_event=canceled,
                    media_type="turntable", profile_override=profile, profiles_snapshot=profiles)
                task.signals.progress.connect(lambda source, percent, msg: print(percent, msg, flush=True))
                task.run()
                for thread in monitors:
                    thread.join(timeout=2)
                print("RESULT", "seconds", round(time.monotonic() - started, 1), "peak_GiB",
                      round(max(memory_samples, default=0) / 1024**3, 2), flush=True)
                self.assertFalse(canceled.is_set(), "Limite de memoire ou de duree atteinte")
                self.assertEqual(len(pv._turntable_frames(source, mtime, profiles)), 72)
                self.assertEqual(source.stat().st_mtime, mtime)


if __name__ == "__main__":
    unittest.main()
