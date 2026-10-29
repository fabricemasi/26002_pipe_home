"""Temps réel de fm_theme (fm_theme/live.py) : canal local éditeur -> applis (fusion, une émission par image)
et surveillance du fichier d'un preset (remplacement atomique compris). Canal et fichiers de test seulement."""
import _isolate  # noqa: F401
import json
import os
import tempfile
import time
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QCoreApplication  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from fm_theme import live  # noqa: E402

APP = QApplication.instance() or QApplication([])


def wait_until(predicate, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        QCoreApplication.processEvents()
        if predicate():
            return True
        time.sleep(0.005)
    return predicate()


class ChannelTest(unittest.TestCase):
    def setUp(self):
        self.name = f"fm_theme_test_{os.getpid()}_{time.monotonic_ns()}"

    def test_client_receives_merged_values_once_per_frame(self):
        server = live.LiveServer(name=self.name)
        self.assertTrue(server.is_listening())
        client = live.LiveClient(name=self.name)
        got = []
        client.received.connect(lambda preset, values: got.append((preset, values)))
        self.assertTrue(wait_until(lambda: client.is_connected() and server._clients))
        for radius in (1, 2, 3):                        # trois pas de curseur dans la même image
            server.broadcast("fab", {"button_radius": radius})
        server.broadcast("fab", {"window_radius": 9})
        self.assertTrue(wait_until(lambda: got))
        wait_until(lambda: False, 0.1)
        self.assertEqual(got, [("fab", {"button_radius": 3, "window_radius": 9})])

    def test_client_connects_when_the_editor_starts_later(self):
        client = live.LiveClient(name=self.name)
        client._retry.setInterval(50)
        wait_until(lambda: False, 0.1)
        self.assertFalse(client.is_connected())
        server = live.LiveServer(name=self.name)
        self.assertTrue(wait_until(lambda: client.is_connected(), 2.0))
        del server


class WatcherTest(unittest.TestCase):
    def test_atomic_replace_is_seen_once(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "fab.json"
            path.write_text("{}", encoding="utf-8")
            watcher = live.PresetWatcher()
            fired = []
            watcher.changed.connect(lambda: fired.append(1))
            watcher.watch(path)
            time.sleep(0.02)
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps({"a": 1}), encoding="utf-8")
            os.replace(tmp, path)
            self.assertTrue(wait_until(lambda: fired))
            wait_until(lambda: False, 0.3)
            self.assertEqual(fired, [1])
            (Path(folder) / "autre.json").write_text("{}", encoding="utf-8")   # autre fichier : ignoré
            wait_until(lambda: False, 0.3)
            self.assertEqual(fired, [1])


if __name__ == "__main__":
    unittest.main()
