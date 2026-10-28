"""Barre de navigation : racine, parcourir, presets, reglages dedans (plus de barre du haut) ; boutons de meme taille ;
tabs : rayon sur TOUS les onglets ; chemin rapide des reglages Bouton / Zone de saisie / Tabs."""
import os as _os, sys as _sys  # jamais les vrais reglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
from _lent import lent  # noqa: E402
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

from PySide6.QtWidgets import QApplication

APP = QApplication.instance() or QApplication([])

import app_style
import pipeline_browser as pb
import settings_layout
import settings_store
import settings_window_v2 as v2
from preview_column import IconButton


def settle(seconds=0.2):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        APP.processEvents()
        time.sleep(0.005)


@lent
class NavigationBarTest(unittest.TestCase):
    def setUp(self):
        app_style.apply_style(APP)
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)
        (self.root / "a").mkdir()
        self.win = pb.PipelineBrowser(self.root)
        self.win._idle_preview_scheduler.timer.stop()
        self.win.resize(1300, 800)
        self.win.show()
        self.addCleanup(self.win.deleteLater)
        settle()

    def test_tools_live_in_the_navigation_bar_and_the_top_bar_is_gone(self):
        win = self.win
        for name in ("topbar", "btn_reload", "btn_last_place", "synced_label", "root_label"):
            self.assertFalse(hasattr(win, name), name)
        bar = win.titlebar
        for widget in (win.root_field, win.btn_browse, win.preset_picker, win.btn_presets, win.btn_settings):
            self.assertTrue(bar.isAncestorOf(widget))
            self.assertTrue(widget.isVisible())
        self.assertTrue(win.preset_picker.manage.isHidden())            # « Gerer » = l'icone de la barre
        self.assertLess(win.root_field.width(), 300)                    # beaucoup moins large qu'avant
        sizes = {(b.width(), b.height()) for b in (win.btn_browse, win.btn_presets, win.btn_settings,
                                                   win.btn_collapse, bar.btn_min)}
        self.assertEqual(len(sizes), 1)                                 # tous les boutons de la meme taille
        self.assertEqual(win.scroll.geometry().top(), bar.geometry().bottom() + 1)   # colonnes jusqu'a la barre

    def test_bar_buttons_have_their_own_settings_icons(self):
        rows = {s.params["ui_key"] for s in v2.CATALOG["Barre de navigation : Icones"] if s.kind == "ui_icon"}
        self.assertTrue({"navbar_browse", "navbar_presets", "settings_gear"} <= rows)
        button = self.win.btn_browse
        self.assertEqual(button._kind, "browse")
        self.assertIsNone(button._custom_icon_pixmap(button.rect()))     # glyphe peint par defaut

    def test_icon_rows_are_split_cells_with_a_preview_cell(self):
        spec = next(s for s in v2.CATALOG["Barre de navigation : Icones"] if s.kind == "ui_icon" and
                    s.params["ui_key"] == "navbar_browse")
        holder = v2._f_ui_icon(spec, None, {})
        from settings_cells import split_of
        cell = split_of(holder)
        self.assertIsNotNone(cell)
        captions = cell.capTexts()
        self.assertIn("Icône".upper(), [c.upper() for c in captions])
        caption, avatar, widgets = holder._ui_icon_field.states()[0]
        from PySide6.QtWidgets import QPushButton
        buttons = widgets[0].findChildren(QPushButton)
        self.assertEqual(len(widgets), 1)
        self.assertEqual(len(buttons), 2)                               # changer / reinitialiser : plus de capture
        self.assertNotIn("Capturer", " ".join(b.text() for b in buttons))
        self.assertEqual(abs(buttons[0].y() - buttons[1].y()), 0)       # cote a cote
        self.assertFalse(avatar.pixmap().isNull())                       # l'icone en cours (glyphe par defaut)

    def test_only_button_input_and_tabs_keys_take_the_fast_path(self):
        win = self.win
        import browser_core
        import settings_store
        import ui_state
        browser_core.apply_all_settings(settings_store.load_settings())
        win._last_style_key = win._style_key(ui_state.APPLIED_SETTINGS)
        settings = dict(ui_state.APPLIED_SETTINGS)
        settings["button_bg_color"] = "#aa3355"
        with mock.patch.object(win, "refresh_all_columns") as columns, \
                mock.patch.object(win, "refresh_colors") as colors:
            win._apply_settings(settings)
        columns.assert_not_called()
        colors.assert_not_called()
        self.assertTrue(win._pending_stylesheet_rebuild)
        settings = dict(ui_state.APPLIED_SETTINGS)
        settings["header_height"] = int(settings.get("header_height", 30)) + 3
        settings["root_path"] = win.root_field.text()
        with mock.patch.object(win, "refresh_all_columns") as columns:
            win._apply_settings(settings)
        columns.assert_called()                                          # le reste suit le chemin complet

    def test_each_column_choice_is_marked_under_the_title_on_the_left(self):
        from browser_core import ROLE_PATH
        (self.root / "3d" / "projA" / "sp1").mkdir(parents=True)
        self.win.reload()
        settle(0.3)

        def select(column, name):
            for i in range(column.list.count()):
                item = column.list.item(i)
                if Path(item.data(ROLE_PATH)).name == name:
                    column.list.setCurrentItem(item)
                    settle(0.3)
                    return
            self.fail(name)
        select(self.win.columns[0], "3d")
        select(self.win.columns[1], "projA")
        bar = self.win.titlebar
        self.assertEqual(bar._crumb_names[:2], ["3d", "projA"])
        self.assertGreaterEqual(bar.crumbs.geometry().top(), bar.title_label.geometry().bottom())   # sous le titre
        self.assertEqual(bar.crumbs.geometry().left(), app_style.scaled(10, 0))                      # colle a gauche
        self.win.prune_after(0)                                       # re-clic : les colonnes suivantes disparaissent
        settle(0.2)
        self.assertEqual(bar._crumb_names, ["3d", "projA"])           # le chemin parcouru reste (apres le focus)
        self.assertEqual([k for k, _n, _c in bar._crumb_items], ["set!", "after_focus"])

    @staticmethod
    def _fake_column(path):
        from PySide6.QtCore import QObject

        class Fake(QObject):
            def __init__(self):
                super().__init__()
                self.clicks = 0
                outer = self

                class _List:
                    def setFocus(self, *_reason):
                        pass

                self.list = _List()

            def reselect_current(self):
                self.clicks += 1                               # focus : la selection est rejouee

            def set_active(self, _on):
                pass

            def current_path(self):
                return Path(path) if path else None
        return Fake()

    def test_crumbs_cover_set_group_and_following_columns_and_click_replays_the_item(self):
        win = self.win
        chain = [self._fake_column(p) for p in ("F:/x/3d", "F:/x/projA", "F:/x/sp1")]
        content = self._fake_column("F:/x/sp1/in/ref")
        group = self._fake_column("F:/x/sp1/in/textures")
        empty_group = self._fake_column(None)
        win.columns = [*chain, content]
        win.group_columns = [empty_group, group]
        win._active_project_config = {"set_enabled": True, "columns": [{"name": "sp"}]}
        items = win._crumb_items()
        self.assertEqual([(k, n) for k, n, _c in items],
                         [("set", "3d"), ("set", "projA"), ("set", "sp1"), ("after", "textures"), ("after!", "ref")])
        items[1][2]()                                              # clic sur « projA »
        self.assertEqual((chain[1].clicks, chain[0].clicks, chain[2].clicks), (1, 0, 0))
        items[3][2]()                                              # le choix LOGICIELS / IN / OVER / OUT aussi
        self.assertEqual(group.clicks, 1)
        win._active_project_config = {"set_enabled": False, "columns": []}      # projet SANS set
        win.columns = [*chain[:2], content]
        kinds = {k for k, _n, _c in win._crumb_items()}
        self.assertEqual({k.rstrip("!") for k in kinds}, {"after"})   # tout en « couleur fond apres set »
        win.columns, win.group_columns = [], []                    # laisse la fenetre se detruire proprement

    def test_clicking_a_crumb_focuses_its_item_and_closes_the_columns_after_it(self):
        from browser_core import ROLE_PATH
        (self.root / "3d" / "projA" / "sp1" / "deep").mkdir(parents=True)
        self.win.reload()
        settle(0.3)

        def select(column, name):
            for i in range(column.list.count()):
                item = column.list.item(i)
                if Path(item.data(ROLE_PATH)).name == name:
                    column.list.setCurrentItem(item)
                    settle(0.3)
                    return
            self.fail(name)
        select(self.win.columns[0], "3d")
        select(self.win.columns[1], "projA")
        select(self.win.columns[2], "sp1")
        settle(0.5)
        items = self.win._crumb_items()
        self.assertGreaterEqual(len(items), 3)
        items[1][2]()                                                 # clic sur « projA » dans le cheminement
        settle(0.8)
        self.assertEqual(self.win.columns[1].current_path().name, "projA")   # FOCUS : projA reste choisi
        self.assertIsNone(self.win.columns[2].current_path())        # colonnes suivantes refermees (sp1 lache)
        self.assertEqual(len(self.win.columns), 3)                    # son contenu reaffiche
        # Le chemin parcouru reste affiche apres le focus (« apres focus »).
        self.assertEqual(self.win.titlebar._crumb_names, ["3d", "projA", "sp1"])
        self.assertEqual([k for k, _n, _c in self.win.titlebar._crumb_items], ["set", "set!", "after_focus"])

    def test_viewer_crumbs_end_at_the_central_folder_and_follow_the_image_at_once(self):
        win = self.win
        folder = self.root / "3d" / "projA"
        sub = folder / "sub"
        sub.mkdir(parents=True)
        images = [folder / "a.png", folder / "b.png", sub / "c.png"]
        win.columns, win.group_columns = [], []
        win._project_columns_hidden = True
        win._viewer_folder = folder
        win._viewer_paths, win._viewer_index = images, 0
        items = win._viewer_crumb_items()
        self.assertEqual([n for _k, n, _c in items], ["3d", "projA", "a.png"])   # dossier central puis image
        self.assertEqual([k for k, _n, _c in items], ["after", "after!", "after_focus"])   # focus : le central
        win._viewer_index = 2
        names = [n for _k, n, _c in win._viewer_crumb_items()]
        self.assertEqual(names[-2:], ["sub", "c.png"])                # image d'un sous-dossier (recursif)
        with mock.patch.object(win, "_apply_viewer_base"), mock.patch.object(win, "_viewer_folder_files",
                                                                             return_value=[images[0]]):
            win._viewer_crumb_items()[0][2]()                         # clic sur « 3d » : nouveau dossier central
        self.assertEqual(win._viewer_folder, self.root / "3d")
        win._project_columns_hidden = False
        win._viewer_folder, win._viewer_paths, win._viewer_index = None, [], -1

    def test_separator_row_dims_follow_the_separator_type(self):
        import copy
        group = "Barre de navigation : Cheminement"
        settings = copy.deepcopy(settings_store.DEFAULT_SETTINGS)
        fields: dict = {}
        v2.build_group(group, v2.ScopeValues(settings, None), settings["colors"], fields, {}, [], [],
                       lambda: None)
        char_row, icon_row = fields["crumb_sep_font_family"], fields["ui_icon:navbar_crumb_separator"]
        kind = fields["crumb_separator_kind"]
        self.assertTrue(char_row.isEnabled())                          # type caractere : ligne icone grisee
        self.assertFalse(icon_row.isEnabled())
        kind._select("Icône")
        self.assertFalse(char_row.isEnabled())                         # type icone : ligne caractere grisee
        self.assertTrue(icon_row.isEnabled())
        # la ligne caractere porte le caractere ET tous les champs de police
        parts = char_row._v2_parts
        self.assertEqual(set(parts), {"char", "family", "bold", "italic", "size", "smoothing", "color"})
        spec = next(s for s in v2.CATALOG[group] if s.key == "crumb_sep_font_family")
        parts["char"].setText("/")
        self.assertEqual(v2.read_spec(spec, char_row)["crumb_separator_char"], "/")

    def test_default_crumb_backgrounds_are_transparent(self):
        for key in ("crumb_set_bg_color", "crumb_after_bg_color"):
            self.assertEqual(settings_store.DEFAULT_SETTINGS[key], "#00000000")

    def test_every_linked_toggle_of_the_catalog_is_saved(self):
        # « lier les 4 » (cotes, coins, padding) : sa cle `<cle>_linked` doit exister dans les reglages, sinon
        # load_settings l'ignore et le toggle ne s'enregistre pas (signale : Tabs > Border radius).
        missing = [(group, spec.key) for group, specs in v2.CATALOG.items() for spec in specs
                   if spec.kind in ("corners", "padding", "sides_thick", "shadow")
                   and f"{spec.key}_linked" not in settings_store.DEFAULT_SETTINGS]
        self.assertEqual(missing, [])
        saved = settings_store.load_settings()
        self.assertIn("tabs_corner_radius_linked", saved)

    def test_separator_follows_the_text_size_unless_it_has_its_own(self):
        import browser_core
        base = settings_store.load_settings()
        browser_core.apply_all_settings({**base, "crumb_font_size": 15, "crumb_sep_font_size": 0})
        look = pb._build_crumb_look()
        self.assertEqual(look["sep_font"].pixelSize(), 15)              # 0 = comme les textes
        browser_core.apply_all_settings({**base, "crumb_font_size": 15, "crumb_sep_font_size": 22})
        self.assertEqual(pb._build_crumb_look()["sep_font"].pixelSize(), 22)

    def test_chip_colors_follow_the_settings(self):
        import ui_state
        import browser_core
        import settings_store
        browser_core.apply_all_settings({**settings_store.load_settings(), "crumb_set_bg_color": "#224466",
                                         "crumb_after_bg_color": "#664422", "crumb_spacing": 9,
                                         "crumb_padding": {"left": 6, "top": 3, "right": 6, "bottom": 3}})
        look = pb._crumb_look()
        self.assertEqual(look["set_bg"].name(), "#224466")
        self.assertEqual(look["after_bg"].name(), "#664422")
        self.assertEqual(look["spacing"], 9)
        chip = pb._CrumbChip("abc", "set", look)
        self.assertEqual(chip.toolTip(), "")                             # pas d'info-bulle au survol
        bare = {**look["states"]["set"], "padding": {s: 0 for s in ("left", "top", "right", "bottom")}}
        plain = pb._CrumbChip("abc", "set", {**look, "states": {**look["states"], "set": bare}})
        self.assertEqual(chip.width() - plain.width(), 12)          # padding horizontal compte
        rows = {s.key for group in ("Barre de navigation : Cheminement", "Cheminement : Set", "Cheminement : Apres set")
                for s in v2.CATALOG[group]}
        for key in ("crumb_spacing", "crumb_separator_kind", "crumb_set_bg_color", "crumb_after_bg_color",
                    "crumb_border_enabled", "crumb_corner_radius", "crumb_padding", "crumb_shadow_enabled",
                    "crumb_font_family", "crumb_hover_bg_color", "crumb_focus_border_enabled"):
            self.assertIn(key, rows)

    def test_after_set_rows_follow_the_set_table_unless_their_toggle_is_on(self):
        import browser_core
        import settings_store
        base = settings_store.load_settings()
        browser_core.apply_all_settings({**base, "crumb_padding": {"left": 4, "top": 0, "right": 4, "bottom": 0},
                                         "crumb_after_padding": {"left": 9, "top": 0, "right": 9, "bottom": 0},
                                         "crumb_after_ovr_padding": False, "crumb_afterfocus_ovr_padding": True,
                                         "crumb_afterfocus_padding": {"left": 1, "top": 0, "right": 1, "bottom": 0}})
        states = pb._crumb_look()["states"]
        self.assertEqual(states["after"]["padding"]["left"], 4)          # toggle eteint : celui du Set
        self.assertEqual(states["after_focus"]["padding"]["left"], 1)    # toggle allume : le sien
        self.assertEqual(pb._crumb_state("after_focus"), ("after_focus", False))
        self.assertEqual(pb._crumb_state("set!"), ("set", True))
        browser_core.apply_all_settings(base)

    def test_separators_can_be_turned_off_and_their_rows_are_dimmed(self):
        import browser_core
        import settings_store
        base = settings_store.load_settings()
        browser_core.apply_all_settings({**base, "crumb_separator_enabled": False})
        bar = self.win.titlebar
        bar.set_crumbs([("set", "a", lambda: None), ("set!", "b", lambda: None)], force=True)
        self.assertEqual(bar.crumbs.findChildren(pb.QLabel), [])         # aucun separateur
        browser_core.apply_all_settings(base)
        spec = next(s for s in v2.CATALOG["Barre de navigation : Cheminement"] if s.key == "crumb_separator_kind")
        self.assertEqual(spec.params["column"].key, "crumb_separator_enabled")     # colonne « Activer »
        fields, toggles, resizers = {}, {}, []
        frame = v2.build_group("Barre de navigation : Cheminement", v2.ScopeValues(dict(base), None), base["colors"],
                               fields, toggles, resizers)
        head_titles = [c.text().upper() for c in frame._v2_head._cells]
        self.assertIn("ACTIVER", head_titles)
        toggle = fields["crumb_separator_enabled"]
        toggle = toggle if hasattr(toggle, "setChecked") else toggle.findChild(v2._Toggle)
        toggle.setChecked(False)
        char_row = fields["crumb_sep_font_family"]
        self.assertFalse(char_row.isEnabled())                           # ligne du caractere grisee
        frame.deleteLater()

    def test_state_tables_are_linked_copies(self):
        groups = ("Cheminement : Set", "Cheminement : Apres set", "Cheminement : Apres focus")
        labels = [[s.label for s in v2.CATALOG[g]] for g in groups]
        self.assertEqual(labels[0], labels[1])
        self.assertEqual(labels[0], labels[2])
        self.assertTrue(all(s.general_toggle for s in v2.CATALOG[groups[1]]))     # toggle d'override
        self.assertFalse(any(s.general_toggle for s in v2.CATALOG[groups[0]]))
        self.assertIn("cheminement", v2._LINKED_TABLES)


