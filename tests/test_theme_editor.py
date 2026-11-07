"""Éditeur fm_theme (theme_editor.py, fm_theme.bat) : onglet « Thème » réduit à l'aspect, magasin qui écrit
l'aspect dans le preset fm_theme et le reste dans les réglages de l'appli, gestion des presets (renommer =
alias retrouvé, dupliquer, nouveau, supprimer). Presets et réglages : copies temporaires (_isolate)."""
import _isolate  # noqa: F401
import os
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QPoint  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import settings_store  # noqa: E402
import settings_window_v2 as v2  # noqa: E402
import theme_editor  # noqa: E402
from fm_theme import presets as tp  # noqa: E402
from _window_cleanup import WindowTestCase, track_class  # noqa: E402

APP = QApplication.instance() or QApplication([])
track_class(v2.SettingsWindowV2)


def fresh_preset(name: str) -> str:
    """Preset de test (copie des défauts), nom unique."""
    return tp.new_preset(name, settings_store.DEFAULT_SETTINGS)


class TreeTest(unittest.TestCase):
    def test_theme_tab_holds_only_the_aspect(self):
        titles = [n.title for n in v2.theme_tree()]
        self.assertEqual(titles[0], "Général")
        self.assertIn("Couleurs", titles)
        self.assertIn("Toggles", titles)
        for app_only in ("Colonnes", "LUT", "Application", "ICONES"):
            self.assertNotIn(app_only, titles)
        # Barres de la fenetre : aspect general (2026-11-05).
        self.assertIn("Barre de navigation", titles)
        self.assertIn("Barre d'état", titles)
        self.assertEqual([s.key for s in v2.CATALOG["Thème : Général"]],
                         ["ui_scale", "window_radius", "window_border_enabled"])

    def test_general_window_no_longer_holds_the_aspect(self):
        """Étape 6 : fm_browser garde le fonctionnement et son aspect propre ; l'aspect générique est dans Thème."""
        titles = [n.title for n in v2.tab_tree("General")]
        for title in v2.THEME_SECTIONS:
            self.assertNotIn(title, titles)
        for kept in ("Colonnes", "Application", "ICONES"):
            self.assertIn(kept, titles)
        self.assertNotIn("ui_scale", [s.key for s in v2.CATALOG["Application"]])


class StoreTest(unittest.TestCase):
    def test_aspect_goes_to_the_preset_and_the_rest_to_the_app(self):
        name = fresh_preset("Magasin")
        store = theme_editor.ThemeStore(name)
        self.assertEqual(store.load()["button_radius"], settings_store.DEFAULT_SETTINGS["button_radius"])
        saved = store.save_changes({"button_radius": 9, "table_dims": {"x#0": {"width": 1}}})
        self.assertEqual(saved["button_radius"], 9)
        self.assertEqual(tp.to_settings(tp.load_preset(tp.find_preset(name)))["button_radius"], 9)
        self.assertNotIn("table_dims", tp.to_settings(tp.load_preset(tp.find_preset(name))))
        self.assertEqual(settings_store.load_settings()["table_dims"].get("x#0"), {"width": 1})
        tp.delete_preset(name)


class ManagementTest(unittest.TestCase):
    def test_rename_keeps_the_old_name_as_alias(self):
        name = fresh_preset("Ancien")
        new = tp.rename_preset(name, "Nouveau nom")
        self.assertEqual(tp.find_preset(name), tp.find_preset(new))
        self.assertEqual(tp.load_preset(tp.find_preset(name))["nom"], new)
        # Une appli liée à l'ancien nom garde son thème.
        self.assertEqual(settings_store.theme_in_use({"theme_preset": name}), name)
        tp.delete_preset(new)
        self.assertIsNone(tp.find_preset(name))

    def test_duplicate_and_unique_names(self):
        name = fresh_preset("Double")
        copy = tp.duplicate_preset(name)
        self.assertEqual(copy, f"{name} copie")
        self.assertEqual(tp.unique_name(name), f"{name} 2")
        self.assertEqual(tp.to_settings(tp.load_preset(tp.find_preset(copy))),
                         tp.to_settings(tp.load_preset(tp.find_preset(name))))
        for n in (name, copy):
            tp.delete_preset(n)


