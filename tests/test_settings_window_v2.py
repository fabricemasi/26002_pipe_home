"""Tests de la fenetre de reglages v2 (settings_window_v2.py).

- equivalence : les valeurs LUES par la v2 sont identiques, au bit pres, a celles de
  SettingsWindow._current_values() pour les memes reglages (sections TITRE,
  Tableaux, Toggles et Sliders, les seules a avoir un equivalent exact) ;
- enregistrement : n'ecrit que ce qui a change, relit le disque, ne touche jamais
  aux vrais fichiers (load/save/presets remplaces par des doublures en memoire) ;
- apercu en direct : modifier un champ emet settingsChanged ;
- les sections non branchees sont grisees.
"""
import os as _os, sys as _sys  # jamais les vrais reglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import copy
import os
import sys
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication, QWidget

app = QApplication.instance() or QApplication([])

import settings_window as sw
import settings_store
import settings_window_v2 as v2

ALL_EQUIVALENT = ("Colonnes", "TITRES", "Tableaux", "Toggles", "Sliders")


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
            # update_active_preset (appele a l'enregistrement) lit / ecrit les presets par settings_store : sans
            # ces doublures, le preset ACTIF de l'utilisateur (« fab ») recevait les valeurs du test (signale).
            mock.patch.object(settings_store, "_load_presets", lambda: self.presets),
            mock.patch.object(settings_store, "_save_presets", lambda p: self.presets.update(p)),
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
        self.disk["default_preset"] = self.disk["active_preset"] = "Mon preset"
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
        for title in ("Colonnes", "Tableaux", "Toggles", "TITRES"):
            self.assertFalse(by_title[title]._head._body.isEnabled(), title)

    def _override_tab(self, label):
        win = build()
        index = [lab for lab, _t in v2.SCOPES].index(label)
        win._ensure_page(index)
        page = win.stack.widget(index)
        for _ in range(4):                      # sections racines puis sous-sections
            for node in page.findChildren(v2._LazyNode):
                node.set_collapsed(False)
        return win, page, win.stores[label]

    def test_override_tabs_are_editable(self):
        _win, page, _store = self._override_tab("Type")
        nodes = page.findChildren(v2._LazyNode)
        self.assertTrue(nodes)
        self.assertTrue(all(n._head._body.isEnabled() for n in nodes if n.node.group))

    def test_override_tab_writes_into_the_override_dicts_only(self):
        win, _page, store = self._override_tab("Projets")
        field = {sp.key: w for sp, w in store["specs"]}["column_bg_color"]
        store["toggles"]["column_bg_color"].setChecked(True)
        field._apply_custom_live("#123456")
        seen = []
        win.settingsChanged.connect(seen.append)
        # L'apercu en direct attend la fin de la bascule du toggle (fluidite) : ce test verifie quoi, pas quand.
        with mock.patch.object(v2, "toggle_animation_left_ms", lambda: 0):
            win._flush_live()
        merged = seen[-1]
        self.assertEqual(merged["column_overrides_by_title"]["Projets"]["column_bg_color"], "#123456")
        self.assertTrue(merged["column_override_enabled_by_title"]["Projets"]["column_bg_color"])
        self.assertEqual(merged["column_bg_color"], win.settings["column_bg_color"])     # General intact
        for title, enabled in (win.settings.get("column_override_enabled_by_title") or {}).items():
            if title != "Projets":                                                       # autres onglets intacts
                self.assertEqual(merged["column_override_enabled_by_title"][title], enabled, title)

    def test_override_toggle_alone_is_a_live_change(self):
        win, _page, store = self._override_tab("Type")
        self.assertFalse(win._dirty)
        toggle = store["toggles"]["item_row_height"]
        toggle.setChecked(not toggle.isChecked())
        self.assertTrue(win._dirty)

    def test_window_is_resizable_through_native_events(self):
        self.assertTrue(callable(v2.SettingsWindowV2.nativeEvent))
        self.assertGreater(v2.SettingsWindowV2._RESIZE_BORDER, 0)


