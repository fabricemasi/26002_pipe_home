"""Barre de navigation (2026-11-07) : cheminement pose sur la bordure du bas sans arrondi en bas, hauteurs de la barre
(1re ligne + hauteur additionnelle), icone fm_theme teintee (`IconButton.set_icon_tint`), coins carres d'une fenetre agrandie
(`fm_theme.style.fills_screen`)."""
import _isolate  # noqa: F401
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QColor, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication, QMainWindow, QWidget  # noqa: E402

import pipeline_browser  # noqa: E402,F401  (ordre des imports de l'appli)
import ui_state  # noqa: E402
from settings_store import DEFAULT_SETTINGS  # noqa: E402
from main_window.title_bar import TitleBar, _CrumbChip  # noqa: E402
from preview_column import IconButton  # noqa: E402
from fm_theme.style import fills_screen  # noqa: E402

APP = QApplication.instance() or QApplication([])


class NavbarLookTest(unittest.TestCase):
    def setUp(self):
        self._saved = ui_state.APPLIED_SETTINGS
        self.settings = dict(DEFAULT_SETTINGS, crumb_corner_radius=6, navbar_bottom_thickness=2)
        ui_state.APPLIED_SETTINGS = self.settings
        self.window = QMainWindow()
        self.bar = TitleBar(self.window)
        self.bar.resize(800, 10)
        self.bar.refresh_look()
        self.bar.refresh_sizes()

    def tearDown(self):
        ui_state.APPLIED_SETTINGS = self._saved
        self.bar.deleteLater()
        self.window.deleteLater()

    def test_crumbs_sit_on_the_bottom_border_without_bottom_radius(self):
        self.bar.set_crumbs([("set", "PROJET", lambda: None), ("after", "SHOT", lambda: None)], force=True)
        self.bar.crumbs.layout().activate()
        self.assertEqual(self.bar.crumbs.geometry().bottom() + 1, self.bar.height() - 2)   # juste sur le filet
        chips = self.bar.crumbs.findChildren(_CrumbChip)
        self.assertTrue(chips)
        for chip in chips:
            self.assertEqual(chip._below, 0)
            self.assertEqual(chip.geometry().bottom() + 1, self.bar.crumbs.height())
            self.assertEqual((chip._radius["bottom_left"], chip._radius["bottom_right"]), (0, 0))
            self.assertEqual(chip._radius["top_left"], 6)

    def test_first_row_height_plus_extra_and_centred_items(self):
        self.settings.update(navbar_height=30, navtool_extra_height=70)
        self.bar.refresh_sizes()
        self.assertEqual(self.bar.height(), 100)
        for widget in (self.bar.title_label, self.bar.btn_min, self.bar.btn_close):
            self.assertEqual(widget.height(), 30)                   # toute la 1re ligne : centres dessus
        self.assertEqual(self.bar.layout().contentsMargins().bottom(), 70)
        self.settings.update(navtool_extra_height=0)
        self.bar.refresh_sizes()
        self.assertGreaterEqual(self.bar.height(), 30 + self.bar._crumb_row_height())   # jamais sous le cheminement

    def _chips(self):
        import main_window.title_bar as title_bar
        title_bar._CRUMB_LOOK_CACHE[:] = [None, None]     # reglages modifies sur place : habillage a refaire
        self.bar.refresh_sizes()
        self.bar.set_crumbs([("set", "PROJET", lambda: None), ("set", "SEQ", lambda: None),
                             ("after", "SHOT", lambda: None)], force=True)
        self.bar.crumbs.layout().activate()
        return [self.bar._crumb_layout.itemAt(i).widget() for i in range(3)]

    def test_zero_spacing_touching_and_left_spacing(self):
        """Espacement 0 = onglets jointifs ; « Espacement a gauche » avant le 1er (2026-11-07)."""
        self.settings.update(crumb_spacing=0, crumb_left_spacing=37)
        chips = self._chips()
        boxes = [chip.box_rect().translated(chip.pos()) for chip in chips]
        self.assertEqual(boxes[0].left() + self.bar.crumbs.x(), 37)
        for left, right in zip(boxes, boxes[1:]):
            self.assertEqual(left.right() + 1, right.left())

    def _cut_image(self, **settings):
        self.settings.update(navbar_bottom_color="#ff0000", crumb_bg_color="#00ff00", crumb_border="#0000ff",
                             crumb_border_enabled={"top": True, "right": True, "bottom": True, "left": True},
                             crumb_border_thickness=1, **settings)
        chips = self._chips()
        self.bar.refresh_look()
        self.bar.crumbs.layout().activate()
        return chips, self.bar.grab().toImage()

    def _column(self, chip):
        return chip.box_rect().translated(chip.pos() + self.bar.crumbs.pos()).center().x()

    def test_cut_border_under_the_active_tab_only(self):
        """« Couper la bordure (onglet actif) » : ni filet ni bordure basse sous l'onglet actif ; les autres restent
        au-dessus du filet (2026-11-08)."""
        self.settings.update(crumb_cut_border_active=True, crumb_cut_border_others=False)
        import main_window.title_bar as title_bar
        title_bar._CRUMB_LOOK_CACHE[:] = [None, None]
        self.bar.refresh_sizes()
        self.bar.set_crumbs([("set", "PROJET", lambda: None), ("set!", "SEQ", lambda: None),
                             ("after_focus", "SHOT", lambda: None)], force=True)
        self.settings.update(navbar_bottom_color="#ff0000", crumb_bg_color="#00ff00", crumb_border="#0000ff",
                             crumb_border_enabled={"top": True, "right": True, "bottom": True, "left": True},
                             crumb_border_thickness=1)
        title_bar._CRUMB_LOOK_CACHE[:] = [None, None]
        self.bar.refresh_look()
        self.bar.crumbs.layout().activate()
        chips = [self.bar._crumb_layout.itemAt(i).widget() for i in range(3)]
        image = self.bar.grab().toImage()
        bottom = self.bar.height() - 1
        self.assertEqual(self.bar.crumbs.geometry().bottom() + 1, self.bar.height())   # descend sur le filet
        for y in (bottom, bottom - 1, bottom - 2):                   # sous l'actif : le fond de l'onglet
            self.assertEqual(image.pixelColor(self._column(chips[1]), y).name(), "#00ff00", y)
        for chip in (chips[0], chips[2]):                            # les autres : le filet rouge reste dessous
            self.assertEqual(image.pixelColor(self._column(chip), bottom).name(), "#ff0000")
            self.assertEqual(chip._below, 2)
        self.assertIn("transparent", self.bar.styleSheet())

    def test_cut_border_under_the_other_tabs_only(self):
        self.settings.update(crumb_cut_border_active=False, crumb_cut_border_others=True)
        chips, image = self._cut_image()          # « set », « set », « after » : aucun actif, tous coupes
        bottom = self.bar.height() - 1
        for chip in chips:
            self.assertTrue(chip._cut)
            self.assertEqual(image.pixelColor(self._column(chip), bottom).name(), "#00ff00")
        self.assertEqual(image.pixelColor(self.bar.width() - 5, bottom).name(), "#ff0000")   # ailleurs : le filet

    def test_fm_browser_overrides_bottom_border_title_font_and_height(self):
        """fm_browser > Barre de navigation : bordure basse, police du titre, hauteur de fm_theme surchargeables
        (`navtool_ovr_*`, coupe = la valeur de fm_theme ; 2026-11-07)."""
        own = dict(navtool_height=40, navtool_bottom_enabled=True, navtool_bottom_thickness=4,
                   navtool_title_font_size=19, navbar_height=30, navbar_bottom_thickness=1, navbar_title_font_size=11)

        def apply(**overrides):
            ui_state.APPLIED_SETTINGS = dict(self.settings, **own, **overrides)
            self.bar.refresh_look()
            self.bar.refresh_sizes()
            return self.bar._row_height(), self.bar._bottom_border_px, self.bar.title_label.font().pixelSize()

        row, border, size = apply()
        self.assertEqual((row, border), (30, 1))                           # overrides coupes : fm_theme
        self.assertEqual(apply(navtool_ovr_height=True)[0], 40)
        self.assertEqual(self.bar.title_label.height(), 40)
        self.assertEqual(apply(navtool_ovr_bottom_enabled=True)[1], 4)
        self.assertNotEqual(apply(navtool_ovr_title_font_family=True)[2], size)

    def test_override_rows_follow_fm_theme_while_off(self):
        import settings_window_v2 as v2
        values = v2.ScopeValues({**DEFAULT_SETTINGS, "navbar_height": 33, "navtool_height": 50})
        self.assertEqual(values.seed("navtool_height", 0), 33)             # override coupe : la valeur de fm_theme
        values.settings["navtool_ovr_height"] = True
        self.assertEqual(values.seed("navtool_height", 0), 50)
        rows = {sp.key: sp.general_toggle for sp in v2.CATALOG["Barre de navigation (appli)"]}
        self.assertEqual(rows["navtool_bottom_enabled"], "navtool_ovr_bottom_enabled")
        self.assertEqual(rows["navtool_title_font_family"], "navtool_ovr_title_font_family")
        self.assertEqual(rows["navtool_height"], "navtool_ovr_height")

    def test_tool_buttons_take_the_icon_look(self):
        browse = IconButton("browse", "#ffffff", "#ffffff")
        self.bar._tool_buttons = [browse]
        self.settings.update(navtool_bg_color="#112233", navtool_hover_bg_color="#445566",
                             navtool_corner_radius={"top_left": 4, "top_right": 4, "bottom_right": 4, "bottom_left": 4},
                             navtool_border_enabled={"top": True, "right": True, "bottom": True, "left": True},
                             navtool_border_thickness=2)
        self.bar.refresh_look()
        bg, enabled, _colors, thickness, radius = browse._frame
        self.assertEqual((bg, thickness, radius["top_left"]), ("#112233", 2, 4))
        self.assertTrue(all(enabled.values()))
        self.assertEqual(browse._hover_bg, "#445566")
        browse.deleteLater()


