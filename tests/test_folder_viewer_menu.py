"""Menu contextuel d'un dossier : « Ouvrir la visionneuse à cet endroit » (directement la PLANCHE, aucune image
en focus) et case « Récursif » (photos des sous-dossiers aussi). Dossier temporaire ; réglages jamais écrits."""
import os as _os, sys as _sys  # jamais les vrais reglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

APP = QApplication.instance() or QApplication([])

import app_style
import browser_core
import column as column_module
import pipeline_browser as pb
import settings_store
import ui_state
from browser_core import ROLE_PATH


def select(column, name):
    # Le contenu arrive maintenant par signal : une passe Qt ne garantit pas
    # qu'un worker a fini, même sur un petit dossier local.
    deadline = time.monotonic() + 5
    while column.loading or column._load_timer.isActive():
        APP.processEvents()
        if time.monotonic() >= deadline:
            raise AssertionError(f"Lecture inachevée : {column.column_title}")
        time.sleep(.001)
    for i in range(column.list.count()):
        item = column.list.item(i)
        if Path(item.data(ROLE_PATH)).name == name:
            column.list.setCurrentItem(item)
            APP.processEvents()
            return
    raise AssertionError(f"{name} absent de {column.column_title}")


def settle(seconds=0.6):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        APP.processEvents()
        time.sleep(0.01)


class FolderViewerMenuTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app_style.apply_style(APP)

    def setUp(self):
        for module in (settings_store, pb, browser_core):
            for name in ("save_settings", "_save_window_geometry", "save_layout_settings", "_update_layout_setting"):
                if hasattr(module, name):
                    patcher = mock.patch.object(module, name, lambda *a, **k: None)
                    patcher.start()
                    self.addCleanup(patcher.stop)
        self.saved = []
        patcher = mock.patch.object(settings_store, "save_live_state", lambda k, v: self.saved.append((k, v)))
        patcher.start()
        self.addCleanup(patcher.stop)
        applied = ui_state.APPLIED_SETTINGS
        self.addCleanup(setattr, ui_state, "APPLIED_SETTINGS", applied)
        ui_state.APPLIED_SETTINGS = settings_store.load_settings()
        ui_state.APPLIED_SETTINGS["viewer_recursive"] = False
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)
        self.folder = self.root / "3d/projA/sp1/in"
        (self.folder / "deep").mkdir(parents=True)
        for where, name in ((self.folder, "a.png"), (self.folder, "b.png"), (self.folder / "deep", "c.png")):
            image = QImage(64, 48, QImage.Format_RGB32)
            image.fill(QColor("red"))
            image.save(str(where / name))
        self.win = pb.PipelineBrowser(self.root)
        self.win._idle_preview_scheduler.timer.stop()
        self.win.resize(1500, 850)
        self.win.show()
        self.addCleanup(self.win.deleteLater)
        settle(0.2)
        select(self.win.columns[0], "3d")
        select(self.win.columns[1], "projA")
        select(self.win.columns[2], "sp1")
        settle()

    def _column_with(self, name):
        for column in [*self.win.columns, *self.win.group_columns]:
            for i in range(column.list.count()):
                if Path(column.list.item(i).data(ROLE_PATH)).name == name:
                    return column
        raise AssertionError(name)

    def test_menu_signals_are_connected_on_every_column(self):
        win = self.win
        for column in [*win.columns, *win.group_columns]:
            with mock.patch.object(win, "_view_folder_in_viewer") as view:
                column.folder_gallery_requested.emit(self.folder)
            view.assert_called_once_with(self.folder, column, True)
            column.recursive_requested.emit(True)
            self.assertEqual(self.saved[-1], ("viewer_recursive", True))
            column.recursive_requested.emit(False)
            self.assertEqual(self.saved[-1], ("viewer_recursive", False))

    def test_open_viewer_here_opens_the_gallery_without_a_focused_image(self):
        win = self.win
        win._view_folder_in_viewer(self.folder, None, True)
        settle()
        self.assertTrue(win._project_columns_hidden)
        self.assertIsNotNone(win._focus_gallery)                       # la planche, pas l'image seule
        self.assertIsNone(win._focus_gallery.current)                  # aucune case « en cours » : pas de focus
        self.assertEqual({p.name for p in win._gallery_list}, {"a.png", "b.png"})   # non récursif
        self.assertTrue(win._focus_overlay is None or not win._focus_overlay.isVisible())

    def test_recursive_shows_the_photos_of_the_subfolders_too(self):
        win = self.win
        win._set_recursive(True)
        self.assertEqual(self.saved[-1], ("viewer_recursive", True))   # enregistré aussitôt
        win._view_folder_in_viewer(self.folder, None, True)
        settle(1.5)
        self.assertIsNotNone(win._focus_gallery)
        self.assertEqual({p.name for p in win._gallery_list}, {"a.png", "b.png", "c.png"})
        self.assertIsNone(win._focus_gallery.current)
        win._set_recursive(False)                                      # bouton / case : retour au dossier seul
        settle(0.5)
        self.assertEqual({p.name for p in win._gallery_list}, {"a.png", "b.png"})

    def _folder_row(self):
        """(colonne, nom) d'une ligne qui est un DOSSIER : une colonne autonome, affichée, sur le projet."""
        column = column_module.Column(self.root / "3d" / "projA", "Test")
        self.addCleanup(column.deleteLater)
        column.resize(300, 400)
        column.show()
        settle(0.3)
        return column, "sp1"

    def _context_menu_choice(self, column, name, choose):
        """Ouvre le menu contextuel de la ligne `name` de `column`, y « clique » l'action de texte `choose`
        (None : aucune) et rend les textes du menu."""
        item = next(column.list.item(i) for i in range(column.list.count())
                    if Path(column.list.item(i).data(ROLE_PATH)).name == name)
        column.list.scrollToItem(item)
        settle(0.1)
        pos = column.list.visualItemRect(item).center()
        self.assertIs(column.list.itemAt(pos), item)       # le clic droit tombe bien sur la ligne
        seen = {}

        def fake_exec(menu, *args, **kwargs):
            seen["texts"] = [a.text() for a in menu.actions()]
            action = next((a for a in menu.actions() if a.text() == choose), None)
            if action is not None and action.isCheckable():
                action.setChecked(not action.isChecked())          # ce que fait Qt au clic
            return action

        with mock.patch.object(column_module.Menu, "exec", fake_exec):
            column._on_context_menu(pos)
        return seen["texts"]

    def test_folder_menu_has_the_viewer_entry_and_the_recursive_box(self):
        column, name = self._folder_row()
        texts = self._context_menu_choice(column, name, None)
        self.assertIn("Ouvrir la visionneuse à cet endroit", texts)
        self.assertIn("Récursif (photos des sous-dossiers)", texts)
        asked = []
        column.folder_gallery_requested.connect(asked.append)
        self._context_menu_choice(column, name, "Ouvrir la visionneuse à cet endroit")
        settle(0.1)
        self.assertEqual([p.name for p in asked], [name])  # le signal part ; la fenêtre l'ouvre en planche
        checks = []
        column.recursive_requested.connect(checks.append)
        self._context_menu_choice(column, name, "Récursif (photos des sous-dossiers)")
        self.assertEqual(checks, [True])

    def test_gallery_opens_even_without_a_focus_column(self):
        # Pas de colonne Focus ni d'image a envoyer au centre (la garde de _set_columns_hidden refuse alors de
        # masquer) : la planche s'ouvre quand meme, l'explorateur jamais.
        win = self.win
        win.image_preview_columns = []
        with mock.patch.object(win, "_focus_source", return_value=None),                 mock.patch.object(win, "on_activated") as explorer:
            win._view_folder_in_viewer(self.folder, None, True)
            settle(1.0)
        explorer.assert_not_called()
        self.assertTrue(win._project_columns_hidden)
        self.assertIsNotNone(win._focus_gallery)
        self.assertEqual({p.name for p in win._gallery_list}, {"a.png", "b.png"})

    def test_photos_only_in_subfolders_still_open_the_gallery(self):
        # Dossier sans photo directe : la planche de l'appli montre celles des sous-dossiers, jamais l'explorateur.
        win = self.win
        outer = self.root / "3d/projA"
        with mock.patch.object(win, "on_activated") as explorer:
            win._view_folder_in_viewer(outer, None, True)
            settle(1.5)
        explorer.assert_not_called()
        self.assertIsNotNone(win._focus_gallery)
        self.assertIsNone(win._focus_gallery.current)
        self.assertEqual({p.name for p in win._gallery_list}, {"a.png", "b.png", "c.png"})
        self.assertTrue(win._recursive_on())                           # allumé pour cela

    def test_empty_folder_says_so_and_never_opens_the_explorer(self):
        win = self.win
        empty = self.root / "3d/projA/vide"
        empty.mkdir()
        with mock.patch.object(win, "on_activated") as explorer:
            win._view_folder_in_viewer(empty, None, True)
            settle(1.5)
        explorer.assert_not_called()
        self.assertIsNone(win._focus_gallery)
        self.assertFalse(win._project_columns_hidden)
        self.assertFalse(win._recursive_on())                          # remis : rien n'a été trouvé
        self.assertIn("Aucune photo", win.path_label.text())

    def test_double_click_still_opens_the_first_photo(self):
        win = self.win
        win._view_folder_in_viewer(self.folder, None)
        settle()
        self.assertTrue(win._project_columns_hidden)
        self.assertIsNone(win._focus_gallery)                          # l'image, comme avant (G = planche)


if __name__ == "__main__":
    unittest.main()