class LiveLookTest(unittest.TestCase):
    """Les reglages qui habillent la fenetre elle-meme se rejouent en direct, et se restaurent a l'annulation."""

    def setUp(self):
        # Valeurs par defaut, jamais les reglages reels de l'utilisateur (fonds, bordures... enregistres).
        from settings_store import DEFAULT_SETTINGS
        patch = mock.patch.object(v2, "load_settings", lambda: copy.deepcopy(DEFAULT_SETTINGS))
        patch.start()
        self.addCleanup(patch.stop)
        # L'apercu en direct attend la fin d'une bascule de toggle (fluidite, _flush_live) : ces tests
        # verifient CE qui est rejoue, pas quand -> pas d'attente ici.
        wait = mock.patch.object(v2, "toggle_animation_left_ms", lambda: 0)
        wait.start()
        self.addCleanup(wait.stop)
        self.win = build()
        self.fields = {sp.key: w for sp, w in self.win.stores["General"]["specs"] if not isinstance(sp, str)}
        self.addCleanup(self.win.reject)

    def _change(self, key, value):
        self.fields[key].setValue(value)
        self.win._flush_live()

    def test_no_indent_section_in_v2(self):
        """Titre > Retraits supprime (double emploi avec les paddings) : les retraits enregistres
        (cles v1) ne deplacent plus rien, une boite sans margin commence au contenu de son parent."""
        self.assertNotIn("Titre : Retraits", v2.CATALOG)
        self.assertFalse([k for k in self.fields if k.endswith("_indent")])
        for title in self._titles(2) + self._titles(3):
            parent = title._parent_title()
            self.assertEqual(title._box_abs, parent.content_abs_x() + title._box_style["margin"][0])

    def test_space_before_first_and_after_last_title(self):
        """Paragraphes > Padding (titre) > Avant / Apres : padding avant le 1er et apres le dernier titre d'une pile de niveau N,
        DANS la boite (sous le fond), pas une margin."""
        self.fields["title_level2_text_padding"]._v2_parts["before"].setValue(11)   # Padding (titre) > Avant
        self.fields["title_level2_text_padding"]._v2_parts["after"].setValue(13)    # Padding (titre) > Apres
        self.win._flush_live()
        section = next(t for t in self._titles(1) if t._title_text == "TITRES")
        kids = [t for t in self._titles(2) if t._parent_title() is section]
        self.assertEqual(kids[0].layout().contentsMargins().top() - kids[0]._box_style["margin"][1], 11 +
                         kids[0]._box_thickness(kids[0]._box_style)["top"] + kids[0]._box_style["padding"][1])
        self.assertEqual(kids[0]._box_spaces, (11, 0))
        for middle in kids[1:-1]:                    # ni premier ni dernier : aucun espacement
            self.assertEqual(middle._box_spaces, (0, 0))
        self.assertEqual(kids[-1]._box_spaces, (0, 13))
        rect = kids[0]._box_rect()                  # le fond couvre l'espacement (padding, pas margin)
        self.assertEqual(rect.top(), kids[0]._box_style["margin"][1])
        self.assertEqual(kids[-1]._box_rect().bottom(), kids[-1].height() - 1 - kids[-1]._box_style["margin"][3])

    def _titles(self, level):
        cls = v2._Section if level == 1 else v2._SubSection
        return [t for t in self.win.findChildren(cls) if t._title_level() == level]

    def test_text_padding_moves_the_title_text(self):
        """Titre > Espacements : padding du texte seul, par niveau, replie ou deplie."""
        for level in (1, 2, 3):
            title = self._titles(level)[0]
            for collapsed in (False, True):
                title.set_collapsed(collapsed)
                self.fields[f"title_level{level}_text_padding"].setValue(
                    False, {"left": 5 + level, "top": 7, "right": 2, "bottom": 9 + level})
                self.win._flush_live()
                m = title._head_layout.contentsMargins()
                self.assertEqual((m.left(), m.top(), m.right(), m.bottom()), (5 + level, 7, 2, 9 + level))
                self.assertEqual(title._body_offset, 5 + level + title._chevron_room())

    def test_no_gap_spacers_between_titles(self):
        self.assertEqual([w for w in self.win.findChildren(QWidget) if hasattr(w, "_gap_spacer")], [])

    def test_background_padding_border_and_child_position(self):
        """Titre > Fond : padding + bordure decalent le contenu du paragraphe ; les titres enfants
        commencent au debut de ce contenu."""
        fields = self.fields
        fields["title_level1_bg_padding"].setValue(False, {"left": 4, "top": 3, "right": 2, "bottom": 5})
        fields["title_level1_bg_enabled"]._v2_parts["enabled"].setChecked(True)
        self.win._flush_live()
        section = next(t for t in self._titles(1) if t._title_text == "TITRES")
        m = section.layout().contentsMargins()
        self.assertEqual((m.left() - section._box_off, m.top(), m.right(), m.bottom()), (4, 3, 2, 5))
        self.assertIsNotNone(section._box_style["fill"])
        child = next(t for t in self._titles(2) if t._parent_title() is section)
        self.assertEqual(child._box_abs, section.content_abs_x())
        self.assertEqual(child._box_off, 0)

    def test_background_margin_is_outside_the_box(self):
        """Titre > Fond > Margin : espace HORS de la boite (decale le bord, s'ajoute avant la bordure)."""
        section = next(t for t in self._titles(1) if t._title_text == "TITRES")
        off0 = section._box_off
        self.fields["title_level1_bg_margin"].setValue(False, {"left": 6, "top": 3, "right": 2, "bottom": 5})
        self.fields["title_level1_bg_padding"].setValue(False, {"left": 4, "top": 1, "right": 1, "bottom": 1})
        self.win._flush_live()
        self.assertEqual(section._box_off, off0 + 6)
        m = section.layout().contentsMargins()
        self.assertEqual((m.left() - section._box_off, m.top(), m.right(), m.bottom()), (4, 3 + 1, 2 + 1, 5 + 1))
        self.assertEqual(section.content_abs_x(), section._box_abs + 4)

    def test_touching_boxes_share_one_border_and_square_junctions(self):
        """Boites collees (freres, ou enfant contre le bord interieur du parent) : un seul filet a la
        jonction, comme les colonnes, et coins droits a cet endroit."""
        from settings_store import DEFAULT_SETTINGS
        merged = copy.deepcopy(DEFAULT_SETTINGS)
        for lv in (1, 2):
            merged[f"title_level{lv}_bg_border_enabled"] = {k: True for k in ("top", "right", "bottom", "left")}
            merged[f"title_level{lv}_bg_radius"] = {k: 8 for k in ("top_left", "top_right", "bottom_right", "bottom_left")}
        self.win._restyle_titles(merged)
        section = next(t for t in self._titles(1) if t._title_text == "TITRES")
        kids = [t for t in self._titles(2) if t._parent_title() is section]
        first, middle, last = kids[0]._box_style, kids[1]._box_style, kids[-1]._box_style
        self.assertTrue(first["border_on"]["top"])
        self.assertFalse(middle["border_on"]["top"])                  # filet du frere du dessus
        self.assertEqual((middle["radius"]["top_left"], middle["radius"]["bottom_left"]), (0, 0))
        self.assertEqual(first["radius"]["top_left"], 0)               # le long du bord gauche du parent
        self.assertFalse(first["border_on"]["left"])                   # filet gauche du parent partage
        self.assertFalse(first["border_on"]["right"])                  # bord droit du parent
        self.assertFalse(last["border_on"]["bottom"])                  # bord bas du parent
        # niche dans le coin du parent : son rayon interieur (0 si le parent touche lui-meme son frere)
        self.assertEqual(last["radius"]["bottom_right"], max(0, section._box_style["radius"]["bottom_right"] - 1))
        self.assertEqual(kids[1].layout().contentsMargins().top(), 0)
        if section._box_next is not None:
            self.assertEqual(section._box_style["radius"]["bottom_left"], 0)
            self.assertFalse(section._box_next._box_style["border_on"]["top"])
        merged["title_level1_bg_padding"] = {"left": 5, "top": 0, "right": 0, "bottom": 0}
        self.win._restyle_titles(merged)                               # decolle du bord gauche du parent
        self.assertEqual(kids[0]._box_style["radius"]["top_left"], 8)  # coin libre : rayon garde
        self.assertTrue(kids[0]._box_style["border_on"]["left"])

    def test_paragraph_padding_wraps_everything_under_the_title(self):
        """Paragraphes > Padding (paragraphe) : padding autour de tout ce que contient le titre
        (tableaux et sous-titres), pas de la ligne du titre."""
        self.fields["title_level1_body_padding"].setValue(False, {"left": 9, "top": 5, "right": 3, "bottom": 7})
        self.win._flush_live()
        section = next(t for t in self._titles(1) if t._title_text == "TITRES")
        m = section._body_layout.contentsMargins()
        self.assertEqual((m.left(), m.top(), m.right(), m.bottom()), (9, 5, 3, 7))
        head = section._head_layout.contentsMargins()
        self.assertEqual((head.left(), head.right()), section._box_style["text_padding"][::2])  # titre intact
        child = next(t for t in self._titles(2) if t._parent_title() is section)
        self.assertEqual(child._box_abs, section.content_abs_x())
        self.assertEqual(section.content_abs_x() - section._box_abs,
                         section._box_thickness(section._box_style)["left"] + section._box_style["padding"][0] + 9)

    def test_header_click_zone_is_limited_to_the_title(self):
        section = self._titles(1)[0]
        head = section.head
        head.resize(900, head.sizeHint().height())
        head.layout().activate()
        right = section._name_label.geometry().right()
        self.assertTrue(head._hit(right - 1))
        self.assertFalse(head._hit(right + 20))

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
        before = section._head_layout.contentsMargins().top()
        self.fields["title_level1_text_padding"].setValue(False, {"left": 0, "top": before + 25, "right": 0, "bottom": 0})
        self.win._flush_live()
        self.assertEqual(section._head_layout.contentsMargins().top(), before + 25)
        self.win.reject()
        self.assertEqual(section._head_layout.contentsMargins().top(), before)


