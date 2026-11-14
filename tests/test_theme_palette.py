"""Une barre d'outils (fm_theme/palette.py, type « palette » : section « Palette » de l'éditeur), d'après la spec
docs/agents/barres_outils_spec.md, le prototype docs/agents/prototype_barres_outils.html et la capture annotée de
l'utilisateur : grille de cases de la taille d'une icône (une icône dans n'importe quelle case libre, redimensionnement et
largeur des contrôles accrochés à la grille), marges égales, pas de poignée d'étages, images gardées, réglages complets."""
import _isolate  # noqa: F401
import math
import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QEvent, QPoint, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QKeyEvent  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

import settings_store  # noqa: E402
import settings_window_v2 as v2  # noqa: E402
from fm_theme import palette as P  # noqa: E402
from fm_theme import presets as tp  # noqa: E402
from fm_theme.palette_defaults import PALETTE_DEFAULTS  # noqa: E402
from fm_theme.preview import PreviewPanel  # noqa: E402

APP = QApplication.instance() or QApplication([])


class PaletteCase(unittest.TestCase):
    def setUp(self):
        P.set_look({})
        self.addCleanup(P.set_look, {})
        self.root = QWidget()
        self.addCleanup(self.root.deleteLater)
        self.root.resize(600, 400)
        self.palette = P.sample_palette("Créer", self.root)            # 6 icônes en ligne 0, « Opacité » en ligne 1
        self.palette.move(20, 20)
        self.root.show()
        APP.processEvents()


class DefaultsTest(unittest.TestCase):
    def test_every_key_is_a_declared_theme_key(self):
        for key in PALETTE_DEFAULTS:
            self.assertIn(key, settings_store.DEFAULT_SETTINGS)
            self.assertEqual(tp.theme_key(key), ("palette", tp.STANDARD, key[len("palette_"):]))

    def test_every_look_key_has_a_row_in_the_editor(self):
        """« Entièrement paramétrable » : aucune clé `palette_*` sans ligne de réglage (et inversement)."""
        specs = [s for group in ("Grille", "Barre", "En-tete", "Icones", "Controleur", "Slider", "Liste", "Saisie", "Toggle") for s in v2.CATALOG[f"Palette : {group}"]]
        covered = {key for s in specs for key in (s.key, *s.extra_keys)}
        # « lier les 4 » d'une ligne Bordures / Border radius / Ombres : clé compagne `<clé>_linked` (2026-11-12)
        covered |= {f"{s.key}_linked" for s in specs if s.kind in ("corners", "padding", "sides", "sides_thick", "shadow")}
        self.assertEqual(set(PALETTE_DEFAULTS) - covered, set())
        self.assertEqual({k for k in covered if k.startswith("palette_")} - set(PALETTE_DEFAULTS), set())

    def test_the_section_is_in_the_theme_editor(self):
        self.assertIn("Barres d'outils", v2.THEME_SECTIONS)
        node = next(n for n in v2.theme_tree() if n.title == "Barres d'outils")
        self.assertEqual([c.title for c in node.children], ["Grille", "Barre", "En-tête", "Icônes", "Contrôleur"])
        controller = next(c for c in node.children if c.title == "Contrôleur")
        self.assertEqual([c.title for c in controller.children], ["Slider", "Liste déroulante", "Zone de saisie", "Toggle"])
        self.assertNotIn("Barres d'outils", [n.title for n in v2.tab_tree("General")])
        import theme_editor
        self.assertEqual(theme_editor.SECTION_TYPES["Barres d'outils"], "palette")

    def test_snapped_side_menu_shows_its_colour_only_for_choice_three(self):
        """« Clipsée : comportement du côté collé » : menu 1. rien / 2. pas de bordure / 3. couleur de bordure, la
        couleur dans la sous-cellule voisine seulement au 3 (2026-11-08)."""
        spec = next(s for s in v2.CATALOG["Palette : Barre"] if s.key == "palette_snap_side")
        self.assertEqual(spec.label, "Clipsée : comportement du côté collé")
        values = dict(settings_store.DEFAULT_SETTINGS, palette_snap_side="color", palette_snap_side_color="#00ff00")
        field = v2.make_field(spec, v2.ScopeValues(values, None), values.get("colors") or {})
        self.addCleanup(field.deleteLater)
        self.assertFalse(field._color.isHidden())
        self.assertEqual(v2.read_spec(spec, field)["palette_snap_side"], "color")
        field._menu.setValue("2. Pas de bordure")
        field._menu.changed.emit("2. Pas de bordure")
        self.assertTrue(field._color.isHidden())
        self.assertEqual(v2.read_spec(spec, field)["palette_snap_side"], "no_border")
        self.assertTrue(any(s.key == "palette_snap_separator" for s in v2.CATALOG["Palette : Barre"]))

    def test_a_preset_keeps_the_palette_as_a_type_with_variants(self):
        values = {k: v for k, v in settings_store.DEFAULT_SETTINGS.items() if k.startswith("palette_")}
        values["palette_cell_size"] = 44
        preset = tp.from_settings(values, "essai")
        self.assertEqual(preset["types"]["palette"]["defaut"], "standard")
        self.assertEqual(preset["types"]["palette"]["variantes"]["standard"]["cell_size"], 44)
        self.assertEqual(tp.to_settings(preset)["palette_cell_size"], 44)

    def test_the_defaults_are_the_prototype_dimensions(self):
        """Spec § 2 et § 4 : icône 34, écart 4, padding 6, rayon 8, aimantation 24 ; plus de poignée d'étages."""
        d = PALETTE_DEFAULTS
        self.assertEqual((d["palette_cell_size"], d["palette_cell_gap"], d["palette_margin"], d["palette_corner_radius"],
                          d["palette_snap_distance"]), (34, 4, 6, 8, 24))
        self.assertFalse([k for k in d if "rows" in k])


class LookTest(unittest.TestCase):
    def tearDown(self):
        P.set_look({})

    def test_transparent_colors_follow_the_theme_tokens(self):
        from fm_theme.tokens import M
        look = P.palette_look({})
        self.assertEqual(look["bg"], M["panel_bg"])
        self.assertEqual(look["bar_bg"], M["field_bg"])
        self.assertEqual(look["border"]["top"], M["panel_border"])
        with mock.patch.dict(M, {"panel_bg": "#223344"}):
            self.assertEqual(P.palette_look({})["bg"], "#223344")

    def test_a_chosen_color_wins_and_changes_the_key(self):
        a, b = P.palette_look({}), P.palette_look({"palette_bg_color": "#112233"})
        self.assertEqual(b["bg"], "#112233")
        self.assertNotEqual(a["key"], b["key"])
        self.assertEqual(a["key"], P.palette_look({})["key"])

    def test_set_look_reports_a_change_only_once(self):
        self.assertFalse(P.set_look({}))
        self.assertTrue(P.set_look({"palette_cell_size": 40}))
        self.assertFalse(P.set_look({"palette_cell_size": 40}))

    def test_values_are_bounded(self):
        look = P.palette_look({"palette_cell_size": 1, "palette_margin": 999, "palette_icon_ratio": "x"})
        self.assertGreaterEqual(look["cell"], 16)
        self.assertLessEqual(look["margin"], 32)
        self.assertEqual(look["icon_ratio"], PALETTE_DEFAULTS["palette_icon_ratio"])


