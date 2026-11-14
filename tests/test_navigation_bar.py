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
                                                   win.btn_collapse)}
        self.assertEqual(len(sizes), 1)                                 # tous les boutons de la meme taille
        self.assertEqual(bar.btn_min.width(), bar.btn_min.height())     # reduire / agrandir / fermer : carres
        self.assertEqual(win.scroll.geometry().top(), bar.geometry().bottom() + 1)   # colonnes jusqu'a la barre

    def test_bar_buttons_have_their_own_settings_icons(self):
        rows = {s.params["ui_key"] for s in v2.CATALOG["Barre de navigation : Icones (appli)"] if s.kind == "ui_icon"}
        self.assertTrue({"navbar_browse", "navbar_presets", "settings_gear"} <= rows)
        button = self.win.btn_browse
        self.assertEqual(button._kind, "browse")
        self.assertIsNone(button._custom_icon_pixmap(button.rect()))     # glyphe peint par defaut

    def test_icon_rows_are_split_cells_with_a_preview_cell(self):
        spec = next(s for s in v2.CATALOG["Barre de navigation : Icones (appli)"] if s.kind == "ui_icon" and
                    s.params["ui_key"] == "navbar_browse")
        holder = v2._f_ui_icon(spec, None, {})
        from settings_cells import split_of
        cell = split_of(holder)
        self.assertIsNotNone(cell)
        captions = cell.capTexts()
        self.assertIn("Icône".upper(), [c.upper() for c in captions])
        # (legende, apercu, boutons Changer / Reinitialiser, etat) : un seul conteneur de boutons par etat
        caption, avatar, box, _state = holder._ui_icon_field.states()[0]
        from PySide6.QtWidgets import QPushButton
        buttons = box.findChildren(QPushButton)
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
            for _attempt in range(30):                   # colonnes remplies en differe : 3 s au plus
                for i in range(column.list.count()):
                    item = column.list.item(i)
                    if Path(item.data(ROLE_PATH)).name == name:
                        column.list.setCurrentItem(item)
                        settle(0.3)
                        return
                settle(0.1)
            self.fail(name)
        select(self.win.columns[0], "3d")
        select(self.win.columns[1], "projA")
        bar = self.win.titlebar
        self.assertEqual(bar._crumb_names[:2], ["3d", "projA"])
        self.assertGreaterEqual(bar.crumbs.geometry().top(), bar.title_label.geometry().bottom())   # sous le titre
        first = bar._crumb_layout.itemAt(0).widget()                  # « Espacement a gauche » (10 par defaut)
        # Reperes reconstruits (leur nombre change) : Qt les affiche au tour de boucle suivant (cachés jusque-là, donc
        # pas encore places) — on attend qu'ils le soient (2026-11-12 : verifie trop tot, puce encore en (0, 0)).
        for _attempt in range(30):
            if not first.isHidden():
                break
            settle(0.1)
        self.assertEqual(bar.crumbs.x() + first.x(),
                         app_style.scaled(int((__import__("ui_state").APPLIED_SETTINGS or {})      # comme l'appli
                                              .get("crumb_left_spacing", 10)), 0))
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
            for _attempt in range(30):                   # colonnes remplies en differe : 3 s au plus
                for i in range(column.list.count()):
                    item = column.list.item(i)
                    if Path(item.data(ROLE_PATH)).name == name:
                        column.list.setCurrentItem(item)
                        settle(0.3)
                        return
                settle(0.1)
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

    def test_crumb_overlay_backgrounds_default_to_the_common_one(self):
        for key in ("crumb_active_bg_color", "crumb_after_active_bg_color", "crumb_hover_bg_color"):
            self.assertEqual(settings_store.DEFAULT_SETTINGS[key], "#00000000")     # transparent = fond commun

    def test_every_linked_toggle_of_the_catalog_is_saved(self):
        # « lier les 4 » (cotes, coins, padding) : sa cle `<cle>_linked` doit exister dans les reglages, sinon
        # load_settings l'ignore et le toggle ne s'enregistre pas (signale : Tabs > Border radius).
        missing = [(group, spec.key) for group, specs in v2.CATALOG.items() for spec in specs
                   if spec.kind in ("corners", "padding", "sides_thick", "shadow")
                   and f"{spec.key}_linked" not in settings_store.DEFAULT_SETTINGS]
        self.assertEqual(missing, [])
        saved = settings_store.load_settings()
        self.assertIn("tabs_corner_radius_linked", saved)

    def test_chip_colors_and_fonts_follow_the_settings(self):
        """Refonte du 2026-11-08 : fond commun, de l'onglet actif, d'apres l'onglet actif, du survol ; police
        commune ou d'apres l'onglet actif ; ces lignes SEULES dans les reglages."""
        import browser_core
        base = settings_store.load_settings()
        browser_core.apply_all_settings({**base, "crumb_bg_color": "#224466", "crumb_active_bg_color": "#00ff00",
                                         "crumb_after_active_bg_color": "#664422", "crumb_hover_bg_color": "#ff00ff",
                                         "crumb_spacing": 9, "crumb_font_size": 10,
                                         "crumb_after_active_font_size": 20})
        try:
            look = pb._crumb_look()
            self.assertEqual(look["spacing"], 9)
            chips = {kind: pb._CrumbChip("abc", kind, look) for kind in ("set", "after", "set!", "after_focus")}
            self.assertEqual(chips["set"]._bg.name(), "#224466")
            self.assertEqual(chips["after"]._bg.name(), "#224466")               # plus d'etat « apres set »
            self.assertEqual(chips["set!"]._bg.name(), "#00ff00")                # onglet actif
            self.assertEqual(chips["after_focus"]._bg.name(), "#664422")         # apres l'onglet actif
            self.assertGreater(chips["after_focus"].height(), chips["set"].height())   # sa police (20 px)
            self.assertEqual(look["hover_bg"].name(), "#ff00ff")
            self.assertEqual(chips["set"].toolTip(), "")                         # pas d'info-bulle au survol
        finally:
            browser_core.apply_all_settings(base)
        keys = [s.key for s in v2.CATALOG["Barre de navigation : Cheminement"]]
        self.assertEqual(keys, ["crumb_left_spacing", "crumb_spacing", "crumb_cut_border_active",
                                "crumb_cut_border_others", "crumb_bg_color", "crumb_border_enabled",
                                "crumb_corner_radius", "crumb_active_bg_color", "crumb_hover_bg_color",
                                "crumb_after_active_bg_color", "crumb_font_family", "crumb_after_active_font_family"])
        app = next(n for n in v2.tab_tree("General") if n.title == "Barre de navigation")
        crumbs = next(n for n in app.children if n.title == "Cheminement")
        self.assertEqual(crumbs.children, ())                                    # plus de Set / Apres set / focus
        old = ("crumb_set_bg", "crumb_after_bg", "crumb_afterfocus", "crumb_focus", "crumb_padding", "crumb_margin",
               "crumb_shadow", "crumb_hover_border", "crumb_sep", "crumb_separator", "crumb_after_ovr")
        self.assertFalse([k for k in settings_store.DEFAULT_SETTINGS if k.startswith(old)])
        self.assertNotIn("cheminement", v2._LINKED_TABLES)
        self.assertEqual(pb._crumb_state("after_focus"), ("after_focus", False))
        self.assertEqual(pb._crumb_state("set!"), ("set", True))

    def test_no_separator_between_crumbs(self):
        """Separateur retire (demande de l'utilisateur, 2026-11-07) : rien entre les onglets de la barre."""
        bar = self.win.titlebar
        bar.set_crumbs([("set", "a", lambda: None), ("set!", "b", lambda: None)], force=True)
        self.assertEqual(bar.crumbs.findChildren(pb.QLabel), [])


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
