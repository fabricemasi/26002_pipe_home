"""Bouton logiciel a cote de la punaise : dans un set, Blender choisi dans la colonne LOGICIELS = toutes les
colonnes ouvertes sous son dossier ont un bouton qui ouvre Blender dans LEUR dossier (scene vide dont le
chemin est dans ce dossier). Dossier temporaire ; aucun logiciel n'est lance (lanceur remplace)."""
import os as _os, sys as _sys  # jamais les vrais reglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PySide6.QtWidgets import QApplication

APP = QApplication.instance() or QApplication([])
import app_style
import browser_core
import pipeline_browser as pb
import settings_store
import software_launch
from browser_core import ROLE_PATH



def select(column, name):
    for i in range(column.list.count()):
        item = column.list.item(i)
        if Path(item.data(ROLE_PATH)).name == name:
            column.list.setCurrentItem(item)
            APP.processEvents()
            return
    raise AssertionError(f"{name} absent de {column.column_title}")


class FreeScenePathTest(unittest.TestCase):
    def test_existing_scene_is_never_reused(self):
        folder = Path(tempfile.mkdtemp())
        self.assertEqual(software_launch._free_scene_path(folder, "untitled", ".blend").name, "untitled.blend")
        (folder / "untitled.blend").write_bytes(b"")
        self.assertEqual(software_launch._free_scene_path(folder, "untitled", ".blend").name, "untitled_01.blend")

    def test_blender_gets_a_scene_path_inside_the_folder(self):
        folder, config = Path(tempfile.mkdtemp()), Path(tempfile.mkdtemp())
        with mock.patch.object(software_launch, "_blender_executable", return_value="blender.exe"), \
                mock.patch.object(software_launch, "_blender_config_dir", return_value=config), \
                mock.patch.object(software_launch, "_RECENT_ADDED", config / "added.json"), \
                mock.patch.object(software_launch.QProcess, "startDetached", return_value=(True, 1)) as start:
            self.assertTrue(software_launch.launch("BLENDER", folder, "spaceship_01"))
        self.assertIn(f"!spaceship_01\n{folder}\\\n", (config / "bookmarks.txt").read_text(encoding="utf-8"))
        # File > Open : la scene en tete des fichiers recents.
        self.assertEqual((config / "recent-files.txt").read_text(encoding="utf-8").splitlines()[0],
                         str(folder / "untitled.blend"))
        program, args, cwd = start.call_args.args
        self.assertEqual((program, Path(args[0]), Path(cwd)), ("blender.exe", folder / "untitled.blend", folder))
        self.assertFalse((folder / "untitled.blend").exists())
        self.assertFalse(software_launch.launch("MAYA", folder))

    def test_houdini_starts_without_scene_in_the_folder(self):
        # Scene sans titre : $HIP = dossier courant, donc Enregistrer sous / Ouvrir dans le dossier.
        folder = Path(tempfile.mkdtemp())
        with mock.patch.object(software_launch, "_houdini_executable", return_value="houdini.exe"), \
                mock.patch.object(software_launch.QProcess, "startDetached", return_value=(True, 1)) as start:
            self.assertTrue(software_launch.launch("HOUDINI", folder, "sp1"))
        program, args, cwd = start.call_args.args
        self.assertEqual((program, args, Path(cwd)), ("houdini.exe", [], folder))
        self.assertEqual(list(folder.iterdir()), [])

    def test_bookmark_is_added_once_and_the_rest_of_the_file_is_kept(self):
        config = Path(tempfile.mkdtemp())
        (config / "bookmarks.txt").write_bytes(b"[Bookmarks]\r\nD:\\old\\\r\n[Recent]\r\nC:\\recent\\\r\n")
        folder = Path(tempfile.mkdtemp()) / "scenes"
        folder.mkdir()
        self.assertTrue(software_launch.add_blender_bookmark(config, folder))
        self.assertTrue(software_launch.add_blender_bookmark(config, folder))      # deja present : rien
        raw = (config / "bookmarks.txt").read_bytes().decode("utf-8")
        self.assertEqual(raw, f"[Bookmarks]\r\nD:\\old\\\r\n{folder}\\\r\n[Recent]\r\nC:\\recent\\\r\n")

    def test_bookmark_is_named_after_the_set_and_renamed_in_place(self):
        config = Path(tempfile.mkdtemp())
        folder = Path(tempfile.mkdtemp())
        head = f"[Bookmarks]\r\n!autre\r\nD:\\old\\\r\n"
        (config / "bookmarks.txt").write_bytes(f"{head}{folder}\\\r\n[Recent]\r\n".encode("utf-8"))
        self.assertTrue(software_launch.add_blender_bookmark(config, folder, "set_a"))   # sans nom -> nomme
        self.assertEqual((config / "bookmarks.txt").read_bytes().decode("utf-8"),
                         f"{head}!set_a\r\n{folder}\\\r\n[Recent]\r\n")
        self.assertTrue(software_launch.add_blender_bookmark(config, folder, "set_b"))   # renomme
        self.assertTrue(software_launch.add_blender_bookmark(config, folder, "set_b"))   # deja : rien
        self.assertEqual((config / "bookmarks.txt").read_bytes().decode("utf-8"),
                         f"{head}!set_b\r\n{folder}\\\r\n[Recent]\r\n")

    def test_recent_scene_goes_first_and_unsaved_ones_are_cleaned_next_time(self):
        config, base = Path(tempfile.mkdtemp()), Path(tempfile.mkdtemp())
        store = base / "added.json"
        real = base / "real.blend"
        real.write_bytes(b"")
        (config / "recent-files.txt").write_bytes(f"{real}\r\nD:\\autre.blend\r\n".encode("utf-8"))
        first, second = base / "a" / "untitled.blend", base / "b" / "untitled.blend"
        self.assertTrue(software_launch.add_blender_recent(config, first, store))
        self.assertEqual((config / "recent-files.txt").read_bytes().decode("utf-8"),
                         f"{first}\r\n{real}\r\nD:\\autre.blend\r\n")
        # Jamais enregistree : retiree au lancement suivant ; les autres (meme absentes) restent.
        self.assertTrue(software_launch.add_blender_recent(config, second, store))
        self.assertEqual((config / "recent-files.txt").read_bytes().decode("utf-8"),
                         f"{second}\r\n{real}\r\nD:\\autre.blend\r\n")
        # Enregistree entre-temps : elle reste dans les recents.
        second.parent.mkdir()
        second.write_bytes(b"")
        third = base / "c" / "untitled.blend"
        self.assertTrue(software_launch.add_blender_recent(config, third, store))
        self.assertEqual((config / "recent-files.txt").read_bytes().decode("utf-8").splitlines()[:2],
                         [str(third), str(second)])

    def test_bookmark_file_is_created_when_missing(self):
        config = Path(tempfile.mkdtemp()) / "config"
        folder = Path(tempfile.mkdtemp())
        self.assertTrue(software_launch.add_blender_bookmark(config, folder))
        self.assertEqual((config / "bookmarks.txt").read_bytes().decode("utf-8"),
                         f"[Bookmarks]\r\n{folder}\\\r\n[Recent]\r\n")


class SoftwareButtonTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app_style.apply_style(APP)

    def setUp(self):
        # Jamais les reglages reels, et seulement pendant ce test (les autres tests du lancement ecrivent).
        for module in (settings_store, pb, browser_core):
            for name in ("save_settings", "_save_window_geometry", "save_layout_settings", "_update_layout_setting"):
                if hasattr(module, name):
                    patcher = mock.patch.object(module, name, lambda *a, **k: None)
                    patcher.start()
                    self.addCleanup(patcher.stop)

    def test_columns_under_blender_get_the_button(self):
        root = Path(tempfile.mkdtemp())
        for sub in ("3d/projA/sp1/softs/blender/scenes/wip", "3d/projA/sp1/softs/houdini/hip"):
            (root / sub).mkdir(parents=True)
        win = pb.PipelineBrowser(root)
        win._idle_preview_scheduler.timer.stop()
        win.resize(1600, 800)
        win.show()
        APP.processEvents()
        try:
            select(win.columns[0], "3d"); select(win.columns[1], "projA"); select(win.columns[2], "sp1")
            softs = next(c for c in win.group_columns if c._group_kind == "logiciels")
            chain = len(win.columns)
            select(softs, "blender")
            select(win.columns[-1], "scenes")
            select(win.columns[-1], "wip")
            opened = win.columns[chain:]
            self.assertEqual([c.directory.name for c in opened], ["blender", "scenes", "wip"])
            for column in win.columns[:chain]:
                self.assertTrue(column._launch_btn is None or column._launch_btn.isHidden(), column.directory)
            for column in opened:
                self.assertFalse(column._launch_btn.isHidden(), column.directory)
                header = column._header_layout
                self.assertEqual(header.indexOf(column._launch_btn) + 1, header.indexOf(column._pin_btn))
            with mock.patch.object(software_launch, "launch", return_value=True) as launch:
                opened[1]._launch_btn.click()
            launch.assert_called_once_with("BLENDER", opened[1].directory, "sp1")   # favori au nom du set
            # Houdini a aussi son lanceur : son bouton, dans les colonnes sous son dossier.
            select(softs, "houdini")
            select(win.columns[-1], "hip")
            houdini_cols = win.columns[chain:]
            self.assertEqual([c.directory.name for c in houdini_cols], ["houdini", "hip"])
            for column in houdini_cols:
                self.assertFalse(column._launch_btn.isHidden(), column.directory)
            with mock.patch.object(software_launch, "launch", return_value=True) as launch:
                houdini_cols[1]._launch_btn.click()
            launch.assert_called_once_with("HOUDINI", houdini_cols[1].directory, "sp1")
        finally:
            win.close()
            for _ in range(20):
                APP.processEvents()


if __name__ == "__main__":
    unittest.main()
