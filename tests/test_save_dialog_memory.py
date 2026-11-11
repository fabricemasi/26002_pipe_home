import _isolate  # noqa: F401
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QFileDialog  # noqa: E402

import save_dialog_memory as memory  # noqa: E402

APP = QApplication.instance() or QApplication([])


class SaveDialogMemoryTest(unittest.TestCase):
    """Toute boite « Enregistrer / Exporter » s'ouvre dans le dernier dossier d'enregistrement (2026-11-08)."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.addCleanup(memory._STATE.update, dict(memory._STATE))

    def test_start_path_keeps_the_suggested_name(self):
        last = str(self.dir)
        self.assertEqual(memory.start_path("C:/ailleurs/plan_cad.png", last), str(self.dir / "plan_cad.png"))
        self.assertEqual(memory.start_path("palette.json", last), str(self.dir / "palette.json"))
        self.assertEqual(memory.start_path("", last), last)
        self.assertEqual(memory.start_path(str(Path.home()), last), last)          # dossier seul propose
        self.assertEqual(memory.start_path("a.png", str(self.dir / "absent")), "a.png")
        self.assertEqual(memory.start_path("a.png", ""), "a.png")

    def test_every_save_dialog_reopens_where_the_last_file_went(self):
        memory.install({})
        self.assertIsNot(QFileDialog.getSaveFileName, memory._ORIGINALS["getSaveFileName"])
        seen = []
        first = self.dir / "exports" / "a.svg"
        first.parent.mkdir()
        answers = iter([(str(first), ""), (str(self.dir / "exports" / "b.png"), ""), ("", "")])
        fake = lambda *a, **k: (seen.append(a[2] if len(a) > 2 else k.get("dir")), next(answers))[1]
        saved = []
        with mock.patch.dict(memory._ORIGINALS, {"getSaveFileName": fake}), \
                mock.patch("settings_store.save_live_state", lambda k, v: saved.append((k, v))):
            memory._STATE["dir"] = ""
            QFileDialog.getSaveFileName(None, "Exporter", "C:/projet/a.svg", "SVG (*.svg)")
            QFileDialog.getSaveFileName(None, "Exporter", dir="b.png")
            QFileDialog.getSaveFileName(None, "Exporter")                           # annule : rien de retenu
        self.assertEqual(seen, ["C:/projet/a.svg", str(first.parent / "b.png"), str(first.parent)])
        self.assertEqual(saved, [("last_save_dir", str(first.parent))])
        self.assertEqual(memory.remembered(), str(first.parent))

    def test_open_dialogs_remember_their_own_folder(self):
        """Ouvrir / charger / importer : dernier dossier CHARGE, a part de celui des enregistrements."""
        memory.install({})
        a, b = self.dir / "a", self.dir / "b"
        a.mkdir()
        b.mkdir()
        seen, saved = [], []
        answers = iter([(str(a / "x.dxf"), ""), ([str(b / "y.png"), str(b / "z.png")], ""), (str(a), )])
        fake = lambda *args, **k: (seen.append(args[2] if len(args) > 2 else k.get("dir")), next(answers))[1]
        folder_fake = lambda *args, **k: (seen.append(args[2] if len(args) > 2 else k.get("dir")), str(a))[1]
        with mock.patch.dict(memory._ORIGINALS, {"getOpenFileName": fake, "getOpenFileNames": fake,
                                                 "getExistingDirectory": folder_fake}), \
                mock.patch("settings_store.save_live_state", lambda k, v: saved.append((k, v))):
            memory._STATE.update({"dir": str(self.dir), "open": ""})
            QFileDialog.getOpenFileName(None, "Ouvrir", "C:/projet", "DXF (*.dxf)")
            QFileDialog.getOpenFileNames(None, "Importer", "", "Images (*.png)")
            QFileDialog.getExistingDirectory(None, "Dossier", "C:/projet")
        self.assertEqual(seen, ["C:/projet", str(a), str(b)])
        self.assertEqual(saved, [("last_open_dir", str(a)), ("last_open_dir", str(b)), ("last_open_dir", str(a))])
        self.assertEqual(memory.remembered("dir"), str(self.dir))                 # enregistrements : a part


if __name__ == "__main__":
    unittest.main()
