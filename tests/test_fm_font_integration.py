"""fm_font, BRANCHEMENT dans fm_browser : défauts `typo_*` dans DEFAULT_SETTINGS, fenêtre « Réglages :
Typographie » (catalogue), mixin de la fenêtre principale (double-clic sur .ufo / .ttf, ouverture plein cadre,
colonnes masquées puis remontrées, fermeture prudente d'un projet modifié, autre mode qui ferme le module),
menu de colonne « Créer un projet typographique », réglages appliqués en direct."""
import os as _os, sys as _sys  # jamais les vrais réglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import os as _os2, tempfile as _tempfile  # sauvegardes de secours : jamais dans le dossier de l'utilisateur
_os2.environ.setdefault("FM_FONT_AUTOSAVE_DIR", _tempfile.mkdtemp(prefix="fmfont_secours_"))
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PySide6.QtWidgets import QApplication, QLabel, QListWidget, QListWidgetItem, QScrollArea, QWidget

from _window_cleanup import WindowTestCase, track  # noqa: E402
import settings_store  # noqa: E402
import ui_state  # noqa: E402
from fm_font import pane as pane_mod  # noqa: E402
from fm_font.compile import compile_static  # noqa: E402
from fm_font.document import FontProject  # noqa: E402
from main_window.font_module import FontModuleMixin  # noqa: E402

app = QApplication.instance() or QApplication([])


class _Host(FontModuleMixin):
    """Fenêtre principale réduite à ce que le mixin utilise."""

    def __init__(self):
        self.window = track(QWidget())
        self.window.resize(1200, 800)
        self.scroll = QScrollArea(self.window)
        self.scroll.resize(1200, 800)
        self.scroll.setWidget(QWidget())
        self.path_label = QLabel(self.window)
        self._project_columns_hidden = False
        self._board = None
        self.closed_video = 0
        self.window.show()

    def _close_md_editor(self):
        return True

    def _close_board(self):
        return True

    def _close_video(self):
        self.closed_video += 1

    def _sync_collapse_button(self):
        pass

    def _selected_path(self):
        return None, None

    def open_module_settings(self, module):
        self.opened_settings = module


class IntegrationTest(WindowTestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="fmfont_int_"))
        project = FontProject.new("Essai")
        project.add_glyph("A")
        self.ufo = self.tmp / "Essai.ufo"
        project.save(self.ufo)
        self.ttf = self.tmp / "Essai.ttf"
        compile_static(project.font, "ttf").save(self.ttf)
        self._applied = ui_state.APPLIED_SETTINGS
        ui_state.APPLIED_SETTINGS = dict(settings_store.DEFAULT_SETTINGS)

    def tearDown(self):
        ui_state.APPLIED_SETTINGS = self._applied
        super().tearDown()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_defaults_and_settings_window(self):
        defaults = settings_store.DEFAULT_SETTINGS
        self.assertTrue(defaults["typo_open_double_click"])
        self.assertEqual(defaults["typo_node_size"], 7)
        import settings_window_v2 as v2
        from fm_font.settings import TYPO_TAB
        from fm_font.settings_defaults import TYPO_DEFAULTS
        from settings_catalog import CATALOG
        self.assertEqual(v2.MODULE_SCOPES["font"], [(TYPO_TAB, None)])
        self.assertEqual(v2.MODULE_TITLES["font"], "Typographie")
        keys = {spec.key for name, specs in CATALOG.items() if name.startswith("Typographie") for spec in specs}
        self.assertEqual(keys, set(TYPO_DEFAULTS) - {"typo_preview_text"})
        window = track(v2.SettingsWindowV2(None, module="font"))
        texts = {label.text() for label in window.findChildren(QLabel)}
        self.assertIn("Réglages : Typographie", texts)
        for node in window.findChildren(v2._LazyNode):                    # chaque section construite
            node.set_collapsed(False)
        app.processEvents()
        texts = {label.text() for label in window.findChildren(QLabel)}
        for label in ("Taille des nœuds", "Tolérance cubique -> quadratique", "Pression de la tablette",
                      "Fond du canvas"):
            self.assertIn(label, texts)

    def test_double_click_open_close_and_columns(self):
        host = _Host()
        self.assertTrue(host._font_claims(self.ufo))
        self.assertTrue(host._font_claims(self.ttf))
        self.assertFalse(host._font_claims(self.tmp))
        ui_state.APPLIED_SETTINGS["typo_open_double_click"] = False
        self.assertFalse(host._font_claims(self.ufo))
        ui_state.APPLIED_SETTINGS["typo_open_double_click"] = True
        self.assertTrue(host._open_font(self.ufo))
        pane = host._font
        self.assertIsNotNone(pane)
        self.assertEqual(pane.project.path, self.ufo)
        self.assertFalse(host.scroll.widget().isVisible())                 # colonnes vraiment masquées
        self.assertEqual(pane.geometry(), host.scroll.viewport().rect())
        pane_mod.HOOKS["open_settings"]()
        self.assertEqual(host.opened_settings, "font")
        pane.project.edit_glyph("A", "x", lambda g: setattr(g, "width", 777))
        with mock.patch.object(pane_mod, "confirm", side_effect=[False, False]):
            self.assertFalse(host._leave_font())                           # annulé : reste ouvert
        self.assertIs(host._font, pane)
        with mock.patch.object(pane_mod, "confirm", side_effect=[True]):  # enregistrer
            self.assertTrue(host._leave_font())
        self.assertIsNone(host._font)
        self.assertTrue(host.scroll.widget().isVisible())
        self.assertEqual(FontProject.open(self.ufo).font["A"].width, 777)
        self.assertTrue(host._open_font(self.ttf))                          # police : importée
        self.assertEqual(host._font.project.source, self.ttf)
        self.assertFalse(host._font.project.is_dirty())                     # import intact : rien à perdre
        with mock.patch.object(pane_mod, "confirm", side_effect=AssertionError("aucune question attendue")):
            host._font.request_close()
        self.assertIsNone(host._font)

    def test_viewer_double_click_routes_ufo_folder(self):
        from main_window.viewer import ViewerMixin
        host = _Host()
        host.on_activated = ViewerMixin.on_activated.__get__(host)
        host.on_activated(self.ufo)
        self.assertIsNotNone(host._font)
        host._close_font()

    def test_live_settings_reach_open_pane(self):
        host = _Host()
        host._open_font(None)
        pane = host._font
        pane.apply_settings({"typo_node_size": 12, "typo_canvas_bg": "#000000", "autre": 1})
        self.assertEqual(pane.canvas.settings["typo_node_size"], 12)
        self.assertEqual(pane.canvas._colors["canvas_bg"].name(), "#000000")
        host._close_font()

    def test_column_menu_creates_font_project(self):
        from browser_core import ROLE_PATH
        from column_parts.file_operations import ColumnFileOperationsMixin

        class _Column(ColumnFileOperationsMixin):
            pass
        column = _Column()
        column.directory = self.tmp
        column.list = track(QListWidget())
        target = self.tmp / "Ma Fonte.ufo"

        def refresh():
            item = QListWidgetItem("Ma Fonte.ufo")
            item.setData(ROLE_PATH, str(target))
            column.list.addItem(item)
        column.refresh = refresh
        self.assertEqual(column._create_font_project("Ma Fonte"), target)
        self.assertTrue(target.is_dir())
        self.assertEqual(column.list.currentItem().data(ROLE_PATH), str(target))
        self.assertEqual(FontProject.open(target).family_name, "Ma Fonte")


if __name__ == "__main__":
    unittest.main()