class NavbarIconsTest(unittest.TestCase):
    """Icones de la barre CARREES, marge reglable (`navtool_margin`) : a 0 elles se touchent (2026-11-07)."""

    def setUp(self):
        self._saved = ui_state.APPLIED_SETTINGS
        self.settings = dict(DEFAULT_SETTINGS, navbar_height=30)
        ui_state.APPLIED_SETTINGS = self.settings
        self.window = QMainWindow()
        self.bar = TitleBar(self.window)
        from PySide6.QtWidgets import QLineEdit
        self.buttons = [IconButton(kind, "#fff", "#fff") for kind in ("browse", "presets", "gear", "gear", "viewer")]
        holder = QWidget()
        from PySide6.QtWidgets import QHBoxLayout
        holder.select = QLineEdit()                     # le menu des presets (PresetPicker.select)
        QHBoxLayout(holder).addWidget(holder.select)
        self.root_field = QLineEdit()
        self.bar.add_tools(self.root_field, self.buttons[0], holder, *self.buttons[1:])
        self.bar.resize(900, 100)

    def tearDown(self):
        ui_state.APPLIED_SETTINGS = self._saved
        self.window.deleteLater()

    def test_square_and_touching_at_zero_margin(self):
        self.settings["navtool_margin"] = {"left": 0, "top": 0, "right": 0, "bottom": 0}
        self.settings["navtool_icon_size"] = 30
        self.bar.refresh_sizes()
        self.bar.layout().activate()
        icons = self.buttons[1:]
        icons[0].parentWidget().layout().activate()
        for button in icons:
            self.assertEqual((button.width(), button.height()), (30, 30))
            self.assertEqual(button._inner_rect().width(), button._inner_rect().height())
        for left, right in zip(icons, icons[1:]):
            self.assertEqual(left.geometry().right() + 1, right.geometry().left())     # se touchent
        self.assertEqual((self.bar.btn_min.width(), self.bar.btn_min.height()), (30, 30))

    def test_margin_goes_around_the_square(self):
        self.settings["navtool_margin"] = {"left": 3, "top": 2, "right": 5, "bottom": 4}
        self.bar.refresh_sizes()
        button = self.buttons[1]
        self.assertEqual((button.width(), button.height()), (3 + 24 + 5, 30))
        inner = button._inner_rect()
        self.assertEqual((inner.x(), inner.y(), inner.width(), inner.height()), (3, 2, 24, 24))

    def test_icon_size_padding_and_fields_aligned_on_the_icons(self):
        self.settings.update(navtool_icon_size=20, navtool_margin={"left": 1, "top": 1, "right": 1, "bottom": 5},
                             navtool_padding={"left": 2, "top": 3, "right": 2, "bottom": 3})
        self.bar.refresh_sizes()
        self.bar.resize(900, 100)
        self.window.resize(900, 100)
        self.bar.show()
        QApplication.processEvents()
        button = self.buttons[1]
        self.assertEqual((button.width(), button.height()), (1 + 20 + 1, 1 + 20 + 5))
        icon = button._icon_rect()
        self.assertEqual((icon.x(), icon.y(), icon.width(), icon.height()), (3, 4, 16, 14))
        frame_top = button.mapTo(self.bar, button._inner_rect().topLeft()).y()
        for field in (self.root_field, self.bar._picker.select):
            self.assertEqual(field.height(), 20)                                   # hauteur du cadre des icones
            self.assertEqual(field.mapTo(self.bar, field.rect().topLeft()).y(), frame_top)   # meme Y
        self.bar.hide()

    def test_icon_size_never_exceeds_the_row(self):
        self.settings.update(navtool_icon_size=80, navtool_margin={"left": 0, "top": 2, "right": 0, "bottom": 2})
        self.bar.refresh_sizes()
        self.assertEqual(self.buttons[1].height(), 30)
        self.assertEqual(self.root_field.height(), 26)