class EditorTest(WindowTestCase):
    def test_editor_switches_presets_and_deletes_in_two_clicks(self):
        first, second = fresh_preset("Premier"), fresh_preset("Second")
        editor = theme_editor.ThemeEditor(first)
        self.assertEqual(editor.window.module, "theme")
        self.assertEqual(editor.window.titlebar._title.text(), f"fm_theme : {first}")
        editor.switch_to(second)
        self.assertEqual(editor.name, second)
        bar = editor.window._tab_subbar.findChild(theme_editor.PresetBar)
        bar._delete()
        self.assertIsNotNone(tp.find_preset(second))            # 1er clic : confirmation demandée
        bar._delete()
        self.assertIsNone(tp.find_preset(second))
        self.assertNotEqual(editor.name, second)
        editor.window.hide()
        tp.delete_preset(first)


class PreviewTest(WindowTestCase):
    """Aperçu à gauche : il suit la section ouverte et se restyle en direct avec la fenêtre."""

    def setUp(self):
        self.name = fresh_preset("Aperçu")
        self.editor = theme_editor.ThemeEditor(self.name)
        theme_editor.ThemeEditor._follow_sections(self.editor, self.editor.window)

    def tearDown(self):
        self.editor.window.hide()
        tp.delete_preset(self.name)

    def node(self, title):
        return next(n for n in self.editor.window.stack.findChildren(v2._LazyNode)
                    if n.level == 1 and n.node.title == title)

    def test_follows_the_open_section(self):
        from fm_theme.preview import GALLERY
        self.assertEqual(self.editor.preview.section(), GALLERY)
        self.node("Toggles")._head.head.clicked.emit()
        self.assertEqual(self.editor.preview.section(), "Toggles")
        self.node("Tableaux")._head.head.clicked.emit()        # accordéon : Toggles se replie
        self.assertEqual(self.editor.preview.section(), "Tableaux")
        self.node("Tableaux")._head.head.clicked.emit()
        self.assertEqual(self.editor.preview.section(), GALLERY)

    def test_live_restyle_reaches_the_preview(self):
        from fm_theme.widgets import _Toggle
        self.editor.preview.show_section("Toggles")
        window = self.editor.window
        merged = dict(window.settings, toggle1_off_bg_width=57, toggle1_on_bg_width=57)
        window._apply_look(merged, {"toggle1_off_bg_width": 57, "toggle1_on_bg_width": 57})
        self.assertIn(57, {t._outer_w for t in self.editor.preview.findChildren(_Toggle)})   # toggles de style 1


