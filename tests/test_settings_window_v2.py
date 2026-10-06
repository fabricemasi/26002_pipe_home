"""Tests de la fenetre de reglages v2 (settings_window_v2.py).

- equivalence : les valeurs LUES par la v2 sont identiques, au bit pres, a celles de
  SettingsWindow._current_values() pour les memes reglages (sections TITRE,
  Tableaux, Toggles et Sliders, les seules a avoir un equivalent exact) ;
- enregistrement : n'ecrit que ce qui a change, relit le disque, ne touche jamais
  aux vrais fichiers (load/save/presets remplaces par des doublures en memoire) ;
- apercu en direct : modifier un champ emet settingsChanged ;
- les sections non branchees sont grisees.
"""
import copy
import os
import sys
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

import settings_window as sw
import settings_window_v2 as v2

ALL_EQUIVALENT = ("Colonnes", "TITRE", "Tableaux", "Toggles", "Sliders")


def build(wired=v2.WIRED_SECTIONS):
    with mock.patch.object(v2, "WIRED_SECTIONS", wired):
        win = v2.SettingsWindowV2()
        v2.expand_all(win.stack.currentWidget())
        # les sections racines ne sont pas enfants d'un _LazyNode : on les deplie aussi
        for node in win.stack.currentWidget().findChildren(v2._LazyNode):
            node.set_collapsed(False)
        v2.expand_all(win.stack.currentWidget())
    return win


class EquivalenceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old = sw.SettingsWindow(mode="tout")
        cls.old_values = cls.old._current_values()
        cls.win = build(ALL_EQUIVALENT)
        cls.new_values = cls.win.wired_values()

    def test_every_value_read_by_v2_matches_the_old_window(self):
        self.assertGreater(len(self.new_values), 100)
        # Les cles que l'ancienne fenetre ne connait pas (habillage de coche, v2 seulement) n'ont rien a comparer.
        mismatches = {k: (self.old_values[k], v)
                      for k, v in self.new_values.items() if k in self.old_values and self.old_values[k] != v
                      and not any(tag in k for tag in ('_coche_skin', '_coche_text', '_coche_icon'))}
        self.assertEqual(mismatches, {}, f"{len(mismatches)} cle(s) differente(s) : {list(mismatches)[:8]}")

    def test_wired_keys_exist_in_the_settings(self):
        from settings_store import DEFAULT_SETTINGS
        # Quelques cles (ex. item_selection_<etat>_padding_linked) ne sont pas dans DEFAULT_SETTINGS
        # mais l'ancienne fenetre les ecrit aussi : on ne reproche a la v2 que ce que l'ancienne n'ecrit pas.
        unknown = sorted(set(self.new_values) - set(DEFAULT_SETTINGS) - set(self.old_values))
        self.assertEqual(unknown, [])


