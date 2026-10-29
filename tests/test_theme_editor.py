"""Éditeur fm_theme (theme_editor.py, fm_theme.bat) : onglet « Thème » réduit à l'aspect, magasin qui écrit
l'aspect dans le preset fm_theme et le reste dans les réglages de l'appli, gestion des presets (renommer =
alias retrouvé, dupliquer, nouveau, supprimer). Presets et réglages : copies temporaires (_isolate)."""
import _isolate  # noqa: F401
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
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
        for app_only in ("Colonnes", "Barre de navigation", "LUT", "Application", "ICONES"):
            self.assertNotIn(app_only, titles)
        self.assertEqual([s.key for s in v2.CATALOG["Thème : Général"]], ["ui_scale", "window_radius"])

    def test_general_window_no_longer_holds_the_aspect(self):
        """Étape 6 : fm_browser garde le fonctionnement et son aspect propre ; l'aspect générique est dans Thème."""
        titles = [n.title for n in v2.tab_tree("General")]
        for title in v2.THEME_SECTIONS:
            self.assertNotIn(title, titles)
        for kept in ("Colonnes", "Barre de navigation", "Application", "ICONES"):
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
        merged = dict(window.settings, toggle1_outer_width=57)
        window._apply_look(merged, {"toggle1_outer_width": 57})
        self.assertIn(57, {t._outer_w for t in self.editor.preview.findChildren(_Toggle)})   # toggles de style 1


class EditorVariantTest(WindowTestCase):
    def test_editing_a_variant_writes_there_and_is_not_broadcast(self):
        name = fresh_preset("Variantes")
        editor = theme_editor.ThemeEditor(name)
        sent = []
        editor.server = type("S", (), {"broadcast": lambda _s, preset, values: sent.append(values)})()
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
        self.assertEqual(sent, [])                                  # les applis n'utilisent pas cette variante
        editor.window.hide()
        tp.delete_preset(name)


if __name__ == "__main__":
    unittest.main()