class GridTest(PaletteCase):
    """Capture annotée de l'utilisateur : une grille de cases de la taille d'une icône, marges égales, pas d'étages."""

    def test_the_size_is_a_whole_grid_with_equal_margins(self):
        look, pal = P.LOOK, self.palette
        bw, m = look["border_w"], look["margin"]
        self.assertEqual((pal.cols, pal.rows), (6, 2))
        self.assertEqual(pal.width(), 2 * bw + 2 * m + P.cells_px(6))
        self.assertEqual(pal.height(), 2 * bw + look["header"] + 2 * m + P.cells_px(2))
        opacity = pal.item("opacity").geometry()
        self.assertEqual(opacity.left(), bw + m)                                       # marge gauche…
        self.assertEqual(pal.height() - opacity.bottom() - 1, bw + m)                  # … = marge du bas
        self.assertEqual(pal.width() - opacity.right() - 1, bw + m)                    # … = marge droite

    def test_an_icon_goes_into_any_free_cell(self):
        pal = self.palette
        pal.set_grid(8, 2)
        pal.move_item("pen", 7, 0)                                                     # la case vide à droite
        self.assertEqual(pal.cell_of("pen"), (7, 0, 1))
        self.assertEqual(pal.item("pen").geometry(), pal.cell_rect(7, 0))
        self.assertTrue(pal.free(4, 0, 1))                                             # son ancienne case est libre
        self.assertFalse(pal.free(7, 0, 1))

    def test_resizing_snaps_to_the_grid_and_never_cuts_an_item(self):
        pal = self.palette
        self.assertEqual(pal.snap(pal.width() + 15, pal.height()), (6, 2))           # moins d'une demi-case
        self.assertEqual(pal.snap(pal.width() + 25, pal.height()), (7, 2))
        self.assertEqual(pal.snap(10, 10), pal.min_grid())                             # jamais plus petite que le contenu
        right = QPoint(pal.width() - 2, pal.height() // 2)
        QTest.mousePress(pal, Qt.LeftButton, Qt.NoModifier, right)
        QTest.mouseMove(pal, right + QPoint(2 * P.step(), 0))
        QTest.mouseRelease(pal, Qt.LeftButton, Qt.NoModifier, right + QPoint(2 * P.step(), 0))
        self.assertEqual((pal.cols, pal.rows), (8, 2))
        corner = QPoint(pal.width() - 2, pal.height() - 2)
        QTest.mousePress(pal, Qt.LeftButton, Qt.NoModifier, corner)
        QTest.mouseMove(pal, corner + QPoint(-5 * P.step(), P.step()))
        QTest.mouseRelease(pal, Qt.LeftButton, Qt.NoModifier, corner + QPoint(-5 * P.step(), P.step()))
        self.assertEqual((pal.cols, pal.rows), (6, 3))                                 # bornée par les 6 icônes

    def test_a_docked_bar_resizes_by_the_edge_that_is_free(self):
        pal = self.palette
        pal.set_dock("bottom")
        self.assertEqual(pal._edge(QPoint(10, 1)), "-v")                               # le haut
        self.assertEqual(pal._edge(QPoint(10, pal.height() - 1)), "")                   # le bas touche la fenêtre
        pal.set_dock("right")
        self.assertEqual(pal._edge(QPoint(1, 40)), "-h")
        self.assertEqual(pal._edge(QPoint(pal.width() - 1, 40)), "")

    def test_a_vertical_bar_has_its_title_left_and_a_transposed_grid(self):
        pal = self.palette
        pal.set_orient("v")
        look = P.LOOK
        self.assertEqual(pal.header_rect().width(), look["header"])
        self.assertEqual(pal.cell_of("pen"), (0, 4, 1))                                # (4, 0) -> (0, 4)
        self.assertEqual(pal.item(pal.keys()[0]).geometry().left(), look["border_w"] + look["header"] + look["margin"])
        self.assertGreaterEqual(pal.cols, P.need_cells(pal.item("opacity")))           # le contrôle tient en largeur

    def test_the_title_sets_a_minimum_width(self):
        pal = P.ToolBar("Un très long titre de barre", 1, 1, self.root)
        pal.add_item("a", P.PaletteButton("a", "a", P.demo_glyph("square")))
        self.assertGreater(pal.cols, 1)

    def test_a_vertical_title_does_not_hold_the_height(self):
        pal = P.ToolBar("Un très long titre de barre", 1, 1, self.root)
        pal.add_item("a", P.PaletteButton("a", "a", P.demo_glyph("square")))
        pal.set_orient("v")
        self.assertEqual(pal.min_grid()[1], 1)                                         # coupé d'un « … »

    def test_no_rows_handle_any_more(self):
        self.assertFalse(hasattr(self.palette, "rows_handle_rect"))


class ControlsTest(PaletteCase):
    def test_value_follows_the_slider_and_is_painted(self):
        bar = self.palette.item("opacity")
        seen = []
        bar.valueChanged.connect(seen.append)
        bar.setValue(35)
        self.assertEqual((bar.value(), seen), (35, [35]))
        self.assertEqual(bar._text(), "35 %")
        self.assertFalse(self.palette.grab().isNull())

    def test_the_original_widths_and_the_bounds(self):
        """Spec § 8 : largeurs d'origine, bornes 120 et 520 ; c'est le champ qui s'étire."""
        sl = P.PaletteSliderBar("o", "Opacité", 0, 100, 80, "%")
        field = P.PaletteInputBar("n", "Nom", "Calque 1")
        menu = P.PaletteSelectBar("f", "Police", ["Inter", "Roboto"], "Inter")
        self.assertEqual([w.bar_size().width() for w in (sl, field, menu)], [220, 180, 170])
        self.assertEqual(sl.set_bar_width(9999), 520)
        self.assertEqual(sl.set_bar_width(10), max(120, sl.min_width()))       # jamais sous le contenu (piste de 40 px)
        self.assertGreaterEqual(menu.set_bar_width(10), 120)
        pal = self.palette
        opacity = pal.item("opacity")
        self.assertEqual(opacity.width(), P.cells_px(6))                   # 220 px -> 6 cases (224 px)
        inner = opacity.slider.width()
        pal.set_item_width(opacity, 300)
        self.assertEqual(opacity.width(), P.cells_px(8))                   # 300 px = 8 cases tout juste
        self.assertEqual(opacity.slider.width(), inner + 2 * P.step())     # le libellé et la valeur gardent leur taille

    def test_the_width_handle_snaps_to_the_grid_and_widens_the_bar(self):
        pal = self.palette
        opacity = pal.item("opacity")
        before = pal.width()
        start = QPoint(opacity.width() - 2, opacity.height() // 2)
        QTest.mousePress(opacity, Qt.LeftButton, Qt.NoModifier, start)
        QTest.mouseMove(opacity, start + QPoint(10, 0))
        self.assertEqual(opacity.width(), P.cells_px(6))                   # 10 px : pas encore une case
        QTest.mouseMove(opacity, start + QPoint(40, 0))
        QTest.mouseRelease(opacity, Qt.LeftButton, Qt.NoModifier, start + QPoint(40, 0))
        self.assertEqual(opacity.width(), P.cells_px(7))
        self.assertEqual(pal.width(), before + P.step())                   # la grille gagne une colonne
        self.assertEqual(pal.cols, 7)

    def test_typed_keys_never_reach_the_shortcuts(self):
        field = P.PaletteInputBar("n", "Nom", "")
        event = QKeyEvent(QEvent.ShortcutOverride, Qt.Key_Z, Qt.NoModifier, "z")
        event.ignore()
        QApplication.sendEvent(field.field, event)
        self.assertTrue(event.isAccepted())

    def test_a_control_outside_a_bar_is_a_plain_field(self):
        bar = P.PaletteSliderBar("brush_size", "Taille", 1, 64, 12, "px")
        bar.resize(200, 34)
        bar._layout_parts()
        self.assertTrue(bar._handle_rect.isNull())                         # pas de poignée de largeur hors d'une barre


class LookFollowsSettingsTest(PaletteCase):
    def test_a_new_cell_size_resizes_everything_in_place(self):
        pal = self.palette
        before = pal.size()
        P.restyle_palettes_in(self.root, {"palette_cell_size": 48, "palette_margin": 10})
        self.assertGreater(pal.width(), before.width())
        self.assertEqual(pal.size(), pal.natural_size())
        self.assertEqual(pal.item("pen").width(), 48)
        self.assertEqual(pal.item(pal.keys()[0]).geometry().left(), P.LOOK["border_w"] + 10)
        P.restyle_palettes_in(self.root, {})
        self.assertEqual(pal.size(), before)

    def test_nothing_is_redone_when_the_look_did_not_change(self):
        pal = self.palette
        pal.grab()
        with mock.patch.object(P, "_render", wraps=P._render) as render:
            P.restyle_palettes_in(self.root, {})
            pal.grab()
        render.assert_not_called()

    def test_images_are_kept_between_paints(self):
        """Fluidité : icônes, contrôles et cadre dessinés une fois ; repeindre sans changement ne refait aucune image."""
        pal = self.palette
        pal.grab()
        with mock.patch.object(P, "_render", wraps=P._render) as render:
            pal.update()
            pal.grab()
            self.assertEqual(render.call_count, 0)
            pal.item("pen").set_active(False)
            pal.grab()
            self.assertEqual(render.call_count, 1)                    # seule l'icône changée est refaite


class EditorPreviewTest(unittest.TestCase):
    def test_the_preview_shows_a_working_workspace_of_bars(self):
        panel = PreviewPanel(lambda: dict(settings_store.DEFAULT_SETTINGS))
        try:
            panel.show_section("Barres d'outils")
            bars = panel.findChildren(P.ToolBar)
            self.assertEqual(sorted(b.title() for b in bars), ["Contrôleurs", "Créer", "Outils"])
            self.assertTrue(all(b.size() == b.natural_size() for b in bars))
            self.assertTrue(all(b.manager is not None for b in bars))        # le vrai système
            self.assertIn("Barres d'outils", [s for s in panel._builders])
            panel.show_section(None)                                         # la planche en montre aussi
            self.assertEqual(len(panel.findChildren(P.ToolBar)), 3)
        finally:
            panel.deleteLater()
            P.set_look({})


class SettingsSectionsTest(PaletteCase):
    """Section « Palette » réorganisée (demande de l'utilisateur, 2026-11-02) : en-tête (justification, fond), icônes
    (fond, bordure), quatre contrôleurs (slider, liste déroulante, zone de saisie, toggle) avec leurs réglages."""

    def test_the_title_alignment_and_the_header_background_change_the_image(self):
        pal = self.palette
        left = pal.grab().toImage()
        P.restyle_palettes_in(self.root, {"palette_title_align": "right"})
        self.assertEqual(P.LOOK["title_align"], "right")
        right = pal.grab().toImage()
        self.assertNotEqual(left, right)
        P.restyle_palettes_in(self.root, {"palette_header_bg_color": "#ff0000"})
        image = pal.grab().toImage()
        self.assertEqual(image.pixelColor(pal.width() // 2, P.LOOK["border_w"] + 2).name(), "#ff0000")
        below = pal.item(pal.keys()[0]).geometry().bottom() + 2
        self.assertNotEqual(image.pixelColor(pal.width() - 3, below).name(), "#ff0000")      # seulement l'en-tête

    def test_icons_get_a_background_and_a_border(self):
        button = self.palette.item("square")
        plain = button.grab().toImage()
        sides = {s: True for s in ("top", "right", "bottom", "left")}
        P.restyle_palettes_in(self.root, {"palette_cell_bg_color": "#00ff00", "palette_cell_border_enabled": sides,
                                          "palette_cell_border": {s: "#0000ff" for s in sides}, "palette_cell_radius": 0})
        image = button.grab().toImage()
        self.assertNotEqual(plain, image)
        self.assertEqual(image.pixelColor(0, button.height() // 2).name(), "#0000ff")
        self.assertEqual(image.pixelColor(3, 3).name(), "#00ff00")

    def test_the_four_controllers_share_the_frame_and_the_toggle_works(self):
        toggle = P.PaletteToggleBar("grid", "Grille", False)
        seen = []
        toggle.valueChanged.connect(seen.append)
        toggle.setValue(True)
        self.assertEqual((toggle.value(), seen), (True, [True]))
        self.assertEqual(P.KIND_LABELS[toggle.kind], "Toggle")
        self.palette.add_item("grid", toggle, 0, 2)
        self.assertEqual(self.palette.cell_of("grid")[1], 2)
        for cls in (P.PaletteSliderBar, P.PaletteSelectBar, P.PaletteInputBar, P.PaletteToggleBar):
            self.assertIs(cls._paint_chrome, P.PaletteControl._paint_chrome)       # même cadre, même fond

    def test_each_controller_has_its_own_settings(self):
        P.restyle_palettes_in(self.root, {"palette_select_height": 30, "palette_input_min_width": 90,
                                          "palette_slider_style": "palette", "palette_slider_track_height": 7})
        menu = P.PaletteSelectBar("f", "Police", ["Inter"], "Inter")
        field = P.PaletteInputBar("n", "Nom")
        self.assertEqual(menu.field.height(), 30)
        self.assertEqual(field.field_min, 90)
        opacity = self.palette.item("opacity")
        self.assertEqual(opacity.slider._style["track_h"], 7)                 # slider propre aux barres
        P.restyle_palettes_in(self.root, {})
        self.assertIsNone(P.slider_style())                                   # celui des réglages

    def test_touching_controllers_lose_their_inner_corners(self):
        pal = self.palette
        pal.set_grid(6, 3)
        pal.add_item("size", P.PaletteSliderBar("size", "Taille", 1, 64, 12, "px"), 0, 2)
        P.restyle_palettes_in(self.root, {"palette_cell_gap": 4, "palette_bar_join_gap": 1})
        self.assertEqual(pal.item("opacity").joined, ())                      # 4 px d'écart > 1 : arrondis
        P.restyle_palettes_in(self.root, {"palette_cell_gap": 1, "palette_bar_join_gap": 1})
        pal.set_item_width(pal.item("size"), P.cells_px(pal.cell_of("opacity")[2]))     # même largeur : coins couverts
        self.assertEqual(pal.item("opacity").joined, ("bl", "br"))
        self.assertEqual(pal.item("size").joined, ("tl", "tr"))

    def test_compressing_a_bar_moves_the_items_that_no_longer_fit(self):
        pal = self.palette
        right = QPoint(pal.width() - 2, pal.height() // 2)
        QTest.mousePress(pal, Qt.LeftButton, Qt.NoModifier, right)
        QTest.mouseMove(pal, right + QPoint(3 * P.step(), 0))
        QTest.mouseMove(pal, right + QPoint(0, 0))
        QTest.mouseRelease(pal, Qt.LeftButton, Qt.NoModifier, right)
        self.assertEqual((pal.cols, pal.rows), (6, 2))                        # revenue : rien n'a bougé
        pal.set_grid(8, 2)
        pal.move_item("pen", 7, 0)
        right = QPoint(pal.width() - 2, pal.height() // 2)
        QTest.mousePress(pal, Qt.LeftButton, Qt.NoModifier, right)
        QTest.mouseMove(pal, right - QPoint(2 * P.step(), 0))
        QTest.mouseRelease(pal, Qt.LeftButton, Qt.NoModifier, right - QPoint(2 * P.step(), 0))
        self.assertEqual(pal.cols, 6)
        self.assertEqual(pal.cell_of("pen"), (4, 0, 1))                       # retassée dans la case libre


class ToolbarButtonVariantTest(unittest.TestCase):
    """Demande de l'utilisateur (2026-11-10) : un style de bouton « toolbar » qui reprend les réglages des boutons des
    barres d'outils."""

    def test_fields_come_from_the_toolbar_cells(self):
        import tempfile
        from pathlib import Path
        from fm_theme.style import button_state_css
        settings = {"palette_cell_radius": 9, "palette_cell_bg_color": "#112233", "palette_cell_border_thickness": 2,
                    "palette_cell_border_enabled": {"top": True, "right": True, "bottom": True, "left": True},
                    "palette_cell_border": {s: "#445566" for s in ("top", "right", "bottom", "left")},
                    "palette_icon_color": "#00000000", "palette_bar_font_size": 13}
        fields = P.toolbar_button_fields(settings)
        self.assertEqual((fields["radius"], fields["bg_color"], fields["border_thickness"]), (9, "#112233", 2))
        self.assertEqual(fields["corner_radius"]["bottom_left"], 9)
        self.assertEqual(fields["border"]["left"], "#445566")
        self.assertEqual(fields["font_color"], P.M["value_fg"])          # transparente = la teinte du thème
        self.assertEqual(fields["font_size"], 13)
        with tempfile.TemporaryDirectory() as folder:
            name = tp.new_preset("Toolbar", settings_store.load_settings(), Path(folder))
            made = tp.add_variant(name, "bouton", P.TOOLBAR_BUTTON_VARIANT, folder=Path(folder), fields=fields)
            flat = tp.type_flat(tp.load_preset(tp.find_preset(name, Path(folder))), "bouton", made)
        self.assertEqual(made, "toolbar")
        self.assertEqual(flat["button_bg_color"], "#112233")
        self.assertIn("#112233", button_state_css(flat))

    def test_hover_and_active_states_reach_the_button_type(self):
        from fm_theme import style
        fields = P.toolbar_button_fields({"palette_cell_hover_color": "#202122", "palette_cell_active_color": "#303132",
                                          "palette_cell_active_border_color": "#404142",
                                          "palette_cell_active_border_thickness": 2})
        self.assertEqual((fields["hover_color"], fields["active_color"], fields["active_border"]["left"],
                          fields["active_border_thickness"]), ("#202122", "#303132", "#404142", 2))
        look = {f"button_{k}": v for k, v in fields.items()}
        self.assertIn("#202122", style.button_state_css(look, "survol"))
        pressed = style.button_state_css(look, "enfonce")
        self.assertIn("#303132", pressed)
        self.assertIn("2px solid #404142", pressed)
        self.assertIn(style.C["btn_hover"], style.button_state_css({}, "survol"))   # transparent / absent = le thème
        saved = style._CONTROL_LOOK
        style._CONTROL_LOOK = look
        try:
            sheet = style.build_stylesheet()
        finally:
            style._CONTROL_LOOK = saved
        self.assertIn("QPushButton:hover { background: #202122;", sheet)
        self.assertIn("2px solid #404142", sheet)
        rows = {k for s in v2.CATALOG["Bouton"] if not isinstance(s, str) for k in (s.key, *s.extra_keys)}
        for key in ("button_hover_color", "button_active_color", "button_active_border",
                    "button_active_border_thickness"):
            self.assertIn(key, settings_store.DEFAULT_SETTINGS)
            self.assertIn(key, rows)

    def test_hover_and_focus_states_are_settable(self):
        """Demande de l'utilisateur (2026-11-11) : survol et focus réglables (fond, texte, bordure, épaisseur)."""
        from fm_theme import style
        rows = {k for s in v2.CATALOG["Bouton"] if not isinstance(s, str) for k in (s.key, *s.extra_keys)}
        for state in ("hover", "focus", "active"):
            for key in (f"button_{state}_color", f"button_{state}_text_color", f"button_{state}_font_bold",
                        f"button_{state}_border_enabled", f"button_{state}_border",
                        f"button_{state}_border_thickness"):
                self.assertIn(key, settings_store.DEFAULT_SETTINGS)
                self.assertIn(key, rows)
        look = {"button_hover_color": "#101112", "button_hover_text_color": "#a1a2a3",
                "button_hover_border": dict.fromkeys(("top", "right", "bottom", "left"), "#b1b2b3"),
                "button_hover_border_thickness": 3,
                "button_focus_color": "#c1c2c3", "button_focus_text_color": "#d1d2d3",
                "button_focus_border": dict.fromkeys(("top", "right", "bottom", "left"), "#e1e2e3"),
                "button_active_text_color": "#f1f2f3"}
        self.assertIn("color: #f1f2f3", style.button_state_css(look, "enfonce"))
        self.assertIn(style.C["accent_text"], style.button_state_css({}, "enfonce"))   # transparent = le thème
        hover = style.button_state_css(look, "survol")
        self.assertIn("3px solid #b1b2b3", hover)
        self.assertIn("color: #a1a2a3", hover)
        focus = style.button_state_css(look, "focus")
        self.assertIn("background: #c1c2c3", focus)
        self.assertIn("color: #d1d2d3", focus)
        self.assertIn("border-top-color: #e1e2e3", focus)
        saved = style._CONTROL_LOOK
        try:
            style._CONTROL_LOOK = look
            sheet = style.build_stylesheet()
            style._CONTROL_LOOK = {}
            plain = style.build_stylesheet()
        finally:
            style._CONTROL_LOOK = saved
        self.assertIn("QPushButton:focus { background: #c1c2c3;", sheet)
        self.assertIn("color: #a1a2a3", sheet)
        self.assertIn("color: #f1f2f3", sheet)
        self.assertNotIn("QPushButton:focus", plain)              # rien de réglé = pas de règle focus

    def test_state_border_line_and_bold(self):
        """Demande de l'utilisateur (2026-11-11) : bordures de chaque état = ligne Bordures standard (côtés, couleur
        par côté, épaisseur), police des états = gras + couleur."""
        from fm_theme import style
        look = {"button_hover_border_enabled": {"top": True, "right": False, "bottom": True, "left": True},
                "button_hover_border": {"top": "#111111", "right": "#00000000", "bottom": "#00000000",
                                        "left": "#00000000"},
                "button_hover_border_thickness": 2, "button_hover_font_bold": True,
                "button_border": dict.fromkeys(("top", "right", "bottom", "left"), "#222222")}
        hover = style.button_state_css(look, "survol")
        self.assertIn("border-top: 2px solid #111111;", hover)
        self.assertIn("border-right: none;", hover.split("padding")[1])   # côté coupé dans cet état
        self.assertIn(f"border-bottom: 2px solid {style.C['btn_hover_bd']};", hover)   # transparent = le thème
        self.assertIn("font-weight: bold;", hover.split("padding")[1])
        self.assertNotIn("font-weight: bold", style.button_state_css(look, "focus").split("padding")[1])
        focus = style.button_state_css({**look, "button_focus_border_thickness": 3}, "focus")
        self.assertIn("border-left: 3px solid #222222;", focus)           # focus transparent = la bordure standard
        saved = style._CONTROL_LOOK
        try:
            style._CONTROL_LOOK = {"button_active_font_bold": True}
            sheet = style.build_stylesheet()
        finally:
            style._CONTROL_LOOK = saved
        self.assertIn("font-weight: bold;", sheet.split("QPushButton:pressed")[1].split("}")[0])

    def test_state_font_rows_are_standard_font_rows(self):
        """Demande de l'utilisateur (2026-11-12) : la police de chaque état = une ligne Polices standard (même gabarit
        de ligne, mêmes sous-cellules que la ligne Polices de l'état standard)."""
        from fm_theme.cells import ROW_FAMILIES
        vals = v2.ScopeValues(dict(settings_store.DEFAULT_SETTINGS))
        built = {s.key: v2.make_field(s, vals, {}) for s in v2.CATALOG["Bouton"] if not isinstance(s, str)}
        kinds = {key: ROW_FAMILIES.get(w._row_kind, w._row_kind) for key, w in built.items()}
        for state in ("hover", "focus", "active"):
            key = f"button_{state}_font_family"
            self.assertEqual(kinds[key], kinds["button_font_family"])
            self.assertEqual(set(built[key]._v2_parts), set(built["button_font_family"]._v2_parts))

    def test_old_button_layout_is_converted(self):
        """Ancienne mise en page du tableau Bouton (17 lignes) : splits et textes au-dessus suivent leurs états."""
        dims = {"row_order": [0, 14, 1, 15, 16] + list(range(2, 14)), "row_heights": [34, 70] + [34] * 12 + [70] * 3,
                "row_splits": {"2": 25, "6": 25, "10": 25},
                "above_texts": {"2": "Survol", "6": "Focus", "10": "Enfoncé"},
                "split": {"r1c1": [58, 140], "r16c1": [0, 70]}}
        settings_store._migrate_button_dims(dims)
        # 17 -> 14 (états : fond, bordures, police) -> 20 (+ décalage, ombres) -> 23 (+ border radius ; police standard)
        # -> 26 (+ ligne « suit » en tête de chaque état, qui reprend sa coupe et son texte) -> 27 (+ décalage du texte)
        self.assertEqual(dims["row_order"], [0, 23, 24, 1, 25, 26] + list(range(2, 23)))
        self.assertEqual(dims["above_texts"], {"2": "Survol", "9": "Focus", "16": "Enfoncé"})
        self.assertEqual(dims["row_splits"], {"2": 25, "9": 25, "16": 25})
        self.assertEqual(dims["split"]["r11c1"], [58, 140])               # Bordures du focus = la standard
        self.assertEqual(dims["split"]["r26c1"], [0, 70])                 # Ombres standard
        for row in (8, 15, 22):                                           # Ombres des états = la standard
            self.assertEqual(dims["split"][f"r{row}c1"], [0, 70])
        self.assertEqual(len(v2.CATALOG["Bouton"]), len(dims["row_heights"]))
        settings_store._migrate_button_dims(dims)                         # déjà converti : rien
        self.assertEqual(dims["row_order"], [0, 23, 24, 1, 25, 26] + list(range(2, 23)))

    def test_state_fonts_and_radius_take_the_standard_layout(self):
        """Étape 20 -> 23 : la police de chaque état reprend la mise en page de la ligne Polices standard, son border
        radius celle du Border radius standard."""
        dims = {"row_order": list(range(20)), "row_heights": [34] * 17 + [90, 60, 34],
                "split": {"r4c1": [40, 80], "r17c1": [150, 50, 50, 110, 120, 60], "r18c1": [30, 30, 30, 30, 30]}}
        settings_store._migrate_button_dims(dims)
        self.assertEqual(dims["row_order"], list(range(27)))
        for font, radius in ((5, 6), (12, 13), (19, 20)):                 # (après la ligne « suit » de l'étape 4)
            self.assertEqual(dims["split"][f"r{font}c1"], [150, 50, 50, 110, 120, 60])
            self.assertEqual(dims["split"][f"r{radius}c1"], [30, 30, 30, 30, 30])
            self.assertEqual((dims["row_heights"][font], dims["row_heights"][radius]), (90, 60))
        self.assertEqual(dims["split"]["r23c1"], [150, 50, 50, 110, 120, 60])

    def test_follow_rows_open_their_state_part(self):
        """Étape 23 -> 26 (2026-11-12) : la ligne « suit » ouvre chaque état ; coupe, texte et repli passent dessus."""
        dims = {"row_order": [0, 20, 1, 21, 22] + list(range(2, 20)), "row_heights": [34] * 23,
                "row_splits": {"2": 30, "8": 30, "14": 30}, "collapsed": [2, 8],
                "above_texts": {"0": "Main", "2": "Etat survol", "8": "Etat focus", "14": "Etat enfonce"}}
        settings_store._migrate_button_dims(dims)
        self.assertEqual(dims["row_order"], [0, 23, 24, 1, 25, 26] + list(range(2, 23)))
        self.assertEqual(dims["row_splits"], {"2": 30, "9": 30, "16": 30})
        self.assertEqual(dims["above_texts"], {"0": "Main", "2": "Etat survol", "9": "Etat focus", "16": "Etat enfonce"})
        self.assertEqual(dims["collapsed"], [2, 9])
        keys = [s.key for s in v2.CATALOG["Bouton"]]
        self.assertEqual([keys[r] for r in (2, 9, 16)], [f"button_{s}_follow" for s in ("hover", "focus", "active")])

    def test_text_offset_row_comes_under_the_standard_font(self):
        """Étape 26 -> 27 (2026-11-12) : « Décalage du texte » sous Polices standard, mise en page du Décalage survol."""
        dims = {"row_order": [0, 23, 1, 24, 25] + list(range(2, 23)), "row_heights": [34] * 26,
                "split": {"r7c1": [40, 90, 90], "r25c1": [0, 70]}, "above_texts": {"24": "Rayon"}, "collapsed": [24]}
        settings_store._migrate_button_dims(dims)
        self.assertEqual(dims["row_order"], [0, 23, 24, 1, 25, 26] + list(range(2, 23)))
        self.assertEqual((dims["split"]["r24c1"], dims["split"]["r26c1"]), ([40, 90, 90], [0, 70]))
        self.assertEqual((dims["above_texts"], dims["collapsed"]), ({"25": "Rayon"}, [25]))
        keys = [s.key for s in v2.CATALOG["Bouton"]]
        self.assertEqual((keys[23], keys[24], len(keys)), ("button_font_family", "button_text_offset_x", 27))


class ButtonStateOverrideTest(unittest.TestCase):
    """Demande de l'utilisateur (2026-11-12) : « je n'arrive pas à désactiver l'ombre de l'état enfoncé ; vérifier que
    tous les paramètres sont bien indépendants par état ; chaque état = un override de l'état main »."""

    SIDES = ("top", "right", "bottom", "left")

    def _flags(self, state, on):
        return {f"button_{state}_ovr_{row}": on for row in ("color", "border", "font", "radius", "shadow")}

    def test_pressed_shadow_can_be_turned_off(self):
        from fm_theme import style
        look = {"button_shadow_enabled": dict.fromkeys(self.SIDES, True),
                "button_shadow": dict.fromkeys(self.SIDES, "#ff000000"), "button_shadow_size": 6,
                "button_active_shadow_enabled": dict.fromkeys(self.SIDES, False), "button_active_ovr_shadow": True}
        looks = style.button_effect_look(look)
        self.assertIsNone(looks["active"][0])                            # surchargée sans côté : AUCUNE ombre
        self.assertIsNotNone(looks["hover"][0])                          # les autres états : la standard
        self.assertIsNotNone(looks["standard"][0])
        look["button_active_ovr_shadow"] = False
        self.assertEqual(style.button_effect_look(look)["active"][0], looks["standard"][0])
        # Réglage d'avant sans toggle : « activer » coupé est écrit d'office pour une ligne sans côté (vu dans les
        # réglages de l'utilisateur, les 3 états) : l'aspect d'avant (l'ombre standard) est gardé.
        old = dict(look, button_active_shadow_enabled__on=False)
        del old["button_active_ovr_shadow"]
        self.assertEqual(style.button_effect_look(old)["active"][0], looks["standard"][0])

    def test_every_row_of_every_state_is_independent(self):
        """Chaque ligne de chaque état, surchargée seule : seul CET état change, et seulement par CETTE ligne."""
        from fm_theme import style
        own = {"color": {"color": "#123456"},
               "border": {"border_enabled": dict.fromkeys(self.SIDES, False)},
               "font": {"font_size": 23, "font_bold": True, "text_color": "#654321"},
               "radius": {"corner_radius": 9},
               "shadow": {"shadow_enabled": dict.fromkeys(self.SIDES, True),
                          "shadow": dict.fromkeys(self.SIDES, "#ff0a0b0c"), "shadow_size": 5}}
        markers = {"color": "#123456", "border": "border-top: none", "font": "#654321", "radius": "9px"}
        base = {f"button_{s}_ovr_{row}": False for s in ("hover", "focus", "active") for row in own}
        plain = {s: style.button_state_css(base, s) for s in ("survol", "focus", "enfonce")}
        for state, frozen in (("hover", "survol"), ("focus", "focus"), ("active", "enfonce")):
            for row, values in own.items():
                look = dict(base, **{f"button_{state}_{k}": v for k, v in values.items()})
                self.assertEqual(style.button_state_css(look, frozen), plain[frozen], f"{state} {row} coupé")
                look[f"button_{state}_ovr_{row}"] = True
                for other in ("survol", "focus", "enfonce"):
                    css = style.button_state_css(look, other)
                    if other != frozen:
                        self.assertEqual(css, plain[other], f"{state} {row} déborde sur {other}")
                    elif row in markers:
                        self.assertIn(markers[row], css, f"{state} {row}")
                effect = style.button_effect_look(look)
                shadows = {s: (effect or {}).get(s, (None,))[0] for s in ("hover", "focus", "active")}
                if row == "shadow":
                    self.assertEqual(shadows[state]["colors"]["top"], "#ff0a0b0c")
                    self.assertEqual([s for s, sh in shadows.items() if sh], [state])
                else:
                    self.assertFalse(any(shadows.values()), f"{state} {row}")

    def test_override_off_follows_every_standard_row(self):
        from fm_theme import style
        look = dict(self._flags("active", False), button_bg_color="#111111", button_font_size=17,
                    button_corner_radius=7, button_active_color="#222222", button_active_font_size=30,
                    button_active_corner_radius=2)
        css = style.button_state_css(look, "enfonce").split("padding")[1]
        self.assertNotIn("#222222", css)
        self.assertNotIn("30px", css)
        self.assertNotIn("radius: 2px", css)
        self.assertEqual(style.button_state_value(look, "button_active_font_size"), 17)
        self.assertEqual(style.button_state_value(look, "button_active_color"), "#111111")
        on = dict(look, **self._flags("active", True))
        self.assertEqual(style.button_state_value(on, "button_active_font_size"), 30)
        self.assertEqual(style.button_state_value(dict(on, button_active_font_size=None), "button_active_font_size"), 17)

    def test_a_state_follows_the_state_chosen_in_its_list(self):
        """Demande de l'utilisateur (2026-11-12) : une liste par état, « suit : Standard / Survol / Focus / Enfoncé » ;
        ses lignes non surchargées prennent celles de l'état choisi (de proche en proche ; boucle = le standard)."""
        from fm_theme import style
        sides = dict.fromkeys(self.SIDES, True)
        look = dict(self._flags("focus", False), **self._flags("hover", True), button_focus_follow="hover",
                    button_hover_color="#123456", button_hover_font_size=21, button_hover_shadow_enabled=sides,
                    button_hover_shadow=dict.fromkeys(self.SIDES, "#ff0a0b0c"), button_hover_shadow_size=5,
                    button_focus_color="#999999")
        focus = style.button_state_css(look, "focus").split("padding")[1]
        self.assertIn("#123456", focus)                                  # fond du survol
        self.assertIn(f"font-size: {style.scaled(21)}px", focus)
        self.assertNotIn("#999999", focus)
        self.assertEqual(style.button_effect_look(look)["focus"][0]["colors"]["top"], "#ff0a0b0c")
        self.assertEqual(style.button_state_value(look, "button_focus_color"), "#123456")
        own = dict(look, button_focus_ovr_color=True)                    # surchargée : la sienne
        self.assertIn("#999999", style.button_state_css(own, "focus"))
        chain = dict(look, **self._flags("active", False), button_active_follow="focus")   # enfoncé -> focus -> survol
        self.assertIn("#123456", style.button_state_css(chain, "enfonce").split("padding")[1])
        loop = dict(look, **self._flags("hover", False), button_hover_follow="focus")      # survol <-> focus
        self.assertEqual(style._state_css(style.button_state_look(loop), "focus"), "")     # = le standard

    def test_the_follow_list_in_the_window(self):
        values = dict(settings_store.DEFAULT_SETTINGS, **self._flags("focus", False), button_hover_ovr_color=True,
                      button_hover_color="#123456")
        fields = {}
        frame = v2.build_group("Bouton", v2.ScopeValues(values), {}, fields, {}, [], record=[])
        self.addCleanup(frame.deleteLater)
        spec = next(s for s in v2.CATALOG["Bouton"] if s.key == "button_focus_follow")
        row = fields[spec.key]
        follow = row._v2_follow
        self.assertNotIn("Focus", [t for _k, t in follow._choices])     # jamais lui-même
        self.assertEqual(row._v2_reset.height(), follow.height())        # bouton de la hauteur de la liste
        self.assertEqual(v2.read_spec(spec, row), {"button_focus_follow": "standard"})
        follow.setValue("Survol")
        follow.changed.emit("Survol")
        self.assertEqual(fields["button_focus_color"].value(), "#123456")   # la ligne grisée montre celle du survol
        self.assertEqual(v2.read_spec(spec, row), {"button_focus_follow": "hover"})
        self.assertTrue(v2.write_spec(spec, row, dict(values, button_focus_follow="standard")))
        self.assertEqual(follow.value(), "Standard")
        keys = [s.key for s in v2.CATALOG["Bouton"]]
        for state in ("hover", "focus", "active"):                       # une ligne « suit » en tête de chaque état
            self.assertEqual(keys[keys.index(f"button_{state}_color") - 1], f"button_{state}_follow")

    def test_a_row_without_override_shows_its_driver_live(self):
        """Demande de l'utilisateur (2026-11-12) : l'override est prioritaire ; coupé, la ligne est grisée coûte que
        coûte et montre les valeurs RÉELLES de la ligne qui la pilote (« activer » compris), en direct."""
        values = dict(settings_store.DEFAULT_SETTINGS, button_shadow_enabled=dict.fromkeys(self.SIDES, True),
                      button_shadow=dict.fromkeys(self.SIDES, "#ff000000"), button_shadow_size=3,
                      button_focus_follow="hover", **self._flags("hover", False), **self._flags("focus", False))
        fields = {}
        frame = v2.build_group("Bouton", v2.ScopeValues(values), {}, fields, {}, [], record=[])
        self.addCleanup(frame.deleteLater)
        standard, hover, focus = (fields[f"button_{p}shadow_enabled"] for p in ("", "hover_", "focus_"))
        standard._v2_active.setChecked(False)                            # la ligne standard coupée
        for row in (hover, focus):                                       # focus suit le survol, qui suit le standard
            self.assertFalse(row._v2_active.isChecked())
            self.assertFalse(row.isEnabled())                            # grisée
        standard._v2_active.setChecked(True)
        v2.slider_fields(standard)[-1].setValue(5)
        spec = next(s for s in v2.CATALOG["Bouton"] if s.key == "button_focus_shadow_enabled")
        self.assertEqual(v2.read_spec(spec, focus)["button_focus_shadow_size"], 5)
        self.assertTrue(focus._v2_active.isChecked())
        self.assertFalse(focus.isEnabled())
        fields["button_bg_color"].setValue("#abcdef")
        fields["button_bg_color"].changed.emit("#abcdef")
        self.assertEqual(fields["button_focus_color"].value(), "#abcdef")

    def test_copy_button_takes_the_row_of_the_followed_state(self):
        """Demande de l'utilisateur (2026-11-12) : petit bouton à icône sur chaque ligne des états : la ligne prend celle
        de l'état choisi dans la liste « suit », surchargée donc modifiable ; les autres lignes ne bougent pas."""
        values = dict(settings_store.DEFAULT_SETTINGS, **self._flags("focus", False), button_active_ovr_color=True,
                      button_active_color="#223344", button_active_offset_x=2, button_focus_follow="active")
        fields = {}
        frame = v2.build_group("Bouton", v2.ScopeValues(values), {}, fields, {}, [], record=[])
        self.addCleanup(frame.deleteLater)
        color, offset = fields["button_focus_color"], fields["button_focus_offset_x"]
        self.assertTrue(color._v2_copy._fm_theme_button)                # aspect : fm_theme
        self.assertEqual(color._v2_copy.iconSize().width(), 14)
        for row in (color, offset):                                      # 1re position de la ligne
            self.assertIs(row._v2_copy.parentWidget().layout().itemAt(0).widget(), row._v2_copy)
        self.assertIsNone(getattr(fields["button_focus_follow"], "_v2_copy", None))
        color._v2_copy.click()
        self.assertTrue(color._v2_override.isChecked())
        self.assertTrue(color.isEnabled())
        self.assertEqual(color.value(), "#223344")
        self.assertFalse(fields["button_focus_border_enabled"]._v2_override.isChecked())
        self.assertEqual(offset._v2_parts["x"].value(), 0)
        offset._v2_copy.click()
        self.assertEqual(offset._v2_parts["x"].value(), 2)

    def test_unfolding_a_state_folds_the_other_states(self):
        """Demande de l'utilisateur (2026-11-12) : déplier un état du bouton (Survol, Focus, Enfoncé) replie les
        autres ; la partie standard (main) n'est jamais touchée."""
        fields = {}
        frame = v2.build_group("Bouton", v2.ScopeValues(dict(settings_store.DEFAULT_SETTINGS)), {}, fields, {}, [],
                               record=[])
        self.addCleanup(frame.deleteLater)
        table = next(w for w in [frame, *frame.findChildren(QWidget)]
                     if getattr(getattr(w, "_extra_dims", None), "accordion", None) is not None)
        state = table._extra_dims
        rows = {r: f"r{r}" for r in (0, 2, 9, 16, 23)}           # main, survol, focus, enfoncé, main (suite)
        state.splits = {r: 8 for r in rows if r}
        state.above_texts = dict(rows)
        state.collapsed = {0, 9, 16}
        state.toggle_collapsed(9)                                  # focus déplié : survol et enfoncé repliés
        self.assertEqual(state.collapsed, {0, 2, 16})
        state.toggle_collapsed(23)                                 # main : rien d'autre ne bouge
        self.assertEqual(state.collapsed, {0, 2, 16, 23})
        state.toggle_collapsed(0)
        self.assertEqual(state.collapsed, {2, 16, 23})

    def test_reset_gives_the_state_exactly_the_chosen_one(self):
        """Demande de l'utilisateur (2026-11-12) : bouton « Réinitialiser » à côté de la liste, sur la ligne « suit »
        de l'état : l'état prend EXACTEMENT l'état choisi (toutes ses lignes), modifiable ensuite."""
        from fm_theme import style
        values = dict(settings_store.DEFAULT_SETTINGS, **self._flags("focus", False), button_active_ovr_color=True,
                      button_active_color="#223344", button_active_offset_x=2, button_active_offset_y=1,
                      button_active_ovr_shadow=True, button_active_shadow_enabled=dict.fromkeys(self.SIDES, True),
                      button_active_shadow=dict.fromkeys(self.SIDES, "#ff0a0b0c"), button_active_shadow_size=4)
        fields = {}
        frame = v2.build_group("Bouton", v2.ScopeValues(values), {}, fields, {}, [], record=[])
        self.addCleanup(frame.deleteLater)
        focus = fields["button_focus_follow"]
        focus._v2_follow.setValue("Enfoncé")
        focus._v2_reset.click()
        current = dict(values)
        for spec in v2.CATALOG["Bouton"]:
            current.update(v2.read_spec(spec, fields[spec.key]))
        for row in ("color", "border", "font", "radius", "shadow"):
            self.assertTrue(current[f"button_focus_ovr_{row}"], row)     # tout surchargé : modifiable
        self.assertTrue(fields["button_focus_font_family"].isEnabled())
        states = style.button_state_look(current)
        self.assertEqual(states["focus"], "#223344")
        for part in ("", "_text", "_font"):
            self.assertEqual(states[f"focus{part}"], states[f"active{part}"], part)
        self.assertEqual(style._border_state_css(states["focus_border"]), style._border_state_css(states["active_border"]))
        effect = style.button_effect_look(current)
        self.assertEqual(effect["focus"], effect["active"])              # ombre et décalage compris
        focus._v2_follow.setValue("Standard")                            # l'état standard : le bouton au repos
        focus._v2_reset.click()
        for spec in v2.CATALOG["Bouton"]:
            current.update(v2.read_spec(spec, fields[spec.key]))
        rest = style.button_state_css(current, "standard").split("padding")[0]
        self.assertIn(style.button_state_look(current)["focus"], rest)
        self.assertEqual((current["button_focus_offset_x"], current["button_focus_offset_y"]), (0, 0))
        self.assertIsNone(style.button_effect_look(current)["focus"][0])

    def test_old_settings_keep_their_look(self):
        """Toggles jamais enregistrés : déduits des valeurs, le QSS par défaut est celui d'avant (survol et enfoncé
        teintés par le thème, texte sur accent ; focus inchangé)."""
        from fm_theme import style
        states = style.button_state_look({})
        self.assertEqual(states["hover"], style.C["btn_hover"])
        self.assertEqual(states["active"], style.C["accent"])
        self.assertEqual(states["active_text"], style.C["accent_text"])
        self.assertEqual(style._state_css(states, "focus"), "")
        self.assertTrue(style.button_state_override({"button_hover_font_bold": True}, "hover", "font"))
        self.assertTrue(style.button_state_value({"button_font_bold": True, "button_active_font_bold": False},
                                                 "button_active_font_bold"))   # ancien gras coupé = le standard

    def test_window_rows_follow_and_save_the_override(self):
        """Fenêtre de réglages : toggle devant chaque ligne d'état ; coupé = ligne grisée qui montre la ligne standard ;
        l'état du toggle est lu, enregistré et reposé (variantes, presets)."""
        values = dict(settings_store.DEFAULT_SETTINGS, button_font_size=19, button_active_ovr_font=False,
                      button_active_font_size=31)
        fields = {}
        frame = v2.build_group("Bouton", v2.ScopeValues(values), {}, fields, {}, [], record=[])
        self.addCleanup(frame.deleteLater)
        spec = next(s for s in v2.CATALOG["Bouton"] if s.key == "button_active_font_family")
        field = fields[spec.key]
        self.assertFalse(field._v2_override.isChecked())
        self.assertFalse(field.isEnabled())                              # grisée
        self.assertEqual(field._v2_parts["size"].value(), 19)            # montre la ligne standard
        self.assertFalse(v2.read_spec(spec, field)["button_active_ovr_font"])
        field._v2_override.setChecked(True)
        self.assertTrue(field.isEnabled())
        self.assertTrue(v2.read_spec(spec, field)["button_active_ovr_font"])
        self.assertTrue(v2.write_spec(spec, field, dict(values, button_active_ovr_font=True)))
        self.assertEqual(field._v2_parts["size"].value(), 31)            # surchargée : ses propres valeurs
        self.assertTrue(v2.write_spec(spec, field, values))
        self.assertFalse(field._v2_override.isChecked())
        self.assertEqual(field._v2_parts["size"].value(), 19)
        for state in ("hover", "focus", "active"):                       # toutes les lignes d'état sauf le décalage
            for key in ("color", "border_enabled", "font_family", "corner_radius", "shadow_enabled"):
                self.assertIsNotNone(getattr(fields[f"button_{state}_{key}"], "_v2_override", None), (state, key))
            self.assertIsNone(getattr(fields[f"button_{state}_offset_x"], "_v2_override", None))


class ButtonShadowTest(unittest.TestCase):
    """Remarque de l'utilisateur (2026-11-11) : « les ombres des boutons ne fonctionnent pas » (seuls les boutons de la
    fenêtre principale présents au rafraîchissement l'avaient). Le style commun la pose sur TOUT bouton."""

    ON = {"button_shadow_enabled": dict.fromkeys(("top", "right", "bottom", "left"), True),
          "button_shadow": dict.fromkeys(("top", "right", "bottom", "left"), "#ff102030"), "button_shadow_size": 6}

    def setUp(self):
        from fm_theme import style
        self.style = style
        saved = style._CONTROL_LOOK
        style.apply_style(APP)
        self.addCleanup(style.set_control_look, saved)

    def test_every_new_button_gets_the_shadow_and_loses_it_when_turned_off(self):
        from PySide6.QtWidgets import QGraphicsDropShadowEffect, QPushButton
        self.style.set_control_look(dict(self.ON))
        host = QWidget()                                   # une fenêtre quelconque, créée APRÈS le réglage
        self.addCleanup(host.deleteLater)
        button = QPushButton("Bouton", host)
        host.show()
        APP.processEvents()
        effect = button.graphicsEffect()
        self.assertIsInstance(effect, QGraphicsDropShadowEffect)
        self.assertEqual(effect.color().name(), "#102030")
        self.assertEqual(effect.blurRadius(), 12)
        self.style.set_control_look({})                    # ombre éteinte : retirée des boutons existants
        self.assertIsNone(button.graphicsEffect())

    def test_custom_widgets_built_on_buttons_get_no_shadow(self):
        """Signalé (2026-11-11, capture) : halo sombre autour du champ de choix et des pastilles de couleur des
        réglages, widgets maison qui héritent de QPushButton."""
        from PySide6.QtWidgets import QPushButton
        from fm_theme.widgets import _ColorSwatchButton, _SelectField
        self.style.set_control_look(dict(self.ON))
        host = QWidget()
        self.addCleanup(host.deleteLater)
        plain = QPushButton("Bouton", host)
        select = _SelectField(["Police principale"], "Police principale")
        select.setParent(host)
        swatch = _ColorSwatchButton(host)
        host.show()
        APP.processEvents()
        self.assertIsNotNone(plain.graphicsEffect())
        self.assertIsNone(select.graphicsEffect())
        self.assertIsNone(swatch.graphicsEffect())

    def test_variant_preview_keeps_its_own_shadow(self):
        from PySide6.QtWidgets import QPushButton
        self.style.set_control_look({})
        button = QPushButton("Bouton")
        self.addCleanup(button.deleteLater)
        self.style.set_own_button_shadow(button, dict(self.ON))
        self.assertIsNotNone(button.graphicsEffect())
        self.style.set_control_look({"button_shadow_size": 0})
        self.style.refresh_button_shadows()
        self.assertIsNotNone(button.graphicsEffect())      # jamais remplacée par l'ombre du thème

    def test_state_offset_and_shadow(self):
        """Demande de l'utilisateur (2026-11-11) : survol / focus / enfoncé ont un décalage (X, Y : -3..+3 px) et une
        ombre propre (aucun côté = celle de l'état standard)."""
        from PySide6.QtWidgets import QPushButton
        look = dict(self.ON, button_active_offset_x=1, button_active_offset_y=9,      # 9 : borné à +3
                    button_hover_shadow_enabled=dict.fromkeys(("top", "right", "bottom", "left"), True),
                    button_hover_shadow=dict.fromkeys(("top", "right", "bottom", "left"), "#ff405060"),
                    button_hover_shadow_size=3)
        looks = self.style.button_effect_look(look)
        self.assertEqual(looks["active"][1], (1, 3))
        self.assertEqual(looks["active"][0], looks["standard"][0])       # pas d'ombre propre : la standard
        self.assertEqual(looks["hover"][0]["size"], 3)
        self.assertIsNone(self.style.button_effect_look({}))             # ni ombre ni décalage : pas d'effet
        self.assertIsNotNone(self.style.button_effect_look({"button_focus_offset_y": -2}))
        button = QPushButton("Bouton")
        self.addCleanup(button.deleteLater)
        self.style.set_own_button_shadow(button, look)
        effect = button.graphicsEffect()
        button._state = "survol"                          # aperçu figé dans l'état survol
        effect._show(effect._state())
        self.assertEqual(effect.color().name(), "#405060")
        self.assertEqual(effect.blurRadius(), 6)
        button._state = "enfonce"
        effect._show(effect._state())
        self.assertEqual(effect.color().name(), "#102030")
        self.assertGreaterEqual(effect.boundingRectFor(QRectF(0, 0, 10, 10)).width(), 10 + 2 * 3)

    def test_every_state_shadow_and_offset_combination_is_painted(self):
        """Signalé 2026-11-12 : « ombre du bouton standard coupée = plus de décalage de l'enfoncé » (sans ombre, Qt
        dessinait la source sans la translation). Toutes les combinaisons, vérifiées au pixel : état (survol, focus,
        enfoncé) × ombre standard × ombre propre à l'état × décalage."""
        from PySide6.QtGui import QColor
        from PySide6.QtWidgets import QPushButton
        sides = ("top", "right", "bottom", "left")
        x0, y0, w, h = 60, 40, 60, 30
        failures = []
        for state, prefix in (("survol", "hover"), ("focus", "focus"), ("enfonce", "active")):
            for standard in (False, True):
                for own in (False, True):
                    for dx, dy in ((0, 0), (3, 3), (-2, 1)):
                        look = {"button_shadow_enabled": dict.fromkeys(sides, standard),
                                "button_shadow": dict.fromkeys(sides, "#ff000000"), "button_shadow_size": 4,
                                f"button_{prefix}_shadow_enabled": dict.fromkeys(sides, own),
                                f"button_{prefix}_shadow": dict.fromkeys(sides, "#ff000000"),
                                f"button_{prefix}_shadow_size": 4,
                                f"button_{prefix}_offset_x": dx, f"button_{prefix}_offset_y": dy}
                        host = QWidget()
                        host.resize(220, 130)
                        host.setStyleSheet("background: #ffffff;")
                        button = QPushButton("", host)
                        button.setGeometry(x0, y0, w, h)
                        button.setStyleSheet("background: #0000ff; border: none;")
                        button._state = state
                        self.style.set_own_button_shadow(button, look)
                        host.show()
                        APP.processEvents()
                        image = host.grab().toImage()
                        host.deleteLater()
                        name = f"{state} standard={standard} propre={own} decalage={(dx, dy)}"
                        body = QColor(image.pixel(x0 + dx + w // 2, y0 + dy + h // 2)).name()
                        corner = QColor(image.pixel(x0 + dx + 1, y0 + dy + 1)).name()
                        if (body, corner) != ("#0000ff", "#0000ff"):
                            failures.append(f"{name} : bouton pas a sa place ({body}, {corner})")
                        if dx or dy:          # le coin d'origine est decouvert du cote oppose au decalage
                            gone = QColor(image.pixel(x0 + (w - 1 if dx < 0 else 0), y0 + (h - 1 if dy < 0 else 0)))
                            if gone.name() == "#0000ff":
                                failures.append(f"{name} : bouton non decale")
                        outside = QColor(image.pixel(x0 + dx - 2, y0 + dy + h // 2)).red()
                        if (standard or own) and outside > 245:
                            failures.append(f"{name} : ombre absente ({outside})")
                        if not (standard or own) and outside != 255:
                            failures.append(f"{name} : ombre en trop ({outside})")
        self.assertEqual(failures, [])

    def test_pressed_shadow_is_inside_the_effect_area_whatever_the_state(self):
        """Signalé 2026-11-12 : ombre de l'état enfoncé sans effet. Zone de l'effet calculée sur l'état standard (sans
        ombre) : l'ombre de l'enfoncé, réglée pendant la peinture, était rognée. Zone FIXE, la même dans tous les états."""
        from PySide6.QtWidgets import QPushButton
        sides = ("top", "right", "bottom", "left")
        look = {"button_active_shadow_enabled": dict.fromkeys(sides, True),
                "button_active_shadow": dict.fromkeys(sides, "#ff000000"), "button_active_shadow_size": 10}
        button = QPushButton("Bouton")
        self.addCleanup(button.deleteLater)
        self.style.set_own_button_shadow(button, look)
        effect = button.graphicsEffect()
        rect = QRectF(0, 0, 100, 40)
        standard = effect.boundingRectFor(rect)
        self.assertGreaterEqual(-standard.top(), 20)                     # flou de l'enfoncé (10 × 2) compris
        button._state = "enfonce"
        effect._show(effect._state())
        self.assertEqual(effect.boundingRectFor(rect), standard)
        self.assertTrue(standard.contains(effect.boundingRectFor(rect)))

    def test_offset_row_reads_and_writes(self):
        import settings_store
        spec = next(s for s in v2.CATALOG["Bouton"] if s.key == "button_active_offset_x")
        self.assertEqual(spec.kind, "offset")
        widget = v2.make_field(spec, v2.ScopeValues(dict(settings_store.DEFAULT_SETTINGS)), {})
        self.assertEqual(v2.read_spec(spec, widget), {"button_active_offset_x": 0, "button_active_offset_y": 0})
        self.assertTrue(v2.write_spec(spec, widget, {"button_active_offset_x": -2, "button_active_offset_y": 3}))
        self.assertEqual(v2.read_spec(spec, widget), {"button_active_offset_x": -2, "button_active_offset_y": 3})
        for state in ("hover", "focus", "active"):
            keys = [s.key for s in v2.CATALOG["Bouton"]]
            self.assertIn(f"button_{state}_shadow_enabled", keys)
            self.assertIn(f"button_{state}_shadow_size", settings_store.DEFAULT_SETTINGS)


class PreviewWidthTest(unittest.TestCase):
    def test_the_preview_width_follows_the_right_edge(self):
        from fm_theme import preview
        panel = PreviewPanel(lambda: dict(settings_store.DEFAULT_SETTINGS), width=300)
        try:
            panel.resize(300, 500)
            panel.show()
            APP.processEvents()
            done = []
            panel.widthChanged.connect(done.append)
            grip = panel._grip
            self.assertEqual(grip.x(), panel.width() - grip.width())     # bord DROIT : le volet est à gauche
            QTest.mousePress(grip, Qt.LeftButton, Qt.NoModifier, QPoint(2, 100))
            QTest.mouseMove(grip, QPoint(102, 100))
            QTest.mouseRelease(grip, Qt.LeftButton, Qt.NoModifier, QPoint(102, 100))
            self.assertEqual(panel.width(), 400)
            self.assertEqual(done, [400])
            panel.set_panel_width(5)
            self.assertEqual(panel.width(), preview.MIN_WIDTH)
        finally:
            panel.deleteLater()


if __name__ == "__main__":
    unittest.main()