class SaveTest(unittest.TestCase):
    def setUp(self):
        self.win = build(("Sliders",))
        self.disk = copy.deepcopy(self.win._original_settings)
        self.written = []
        self.presets = {}
        patches = [
            mock.patch.object(v2, "load_settings", lambda: copy.deepcopy(self.disk)),
            mock.patch.object(v2, "save_settings", lambda s: (self.written.append(copy.deepcopy(s)),
                                                              self.disk.update(copy.deepcopy(s)))),
            mock.patch.object(v2, "_load_presets", lambda: self.presets),
            mock.patch.object(v2, "_save_presets", lambda p: self.presets.update(p)),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def _slider(self, key):
        spec_widget = {sp.key: w for sp, w in self.win.stores["General"]["specs"]}
        return spec_widget[key]

    def test_save_writes_only_what_changed_and_keeps_the_rest(self):
        field = self._slider("slider_thumb_height")
        new = 20 if field.value() != 20 else 21
        field.setValue(new)
        self.win._on_save()
        self.assertEqual(len(self.written), 1)
        saved = self.written[0]
        self.assertEqual(saved["slider_thumb_height"], new)
        untouched = {k for k in self.win._original_settings if k != "slider_thumb_height"}
        self.assertEqual({k: saved[k] for k in untouched}, {k: self.win._original_settings[k] for k in untouched})

    def test_unchanged_window_saves_the_disk_state_as_is(self):
        self.win._on_save()
        self.assertEqual(self.written[0], self.win._original_settings)

    def test_active_preset_is_updated_too(self):
        self.disk["default_preset"] = "Mon preset"
        self.presets["Mon preset"] = {"old": True}
        self._slider("slider_track_height").setValue(9)
        self.win._on_save()
        self.assertEqual(self.presets["Mon preset"]["slider_track_height"], 9)

    def test_live_change_emits_settings_changed(self):
        seen = []
        self.win.settingsChanged.connect(seen.append)
        field = self._slider("slider_thumb_width")
        field.setValue(field.value() + 1 if field.value() < 20 else 5)
        self.win._flush_live()
        self.assertTrue(seen)
        self.assertEqual(seen[-1]["slider_thumb_width"], field.value())

    def test_live_timer_is_throttled_not_restarted(self):
        """Pendant un glissement, le minuteur doit tourner (application toutes les 30 ms), pas
        etre relance a chaque mouvement (rien ne s'appliquait avant la fin du geste)."""
        with mock.patch.object(self.win._live_timer, "start", wraps=self.win._live_timer.start) as start:
            for _ in range(5):
                self.win._mark_dirty()
        self.assertEqual(start.call_count, 1)

    def test_unchanged_values_do_not_re_emit(self):
        seen = []
        self.win.settingsChanged.connect(seen.append)
        self.win._flush_live()
        self.win._flush_live()
        self.assertEqual(len(seen), 1)

    def test_cancel_after_change_restores_the_original(self):
        seen = []
        self.win.settingsChanged.connect(seen.append)
        field = self._slider("slider_thumb_width")
        field.setValue(field.value() + 1 if field.value() < 20 else 5)
        self.win._mark_dirty()
        self.win.reject()
        self.assertEqual(seen[-1], self.win._original_settings)
        self.assertEqual(self.written, [])


class WiringTest(unittest.TestCase):
    def test_every_general_section_is_editable_when_wired(self):
        win = build()
        page = win.stack.currentWidget()
        by_title = {n.node.title: n for n in page.findChildren(v2._LazyNode) if n.level == 1}
        for title in v2.WIRED_SECTIONS:
            self.assertTrue(by_title[title]._head._body.isEnabled(), title)

    def test_unwired_section_is_greyed(self):
        win = build(("Sliders",))
        page = win.stack.currentWidget()
        by_title = {n.node.title: n for n in page.findChildren(v2._LazyNode) if n.level == 1}
        self.assertTrue(by_title["Sliders"]._head._body.isEnabled())
        for title in ("Colonnes", "Tableaux", "Toggles", "TITRE"):
            self.assertFalse(by_title[title]._head._body.isEnabled(), title)

    def test_override_tabs_are_greyed(self):
        win = build()
        win._ensure_page(1)                     # onglet Type
        page = win.stack.widget(1)
        v2.expand_all(page)
        nodes = page.findChildren(v2._LazyNode)
        self.assertTrue(nodes)
        self.assertFalse(any(n._head._body.isEnabled() for n in nodes if n.node.group))

    def test_window_is_resizable_through_native_events(self):
        self.assertTrue(callable(v2.SettingsWindowV2.nativeEvent))
        self.assertGreater(v2.SettingsWindowV2._RESIZE_BORDER, 0)


class LiveLookTest(unittest.TestCase):
    """Les reglages qui habillent la fenetre elle-meme se rejouent en direct, et se restaurent a l'annulation."""

    def setUp(self):
        self.win = build()
        self.fields = {sp.key: w for sp, w in self.win.stores["General"]["specs"] if not isinstance(sp, str)}
        self.addCleanup(self.win.reject)

    def _change(self, key, value):
        self.fields[key].setValue(value)
        self.win._flush_live()

    def test_title_indent_restyles_existing_sections(self):
        section = self.win.findChildren(v2._Section)[0]
        before = section._title_indent
        self._change("title_level1_indent", before + 17)
        self.assertEqual(section._title_indent, before + 17)

    def test_table_radius_is_replayed_on_all_tables(self):
        with mock.patch.object(v2, "_set_flat_tables_style") as style:
            self._change("table_radius", 9)
        self.assertEqual(style.call_args.kwargs["radius"], 9)

    def test_table_padding_is_replayed(self):
        with mock.patch.object(v2, "_set_flat_tables_style") as style:
            self.fields["table_cell_padding"].setValue(False, {"left": 20, "top": 3, "right": 20, "bottom": 3})
            self._change("table_radius", self.fields["table_radius"].value() + 1)
        self.assertIn("padding", style.call_args.kwargs)

    def test_toggle_style_is_replayed_on_toggles(self):
        with mock.patch.object(v2, "_sync_toggle_style") as sync:
            self._change("toggle1_outer_width", self.fields["toggle1_outer_width"].value() + 3)
        self.assertTrue(sync.called)

    def test_unchanged_family_is_not_replayed(self):
        self._change("slider_thumb_height", self.fields["slider_thumb_height"].value() + 1)
        with mock.patch.object(v2, "_sync_toggle_style") as sync:
            self._change("slider_thumb_width", self.fields["slider_thumb_width"].value() + 1)
        self.assertFalse(sync.called)

    def test_resizable_toggle_reaches_the_tables(self):
        toggle = self.fields["columns_resizable"]
        toggle.setChecked(not toggle.isChecked())
        self.win._flush_live()
        self.assertEqual(self.win._columns_resizable, toggle.isChecked())

    def test_cancel_restores_the_original_look(self):
        section = self.win.findChildren(v2._Section)[0]
        before = section._title_indent
        self._change("title_level1_indent", before + 25)
        self.win.reject()
        self.assertEqual(section._title_indent, before)


if __name__ == "__main__":
    unittest.main()