class TabStripRadiusTest(unittest.TestCase):
    def test_radius_and_backgrounds_apply_to_every_tab(self):
        look = {"tabs_corner_radius": {"top_left": 9, "top_right": 9, "bottom_right": 3, "bottom_left": 3},
                "tabs_bg_color": "#112233", "tabs_active_bg_color": "#445566", "tabs_hover_bg_color": "#778899",
                "tabs_border_enabled": {"bottom": True}, "tabs_border": {"bottom": "#ffffff"},
                "tabs_border_thickness": 2, "colors": {}}
        settings_layout.set_tab_look(look)
        self.addCleanup(settings_layout.set_tab_look, {})
        strip = settings_layout._TabStrip(["A", "B", "C"])
        for i, button in enumerate(strip._btns):
            sheet = button.styleSheet()
            self.assertIn("border-top-left-radius: 9px", sheet, i)       # pas seulement le premier
            self.assertIn("border-bottom-right-radius: 3px", sheet, i)
        self.assertIn("#445566", strip._btns[0].styleSheet())            # tab en cours
        self.assertIn("#778899", strip._btns[1].styleSheet())            # survol
        strip.setCurrentIndex(2)
        self.assertIn("#445566", strip._btns[2].styleSheet())
        self.assertNotIn("#445566", strip._btns[0].styleSheet())


if __name__ == "__main__":
    unittest.main()