class ModuleGroupTest(NavbarIconsTest):
    """Cadre des modules de la barre (2026-11-08) : boutons a la taille des icones de la barre, habillage
    `viewer_group_btn_*`, nom du module masquable, fond noir par defaut, section dans fm_browser."""

    def test_buttons_take_the_navbar_icon_size_and_look(self):
        self.settings.update(navtool_icon_size=22, navtool_padding={"left": 2, "top": 2, "right": 2, "bottom": 2},
                             viewer_group_btn_bg_color="#112233", viewer_group_btn_icon_color="#abcdef",
                             viewer_group_btn_border_enabled={s: True for s in ("top", "right", "bottom", "left")},
                             viewer_group_btn_border_thickness=2,
                             viewer_group_btn_corner_radius={k: 6 for k in ("top_left", "top_right",
                                                                            "bottom_right", "bottom_left")})
        self.bar.refresh_sizes()
        group = self.bar.board_group()
        button = IconButton("undo", "#999999", "#ffffff", parent=group)
        self.bar.style_group_button(button)
        self.assertEqual((button.width(), button.height()), (22, 22))
        self.assertEqual(button._padding, (2, 2, 2, 2))
        self.assertEqual(button._color, "#abcdef")
        bg, enabled, _colors, thickness, radius = button._frame
        self.assertEqual((bg, thickness, radius["top_left"]), ("#112233", 2, 6))
        self.assertTrue(all(enabled.values()))
        self.bar.release_group_button(button)                     # rendu a la colonne Focus
        self.assertEqual((button._color, button._padding), ("#999999", (0, 0, 0, 0)))
        close = IconButton("close", "#999999", "#ffffff", parent=group)    # fermer le module : survol rouge
        self.bar.style_group_button(close)
        self.assertEqual(QColor(close._hover_bg).name(), "#c42b1c")
        self.assertNotEqual(QColor(button._hover_bg or "#000000").name(), "#c42b1c")

    def test_module_name_toggle_and_black_background(self):
        self.assertEqual(QColor(DEFAULT_SETTINGS["viewer_group_bg_color"]).name(), "#000000")
        group = self.bar.board_group()
        self.assertGreater(group.label_width(), 0)
        with_label = group.content_origin().x()
        self.settings["viewer_group_label_enabled"] = False
        group.restyle()
        self.assertEqual(group.label_width(), 0)
        self.assertLess(group.content_origin().x(), with_label)

    def test_section_in_fm_browser_navbar(self):
        import settings_window_v2 as v2
        keys = {sp.key for sp in v2.CATALOG["Barre de navigation : Cadre des modules"]}
        self.assertLessEqual({"viewer_group_bg_color", "viewer_group_border_enabled", "viewer_group_corner_radius",
                              "viewer_group_label_enabled", "viewer_group_label_font_family",
                              "viewer_group_btn_bg_color", "viewer_group_btn_icon_color",
                              "viewer_group_btn_border_enabled", "viewer_group_btn_corner_radius"}, keys)
        for spec in v2.CATALOG["Barre de navigation : Cadre des modules"]:
            for key in (spec.key, *spec.extra_keys):
                self.assertIn(key, DEFAULT_SETTINGS, key)
        self.assertIn("Cadre des modules", [c.title for c in v2.NAVBAR_APP_NODE.children])
        self.assertNotIn("Visionneuse : Regroupement", v2.CATALOG)


