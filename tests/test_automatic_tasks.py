import _isolate  # noqa: F401
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock
from PySide6.QtWidgets import QApplication, QWidget
from automatic_tasks import AutomaticTasks

APP = QApplication.instance() or QApplication([])


class AutomaticTasksTest(unittest.TestCase):
    def setUp(self):
        self.browser = QWidget()
        self.browser._stop_settings_idle_load = mock.Mock()
        self.tasks = AutomaticTasks(self.browser)
        self.tasks.timer.stop()
        self.addCleanup(self.tasks.stop)
        self.addCleanup(self.browser.deleteLater)

    def test_each_trigger_and_delay(self):
        settings = dict(auto_video_enabled=True, auto_video_when='app', auto_video_delay=10)
        self.assertFalse(self.tasks.eligible('video', settings))
        self.tasks.away_at = time.monotonic() - 11
        self.assertTrue(self.tasks.eligible('video', settings))
        settings['auto_video_when'] = 'computer'
        with mock.patch('settings_window_v2._system_idle_ms', return_value=9000):
            self.assertFalse(self.tasks.eligible('video', settings))
        with mock.patch('settings_window_v2._system_idle_ms', return_value=11000):
            self.assertTrue(self.tasks.eligible('video', settings))
        settings['auto_video_enabled'] = False
        self.assertFalse(self.tasks.eligible('video', settings))

    def test_resume_focus_cancels_both_generators(self):
        import ui_state
        for event in self.tasks.cancel.values():
            event.clear()
        with mock.patch.object(ui_state, 'APPLIED_SETTINGS', {}), \
                mock.patch.object(QApplication, 'applicationState', return_value=__import__('PySide6.QtCore', fromlist=['Qt']).Qt.ApplicationActive):
            self.tasks.tick()
        self.assertTrue(all(e.is_set() for e in self.tasks.cancel.values()))
        self.browser._stop_settings_idle_load.assert_called()

    def test_recursive_scan_follows_shortcuts_and_breaks_cycles(self):
        self.tasks._omit_dirs = {'moodboards'}
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as temporary:
            root = Path(temporary)
            start, target = root/'type', root/'external'
            start.mkdir(); target.mkdir()
            (start/'sub').mkdir()
            (start/'sub'/'a.mkv').touch()
            (target/'b.mp4').touch()
            def shortcuts(folder):
                return [{'target': str(target if folder == start else start)}]
            with mock.patch('browser_core.load_shortcuts', side_effect=shortcuts), \
                    mock.patch.object(self.tasks, 'generate') as generate:
                self.tasks.run('video', [str(start)], {}, threading.Event())
            self.assertEqual({call.args[1].name for call in generate.call_args_list}, {'a.mkv', 'b.mp4'})

    def test_focus_cancellation_terminates_only_decoder_process(self):
        cancel = threading.Event()
        process = mock.Mock()
        process.poll.side_effect = [None, 0]
        def start(*args, **kwargs):
            cancel.set()                         # retour du focus pendant le décodage
            return process
        with mock.patch('automatic_tasks.subprocess.Popen', side_effect=start):
            self.tasks.generate('video', Path('film.mkv'), {}, cancel)
        process.terminate.assert_called_once()
        process.wait.assert_called_once_with(timeout=2)

    def test_existing_video_preview_is_not_regenerated(self):
        from PySide6.QtGui import QImage
        import previews
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as temporary:
            path = Path(temporary)/'film.mkv'; path.touch()
            cached = Path(temporary)/'cached.png'
            image = QImage(8, 8, QImage.Format_RGB888); image.fill(0); image.save(str(cached))
            with mock.patch.object(previews, '_file_image_cache_path', return_value=cached), \
                    mock.patch.object(previews, '_decode_video_frame') as decode:
                self.tasks.video(path, threading.Event())
            decode.assert_not_called()


if __name__ == '__main__':
    unittest.main()
