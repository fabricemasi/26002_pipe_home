import _isolate  # noqa: F401
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
import browser_core as core
from column import Column
import column_loading as loading

APP = QApplication.instance() or QApplication([])


def wait_for(predicate, timeout=5):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        APP.processEvents()
        if predicate():
            return
        time.sleep(.001)
    raise AssertionError("Résultat asynchrone absent")


class ColumnLoadingTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.columns = []
        self.gates = []
        loading._loader = loading.ColumnLoader()

    def tearDown(self):
        for gate in self.gates:
            gate.set()
        for col in self.columns:
            col.cancel_loading()
            col.deleteLater()
        wait_for(lambda: not loading.loader().active)
        self.temp.cleanup()

    def column(self, directory=None, **kw):
        col = Column(directory or self.root, "Contenu", async_load=True, **kw)
        self.columns.append(col)
        return col

    def test_slow_scan_keeps_gui_alive_and_hot_cache_avoids_scan(self):
        (self.root / "a.txt").write_text("abc")
        original = loading.read_column
        gate = threading.Event()
        self.gates.append(gate)
        def slow(*args):
            gate.wait(3)
            return original(*args)
        ticks = []
        timer = QTimer()
        timer.timeout.connect(lambda: ticks.append(time.perf_counter()))
        timer.start(5)
        with patch.object(loading, "read_column", side_effect=slow):
            started = time.perf_counter()
            col = self.column()
            self.assertLess(time.perf_counter() - started, .1)
            wait_for(lambda: len(ticks) >= 10)
            self.assertTrue(col.loading)
            gate.set()
            wait_for(lambda: not col.loading)
            self.assertEqual(col.list.count(), 1)
            scans = loading.loader().scans
            cached = self.column()
            self.assertFalse(cached.loading)
            self.assertEqual(cached.list.count(), 1)
            self.assertEqual(loading.loader().scans, scans)
        timer.stop()

    def test_force_refresh_detects_external_edits_and_keeps_selection(self):
        (self.root / "a.txt").touch()
        col = self.column()
        wait_for(lambda: not col.loading)
        col.list.setCurrentRow(0)
        (self.root / "b.txt").touch()
        col.refresh()
        wait_for(lambda: not col._load_timer.isActive() and not col.loading)
        self.assertEqual(col.list.count(), 2)
        self.assertEqual(col.current_path(), self.root / "a.txt")

    def test_cancelled_column_ignores_late_result(self):
        gate = threading.Event()
        self.gates.append(gate)
        original = loading.read_column
        def slow(*args):
            gate.wait(3)
            return original(*args)
        with patch.object(loading, "read_column", side_effect=slow):
            col = self.column()
            col.cancel_loading()
            gate.set()
            wait_for(lambda: not loading.loader().active)
            self.assertEqual(col.list.count(), 0)
            self.assertIsNone(col._loaded_data)

    def test_error_keeps_last_data_and_is_visible(self):
        (self.root / "a.txt").touch()
        col = self.column()
        wait_for(lambda: not col.loading)
        with patch.object(loading, "read_column", side_effect=PermissionError("serveur indisponible")):
            col.refresh()
            wait_for(lambda: not col._load_timer.isActive() and not col.loading)
            self.assertEqual(col.list.count(), 1)
            self.assertIn("indisponible", col.list.toolTip())

    def test_shared_requests_are_deduplicated(self):
        first, second = self.column(), self.column()
        wait_for(lambda: not first.loading and not second.loading)
        self.assertEqual(loading.loader().scans, 1)

    def test_unchanged_revalidation_keeps_existing_items(self):
        (self.root / "a.txt").touch()
        col = self.column()
        wait_for(lambda: not col.loading)
        item = col.list.item(0)
        col.refresh()
        wait_for(lambda: not col._load_timer.isActive() and not col.loading)
        self.assertIs(col.list.item(0), item)

    def test_removed_selection_is_reported(self):
        path = self.root / "a.txt"
        path.touch()
        col = self.column()
        wait_for(lambda: not col.loading)
        col.list.setCurrentRow(0)
        changes = []
        col.selected.connect(lambda c, p: changes.append(p))
        path.unlink()
        col.refresh()
        wait_for(lambda: not col._load_timer.isActive() and not col.loading)
        self.assertEqual(changes, [None])

    def test_large_folder_insertion_yields_between_batches(self):
        for i in range(1500):
            (self.root / f"{i}.txt").touch()
        col = self.column()
        wait_for(lambda: col.list.count() > 0)
        self.assertTrue(col.loading)
        self.assertLess(col.list.count(), 1500)
        wait_for(lambda: not col.loading)
        self.assertEqual(col.list.count(), 1500)

    def test_prefetch_only_inspects_the_visible_prefix(self):
        import lightroom_bridge
        visited = []
        def paths():
            for i in range(5000):
                visited.append(i)
                yield self.root / f"{i}.txt"
        lightroom_bridge.request_previews(paths(), limit=36)
        self.assertEqual(len(visited), 36)

    def test_layout_shortcuts_and_worker_are_read_only(self):
        target = self.root / "target"
        target.mkdir()
        (self.root / ".pipeline_shortcuts.json").write_text(json.dumps([
            {"target": str(target), "name": "Alias"}]))
        layout = self.root / ".pipeline_layout.json"
        layout.write_text(json.dumps({"pinned": True, "pinned_column_width": 310}))
        before = layout.read_bytes()
        col = self.column()
        wait_for(lambda: not col.loading)
        self.assertTrue(col._pin_active)
        self.assertEqual(col.width(), 310)
        self.assertIn("Alias", [col.list.item(i).text() for i in range(col.list.count())])
        self.assertEqual(layout.read_bytes(), before)

    def test_file_shortcut_is_loaded_like_a_folder_shortcut(self):
        target = self.root.parent / "shortcut_target.mov"
        target.write_bytes(b"video")
        core.add_shortcut(self.root, target)
        col = self.column()
        wait_for(lambda: not col.loading)
        rows = {Path(col.list.item(i).data(core.ROLE_PATH)): col.list.item(i)
                for i in range(col.list.count())}
        item = rows[target]
        self.assertTrue(item.data(core.ROLE_IS_SHORTCUT))
        self.assertFalse(item.data(core.ROLE_ISDIR))
        self.assertEqual(item.data(core.ROLE_META), "5 B")

    def test_snapshot_cache_is_bounded(self):
        service = loading.loader()
        service.MAX_FOLDERS = 2
        for i in range(5):
            folder = self.root / str(i)
            folder.mkdir()
            col = self.column(folder)
            wait_for(lambda: not col.loading)
        self.assertLessEqual(len(service.cache), 2)
        self.assertLessEqual(service.cost, service.MAX_ENTRIES)

    def test_concurrency_is_bounded_and_cancelled_queue_is_removed(self):
        gate = threading.Event()
        self.gates.append(gate)
        original = loading.read_column
        def slow(*args):
            gate.wait(3)
            return original(*args)
        with patch.object(loading, "read_column", side_effect=slow):
            columns = []
            for i in range(10):
                folder = self.root / str(i)
                folder.mkdir()
                columns.append(self.column(folder))
            self.assertEqual(len(loading.loader().active), 2)
            for col in columns[:-1]:
                col.cancel_loading()
            self.assertEqual(len(loading.loader().pending), 1)
            gate.set()
            wait_for(lambda: not columns[-1].loading and not loading.loader().active)
            self.assertEqual(loading.loader().scans, 3)

    def test_force_refresh_during_scan_discards_the_first_snapshot(self):
        (self.root / "a.txt").touch()
        captured, gate = threading.Event(), threading.Event()
        self.gates.append(gate)
        original = loading.read_column
        attempts = []
        def delayed(*args):
            data = original(*args)
            attempts.append(data)
            if len(attempts) == 1:
                captured.set()
                gate.wait(3)
            return data
        with patch.object(loading, "read_column", side_effect=delayed):
            col = self.column()
            ready = []
            col.loaded.connect(lambda: ready.append(col.list.count()))
            wait_for(captured.is_set)
            (self.root / "b.txt").touch()
            col.refresh()
            wait_for(lambda: bool(loading.loader().pending))
            gate.set()
            wait_for(lambda: not col.loading)
            self.assertEqual(ready, [2])

    def test_remote_core_helpers_never_scan_on_gui(self):
        remote = Path(r"\\server\share\offline")
        with patch.object(core, "_remote_gui", return_value=True), \
             patch.object(core, "_request_directory") as request, \
             patch.object(core.os, "scandir", side_effect=AssertionError("scan GUI")), \
             patch.object(core.os, "stat", side_effect=AssertionError("stat GUI")):
            self.assertIsNone(core.config_state(remote / ".pipeline_layout.json"))
            self.assertEqual(core._named_subdir(remote, "softs"), remote)
            self.assertFalse(core.status_folder_state(remote, "in")[0])
            self.assertFalse(core.entry_is_dir(remote))
            self.assertTrue(request.called)

    def test_remote_lightroom_association_uses_only_cached_config(self):
        import lightroom_bridge
        lightroom_bridge._managed_directory.cache_clear()
        remote = Path(r"\\server\share\photos\test.jpg")
        with patch.object(core, "_remote_gui", return_value=True), \
             patch.object(core, "_request_directory"), \
             patch.object(Path, "is_file", side_effect=AssertionError("stat GUI")), \
             patch.object(Path, "resolve", side_effect=AssertionError("resolve GUI")):
            self.assertFalse(lightroom_bridge.is_managed(remote))
        lightroom_bridge._managed_directory.cache_clear()


if __name__ == "__main__":
    unittest.main()