class TextLevelColorsTest(unittest.TestCase):
    def test_three_text_levels_in_the_palette(self):
        """fm_theme > Couleurs : Texte niveau 1 / 2 / 3 (references « @texte1..3 », 2026-11-07)."""
        from fm_theme.style import C, SEMANTIC_COLOR_SLOTS, resolve_color_ref
        labels = {label: (slot, real) for slot, real, label in SEMANTIC_COLOR_SLOTS}
        for level in (1, 2, 3):
            slot, real = labels[f"Texte niveau {level}"]
            self.assertEqual(slot, f"texte{level}")
            self.assertIn(real, DEFAULT_SETTINGS["colors"])
            self.assertEqual(resolve_color_ref(f"@texte{level}"), C[real])


class WindowButtonsTest(unittest.TestCase):
    """fm_theme > Barre de navigation > Boutons fenetre : punaise, reduire, agrandir, fermer CARRES, colles en haut,
    taille / margin / padding / fond / bordures / border radius / fond survol ; punaise toujours visible (2026-11-07)."""

    def setUp(self):
        self._saved = ui_state.APPLIED_SETTINGS
        ui_state.APPLIED_SETTINGS = dict(
            DEFAULT_SETTINGS, navbar_height=30, navbar_winbtn_size=20,
            navbar_winbtn_margin={"left": 2, "top": 3, "right": 4, "bottom": 1},
            navbar_winbtn_padding={"left": 1, "top": 2, "right": 3, "bottom": 4},
            navbar_winbtn_bg_color="#112233", navbar_winbtn_hover_bg_color="#445566",
            navbar_winbtn_corner_radius={"top_left": 5, "top_right": 5, "bottom_right": 5, "bottom_left": 5})
        self.window = QMainWindow()
        self.bar = TitleBar(self.window)
        self.bar.resize(900, 100)
        self.bar.refresh_look()
        self.bar.refresh_sizes()
        self.bar.layout().activate()

    def tearDown(self):
        ui_state.APPLIED_SETTINGS = self._saved
        self.window.deleteLater()

    def test_square_glued_to_the_top_with_margin_padding_and_frame(self):
        buttons = self.bar._window_buttons()
        self.assertEqual(len(buttons), 4)
        for button in buttons:
            self.assertFalse(button.isHidden())                                  # la punaise aussi
            self.assertEqual((button.width(), button.height()), (2 + 20 + 4, 3 + 20 + 1))
            inner = button._inner_rect()
            self.assertEqual((inner.x(), inner.y(), inner.width(), inner.height()), (2, 3, 20, 20))
            icon = button._icon_rect()
            self.assertEqual((icon.width(), icon.height()), (16, 14))
            self.assertEqual(button.geometry().top(), 0)                         # colles en haut
            bg, _enabled, _colors, _thickness, radius = button._frame
            hover = "#c42b1c" if button is self.bar.btn_close else "#445566"     # fermer : son propre survol
            self.assertEqual((bg, radius["top_left"], button._hover_bg), ("#112233", 5, hover))

    def test_touching_at_zero_margin_and_close_hover_setting(self):
        """Margin 0 : les boutons de la fenetre se touchent ; « Fond survol bouton fermer » (2026-11-08)."""
        ui_state.APPLIED_SETTINGS = dict(ui_state.APPLIED_SETTINGS, navbar_winbtn_margin={},
                                         navbar_winbtn_close_hover_bg_color="#00ff00")
        self.bar.refresh_sizes()
        self.bar.refresh_look()
        buttons = self.bar._window_buttons()
        self.bar.show()                                                # barre affichee : mise en page refaite
        APP.processEvents()
        self.addCleanup(self.bar.hide)
        for left, right in zip(buttons, buttons[1:]):
            self.assertEqual(left.geometry().right() + 1, right.geometry().left())
        self.assertEqual(self.bar.btn_close._hover_bg, "#00ff00")
        self.assertEqual(self.bar.btn_min._hover_bg, "#445566")
        import settings_window_v2 as v2
        self.assertIn("navbar_winbtn_close_hover_bg_color",
                      [s.key for s in v2.CATALOG["Barre de navigation : Boutons fenetre"]])

    def test_size_never_exceeds_the_first_row(self):
        ui_state.APPLIED_SETTINGS = dict(ui_state.APPLIED_SETTINGS, navbar_winbtn_size=80,
                                         navbar_winbtn_margin={})
        self.bar.refresh_sizes()
        self.assertEqual(self.bar.btn_close.height(), 30)

    def test_pin_toggles_always_on_top(self):
        from unittest import mock
        from fm_theme.style import C
        with mock.patch("fm_theme.style.set_always_on_top",
                        lambda window, on: setattr(window.window(), "_always_on_top", on)):
            self.bar.set_always_on_top(True, save=False)
            self.assertEqual(self.bar.btn_pin._color, C["accent"])
            self.assertFalse(self.bar.btn_pin.isHidden())
            self.bar.set_always_on_top(False, save=False)
            self.assertEqual(self.bar.btn_pin._color, C["label"])
            self.assertFalse(self.bar.btn_pin.isHidden())

    def test_section_in_fm_theme(self):
        import settings_window_v2 as v2
        labels = [sp.label for sp in v2.CATALOG["Barre de navigation : Boutons fenetre"]]
        self.assertEqual(labels, ["Taille", "Margin", "Padding", "Couleur de fond", "Bordures", "Border radius",
                                  "Fond survol", "Fond survol bouton fermer"])
        self.assertIn("Barre de navigation : Boutons fenetre",
                      [child.group for child in v2.NAVBAR_THEME_NODE.children])
        for spec in v2.CATALOG["Barre de navigation : Boutons fenetre"]:
            self.assertIn(spec.key, DEFAULT_SETTINGS)


