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
from main_window.chrome import ChromeMixin  # noqa: E402
from main_window.font_module import FontModuleMixin  # noqa: E402
from main_window.module_targets import ModuleTargetsMixin  # noqa: E402

app = QApplication.instance() or QApplication([])


class _TitleBar(QWidget):
    """Barre de navigation réduite à ses cadres de module."""

    def font_group(self):
        from main_window.title_bar import _ViewerGroup
        group = getattr(self, "_font_group", None)
        if group is None:
            group = self._font_group = _ViewerGroup(self, "Typographie")
            group.hide()
        return group

    def place_viewer_group(self):
        pass


class _Host(FontModuleMixin, ChromeMixin, ModuleTargetsMixin):
    """Fenêtre principale réduite à ce que le mixin utilise."""

    def __init__(self):
        self.window = track(QWidget())
        self.window.resize(1200, 800)
        self.titlebar = _TitleBar(self.window)
        self.titlebar.resize(1200, 40)
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
        self.assertNotIn("typo_open_double_click", defaults)               # jamais au double-clic (utilisateur)
        self.assertEqual(defaults["typo_node_size"], 7)
        import settings_window_v2 as v2
        from fm_font.settings import TYPO_TAB
        from fm_font.settings_defaults import TYPO_DEFAULTS
        from settings_catalog import CATALOG
        self.assertEqual(v2.MODULE_SCOPES["font"], [(TYPO_TAB, None)])
        self.assertEqual(v2.MODULE_TITLES["font"], "Typographie")
        keys = {spec.key for name, specs in CATALOG.items() if name.startswith("Typographie") for spec in specs}
        self.assertEqual(keys, set(TYPO_DEFAULTS) - {"typo_preview_text", "typo_bars"})     # (états temps réel)
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

    def test_open_close_and_columns(self):
        from main_window.font_module import font_target
        host = _Host()
        self.assertTrue(font_target(self.ufo, True))
        self.assertTrue(font_target(self.ttf, False))
        self.assertFalse(font_target(self.ufo, False))                     # un .ufo est un dossier
        self.assertFalse(font_target(self.tmp, True))
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

    def test_navbar_button_greyed_until_a_font_is_selected(self):
        from main_window.chrome import ChromeMixin
        from preview_column import IconButton

        class _Bar(_Host):
            def __init__(self):
                super().__init__()
                self.selected = None
                self._md_open = False
                self._video = None
                for name in ("btn_viewer", "btn_text_editor", "btn_board", "btn_video", "btn_font"):
                    setattr(self, name, track(IconButton(name[4:], "#c4cacf", "#ffffff")))
                self.btn_font.clicked.connect(self._toggle_font)

            def _selected_path(self):
                return None, self.selected

            def _is_spreadsheet(self, path):
                return False

            def _sync_collapse_button(self):
                self._sync_mode_buttons()

        bar = _Bar()
        bar._sync_mode_buttons()
        self.assertFalse(bar.btn_font.isEnabled())                          # rien de sélectionné : grisé
        for path, usable in ((self.tmp, False), (self.ufo, True), (self.ttf, True), (self.tmp / "notes.ufo", False)):
            bar.selected = path
            bar._sync_mode_buttons()
            self.assertEqual(bar.btn_font.isEnabled(), usable, path)
        bar.selected = self.ttf
        bar._sync_mode_buttons()
        bar.btn_font.click()                                              # ouvre le module sur la police
        self.assertIsNotNone(bar._font)
        self.assertEqual(bar._font.project.source, self.ttf)
        bar.selected = None
        bar._sync_mode_buttons()
        self.assertTrue(bar.btn_font.isEnabled())                           # module ouvert : bouton pour en sortir
        with mock.patch.object(pane_mod, "confirm", side_effect=AssertionError("aucune question attendue")):
            bar.btn_font.click()                                            # projet intact : fermé sans question
        self.assertIsNone(bar._font)
        self.assertFalse(bar.btn_font.isEnabled())

    def test_navbar_frame_buttons_follow_the_project(self):
        """Cadre « Typographie » de la barre (comme « Vidéo » / « Board ») : annuler / rétablir grisés selon la
        pile, enregistrer en accent si modifié, réglages du module, fermer ; le module ne les répète pas."""
        host = _Host()
        self.assertTrue(host._open_font(self.ufo))
        pane = host._font
        group = host.titlebar.font_group()
        self.assertTrue(group.isVisible())
        kinds = [b._font_kind for b in host._font_buttons]
        self.assertEqual(kinds, ["gallery", "undo", "redo", "save", "export", "gear", "close"])
        gallery, undo, redo, save = host._font_buttons[:4]
        self.assertFalse(undo.isEnabled())
        self.assertFalse(pane.close_button.isVisible())                    # pas répété dans le module
        self.assertFalse(pane.undo_button.isVisible())
        pane.project.edit_glyph("A", "Largeur", lambda g: setattr(g, "width", 640))
        app.processEvents()
        pane._refresh_views()                                              # (minuterie de 30 ms)
        self.assertTrue(undo.isEnabled())
        self.assertIn("Largeur", undo.toolTip())
        self.assertIsNotNone(save._alert)
        undo.click()
        pane._refresh_views()
        self.assertTrue(redo.isEnabled())
        host._font_buttons[5].click()
        self.assertEqual(host.opened_settings, "font")
        # Bouton planche (comme celui de la visionneuse) : planche <-> lettre, icône selon la page.
        self.assertEqual(gallery._kind, "single_image")                    # planche montrée : vers la lettre
        gallery.click()
        self.assertEqual(pane.current_page(), "Éditeur")
        self.assertEqual(gallery._kind, "gallery")
        self.assertIn("planche", gallery.toolTip())
        gallery.click()
        self.assertEqual(pane.current_page(), "Glyphes")
        with mock.patch.object(pane_mod, "confirm", side_effect=AssertionError("aucune question attendue")):
            host._font_buttons[6].click()                                  # revenu à l'état enregistré
        self.assertIsNone(host._font)
        self.assertFalse(group.isVisible())

    def test_double_click_never_opens_the_module(self):
        """Demande de l'utilisateur : le module s'ouvre par le menu d'une ligne ou le bouton de la barre, jamais au
        double-clic (une police va à la visionneuse, un .ufo à l'explorateur comme tout dossier)."""
        from main_window.viewer import ViewerMixin
        host = _Host()
        host._open_font = lambda path=None: self.fail("module ouvert au double-clic")
        host._video_claims = lambda path: False
        with mock.patch("main_window.viewer.open_in_file_manager") as explorer:
            ViewerMixin.on_activated.__get__(host)(self.ufo)
        explorer.assert_called_once()

    def test_row_menu_opens_the_module(self):
        import column as column_module
        from browser_core import ROLE_PATH
        opened = []

        class _Window(ModuleTargetsMixin, QWidget):                       # menu commun (module_targets)
            def open_in_module(self, key, path, column=None):
                opened.append(Path(path))
        window = track(_Window())
        column = column_module.Column(self.tmp, "Contenu")
        column.setParent(window)
        column.resize(300, 400)
        window.show()
        app.processEvents()
        for path in (self.ufo, self.ttf):
            item = next(column.list.item(i) for i in range(column.list.count())
                        if Path(column.list.item(i).data(ROLE_PATH)) == path)
            seen = []

            def fake_exec(menu, *args, **kwargs):
                seen.extend(a.text() for a in menu.actions())
                return next(a for a in menu.actions() if a.text() == "Ouvrir dans le module typographique")
            with mock.patch.object(column_module.Menu, "exec", fake_exec):
                column._on_context_menu(column.list.visualItemRect(item).center())
            for _ in range(3):
                app.processEvents()
            self.assertEqual(seen.count("Ouvrir dans le module typographique"), 1)
            self.assertEqual(opened[-1], path)

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
