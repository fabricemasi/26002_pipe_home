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
from PySide6.QtCore import QEvent, QPoint, Qt  # noqa: E402
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
        self.assertEqual(set(PALETTE_DEFAULTS) - covered, set())
        self.assertEqual({k for k in covered if k.startswith("palette_")} - set(PALETTE_DEFAULTS), set())

    def test_the_section_is_in_the_theme_editor(self):
        self.assertIn("Palette", v2.THEME_SECTIONS)
        node = next(n for n in v2.theme_tree() if n.title == "Palette")
        self.assertEqual([c.title for c in node.children], ["Grille", "Barre", "En-tête", "Icônes", "Contrôleur"])
        controller = next(c for c in node.children if c.title == "Contrôleur")
        self.assertEqual([c.title for c in controller.children], ["Slider", "Liste déroulante", "Zone de saisie", "Toggle"])
        self.assertNotIn("Palette", [n.title for n in v2.tab_tree("General")])
        import theme_editor
        self.assertEqual(theme_editor.SECTION_TYPES["Palette"], "palette")

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
            panel.show_section("Palette")
            bars = panel.findChildren(P.ToolBar)
            self.assertEqual(sorted(b.title() for b in bars), ["Contrôleurs", "Créer", "Outils"])
            self.assertTrue(all(b.size() == b.natural_size() for b in bars))
            self.assertTrue(all(b.manager is not None for b in bars))        # le vrai système
            self.assertIn("Palette", [s for s in panel._builders])
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


class PreviewWidthTest(unittest.TestCase):
    def test_the_preview_width_follows_the_left_edge(self):
        from fm_theme import preview
        panel = PreviewPanel(lambda: dict(settings_store.DEFAULT_SETTINGS), width=300)
        try:
            panel.resize(300, 500)
            panel.show()
            APP.processEvents()
            done = []
            panel.widthChanged.connect(done.append)
            grip = panel._grip
            QTest.mousePress(grip, Qt.LeftButton, Qt.NoModifier, QPoint(2, 100))
            QTest.mouseMove(grip, QPoint(-98, 100))
            QTest.mouseRelease(grip, Qt.LeftButton, Qt.NoModifier, QPoint(-98, 100))
            self.assertEqual(panel.width(), 400)
            self.assertEqual(done, [400])
            panel.set_panel_width(5)
            self.assertEqual(panel.width(), preview.MIN_WIDTH)
        finally:
            panel.deleteLater()


if __name__ == "__main__":
    unittest.main()