class ColorFieldTest(unittest.TestCase):
    """Champ couleur compact (app | pastille | sys) : la VALEUR suit toujours le mode affiche."""

    def setUp(self):
        from settings_store import DEFAULT_SETTINGS
        self.colors = DEFAULT_SETTINGS["colors"]

    def test_unchecking_app_switches_to_a_custom_color(self):
        field = v2._CompactAppOrCustomColorField("@skinN2", self.colors)
        field.app_toggle.setChecked(False)
        self.assertTrue(field.system_toggle.isChecked())
        self.assertTrue(field.value().startswith("#"))

    def test_round_trip_restores_slot_and_custom_color(self):
        field = v2._CompactAppOrCustomColorField("#123456", self.colors)
        field.app_toggle.setChecked(True)
        slot = field.value()
        self.assertTrue(slot.startswith("@"))
        field.system_toggle.setChecked(True)
        self.assertEqual(field.value(), "#123456")
        field.system_toggle.setChecked(False)
        self.assertEqual(field.value(), slot)

    def test_header_color_keeps_bare_slot_names(self):
        field = v2._CompactHeaderColor("tableHead", self.colors, "t")
        self.assertEqual(field.value(), "tableHead")
        field.app_toggle.setChecked(False)
        self.assertTrue(field.value().startswith("#"))