class SideDetailTest(WindowTestCase):
    """Titres fixes à gauche, paramètres de la section ouverte dans un volet à droite, sous son titre
    (demande de l'utilisateur, 2026-11-02) : ouvrir un titre ne pousse jamais les autres."""

    def setUp(self):
        self.name = fresh_preset("Volet")
        self.editor = theme_editor.ThemeEditor(self.name)
        self.window = self.editor.window
        self.window.resize(1500, 940)
        end = time.monotonic() + 5
        while self.editor.detail is None and time.monotonic() < end:       # _follow_sections : minuterie
            QApplication.processEvents()
        self.assertIsNotNone(self.editor.detail)
        settled = time.monotonic() + 0.3                                   # mise en page de la fenêtre agrandie
        while time.monotonic() < settled:
            QApplication.processEvents()

    def tearDown(self):
        self.window.hide()
        tp.delete_preset(self.name)

    def nodes(self):
        return [n for n in self.window.stack.findChildren(v2._LazyNode) if n.level == 1]

    def node(self, title):
        return next(n for n in self.nodes() if n.node.title == title)

    def tops(self):
        return {n.node.title: n.mapTo(self.window, QPoint(0, 0)).y() for n in self.nodes()}

    def test_titles_stay_in_place_and_the_parameters_open_beside_them(self):
        before = self.tops()
        section = self.node("Tableaux")
        section._head.head.clicked.emit()
        QApplication.processEvents()
        self.assertEqual(self.tops(), before)                              # aucun titre ne bouge
        pane, head = self.editor.detail.pane, section._head
        self.assertTrue(pane.isVisible() and head._body.isVisible())
        self.assertTrue(pane.isAncestorOf(head._body))                     # le corps est dans le volet
        self.assertEqual(pane.mapTo(self.window, QPoint(0, 0)).y(),        # juste sous le titre ouvert
                         head.mapTo(self.window, QPoint(0, head.height())).y())
        for node in self.nodes():                                          # à droite de tous les titres
            label = node._head._name_label
            self.assertGreaterEqual(pane.mapTo(self.window, QPoint(0, 0)).x(),
                                    label.mapTo(self.window, QPoint(label.width(), 0)).x())

    def test_accordion_and_close_follow_the_pane(self):
        tables, toggles = self.node("Tableaux"), self.node("Toggles")
        tables._head.head.clicked.emit()
        toggles._head.head.clicked.emit()                                  # accordéon : Tableaux se replie
        QApplication.processEvents()
        self.assertFalse(tables._head._body.isVisible())
        self.assertTrue(toggles._head._body.isVisible())
        toggles._head.head.clicked.emit()
        QApplication.processEvents()
        self.assertFalse(self.editor.detail.pane.isVisible())

    def test_opening_a_section_shows_its_subsections_folded(self):
        """Ouvrir une section montre ses sous-sections REPLIÉES : un tableau ne se monte qu'en dépliant la sienne
        (demande de l'utilisateur, 2026-11-03)."""
        section = self.node("TITRES")
        section._head.head.clicked.emit()
        for _ in range(20):
            QApplication.processEvents()
            time.sleep(0.01)
        children = section._head._body.findChildren(v2._LazyNode)
        self.assertTrue(children)
        self.assertTrue(all(n.is_collapsed() for n in children))

    def test_children_keep_their_title_path(self):
        """Une sous-section du volet retrouve toujours sa section (clé d'ordre des titres, parent des boîtes)."""
        section = self.node("TITRES")
        section.set_collapsed(False)
        child = next(n for n in section._head._body.findChildren(v2._LazyNode))
        self.assertIsNot(child.parentWidget(), section)
        self.assertEqual(child._stack_key(), f"{child._values.name}|TITRES/{child.node.title}")
        self.assertIs(child._head._parent_title(), section._head)


class TableParentTest(unittest.TestCase):
    """Un tableau naît SOUS son parent, lignes et cellules créées vides sous le leur : rattacher plus tard un
    sous-arbre plein à un parent qui porte une feuille de style en refait le style, niveau par niveau (~30 %
    du temps de montage d'une sous-section des réglages : `docs/agents/pieges-generaux.md`)."""

    def test_cells_table_is_born_under_its_parent(self):
        from PySide6.QtWidgets import QLabel, QWidget
        from fm_theme import cells as tcells
        holder = QWidget()
        frame, _head, cells = tcells.build_cells_table([("A", 100), ("B", 0)], [[QLabel("x"), QLabel("y")]],
                                                       parent=holder)
        self.assertIs(frame.parentWidget(), holder)
        cell = cells[0][0]
        row = cell.parentWidget()
        self.assertIs(row.parentWidget(), frame)
        self.assertIs(cell.content().parentWidget(), cell)
        self.assertIsNone(tcells.build_cells_table([("A", 100)], [[QLabel("x")]])[0].parentWidget())  # comme avant

    def test_group_is_built_under_the_body_that_will_hold_it(self):
        from PySide6.QtWidgets import QWidget
        settings = {**settings_store.DEFAULT_SETTINGS}
        values = v2.ScopeValues(settings, "General", None)
        for group in ("Couleurs", "toggle1 : OFF"):           # un tableau, puis deux
            holder = QWidget()
            built = v2.build_group(group, values, {}, {}, {}, [], parent=holder)
            self.assertIs(built.parentWidget(), holder, group)