class IconTintTest(unittest.TestCase):
    def _source(self):
        source = QPixmap(8, 8)
        source.fill(Qt.transparent)
        from PySide6.QtGui import QPainter
        p = QPainter(source)
        p.fillRect(0, 0, 4, 8, QColor("#808080"))
        p.end()
        return source

    def test_tint_keeps_the_shape(self):
        button = IconButton("gear", "#ffffff", "#ffffff")
        source = self._source()
        button.set_icon_tint("#f28c28")
        image = button._recolored_pixmap(source, button._icon_recolor()).toImage()
        self.assertEqual(image.pixelColor(1, 1).name(), "#f28c28")
        self.assertEqual(image.pixelColor(6, 1).alpha(), 0)
        self.assertIs(button._recolored_pixmap(source, button._icon_recolor()),
                      button._recolored_pixmap(source, button._icon_recolor()))   # en cache
        button.deleteLater()

    def test_blend_multiplies_only_while_enabled(self):
        """Fusion PRODUIT d'une couleur sur l'icone active (bouton fm_theme) ; desactive : la couleur desactivee."""
        from preview_column import multiply_color
        button = IconButton("viewer", "#ffffff", "#ffffff")
        source = self._source()
        button.set_icon_blend("#ff8000")
        button.set_disabled_color("#404040")
        self.assertEqual(button._icon_recolor(), ("mul", "#ff8000"))
        image = button._recolored_pixmap(source, button._icon_recolor()).toImage()
        pixel = image.pixelColor(1, 1)
        self.assertEqual((pixel.red(), pixel.blue(), pixel.alpha()), (128, 0, 255))   # #808080 x #ff8000
        self.assertAlmostEqual(pixel.green(), 64, delta=1)
        self.assertEqual(image.pixelColor(6, 1).alpha(), 0)                          # forme gardee
        self.assertEqual(multiply_color("#c0c0c0", "#ff8000"), "#ffc06000")          # glyphe : meme calcul
        self.assertEqual(multiply_color("#c0c0c0", "#00ff8000"), "#ffc0c0c0")        # transparent = sans fusion
        button.setEnabled(False)
        self.assertEqual(button._icon_recolor(), ("in", "#404040"))
        button.deleteLater()

    def test_colored_icon_gets_a_background_of_its_hue(self):
        """Module OUVERT a l'icone coloree : fond de la meme teinte, valeur eloignee (lisibilite, reglable) ; module
        ferme, blanc ou desactive : fond habituel (2026-11-08)."""
        from preview_column import icon_tone_bg
        self.assertIsNone(icon_tone_bg("#ffffff"))
        self.assertIsNone(icon_tone_bg("#00f28c28"))
        rest, hover = icon_tone_bg("#f28c28")
        icon, bg = QColor("#f28c28"), QColor(rest)
        self.assertAlmostEqual(bg.hsvHueF(), icon.hsvHueF(), delta=0.02)
        self.assertLess(bg.valueF(), icon.valueF() - 0.4)
        self.assertGreater(QColor(hover).valueF(), bg.valueF())
        self.assertGreater(QColor(icon_tone_bg("#3a1a60")[0]).valueF(), 0.6)        # icone sombre : fond clair
        button = IconButton("viewer", "#ffffff", "#ffffff")
        button.resize(24, 24)
        sides = {s: False for s in ("top", "right", "bottom", "left")}
        button.set_frame_style("#00000000", sides, {s: "#000000" for s in sides}, 0, {})
        self.assertGreater(QColor(icon_tone_bg("#f28c28", 60)[0]).valueF(), bg.valueF() + 0.2)   # reglage
        button.set_icon_blend("#f28c28")
        pixel = lambda: button.grab().toImage().pixelColor(1, 1).name()
        self.assertNotEqual(pixel(), QColor(rest).name())                              # module ferme
        button.set_alert("#5a3d8bff")                                                  # module ouvert
        self.assertEqual(pixel(), QColor(rest).name())
        button.set_icon_tone_value(60)
        self.assertEqual(pixel(), QColor(icon_tone_bg("#f28c28", 60)[0]).name())
        button.set_icon_tone_value(30)
        button.setEnabled(False)
        self.assertNotEqual(button.grab().toImage().pixelColor(1, 1).name(), QColor(rest).name())
        button.set_icon_blend("#ffffff")
        button.setEnabled(True)
        self.assertNotEqual(button.grab().toImage().pixelColor(1, 1).name(), QColor(rest).name())
        button.deleteLater()

    def test_navbar_icons_take_their_colors(self):
        """fm_browser > ICONES > Couleur des icones ; colonne Couleur du tableau d'icones de la barre, jamais les
        couleurs des modules du board (2026-11-08)."""
        from types import SimpleNamespace
        from main_window.chrome import ChromeMixin
        saved = ui_state.APPLIED_SETTINGS
        ui_state.APPLIED_SETTINGS = dict(DEFAULT_SETTINGS, navtool_icon_base_color="#ffffff",
                                         navtool_icon_disabled_color="#202020",
                                         board_modulebar_color_pdf="#e0604f", navtool_icon_color_pdf="#00ff00")
        try:
            names = ("btn_browse", "btn_presets", "btn_settings", "btn_style", "btn_collapse", "btn_columns",
                     "btn_viewer", "btn_text_editor", "btn_board", "btn_video", "btn_font", "btn_pdf", "btn_agenda",
                     "btn_theme")
            host = SimpleNamespace(**{n: IconButton("gear", "#000", "#000") for n in names})
            host._NAV_ICON_COLORS = ChromeMixin._NAV_ICON_COLORS
            ChromeMixin._refresh_navbar_icons(host)
            self.assertEqual(host.btn_browse._color, "#ffffff")
            self.assertEqual(host.btn_browse._disabled_color, "#202020")
            self.assertIsNone(host.btn_browse._blend)                                # sans colonne Couleur
            self.assertIsNone(host.btn_columns._blend)
            self.assertEqual(host.btn_pdf._blend, "#00ff00")                         # pas celle du board
            self.assertEqual(host.btn_viewer._blend, "#ffffff")                      # blanc : icone telle quelle
            self.assertEqual((host.btn_theme._blend, host.btn_theme._tint), ("#f28c28", None))
            ChromeMixin._set_button_usable(host.btn_pdf, False)
            self.assertIsNone(host.btn_pdf.graphicsEffect())                       # plus de voile d'opacite
            self.assertEqual(host.btn_pdf._icon_recolor(), ("in", "#202020"))
            for n in names:
                getattr(host, n).deleteLater()
        finally:
            ui_state.APPLIED_SETTINGS = saved

    def test_navbar_icon_table_has_the_color_column(self):
        """fm_browser > Barre de navigation > Icones : nouvelles icones, colonne Couleur sur les seules icones qui en
        ont une ; « Couleur de l'icone fm_theme » supprimee (2026-11-08)."""
        import settings_window_v2 as v2
        from settings_window_v2 import ScopeValues
        group = "Barre de navigation : Icones (appli)"
        self.assertIn(group, v2.ICON_GROUPS)
        icons = [s.params["ui_key"] for s in v2.CATALOG[group] if s.kind == "ui_icon"]
        for key in ("navbar_columns", "navbar_video", "navbar_agenda", "navbar_pdf", "navbar_theme"):
            self.assertIn(key, icons)
        colored = {s.params["icon_color_of"] for s in v2.CATALOG[group] if "icon_color_of" in s.params}
        self.assertEqual(colored, {"navbar_viewer", "navbar_text_editor", "navbar_board", "navbar_font",
                                   "navbar_video", "navbar_agenda", "navbar_taches", "navbar_pdf", "navbar_theme"})
        self.assertNotIn("navbar_theme_button_color", DEFAULT_SETTINGS)
        for spec in v2.CATALOG[group]:
            if spec.kind != "ui_icon":
                self.assertIn(spec.key, DEFAULT_SETTINGS)
        fields, resizers, record = {}, [], []
        saved = ui_state.APPLIED_SETTINGS
        try:
            frame = v2.build_group(group, ScopeValues(dict(DEFAULT_SETTINGS)), {}, fields, {}, resizers, record,
                                   lambda *a: None)
            self.assertTrue(frame.isAncestorOf(fields["navtool_icon_color_theme"]))     # dans la colonne Couleur
            # Valeur du fond des icones colorees : tableau a part SOUS les icones, sans entete, titre au-dessus.
            from fm_theme.widgets import _TableFrame
            tables = [t for t in frame.findChildren(_TableFrame) if t.isAncestorOf(fields["navtool_icon_tone_value"])]
            self.assertEqual(len(tables), 1)
            self.assertTrue(tables[0]._extra_dims.head_hidden)
            self.assertEqual(tables[0]._extra_dims.above_texts, {0: "Valeur du fond des icônes colorées"})
            self.assertFalse(tables[0].isAncestorOf(fields["navtool_icon_color_theme"]))
            self.assertEqual([s.key for s, _w in record if not isinstance(s, str)],
                             [s.key for s in v2.CATALOG[group] if s.kind != "ui_icon"])
            frame.deleteLater()
        finally:
            ui_state.APPLIED_SETTINGS = saved