class SidesLinkTest(unittest.TestCase):
    def test_link_state_of_borders_is_read_and_restored(self):
        spec = next(sp for sp in v2.CATALOG["G Colonnes"] if sp.key == "column_border_enabled")
        settings = {"column_border_enabled_linked": True, "column_border_thickness": 1, "column_border": {},
                    "column_border_enabled": True}
        widget = v2.make_field(spec, v2.ScopeValues(settings, None), {})
        self.assertTrue(v2.read_spec(spec, widget)["column_border_enabled_linked"])
        widget.link_toggle.setChecked(False)
        self.assertFalse(v2.read_spec(spec, widget)["column_border_enabled_linked"])


class EveryControlSignalsTest(unittest.TestCase):
    """CHAQUE controle elementaire de CHAQUE ligne du CATALOG (General et surcharge) doit declencher
    l'apercu en direct. Le curseur « Epaisseur » des lignes Bordure n'etait relie a rien : le lecteur
    le lisait, mais le bouger ne declenchait aucune mise a jour."""

    def _leaves(self, widget):
        from PySide6.QtWidgets import QLineEdit
        from settings_widgets import _MiniSlider, _RatioSliderField, _SelectField, _SliderField, _Toggle
        from settings_sections import _CompactAppOrCustomColorField
        out = []
        for root in (widget, *getattr(widget, "_v2_parts", {}).values()):
            for c in (root, *root.findChildren(QWidget)):
                if isinstance(c.parent(), QWidget) and isinstance(c.parent().parent(), _CompactAppOrCustomColorField):
                    continue        # toggles app/sys : couverts par la bascule du champ couleur
                if isinstance(c, QLineEdit) and isinstance(c.parent().parent(), (_SliderField, _RatioSliderField)):
                    continue        # zone de saisie d'un curseur : le curseur est teste
                if isinstance(c, _SelectField) and len(c._options) < 2:
                    continue
                if isinstance(c, (_MiniSlider, _Toggle, _SelectField, _CompactAppOrCustomColorField, QLineEdit)) \
                        and c not in out:
                    out.append(c)
        return out

    @staticmethod
    def _mutate(c):
        from PySide6.QtWidgets import QLineEdit
        from settings_widgets import _MiniSlider, _SelectField, _Toggle
        if isinstance(c, _MiniSlider):
            c.setValue(c.value() + 1 if c.value() < c._max else c.value() - 1)
        elif isinstance(c, _Toggle):
            c.setChecked(not c.isChecked())
        elif isinstance(c, _SelectField):
            c._select(next(o for o in c._options if o != c.value()))
        elif isinstance(c, QLineEdit):
            c.setText(c.text() + "Ab")
            c.editingFinished.emit()
        else:                       # couleur : bascule app <-> sys, comme l'utilisateur
            c.system_toggle.setChecked(not c.system_toggle.isChecked())

    def test_every_control_triggers_the_live_preview(self):
        from settings_store import DEFAULT_SETTINGS
        settings = copy.deepcopy(DEFAULT_SETTINGS)
        silent = []
        for title in (None, "Type"):
            for group in v2.CATALOG:
                count, record = [0], []
                table = v2.build_group(group, v2.ScopeValues(settings, title), settings["colors"], {}, {}, [],
                                       record, lambda: count.__setitem__(0, count[0] + 1))   # garde le tableau en vie
                for spec, widget in record:
                    if not isinstance(spec, v2.Spec):
                        continue
                    for c in self._leaves(widget):
                        before = count[0]
                        self._mutate(c)
                        if count[0] == before:
                            silent.append((title, group, spec.key, type(c).__name__))
        self.assertEqual(silent, [])


class AppliedSettingsTest(unittest.TestCase):
    def test_inspector_restyle_uses_the_applied_settings_not_the_disk(self):
        """L'inspecteur se restylait en relisant le disque, ce qui ecrasait l'apercu en direct (toggles,
        palette) de la fenetre de reglages ouverte."""
        import ui_state
        import detail_panel
        import browser_core
        from settings_store import load_settings
        live = load_settings()
        browser_core.apply_all_settings(live)
        self.assertIs(ui_state.APPLIED_SETTINGS, live)
        panel = detail_panel.DetailPanel.__new__(detail_panel.DetailPanel)     # non construit
        # Relire le disque leve ; un panneau non construit leve AttributeError APRES avoir lu ses reglages.
        with mock.patch.object(detail_panel, "load_settings", side_effect=AssertionError("disque relu")), \
                mock.patch.object(detail_panel, "_sync_dynamic_M") as sync_m:
            with self.assertRaises(AttributeError):
                detail_panel.DetailPanel._apply_preview_table_style(panel)
        sync_m.assert_called_once_with(live.get("colors") or {})


if __name__ == "__main__":
    unittest.main()