class EditorVariantTest(WindowTestCase):
    def test_editing_a_variant_writes_there_and_says_which_one(self):
        name = fresh_preset("Variantes")
        editor = theme_editor.ThemeEditor(name)
        sent = []
        editor.server = type("S", (), {"broadcast": lambda _s, preset, values, variants: sent.append(variants)})()
        compact = tp.add_variant(name, "bouton", "compact")
        editor.edit_variant("bouton", compact, save=False)
        self.assertFalse(editor.store.is_default("bouton"))
        corners = {"top_left": 13, "top_right": 13, "bottom_right": 13, "bottom_left": 13}
        editor.store.save_changes({"button_radius": 13, "button_corner_radius": corners})
        preset = tp.load_preset(tp.find_preset(name))
        self.assertEqual(preset["types"]["bouton"]["variantes"][compact]["radius"], 13)
        self.assertNotEqual(tp.to_settings(preset)["button_radius"], 13)
        # Retour à « standard » puis à la variante : ses valeurs reviennent dans les champs, SUR PLACE.
        section = next(n for n in editor.window.stack.findChildren(v2._LazyNode) if n.node.title == "Bouton")
        section._head.head.clicked.emit()
        editor.edit_variant("bouton", "standard", save=False)
        rebuilt = []
        section.rebuild_group = lambda: rebuilt.append(1)
        editor.edit_variant("bouton", compact, save=False)
        self.assertEqual(editor.window.wired_values()["button_corner_radius"], corners)
        self.assertEqual(rebuilt, [])                               # rien de reconstruit
        self.assertFalse(editor.window._dirty)                      # valeurs de référence, pas une modification
        editor.window.live_changed_keys = {"button_radius"}
        editor._broadcast({"button_radius": 13})
        self.assertEqual(sent, [{"bouton": compact}])               # la variante éditée voyage : l'appli filtre
        editor.window.hide()
        tp.delete_preset(name)


class AppVariantTest(unittest.TestCase):
    """Étape 7 : fm_browser choisit la variante qu'il utilise (`theme_default_variants`)."""

    def setUp(self):
        self.saved = settings_store.load_settings()
        self.name = fresh_preset("Appli")
        self.compact = tp.add_variant(self.name, "bouton", "compact")
        tp.update_preset(self.name, {"button_radius": 21}, editing={"bouton": self.compact})
        settings = settings_store.load_settings()
        settings["theme_preset"], settings["active_preset"] = self.name, ""
        settings_store.save_settings(settings)

    def tearDown(self):
        settings_store.save_settings(self.saved)
        tp.delete_preset(self.name)

    def test_the_app_uses_its_variant_and_writes_into_it(self):
        self.assertNotEqual(settings_store.load_settings()["button_radius"], 21)     # défaut du preset
        settings = settings_store.set_app_variant("bouton", self.compact)
        self.assertEqual(settings["button_radius"], 21)                             # la variante choisie
        self.assertEqual(settings_store.app_variant(settings, "bouton"), self.compact)
        settings["button_radius"] = 22
        settings_store.update_theme_preset(settings)                                # écrit dans SA variante
        preset = tp.load_preset(tp.find_preset(self.name))
        self.assertEqual(preset["types"]["bouton"]["variantes"][self.compact]["radius"], 22)
        self.assertNotEqual(preset["types"]["bouton"]["variantes"]["standard"].get("radius"), 22)

    def test_live_values_of_another_variant_are_ignored(self):
        from main_window.settings_link import SettingsLinkMixin
        import ui_state
        applied = []
        host = type("Host", (), {"_apply_settings": lambda _s, s, keys=None: applied.append(set(keys)),
                                 "_theme_to_settings_windows": lambda _s, values: None})()
        ui_state.APPLIED_SETTINGS = settings_store.load_settings()                  # utilise « standard »
        SettingsLinkMixin._on_theme_live(host, self.name, {"button_radius": 30, "window_radius": 4},
                                         {"bouton": self.compact})
        self.assertEqual(applied, [{"window_radius"}])                               # le bouton : pas sa variante
        SettingsLinkMixin._on_theme_live(host, self.name, {"button_radius": 30}, {"bouton": "standard"})
        self.assertEqual(applied[-1], {"button_radius"})


if __name__ == "__main__":
    unittest.main()
