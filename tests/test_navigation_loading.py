import _isolate  # noqa: F401
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import copy
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication
import column_loading
import pipeline_browser as pb
import settings_store
from browser_core import ROLE_PATH
from test_column_loading import wait_for

APP = QApplication.instance() or QApplication([])


class NavigationLoadingTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.folder = self.root / "type" / "project"
        self.folder.mkdir(parents=True)
        # Le contenu après le projet se parcourt sans convention de set.
        (self.folder / ".pipeline_columns.json").write_text(json.dumps({
            "set_enabled": False, "focus_enabled": False, "in_over_out_enabled": False,
            "columns": [], "work_dir": {"type": "standard", "show_dirs": True, "show_files": True}}))
        self.deep = self.folder
        for i in range(12):
            (self.deep / "other").mkdir()
            self.deep /= f"level_{i}"
            self.deep.mkdir()
        settings = copy.deepcopy(settings_store.DEFAULT_SETTINGS)
        settings["root_path"] = str(self.root)
        pb.apply_all_settings(settings)
        self.win = pb.PipelineBrowser(self.root)
        self.win._idle_preview_scheduler.timer.stop()
        self.win.resize(1400, 800)
        self.win.show()
        wait_for(lambda: not self.win.columns[0].loading)

    def tearDown(self):
        self.win.close()
        for c in [*self.win.columns, *self.win.group_columns]:
            c.cancel_loading()
        self.win.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        wait_for(lambda: not column_loading.loader().active)
        self.temp.cleanup()

    def select(self, col, name):
        for i in range(col.list.count()):
            item = col.list.item(i)
            if Path(item.data(ROLE_PATH)).name == name:
                col.list.setCurrentItem(item)
                return
        self.fail(f"{name} absent")

    def test_deep_jump_rapid_navigation_shortcut_and_f5(self):
        started = time.perf_counter()
        self.win._navigate_to(self.deep)
        self.assertLess(time.perf_counter() - started, .15)
        wait_for(lambda: any(c.directory == self.deep and not c.loading for c in self.win.columns))
        self.assertEqual(self.win.columns[-1].directory, self.deep)
        self.assertEqual(len(self.win.columns), 14)
        col = next(c for c in [*self.win.columns, *self.win.group_columns] if c.directory == self.folder)
        self.select(col, "other")
        self.select(col, "level_0")
        wait_for(lambda: self.win.columns[-1].directory == self.folder / "level_0"
                 and not self.win.columns[-1].loading)
        (self.folder / ".pipeline_shortcuts.json").write_text(json.dumps([{"target": str(self.deep)}]))
        col.refresh()
        wait_for(lambda: not col._load_timer.isActive() and not col.loading)
        self.select(col, self.deep.name)
        wait_for(lambda: self.win.columns[-1].directory == self.deep and not self.win.columns[-1].loading)
        (self.root / "new_type").mkdir()
        self.win.reload()
        wait_for(lambda: not self.win.columns[0].loading)
        self.assertIn("new_type", [self.win.columns[0].list.item(i).text()
                                    for i in range(self.win.columns[0].list.count())])

    def test_slow_remote_selection_keeps_only_the_latest_choice(self):
        (self.root / "other_type").mkdir()
        col = self.win.columns[0]
        col.refresh()
        wait_for(lambda: not col._load_timer.isActive() and not col.loading)
        gate = threading.Event()
        original = column_loading.read_column
        def slow(*args):
            gate.wait(3)
            return original(*args)
        with patch.object(pb._previews, "is_remote_path", side_effect=lambda p: str(p).startswith(str(self.root))), \
             patch.object(column_loading, "read_column", side_effect=slow):
            try:
                self.select(col, "type")
                self.select(col, "other_type")
                self.assertEqual(col.current_path(), self.root / "other_type")
                gate.set()
                wait_for(lambda: len(self.win.columns) == 2 and not self.win.columns[-1].loading)
                self.assertEqual(self.win.columns[-1].directory, self.root / "other_type")
            finally:
                gate.set()


if __name__ == "__main__":
    unittest.main()
