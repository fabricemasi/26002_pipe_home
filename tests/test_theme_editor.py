"""Éditeur fm_theme (theme_editor.py, fm_theme.bat) : onglet « Thème » réduit à l'aspect, magasin qui écrit
l'aspect dans le preset fm_theme et le reste dans les réglages de l'appli, gestion des presets (renommer =
alias retrouvé, dupliquer, nouveau, supprimer). Presets et réglages : copies temporaires (_isolate)."""
import _isolate  # noqa: F401
import os
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QPoint  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

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
                         ["ui_scale", "window_radius", "window_border_enabled", "variant_sel_border_enabled",
                          "variant_sel_corner_radius", "variant_sel_bg_color"])     # cadre de sélection des variantes

    def test_general_window_no_longer_holds_the_aspect(self):
        """Étape 6 : fm_browser garde le fonctionnement et son aspect propre ; l'aspect générique est dans Thème."""
        titles = [n.title for n in v2.tab_tree("General")]
        for title in v2.THEME_SECTIONS:
            if title != "Barre de navigation":             # partagee (2026-11-07) : la partie de fm_browser reste
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
        first = min(n._head.mapTo(self.window, QPoint(0, n._head._box_rect().top())).y() for n in self.nodes())
        self.assertEqual(pane.mapTo(self.window, QPoint(0, 0)).y(), first)  # du haut de la liste (2026-11-08)
        for node in self.nodes():                                          # à droite de tous les titres
            label = node._head._name_label
            self.assertGreaterEqual(pane.mapTo(self.window, QPoint(0, 0)).x(),
                                    label.mapTo(self.window, QPoint(label.width(), 0)).x())

    def test_open_title_and_pane_are_one_shape(self):
        """Titre déployé (demande de l'utilisateur, 2026-11-08, schéma) : son fond et celui du volet sont le même
        (« Déployé : couleur de fond »), le volet est aligné sur son bord droit, coins du bas arrondis comme les
        titres ; texte : couleur, gras, italique imposés tant qu'il est déployé."""
        radius = {k: 10 for k in ("top_left", "top_right", "bottom_left", "bottom_right")}
        merged = dict(self.window.settings, title_level1_bg_enabled=True, title_level1_bg_color="#202020",
                      title_level1_bg_radius=radius, title_level1_open_bg_color="#804020",
                      title_level1_open_color_enabled=True, title_level1_open_color="#ffcc00",
                      title_level1_open_bold="on", title_level1_open_italic="on")
        v2.restyle_titles_in(self.window, merged)
        self.addCleanup(v2.restyle_titles_in, self.window, dict(self.window.settings))
        section = self.node("Tableaux")
        head, label = section._head, section._head._name_label
        self.assertEqual(head.box_fill(), "#202020")                       # replié : son fond habituel
        head.head.clicked.emit()
        for _ in range(5):
            QApplication.processEvents()
        self.assertEqual(head.box_fill(), "#804020")
        self.assertTrue(label.font().bold() and label.font().italic())
        self.assertIn("#ffcc00", label.styleSheet())
        pane = self.editor.detail.pane
        right = head.mapTo(self.window, QPoint(head._box_rect().right() + 1, 0)).x()
        self.assertEqual(pane.mapTo(self.window, QPoint(pane.width(), 0)).x(), right)
        image = pane.grab().toImage()
        self.assertEqual(image.pixelColor(pane.width() // 2, pane.height() - 3).name(), "#804020")   # marge basse
        self.assertNotEqual(image.pixelColor(0, pane.height() - 1).name(), "#804020")   # coin arrondi
        self.assertEqual(image.pixelColor(0, 0).name(), "#804020")                      # haut gauche : droit
        self.assertNotEqual(image.pixelColor(pane.width() - 1, 0).name(), "#804020")    # haut droit : arrondi
        head.head.clicked.emit()
        QApplication.processEvents()
        self.assertFalse(label.font().italic())
        self.assertNotIn("#ffcc00", label.styleSheet())

    def test_open_border_outlines_title_and_pane_like_a_tab(self):
        """« Déployé : bordures » : contour du titre ouvert ET du volet ; le titre entre dans le volet comme un
        onglet : bord gauche du volet ouvert sur la hauteur du titre, filets du titre gardés à gauche du volet
        (demande de l'utilisateur sur capture annotée, 2026-11-08)."""
        on = {k: True for k in ("top", "right", "bottom", "left")}
        merged = dict(self.window.settings, title_level1_bg_enabled=True, title_level1_bg_color="#202020",
                      title_level1_open_bg_color="#804020", title_level1_open_border_enabled=on,
                      title_level1_open_border={k: "#ff0000" for k in on}, title_level1_open_border_thickness=2)
        v2.restyle_titles_in(self.window, merged)
        self.addCleanup(v2.restyle_titles_in, self.window, dict(self.window.settings))
        section = self.node("Tableaux")
        head = section._head
        head.head.clicked.emit()
        for _ in range(5):
            QApplication.processEvents()
        self.assertEqual(head.box_border()[2], 2)
        pane = self.editor.detail.pane
        title = head.grab().toImage()
        box = head._box_rect()
        self.assertEqual(title.pixelColor(box.left() + 30, box.bottom()).name(), "#ff0000")    # filet bas du titre
        image = pane.grab().toImage()
        gap = self.editor.detail.tab_gap()
        middle = (gap[0] + gap[1]) // 2
        self.assertEqual(image.pixelColor(0, middle).name(), "#804020")                 # ouvert sur le titre
        self.assertEqual(image.pixelColor(0, pane.height() - 20).name(), "#ff0000")      # bord gauche ailleurs
        self.assertEqual(image.pixelColor(pane.width() // 2, pane.height() - 1).name(), "#ff0000")   # bas
        self.assertEqual(image.pixelColor(pane.width() // 2, 0).name(), "#ff0000")                   # haut
        # Rien des titres n'est peint sous le volet (un fond semi-transparent laissait voir leurs filets).
        page = pane.parentWidget()
        for node in self.nodes():
            self.assertEqual(node._head._side_clip, node._head.mapFrom(page, pane.pos()).x())
        head.head.clicked.emit()
        QApplication.processEvents()
        self.assertIsNone(head._side_clip)                                     # volet fermé : titres entiers

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


class VariantPreviewsTest(WindowTestCase):
    """Demande de l'utilisateur (2026-11-11) : un aperçu SOUS CHAQUE variante pour tous les types (l'éditée vivante,
    les autres en image dessinée avec leurs valeurs) ; toggles comme les autres ; tableau réduit ; menu déployé ;
    fenêtre en aperçu ; barres de navigation et d'état en « capture »."""

    def setUp(self):
        self.name = fresh_preset("Aperçus")
        self.editor = theme_editor.ThemeEditor(self.name)
        self.editor.window.resize(1200, 900)
        self.editor.window.show()
        APP.processEvents()

    def tearDown(self):
        self.editor.window.hide()
        tp.delete_preset(self.name)

    def pane(self, section):
        self.editor.preview.show_section(section)
        self.editor._refresh_variant_bar()
        APP.processEvents()
        return self.editor.preview.tools()

    def test_every_variant_has_its_own_preview(self):
        from fm_theme import tokens
        for section, type_name in theme_editor.SECTION_TYPES.items():
            if type_name in ("bouton", "toggle"):
                continue
            tp.add_variant(self.name, type_name, "autre")
            pane = self.pane(section)
            self.assertEqual(list(pane.blocks)[-1], "autre", section)
            for variant, block in pane.blocks.items():
                self.assertIsNotNone(block.preview, (section, variant))
                self.assertLessEqual(block.preview.width(), pane.preview_width + 1, (section, variant))
            self.assertIsInstance(pane.blocks["autre"].preview, QLabel)          # non éditée : une image
            self.assertFalse(pane.blocks["autre"].preview.pixmap().isNull())
        # L'habillage global est remis après le dessin d'une variante : la variante « autre » des sliders rouge.
        before = dict(tokens._SLIDER_STYLE)
        preset = tp.load_preset(tp.find_preset(self.name))
        preset["types"]["slider"]["variantes"]["autre"]["track_fill_color"] = "#ff0000"
        tp.save_preset(preset)
        self.pane("Sliders")
        self.assertEqual(tokens._SLIDER_STYLE, before)

    def test_table_preview_is_small_and_keeps_its_own_widths(self):
        pane = self.pane("Tableaux")
        table = pane.blocks[pane.current].preview
        self.assertEqual(table.width(), pane.preview_width)
        self.assertEqual(table.dimsKey(), "fm_theme:apercu_tableau")     # pas les largeurs d'un autre tableau

    def test_bars_look_like_a_piece_of_window(self):
        from fm_theme.preview import BarShot, SHOT_BODY
        values = dict(self.editor.window.current_values(), navbar_height=40, navbar_bg_color="#ff0000",
                      statusbar_bg_color="#0000ff")
        nav = BarShot("navigation", values, 300)
        self.assertEqual(nav.height(), 40 + SHOT_BODY)
        image = nav.grab().toImage()
        self.assertEqual(image.pixelColor(150, 20).name(), "#ff0000")        # la barre en haut
        status = BarShot("etat", values, 300)
        image = status.grab().toImage()
        self.assertEqual(image.pixelColor(150, status.height() - 5).name(), "#0000ff")   # la barre en bas
        self.assertNotEqual(image.pixelColor(299, status.height() - 12).name(), "#0000ff")   # fermé à DROITE
        pane = self.pane("Barre d'état")
        pane.refresh_values(dict(values, statusbar_bg_color="#00ff00"))       # l'éditée suit le geste
        block = pane.blocks[pane.current]
        self.assertEqual(block.preview._v["statusbar_bg_color"], "#00ff00")

    def test_menu_is_deployed(self):
        pane = self.pane("Menu contextuel")
        shot = pane.blocks[pane.current].preview
        self.assertGreater(shot.pixmap().height(), 60)                      # ses lignes, pas un bouton

    def test_toggles_work_like_the_other_types(self):
        window = self.editor.window
        self.editor._follow_sections(window)
        node = next(n for n in window.stack.findChildren(v2._LazyNode) if n.level == 1 and n.node.title == "Toggles")
        node._head.head.clicked.emit()                                      # la section ouverte (construite)
        for _ in range(5):
            APP.processEvents()
        pane = self.editor.preview.tools()
        styles = [s["key"] for s in theme_editor.toggle_style_list(window.settings)]
        self.assertEqual(list(pane.blocks), styles)
        self.assertEqual(pane.blocks[styles[0]].name_field.text(), theme_editor.toggle_style_list(window.settings)[0]["name"])
        nodes = [n for n in window.findChildren(v2._LazyNode) if n.node.toggle_key]
        self.assertEqual({n.node.toggle_key for n in nodes if not n.isHidden()}, {pane.current})   # seul l'édité
        other = next(k for k in styles if k != pane.current)
        pane.blocks[other]._edit()                                          # éditer un autre style
        pane = self.editor.preview.tools()
        self.assertEqual(pane.current, other)
        self.assertEqual({n.node.toggle_key for n in nodes if not n.isHidden()}, {other})
        pane.blocks[other].default.setChecked(True)                         # « par défaut »
        self.assertEqual(window.settings.get("toggle_style"), other)
        self.editor.preview.tools().add()                                    # « + » : copie du style édité
        pane = self.editor.preview.tools()
        self.assertEqual(len(pane.blocks), len(styles) + 1)
        self.assertNotIn(pane.current, styles)


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
    def test_variant_pane_on_the_left_with_one_line_per_variant(self):
        """Croquis de l'utilisateur (2026-11-10) : volet À GAUCHE des sections ; en tête le titre et « + » ; une ligne par
        variante (nom, « − », « par défaut ») ; pour le bouton, ses trois états en aperçu."""
        name = fresh_preset("Volet")
        editor = theme_editor.ThemeEditor(name)
        try:
            editor.window.resize(1200, 900)
            editor.window.show()
            APP.processEvents()                                               # (ouverture : aucune section)
            row = editor.preview.parentWidget().layout()
            self.assertIs(row.itemAt(0).widget(), editor.preview)            # à gauche de la pile des pages
            compact = tp.add_variant(name, "bouton", "compact")
            editor.preview.show_section("Bouton")
            editor._refresh_variant_bar()
            pane = editor.preview.tools()
            self.assertIsInstance(pane, theme_editor.VariantList)
            self.assertEqual(list(pane.blocks), ["standard", compact])
            self.assertIs(editor.preview._head_tool.itemAt(0).widget(), pane.add_button)
            self.assertFalse(editor.preview._content.isVisibleTo(editor.preview))   # les variantes tiennent lieu d'aperçu
            standard = pane.blocks["standard"]
            self.assertTrue(standard.default.isChecked())
            self.assertFalse(pane.blocks[compact].default.isChecked())
            self.assertEqual([b._state for b in standard.buttons], ["standard", "survol", "focus"])
            APP.processEvents()
            other = pane.blocks[compact]                                      # collées : pas de trou entre elles
            self.assertLess(other.geometry().top() - standard.geometry().bottom(), 30)
            self.assertLess(pane.height(), 500)
            frame = editor.window.current_values()["variant_sel_border"]["left"]
            image = standard.grab().toImage()                                 # éditée : cadre de sélection réglé
            self.assertEqual(image.pixelColor(0, standard.height() // 2).name(), frame.lower())
            self.assertNotEqual(other.grab().toImage().pixelColor(0, other.height() // 2).name(), frame.lower())
            pane.refresh_selection(dict(editor.window.current_values(), variant_sel_border={
                "top": "#ff0000", "right": "#ff0000", "bottom": "#ff0000", "left": "#ff0000"}))
            self.assertEqual(standard.grab().toImage().pixelColor(0, standard.height() // 2).name(), "#ff0000")
            pane.refresh_selection(dict(editor.window.current_values(), variant_sel_bg_color="#00ff00"))
            from fm_theme.style import build_stylesheet
            saved = APP.styleSheet()
            APP.setStyleSheet(build_stylesheet())          # celle de l'appli : « QWidget { background: … } »
            try:
                APP.processEvents()
                states = standard.buttons[0].parentWidget()                   # fond SOUS les aperçus aussi
                caption = states.findChildren(QLabel)[0]
                image = standard.grab().toImage()
                for widget in (states, caption):
                    spot = widget.mapTo(standard, widget.rect().topLeft()) + QPoint(1, 1)
                    self.assertEqual(image.pixelColor(spot).name(), "#00ff00")
            finally:
                APP.setStyleSheet(saved)
            live = dict(editor.window.current_values(), button_bg_color="#123456")   # aperçu en direct
            pane.refresh_values(live)
            self.assertIn("#123456", standard.buttons[0].styleSheet())
            pane.blocks[compact].default.setChecked(True)                     # « par défaut » : l'autre variante
            preset = tp.load_preset(tp.find_preset(name))
            self.assertEqual(tp.default_variant(preset["types"]["bouton"]), compact)
            pane = editor.preview.tools()
            pane.blocks[compact].name_field.setText("serré")                  # renommer : son nom validé
            pane.blocks[compact]._rename()
            self.assertIn("serré", tp.variant_names(tp.load_preset(tp.find_preset(name)), "bouton"))
            editor.preview.show_section("Toggles")                           # toggles : comme les autres
            editor._refresh_variant_bar()
            self.assertEqual(editor.preview.tools().type_name, "toggle")
            self.assertFalse(editor.preview._content.isVisibleTo(editor.preview))
        finally:
            editor.window.hide()
            tp.delete_preset(name)

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