class FillsScreenTest(unittest.TestCase):
    def test_maximized_or_fullscreen(self):
        window = QWidget()
        child = QWidget(window)
        self.assertFalse(fills_screen(child))
        window.setWindowState(Qt.WindowMaximized)
        self.assertTrue(fills_screen(child))
        window.setWindowState(Qt.WindowFullScreen)
        self.assertTrue(fills_screen(child))
        window.deleteLater()


class TableDimsMergeTest(unittest.TestCase):
    """Largeurs des tableaux (signale, 2026-11-07) : une fenetre n'enregistre que SES tableaux modifies, sur ce qui
    est deja sur le disque ; le tableau fm_browser de la barre a sa propre cle (meme titre que celui de fm_theme)."""

    def test_section_tables_go_in_a_main_subsection(self):
        """Section a sous-sections ET tableaux propres : ceux-ci dans une sous-section « Main » en tete, cle de
        largeurs inchangee (titre « Main » ignore ; 2026-11-08)."""
        import settings_window_v2 as v2
        from PySide6.QtTest import QTest
        from fm_theme.widgets import _TableFrame
        from _window_cleanup import track
        win = track(v2.SettingsWindowV2())
        win.show()
        node = next(n for n in win.stack.findChildren(v2._LazyNode)
                    if n.level == 1 and n.node.title == "Barre de navigation")
        node._head.head.clicked.emit()
        QTest.qWait(50)
        self.assertEqual(node._child_nodes[0].node.title, v2.MAIN_SUBSECTION)
        self.assertIsNone(getattr(node, "_group_widget", None))       # plus de tableau hors sous-section
        self.assertFalse([f for f in node.findChildren(_TableFrame) if f.isVisible()])
        main = node._child_nodes[0]
        main._head.head.clicked.emit()
        QTest.qWait(50)
        frame = next(f for f in main.findChildren(_TableFrame) if f.isVisible())
        frame._dims_key = None                                         # cle deduite des titres
        self.assertEqual(frame.dimsKey(), "Barre de navigation#0")
        self.assertEqual([n.title for n in v2.ordered_nodes(node.node.children + (main.node,), ["Icônes"])][0],
                         v2.MAIN_SUBSECTION)                           # ordre enregistre sans « Main » : en tete

    def test_other_windows_dims_survive_and_keys_differ(self):
        import settings_window_v2 as v2
        from PySide6.QtTest import QTest
        from fm_theme.widgets import _TableFrame
        from settings_store import load_settings, save_settings
        from _window_cleanup import track
        saved = v2.AUTOSAVE
        v2.AUTOSAVE = True
        self.addCleanup(setattr, v2, "AUTOSAVE", saved)
        win = track(v2.SettingsWindowV2())
        win.show()
        node = next(n for n in win.stack.findChildren(v2._LazyNode)
                    if n.level == 1 and n.node.title == "Barre de navigation")
        node._head.head.clicked.emit()
        QTest.qWait(50)
        node._child_nodes[0]._head.head.clicked.emit()             # ses tableaux : sous-section « Main »
        QTest.qWait(50)
        frame = next(f for f in node._head._body.findChildren(_TableFrame) if f.isVisible())   # corps : volet
        self.assertEqual(frame.dimsKey(), "v2:Barre de navigation (appli)#0")
        disk = load_settings()                                     # une autre fenetre enregistre entre-temps
        disk["table_dims"] = {**(disk.get("table_dims") or {}), "Barre de navigation#0": {"cols": [111, 222]}}
        save_settings(disk)
        head, _ = frame._dims_children()
        widths = [w + 9 for w in head.columnWidths()]
        head.setColumnWidths(widths)
        frame.dimsChanged.emit()
        win._persist_now()
        dims = load_settings().get("table_dims") or {}
        self.assertEqual(dims["Barre de navigation#0"], {"cols": [111, 222]})
        self.assertEqual(dims[frame.dimsKey()]["cols"], widths)
        win.close()


if __name__ == "__main__":
    unittest.main()
