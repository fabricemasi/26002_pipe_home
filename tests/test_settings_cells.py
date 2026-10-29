"""Tests des tableaux a cellules de la fenetre de reglages v2 (settings_cells.py) :
entete partout, toggles type 2 sans texte, justification par cellule (clic droit),
bordures de colonnes saisissables sur les cellules, filets verticaux qui suivent,
plage des curseurs, enregistrement en temps reel."""
import os as _os, sys as _sys  # jamais les vrais reglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
from _lent import lent  # noqa: E402
import fm_theme.tokens  # noqa: E402
import copy
import shiboken6
import os
import sys
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QLineEdit, QMenu
from PySide6.QtTest import QTest

app = QApplication.instance() or QApplication([])

import settings_cells as cells
import settings_window_v2 as v2
from _window_cleanup import WindowTestCase, track_class  # fenetres detruites apres chaque test

track_class(v2.SettingsWindowV2)
from settings_widgets import _ColorSwatchButton, _SliderField, _Toggle, _TableFrame, _TableRow

v2.AUTOSAVE = False
# Isolation : jamais les vrais reglages de l'utilisateur (dimensions, justifications enregistrees...).
from settings_store import DEFAULT_SETTINGS as _DEFAULTS
_real_load_settings = v2.load_settings


def setUpModule():
    v2.load_settings = lambda: copy.deepcopy(_DEFAULTS)


def tearDownModule():
    v2.load_settings = _real_load_settings


def build(module: str | None = None):
    win = v2.SettingsWindowV2(module=module)
    v2.expand_all(win.stack.currentWidget())
    for node in win.stack.currentWidget().findChildren(v2._LazyNode):
        node.set_collapsed(False)
    v2.expand_all(win.stack.currentWidget())
    return win


def send_mouse(widget, kind, pos, buttons=Qt.LeftButton):
    local = QPointF(pos)
    event = QMouseEvent(kind, local, QPointF(widget.mapToGlobal(pos)),
                        Qt.LeftButton if kind != QEvent.MouseMove else Qt.NoButton, buttons, Qt.NoModifier)
    QApplication.sendEvent(widget, event)


class TablesTest(WindowTestCase):
    @classmethod
    def setUpClass(cls):
        cls.win = build()
        cls.frames = cls.win.findChildren(_TableFrame)

    def test_every_table_has_a_header(self):
        self.assertTrue(self.frames)
        for frame in self.frames:
            self.assertIsNotNone(getattr(frame, "_flat_head", None), frame.dimsKey())

    def test_toggles_in_tables_type_1_alone_type_2_otherwise_without_text(self):
        # Seul dans sa cellule (« lier les 4 », ligne oui / non...) : type 1 ; a cote d'un autre controle
        # (toggles « app » / « sys » d'une couleur, cote au-dessus de sa couleur) : type 2 (demande).
        from settings_cells import _toggle_alone_in_cell
        toggles = [t for f in self.frames for t in f.findChildren(_Toggle)]
        self.assertGreater(len(toggles), 30)
        kinds = set()
        for toggle in toggles:
            expected = getattr(toggle, "_table_style", None) or (
                "toggle1" if _toggle_alone_in_cell(toggle) else "toggle2")
            if toggle.chosenStyle() is None:
                self.assertEqual(toggle._style_override, expected)
            kinds.add(expected)
            self.assertFalse(toggle._show_label)
        self.assertEqual(kinds, {"toggle1", "toggle2"})

    def test_toggle_above_a_color_is_as_far_as_its_side_toggles(self):
        from settings_sections import _ToggleSideColorsField
        from PySide6.QtCore import QPoint, QRect
        field = next(f for frame in self.frames for f in frame.findChildren(_ToggleSideColorsField))
        side = field.sides
        toggle, color = side.side_checks["left"], side.fields["left"]

        def box(widget):            # place du DESSIN (toggle : 1 px de marge autour)
            r = QRect(widget.mapTo(self.win, QPoint(0, 0)), widget.size())
            return r.adjusted(1, 1, -1, -1) if isinstance(widget, _Toggle) else r
        swatch, app_t, sys_t = box(color.swatch), box(color.app_toggle), box(color.system_toggle)
        above = swatch.top() - box(toggle).bottom() - 1
        self.assertEqual(above, 7)
        if color.width() >= color.minimumSizeHint().width():     # champ a sa largeur naturelle
            self.assertEqual(swatch.left() - app_t.right() - 1, above)
            self.assertEqual(sys_t.left() - swatch.right() - 1, above)

    def test_corners_rows_are_called_border_radius(self):
        labels = {sp.label for specs in v2.CATALOG.values() for sp in specs if sp.kind == "corners"}
        # « Border radius », ou precise par ce qu'il arrondit (Visionneuse : « Border radius de l'image »).
        self.assertEqual({label for label in labels if not label.startswith("Border radius")}, set())
        self.assertIn("Border radius", labels)

    def test_padding_borders_and_radius_are_split_cells(self):
        by_kind = {}
        for store in self.win.stores.values():
            for spec, widget in store.get("specs", ()):
                if not isinstance(spec, str):
                    by_kind.setdefault(spec.kind, widget)
        captions = lambda w: [c.text() for c in cells.split_of(w)._cap_labels]
        self.assertEqual(captions(by_kind["padding"]), ["LIER LES 4", "G", "H", "B", "D"])
        self.assertEqual(captions(by_kind["sides_thick"]), ["LIER LES 4", "G", "H", "B", "D", "ÉPAISSEUR"])
        self.assertEqual(captions(by_kind["corners"])[0], "LIER LES 4")
        self.assertEqual(len(captions(by_kind["corners"])), 5)

    def test_title_fonts_table_reproduces_the_v1_columns(self):
        frames = build("theme").findChildren(_TableFrame)  # aspect generique : fenetre Theme (etape 6 de fm_theme)
        frame = next(f for f in frames if f.dimsKey().startswith("TITRES/Polices"))
        titles = [c.text() for c in frame._flat_head._cells]
        self.assertEqual(titles, ["NIVEAU", "POLICE", "GRAS", "ITALIQUE", "HAUTEUR", "NIVEAU DE LISSAGE", "COULEUR"])
        self.assertEqual(len(frame.findChildren(_TableRow)), 5)


class CellsBehaviourTest(WindowTestCase):
    @classmethod
    def setUpClass(cls):
        cls.win = build("theme")  # aspect generique : fenetre Theme (etape 6 de fm_theme)
        cls.win.resize(1300, 900)
        cls.win.show()
        for _ in range(5):
            app.processEvents()
        cls.frame = next(f for f in cls.win.findChildren(_TableFrame) if f.dimsKey() == "Tableaux#0")

    @classmethod
    def tearDownClass(cls):
        cls.win.close()

    def test_alignment_is_kept_in_the_table_dims_and_restored(self):
        cell = self.frame._extra_dims.cells["r1c1"]
        self.assertEqual(cell.align(), ("right", "center"))
        cell.setAlign("left", "top")
        dims = self.frame.collectDims()
        self.assertEqual(dims["align"], {"r1c1": "left,top"})
        cell.setAlign("right", "center")
        self.frame.applyDims(dims)
        self.assertEqual(cell.align(), ("left", "top"))
        cell.setAlign("right", "center")

    def test_context_menu_offers_both_justifications(self):
        from PySide6.QtWidgets import QMenu
        cell = self.frame._extra_dims.cells["r1c1"]
        menu = QMenu()
        cell.populate_menu(menu)
        titles = [a.text() for a in menu.actions() if a.text()]     # (puis « Split au-dessus », entête…)
        self.assertEqual(titles[:2], ["Justification horizontale", "Justification verticale"])
        self.assertIn("Supprimer l'entête", titles)
        horizontal = menu.actions()[0].menu()
        self.assertEqual([a.text() for a in horizontal.actions()], ["Gauche", "Centre", "Droite"])
        self.assertTrue(horizontal.actions()[2].isChecked())          # valeur : a droite par defaut
        horizontal.actions()[0].trigger()
        self.assertEqual(cell.align()[0], "left")
        cell.setAlign("right", "center")

    def test_range_dialog_returns_the_edited_bounds(self):
        dialog = cells._RangeDialog(None, 0, 10, 1)
        dialog.low.setValue(2)
        dialog.high.setValue(40)
        self.assertEqual(dialog.values(), (2, 40))
        ratio = cells._RangeDialog(None, 20, 500, 100)
        self.assertEqual(ratio.values(), (20, 500))

    def test_alignment_change_notifies_the_table(self):
        seen = []
        self.frame.dimsChanged.connect(lambda: seen.append(1))
        self.frame._extra_dims.cells["r0c0"].setAlign("center", "bottom")
        self.frame._extra_dims.cells["r0c0"].setAlign("left", "center")
        self.assertEqual(len(seen), 2)

    def test_dragging_a_row_cell_border_resizes_the_column(self):
        head = self.frame._flat_head
        row_cell = self.frame._extra_dims.cells["r2c0"]
        before = head._widths[0]
        edge = QPoint(row_cell.width() - 1, row_cell.height() // 2)
        send_mouse(row_cell, QEvent.MouseButtonPress, edge)
        self.assertTrue(head.isDragging())
        send_mouse(row_cell, QEvent.MouseMove, edge + QPoint(60, 0))
        send_mouse(row_cell, QEvent.MouseButtonRelease, edge + QPoint(60, 0), Qt.NoButton)
        app.processEvents()
        self.assertFalse(head.isDragging())
        self.assertEqual(head._widths[0], before + 60)
        self.assertEqual(row_cell.width(), before + 60)

    def test_vertical_lines_follow_a_column_resize(self):
        """Apres un redimensionnement, ce qui est a l'ecran (peint en direct) doit etre ce qu'un
        rendu a neuf donnerait : les filets verticaux suivent les cellules."""
        head = self.frame._flat_head
        head._set_width(0, head._widths[0] + 40)
        for _ in range(5):
            app.processEvents()
        live = self.win.windowHandle().screen().grabWindow(self.win.winId()).toImage()
        fresh = self.win.grab().toImage()
        row = self.frame.findChildren(_TableRow)[1]
        y = row.mapTo(self.win, QPoint(0, 4)).y()
        x0 = self.frame.mapTo(self.win, QPoint(0, 0)).x()
        for x in range(x0, x0 + self.frame.width() - 8):
            self.assertEqual(live.pixelColor(x, y), fresh.pixelColor(x, y), f"x={x - x0}")

    def test_split_cell_border_drag_sets_a_minimum_width(self):
        split = next(s for s in self.win.findChildren(cells.SplitCell))
        edge_x = split._cells[1].x()
        y = split.height() // 2
        send_mouse(split, QEvent.MouseButtonPress, QPoint(edge_x, y))
        send_mouse(split, QEvent.MouseMove, QPoint(edge_x + 50, y))
        send_mouse(split, QEvent.MouseButtonRelease, QPoint(edge_x + 50, y), Qt.NoButton)
        self.assertGreaterEqual(split.widths()[0], 50)


class SplitCellTest(WindowTestCase):
    @classmethod
    def setUpClass(cls):
        cls.win = build()
        cls.win.resize(1300, 900)
        cls.win.show()
        for _ in range(5):
            app.processEvents()
        cls.splits = cls.win.findChildren(cells.SplitCell)

    @classmethod
    def tearDownClass(cls):
        cls.win.close()

    def test_controls_of_split_cells_are_reachable(self):
        """Regression : un parent transparent aux evenements souris les rendait tous inaccessibles."""
        checked = 0
        for split in self.splits:
            for toggle in split.findChildren(_Toggle):
                if not toggle.isVisible():
                    continue
                pos = split.mapFromGlobal(toggle.mapToGlobal(toggle.rect().center()))
                hit = split.childAt(pos)
                if isinstance(hit, _ColorSwatchButton):
                    continue        # colonne trop etroite (largeurs par defaut d'un tableau sans dimensions enregistrees) : recouvrement, pas une transparence
                self.assertIs(hit, toggle)
                checked += 1
        self.assertGreater(checked, 5)

    def test_split_cells_use_the_padding_of_normal_cells(self):
        normal = next(c for f in self.win.findChildren(_TableFrame) for c in f.findChildren(cells._Cell)
                      if not getattr(c.content(), "_fill_cell", False))
        expected = normal.layout().getContentsMargins()
        for split in self.splits:
            for cell in split._cells:
                self.assertEqual(cell.layout().getContentsMargins(), expected)
            outer = split.parentWidget()
            while outer is not None and not isinstance(outer, cells._Cell):
                outer = outer.parentWidget()
            left, top, right, bottom = outer.layout().getContentsMargins()
            self.assertEqual((top, right, bottom), (0, 0, 0))
            self.assertLessEqual(left, 1)         # rentre au plus de l'epaisseur du filet vertical

    def test_split_cell_runs_from_rule_to_rule_without_covering_them(self):
        """La cellule divisee remplit la hauteur de sa ligne : sous le filet haut (rentre de son epaisseur),
        jusqu'au bord bas, sans le debordement de marges d'avant."""
        from settings_widgets import _TABLE_INNER_BORDER
        checked = 0
        for split in self.splits:
            row = split.parentWidget()
            while row is not None and not isinstance(row, _TableRow):
                row = row.parentWidget()
            if row is None:
                continue
            top = split.mapTo(row, QPoint(0, 0)).y()
            h = _TABLE_INNER_BORDER["h"]
            first = row.parentWidget().findChildren(_TableRow)[0] is row
            expected = 0 if first else (h["thickness"] if h["enabled"] else 0)
            self.assertEqual(top, expected)
            self.assertEqual(top + split.height(), row.height())
            checked += 1
        self.assertGreater(checked, 3)

    def test_alignment_is_individual_per_sub_cell(self):
        split = self.splits[0]
        before = split.aligns()
        split.setSubAlign(1, "left", "top", notify=False)
        after = split.aligns()
        self.assertEqual(after[1], ("left", "top"))
        self.assertEqual([a for i, a in enumerate(after) if i != 1], [a for i, a in enumerate(before) if i != 1])
        split.setSubAlign(1, *before[1], notify=False)

    def test_sub_cell_alignment_and_widths_round_trip(self):
        frame = next(f for f in self.win.findChildren(_TableFrame) if cells.split_of(
            next((w for w in f.findChildren(cells.SplitCell)), None)) is not None)
        state = frame._extra_dims
        key, cell = next((k, c) for k, c in state.cells.items() if cells.split_of(c.content()))
        split = cells.split_of(cell.content())
        split.setSubAlign(2, "right", "bottom", notify=False)
        dims = frame.collectDims()
        self.assertEqual(dims["split_align"][key][2], "right,bottom")
        split.setSubAlign(2, "center", "center", notify=False)
        frame.applyDims(dims)
        self.assertEqual(split.aligns()[2], ("right", "bottom"))
        split.setSubAlign(2, "center", "center", notify=False)


class RowHeightTest(WindowTestCase):
    @classmethod
    def setUpClass(cls):
        cls.win = build("theme")  # aspect generique : fenetre Theme (etape 6 de fm_theme)
        cls.win.resize(1300, 900)
        cls.win.show()
        for _ in range(5):
            app.processEvents()
        cls.frame = next(f for f in cls.win.findChildren(_TableFrame) if f.dimsKey() == "Tableaux#0")

    @classmethod
    def tearDownClass(cls):
        cls.win.close()

    def test_dragging_the_bottom_border_of_a_row_sets_its_height(self):
        heights = self.frame._extra_dims.heights
        row = heights.rows[1]
        before = row.height()
        pos = QPoint(10, row.height() - 1)           # bord bas de la ligne
        send_mouse(row, QEvent.MouseButtonPress, pos)
        send_mouse(row, QEvent.MouseMove, pos + QPoint(0, 30))
        send_mouse(row, QEvent.MouseButtonRelease, pos + QPoint(0, 30), Qt.NoButton)
        app.processEvents()
        self.assertEqual(row.height(), before + 30)
        dims = self.frame.collectDims()
        self.assertEqual(dims["row_heights"][1], before + 30)
        heights.set_height(1, 0)
        self.frame.applyDims(dims)
        self.assertEqual(row.height(), before + 30)
        heights.user = [0] * len(heights.rows)
        heights.apply()

    def test_equal_rows_option_makes_all_rows_identical_and_is_kept(self):
        heights = self.frame._extra_dims.heights
        heights.set_equal(True)
        app.processEvents()
        values = {r.height() for r in heights.rows}
        self.assertEqual(len(values), 1)
        self.assertTrue(self.frame.collectDims()["equal_rows"])
        heights.set_equal(False)
        app.processEvents()
        self.assertNotIn("equal_rows", self.frame.collectDims())

    def test_header_menu_has_the_equal_rows_option(self):
        head = self.frame._flat_head
        self.assertEqual(head.contextMenuPolicy(), Qt.CustomContextMenu)


class AccordionTest(WindowTestCase):
    def setUp(self):
        self.win = v2.SettingsWindowV2()
        page = self.win.stack.currentWidget()
        self.nodes = [n for n in page.findChildren(v2._LazyNode) if n.level == 1]
        self.addCleanup(self.win.close)

    def test_opening_a_section_closes_the_others(self):
        a, b = self.nodes[0], self.nodes[1]
        a.head.clicked.emit()
        self.assertFalse(a.is_collapsed())
        b.head.clicked.emit()
        self.assertFalse(b.is_collapsed())
        self.assertTrue(a.is_collapsed())

    def test_ctrl_keeps_the_others_open(self):
        a, b = self.nodes[0], self.nodes[1]
        a.head.clicked.emit()
        with mock.patch.object(QApplication, "keyboardModifiers", return_value=Qt.ControlModifier):
            b.head.clicked.emit()
        self.assertFalse(a.is_collapsed())
        self.assertFalse(b.is_collapsed())


class GapsTableTest(WindowTestCase):
    @lent
    def test_title_padding_lives_in_the_paragraph_tables(self):
        """Plus de sous-section « Padding (titre seulement) » ni « Retraits » : le padding du titre (avec
        avant / apres) est la ligne « Padding (titre) » de Paragraphes > Niveau N."""
        win = build()
        keys = [f.dimsKey() for f in win.findChildren(_TableFrame)]
        self.assertFalse([k for k in keys if k.startswith(("TITRES/Padding", "TITRES/Retraits"))])
        self.assertNotIn("Titre : Espacements", v2.CATALOG)
        field = next(w for sp, w in win.stores["General"]["specs"]
                     if not isinstance(sp, str) and sp.key == "title_level3_text_padding")
        captions = [c.text() for c in cells.split_of(field)._cap_labels]
        self.assertEqual(captions, ["LIER LES 4", "G", "H", "B", "D", "AVANT", "APRÈS"])

    @lent
    def test_background_tables_one_per_level(self):
        win = build()
        frames = [f for f in win.findChildren(_TableFrame) if f.dimsKey() == "TITRES/Paragraphes#0"]
        self.assertEqual(len(frames), 5)
        for frame in frames:
            rows = frame.findChildren(_TableRow)
            self.assertEqual(len(rows), 7)
        for n in range(1, 6):   # margin AU-DESSUS du padding ; padding (titre) puis (paragraphe) dessous
            labels = [spec.label for spec in v2.CATALOG[f"Titre : Fond {n}"]]
            self.assertEqual(labels, ["Couleur de fond", "Margin", "Padding", "Padding (titre)",
                                      "Padding (paragraphe)", "Bordures", "Border radius"])


class ToggleStylesTest(WindowTestCase):
    def setUp(self):
        self.win = build()
        self.addCleanup(self.win.close)

    @lent
    def test_coche_has_a_skin_row_with_text_and_icon_choices(self):
        labels = [sp.label for sp in v2.CATALOG["toggle1 : Coche"]]
        for wanted in ("Habillage", "Texte", "Police du texte", "Icône", "Couleur de l'icône"):
            self.assertIn(wanted, labels)

    @lent
    def test_skin_text_and_icon_are_painted_inside_the_coche(self):
        import settings_widgets as sw
        from settings_store import DEFAULT_SETTINGS
        toggle = sw._Toggle(True, style_override="toggle1", show_label=False)
        plain = toggle.grab().toImage()
        settings = copy.deepcopy(DEFAULT_SETTINGS)
        settings.update({"toggle1_coche_skin": "text", "toggle1_coche_text": "A", "toggle1_coche_width": 14,
                         "toggle1_outer_height": 24, "toggle1_outer_width": 40})
        sw._sync_toggle_style(settings)
        toggle.apply_style()
        with_text = toggle.grab().toImage()
        settings["toggle1_coche_skin"] = "icon"
        settings["toggle1_coche_icon"] = "punaise_01.png"
        sw._sync_toggle_style(settings)
        toggle.apply_style()
        with_icon = toggle.grab().toImage()
        sw._sync_toggle_style(copy.deepcopy(DEFAULT_SETTINGS))
        toggle.apply_style()
        self.assertNotEqual(plain, with_text)
        self.assertNotEqual(with_text, with_icon)

    @lent
    def test_menu_of_the_style_cell_offers_a_new_toggle(self):
        from PySide6.QtWidgets import QMenu
        picker = self.win.findChildren(v2._ToggleStylePicker)[0]
        cell = picker.parentWidget()
        while not isinstance(cell, cells._Cell):
            cell = cell.parentWidget()
        menu = QMenu()
        cell.populate_menu(menu)
        self.assertIn("Ajouter un nouveau toggle…", [a.text() for a in menu.actions()])

    @lent
    def test_adding_a_toggle_creates_its_subsection_card_and_settings(self):
        picker = self.win.findChildren(v2._ToggleStylePicker)[0]
        cards_before = len(picker._cards)
        key = self.win.add_toggle_style("Mon toggle")
        self.assertEqual(key, "toggle3")
        self.assertEqual(self.win.settings["toggle_styles"][-1], {"key": "toggle3", "name": "Mon toggle"})
        self.assertIn("toggle3_outer_width", self.win.settings)
        self.assertIn("toggle3_kind", self.win.settings)
        self.assertEqual(len(picker._cards), cards_before + 1)
        node = next(n for n in self.win.findChildren(v2._LazyNode) if n.node.title == "Mon toggle")
        v2.expand_all(self.win.stack.currentWidget())
        self.assertEqual([c.node.title for c in node._child_nodes], ["Type", "Cadre", "Coche"])
        values = self.win.wired_values()
        self.assertIn("toggle3_coche_skin", values)
        self.assertIn("toggle3_icon_frames", values)
        self.assertEqual(self.win.add_toggle_style("Autre"), "toggle4")
        self.assertEqual(self.win.add_toggle_style("Autre"), "toggle5")
        self.assertEqual(self.win.settings["toggle_styles"][-1]["name"], "Autre (2)")    # noms uniques

    @lent
    def test_cards_have_the_same_width_and_the_column_grows_with_them(self):
        picker = self.win.findChildren(v2._ToggleStylePicker)[0]
        self.win.add_toggle_style("Un toggle au nom nettement plus long")
        app.processEvents()
        widths = {card.width() for card in picker._cards.values()}
        self.assertEqual(len(widths), 1)
        cell = picker.parentWidget()
        while not isinstance(cell, cells._Cell):
            cell = cell.parentWidget()
        self.assertGreaterEqual(cell.width(), picker.minimumSizeHint().width())

    @lent
    def test_rename_and_delete_from_the_card_and_the_subsection_title(self):
        from PySide6.QtWidgets import QMenu
        from settings_widgets import add_context_extras
        picker = self.win.findChildren(v2._ToggleStylePicker)[0]
        node = next(n for n in self.win.findChildren(v2._LazyNode) if n.node.toggle_key == "toggle2")
        for menu_of in (lambda m: picker.populate_card_menu(m, "toggle2"),
                        lambda m: add_context_extras(node._head.head, m)):
            menu = QMenu()
            menu_of(menu)
            texts = [a.text() for a in menu.actions()]
            self.assertIn("Renommer le toggle…", texts)
            self.assertIn("Supprimer le toggle", texts)
        self.assertEqual(self.win.rename_toggle_style("toggle2", "Carré"), "Carré")
        self.assertEqual(node.node.title, "Carré")
        self.assertEqual(picker._cards["toggle2"].title.text(), "Carré")
        self.assertIn({"key": "toggle2", "name": "Carré"}, self.win.settings["toggle_styles"])
        # Supprimer le style choisi par defaut : le premier restant le devient ; ses champs sont oublies.
        picker.setValue("toggle2")
        self.win.settings["toggle_style"] = "toggle2"
        self.assertTrue(self.win.delete_toggle_style("toggle2"))
        app.processEvents()
        self.assertNotIn("toggle2", picker._cards)
        self.assertFalse([n for n in self.win.findChildren(v2._LazyNode) if n.node.toggle_key == "toggle2"])
        self.assertEqual(self.win.settings["toggle_style"], "toggle1")
        self.assertEqual(picker.value(), "toggle1")
        self.assertFalse(any(k.startswith("toggle2_") for k in self.win.wired_values()))
        # Le dernier style ne se supprime pas (ligne grisee).
        self.assertFalse(self.win.delete_toggle_style("toggle1"))
        menu = QMenu()
        picker.populate_card_menu(menu, "toggle1")
        delete = next(a for a in menu.actions() if a.text() == "Supprimer le toggle")
        self.assertFalse(delete.isEnabled())

    @lent
    def test_toggle_tables_are_linked_between_styles(self):
        self.win.add_toggle_style("Nouveau")
        v2.expand_all(self.win.stack.currentWidget())
        self.win.resize(1300, 900)
        self.win.show()
        for _ in range(5):
            app.processEvents()
        frames = [f for f in self.win.findChildren(_TableFrame) if f.dimsKey() == "Toggles/Cadre#0"]
        self.assertEqual(len(frames), 3)
        head = frames[0]._flat_head
        head._set_width(0, head._widths[0] + 37)
        for frame in frames[1:]:
            self.assertEqual(frame._flat_head._widths, head._widths)

    @lent
    def test_right_click_on_any_toggle_changes_its_style_and_it_is_kept(self):
        from PySide6.QtWidgets import QMenu
        from settings_widgets import _SelectField, add_toggle_style_menu
        toggle = next(t for t in self.win.findChildren(_Toggle) if t.style_id)
        base = toggle._base_override                       # type 1 seul dans sa cellule, type 2 sinon
        other, other_name = ("toggle2", "Toggle 2") if base == "toggle1" else ("toggle1", "Toggle 1")
        menu = QMenu()
        add_toggle_style_menu(toggle, menu)
        select = menu.actions()[0].defaultWidget().findChild(_SelectField)
        self.assertEqual(select._options, ["Par défaut", "Toggle 1", "Toggle 2"])
        select._select(other_name)
        self.assertEqual(toggle._style_key(), other)
        self.assertEqual(self.win.settings["toggle_style_overrides"], {toggle.style_id: other})
        # A la reouverture, le toggle retrouve son style.
        saved = copy.deepcopy(self.win.settings)
        with mock.patch.object(v2, "load_settings", lambda: copy.deepcopy(saved)):
            win = build()
        self.addCleanup(win.close)
        again = next(t for t in win.findChildren(_Toggle) if t.style_id == toggle.style_id)
        self.assertEqual(again._style_key(), other)
        # « Par defaut » : retour au style d'origine.
        menu = QMenu()
        add_toggle_style_menu(again, menu)
        menu.actions()[0].defaultWidget().findChild(_SelectField)._select("Par défaut")
        self.assertEqual(again._style_key(), base)
        self.assertEqual(win.settings["toggle_style_overrides"], {})

    @lent
    def test_icon_toggle_shows_its_images_and_plays_the_sequence(self):
        import shutil
        import tempfile
        from pathlib import Path
        from PySide6.QtGui import QColor, QImage
        import settings_store
        import settings_widgets as sw
        folder = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(folder, ignore_errors=True))
        with mock.patch.object(fm_theme.tokens, "_TOGGLE_ICONS_DIR", Path(folder) / "toggle_icons"):
            paths = {}
            for name, color in (("on", "#00ff00"), ("off", "#ff0000"), ("step2", "#0000ff"), ("step10", "#ffff00")):
                image = QImage(20, 20, QImage.Format_ARGB32)
                image.fill(QColor(color))
                paths[name] = str(Path(folder) / f"{name}.png")
                image.save(paths[name])
            specs = {getattr(sp, "key", sp): w for sp, w in self.win.stores["General"]["specs"]}
            specs["toggle1_icon_on"]._v2_parts["on"].setFiles([paths["on"]])
            specs["toggle1_icon_on"]._v2_parts["off"].setFiles([paths["off"]])
            specs["toggle1_icon_frames"].setFiles([paths["step10"], paths["step2"]])
            specs["toggle1_kind"]._select("Icônes")
            values = self.win.current_values()
            self.assertEqual(values["toggle1_kind"], "icons")
            self.assertEqual(values["toggle1_icon_frames"], ["toggle1_step2.png", "toggle1_step10.png"])
            sw._sync_toggle_style(values)
            try:
                toggle = sw._Toggle(True, style_override="toggle1", show_label=False)

                def center():
                    image = toggle.grab().toImage()
                    return image.pixelColor(image.width() // 2, image.height() // 2).name()

                self.assertEqual(center(), "#00ff00")
                toggle.setChecked(False)
                toggle._anim.setCurrentTime(toggle._anim.duration() // 2)
                self.assertIn(center(), ("#0000ff", "#ffff00"))      # une image de la sequence
                toggle._anim.setCurrentTime(toggle._anim.duration())
                self.assertEqual(center(), "#ff0000")
            finally:
                sw._sync_toggle_style(copy.deepcopy(_DEFAULTS))

    @lent
    def test_icon_rows_are_greyed_while_the_type_is_qt(self):
        specs = {getattr(sp, "key", sp): w for sp, w in self.win.stores["General"]["specs"]}
        kind, icons, frames = specs["toggle1_kind"], specs["toggle1_icon_on"], specs["toggle1_icon_frames"]
        self.assertEqual(kind.value(), "Qt")
        self.assertFalse(icons.isEnabled())
        self.assertFalse(frames.isEnabled())
        self.assertTrue(specs["toggle1_anim_ms"].isEnabled())
        kind._select("Icônes")
        self.assertTrue(icons.isEnabled())
        self.assertTrue(frames.isEnabled())
        kind._select("Qt")
        self.assertFalse(icons.isEnabled())

    @lent
    def test_split_cell_captions_have_their_own_header_color(self):
        from settings_layout import _TABLE_HEAD
        labels = [sp.label for sp in v2.CATALOG["Tableaux"]]
        self.assertIn("Couleur d'entête (cellules)", labels)
        self.win.resize(1300, 900)
        self.win.show()
        for _ in range(5):
            app.processEvents()
        merged = self.win.current_values()
        merged["table_cell_head_color"] = "#ff0000"
        self.win._restyle_tables(merged)
        try:
            self.assertEqual(_TABLE_HEAD["cell_bg"], "#ff0000")
            split = next(s for s in self.win.findChildren(cells.SplitCell) if s.isVisible())
            image = split.grab().toImage()
            self.assertEqual(image.pixelColor(2, 2).name(), "#ff0000")
            self.assertNotEqual(_TABLE_HEAD["bg"], "#ff0000")          # l'entete des tableaux ne change pas
        finally:
            merged["table_cell_head_color"] = "tableHead"
            self.win._restyle_tables(merged)

    @lent
    def test_selection_color_tints_selected_columns(self):
        import settings_widgets as sw
        labels = [sp.label for sp in v2.CATALOG["Tableaux"]]
        self.assertIn("Couleur de sélection", labels)
        merged = self.win.current_values()
        merged["table_selection_color"] = "#ff0000"
        self.win._restyle_tables(merged)
        try:
            self.assertEqual(sw._selection_color(56).name(), "#ff0000")
            head = self.win.findChildren(cells._ResizableTableHeader)[0]
            head._selected = {0}
            head._refresh_cell_style(0)
            self.assertIn("rgba(255, 0, 0, 56)", head._cells[0].styleSheet())
        finally:
            sw._TABLE_SELECTION["color"] = "#5f9bd0"

    @lent
    def test_custom_style_keys_survive_loading(self):
        from settings_store import _DYNAMIC_KEY
        self.assertTrue(_DYNAMIC_KEY.match("toggle3_outer_width"))
        self.assertTrue(_DYNAMIC_KEY.match("toggle12_coche_skin"))
        self.assertFalse(_DYNAMIC_KEY.match("toggle1_outer_width"))


class RoundTripTest(WindowTestCase):
    """Ce que l'utilisateur dimensionne est retrouve a la reouverture."""

    @lent
    def test_everything_dimensioned_comes_back_in_a_new_window(self):
        v2.AUTOSAVE = True
        disk = {}
        geometry = {}
        self.addCleanup(lambda: setattr(v2, "AUTOSAVE", False))
        import settings_widgets as sw
        patches = [
            mock.patch.object(v2, "save_settings", lambda s: disk.update(copy.deepcopy(s))),
            mock.patch.object(v2, "_save_window_geometry", lambda b64, key: geometry.update({key: b64})),
        ]
        first = v2.SettingsWindowV2()
        disk.update(copy.deepcopy(first.settings))
        patches.append(mock.patch.object(v2, "load_settings", lambda: copy.deepcopy(disk)))
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        first.resize(1200, 880)
        first.show()
        v2.expand_all(first.stack.currentWidget())
        for node in first.stack.currentWidget().findChildren(v2._LazyNode):
            node.set_collapsed(False)
        v2.expand_all(first.stack.currentWidget())
        for _ in range(5):
            app.processEvents()
        frame = next(f for f in first.findChildren(_TableFrame) if f.dimsKey() == "Tableaux#0")
        frame._flat_head._set_width(0, frame._flat_head._widths[0] + 25)
        frame._extra_dims.cells["r1c1"].setAlign("left", "bottom")
        frame._extra_dims.heights.set_height(2, 120)
        frame._flat_head._set_width(1, 700)         # colonnes libres : l'ancienne extensible aussi
        split_frame = next(f for f in first.findChildren(_TableFrame) if f.findChildren(cells.SplitCell))
        split = split_frame.findChildren(cells.SplitCell)[0]
        split.setSubAlign(1, "right", "top")
        first._on_range("item_column_width", 50, 777)
        expected_col = frame._flat_head._widths[0]
        expected_cols = list(frame._flat_head._widths)
        first._persist_now()
        first.close()
        self.assertIn(v2.GEOMETRY_KEY, geometry)
        self.assertEqual(disk["slider_ranges"]["item_column_width"], [50, 777])

        v2._set_table_dims(disk["table_dims"])
        second = v2.SettingsWindowV2()
        second.resize(1200, 880)
        second.show()
        v2.expand_all(second.stack.currentWidget())
        for node in second.stack.currentWidget().findChildren(v2._LazyNode):
            node.set_collapsed(False)
        v2.expand_all(second.stack.currentWidget())
        for _ in range(5):
            app.processEvents()
        again = next(f for f in second.findChildren(_TableFrame) if f.dimsKey() == "Tableaux#0")
        self.assertEqual(again._flat_head._widths[0], expected_col)
        self.assertEqual(again._extra_dims.cells["r1c1"].align(), ("left", "bottom"))
        self.assertEqual(again._extra_dims.heights.user[2], 120)
        self.assertEqual(again._flat_head._widths, expected_cols)
        m = again.layout().contentsMargins()
        self.assertEqual(again.width(), sum(expected_cols) + m.left() + m.right())   # tableau = somme
        key = split_frame.dimsKey()
        same = next(f for f in second.findChildren(_TableFrame) if f.dimsKey() == key)
        self.assertEqual(same.findChildren(cells.SplitCell)[0].aligns()[1], ("right", "top"))
        field = next(w for sp, w in second.stores["General"]["specs"]
                     if not isinstance(sp, str) and sp.key == "item_column_width")
        self.assertEqual((field.slider._min, field.slider._max), (50, 777))
        second.close()


class SliderRangeTest(WindowTestCase):
    def test_range_is_applied_and_kept_around_the_value(self):
        field = _SliderField(0, 10, 7)
        cells.set_field_range(field, 0, 100)
        self.assertEqual((field.slider._min, field.slider._max, field.value()), (0, 100, 7))
        cells.set_field_range(field, 0, 5)
        self.assertEqual(field.value(), 5)

    def test_saved_range_never_changes_the_stored_value(self):
        field = _SliderField(0, 10, 7)
        cells.apply_saved_range(field, [0, 3])
        self.assertEqual(field.value(), 7)
        self.assertEqual(field.slider._max, 7)

    def test_range_change_is_written_straight_away(self):
        v2.AUTOSAVE = True
        try:
            win = v2.SettingsWindowV2()
            disk = copy.deepcopy(win.settings)
            written = []
            with mock.patch.object(v2, "load_settings", lambda: copy.deepcopy(disk)), \
                    mock.patch.object(v2, "save_settings", lambda s: (written.append(s), disk.update(s))):
                win._on_range("column_padding#1", 0, 99)
            self.assertEqual(written[-1]["slider_ranges"]["column_padding#1"], [0, 99])
        finally:
            v2.AUTOSAVE = False

    @lent
    def test_saved_range_comes_back_in_new_fields(self):
        win = v2.SettingsWindowV2()
        win.settings["slider_ranges"] = {"item_column_width": [100, 999]}
        v2.expand_all(win.stack.currentWidget())
        for node in win.stack.currentWidget().findChildren(v2._LazyNode):
            node.set_collapsed(False)
        v2.expand_all(win.stack.currentWidget())
        field = next(w for sp, w in win.stores["General"]["specs"]
                     if not isinstance(sp, str) and sp.key == "item_column_width")
        self.assertEqual((field.slider._min, field.slider._max), (100, 999))


class AutosaveTest(WindowTestCase):
    def setUp(self):
        v2.AUTOSAVE = True
        self.win = build()
        self.win.resize(1200, 900)
        self.win.show()
        for _ in range(5):
            app.processEvents()
        self.disk = copy.deepcopy(self.win.settings)
        self.written, self.geometry = [], []
        patches = [
            mock.patch.object(v2, "load_settings", lambda: copy.deepcopy(self.disk)),
            mock.patch.object(v2, "save_settings", lambda s: (self.written.append(copy.deepcopy(s)),
                                                              self.disk.update(copy.deepcopy(s)))),
            mock.patch.object(v2, "_save_window_geometry", lambda b64, key: self.geometry.append((key, b64))),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(lambda: setattr(v2, "AUTOSAVE", False))
        self.addCleanup(self.win.close)

    @lent
    def test_window_size_is_saved(self):
        self.win._persist_now()
        self.assertTrue(self.geometry)
        self.assertEqual(self.geometry[-1][0], v2.GEOMETRY_KEY)

    @lent
    def test_table_dims_are_saved_without_validating(self):
        frame = next(f for f in self.win.findChildren(_TableFrame) if f.dimsKey() == "Tableaux#0")
        head = frame._flat_head
        head._set_width(0, head._widths[0] + 33)
        frame._extra_dims.cells["r0c1"].setAlign("center", "top")
        self.win._persist_now()
        saved = self.written[-1]["table_dims"]["Tableaux#0"]
        self.assertEqual(saved["cols"][0], head._widths[0])
        self.assertEqual(saved["align"]["r0c1"], "center,top")

    @lent
    def test_a_resize_arms_the_debounced_save(self):
        self.win._persist_timer.stop()
        self.win.resize(self.win.width() + 20, self.win.height())
        app.processEvents()
        self.assertTrue(self.win._persist_timer.isActive())


class RenamedSectionsTest(WindowTestCase):
    """TITRE -> TITRES, Espacements -> Padding (titre seulement), Fond -> Paragraphes : les dimensions
    enregistrees sous les anciens noms sont recopiees (pas deplacees : la v1 garde les siennes)."""

    def test_old_dims_keys_are_copied_to_the_new_names(self):
        old = {"TITRE/Espacements#0": {"cols": [1]}, "TITRE/Fond/Niveau 2#0": {"cols": [2]},
               "TITRE/Polices#0": {"cols": [3]}, "Tableaux#0": {"cols": [4]}}
        out = v2._renamed_dims(old)
        self.assertEqual(out["TITRES/Padding (titre seulement)#0"], {"cols": [1]})
        self.assertEqual(out["TITRES/Paragraphes/Niveau 2#0"], {"cols": [2]})
        self.assertEqual(out["TITRES/Polices#0"], {"cols": [3]})
        for key in old:
            self.assertEqual(out[key], old[key])
        self.assertEqual(v2._renamed_dims({"TITRE/Polices#0": 1, "TITRES/Polices#0": 2})["TITRES/Polices#0"], 2)

    def test_section_names(self):
        titres = next(n for n in v2.GENERAL_TREE if n.title == "TITRES")
        self.assertEqual([n.title for n in titres.children], ["Polices", "Paragraphes"])

    def test_old_paragraph_rows_are_shifted(self):
        """Dimensions d'avant les 2 nouvelles lignes : Bordures/Border radius (r3, r4) passent en r5, r6."""
        old = {"split": {"r1c1": [1], "r3c1": [3], "r4c1": [4]}, "align": {"r4c0": "left,top"},
               "row_heights": [10, 11, 12, 13, 14]}
        new = v2._shift_paragraph_rows(old)
        self.assertEqual(new["split"], {"r1c1": [1], "r5c1": [3], "r6c1": [4]})
        self.assertEqual(new["align"], {"r6c0": "left,top"})
        self.assertEqual(new["row_heights"], [10, 11, 12, 0, 0, 13, 14])
        self.assertEqual(v2._shift_paragraph_rows(new), new)               # une seule fois


class LinkedParagraphTablesTest(WindowTestCase):
    """Titres > Paragraphes : les 5 tableaux (un par niveau) sont LE MEME tableau : une seule serie de
    dimensions, et toute modification se reporte sur les autres niveaux."""

    def setUp(self):
        self.win = build()
        self.win.resize(1300, 900)
        self.win.show()
        for _ in range(5):
            app.processEvents()
        self.addCleanup(self.win.close)
        self.frames = [f for f in self.win.findChildren(_TableFrame) if f.dimsKey() == "TITRES/Paragraphes#0"]

    @lent
    def test_five_tables_share_one_key(self):
        self.assertEqual(len(self.frames), 5)

    @lent
    def test_column_row_and_sub_cell_changes_reach_every_level(self):
        source, others = self.frames[0], self.frames[1:]
        source._flat_head._set_width(0, 233)                                   # largeur de colonne
        source._extra_dims.heights.set_height(1, 77)                           # hauteur de ligne
        split = next(c for c in source.findChildren(cells.SplitCell) if len(c._cells) >= 5)
        split.snap_provider = None
        split._drag = (1, 100, split._cells[1].width())                        # largeur de sous-cellule
        split._move(0, 140, split)
        split._end_drag()
        key = next(k for k, c in source._extra_dims.cells.items() if cells.split_of(c.content()) is split)
        for frame in others:
            self.assertEqual(frame._flat_head._widths, source._flat_head._widths)
            self.assertEqual(frame._extra_dims.heights.user[1], 77)
            twin = cells.split_of(frame._extra_dims.cells[key].content())
            self.assertEqual(twin.widths(), split.widths())

    @lent
    def test_old_per_level_dims_seed_the_shared_one(self):
        out = v2._renamed_dims({"TITRE/Fond/Niveau 1#0": {"cols": [111, 222]}})
        self.assertEqual(out["TITRES/Paragraphes#0"], {"cols": [111, 222]})


class SpaceAboveTest(WindowTestCase):
    """Clic droit sur un element d'une zone titre (tableau, titre) : « Ajouter une espace au-dessus »,
    curseur en direct ; l'espace est retenu (element_spaces) et reapplique a la reouverture."""

    def setUp(self):
        self.win = build()
        self.win.resize(1300, 900)
        self.win.show()
        for _ in range(5):
            app.processEvents()
        self.addCleanup(self.win.close)

    def _slider(self, widget):
        from PySide6.QtWidgets import QMenu, QWidgetAction
        menu = QMenu()
        self.win.add_space_action(widget, menu)
        action = next(a for a in menu.actions() if isinstance(a, QWidgetAction))
        return menu, action.defaultWidget().findChild(_SliderField)

    @lent
    def test_space_above_a_table(self):
        frame = next(f for f in self.win.findChildren(_TableFrame) if f.dimsKey() == "TITRES/Polices#0")
        cell = frame._extra_dims.cells["r0c0"]
        _menu, slider = self._slider(cell)                        # clic droit sur une cellule du tableau
        y0 = frame.mapTo(self.win, QPoint(0, 0)).y()
        slider.setValue(30)
        for _ in range(3):
            app.processEvents()
        self.assertEqual(frame._space_above_px, 30)
        # (le tableau avait deja l'espace par defaut au-dessus : TABLE_SPACE)
        self.assertEqual(frame.mapTo(self.win, QPoint(0, 0)).y(), y0 + 30 - self.win.TABLE_SPACE[False])
        key = self.win._space_key(frame)
        self.assertEqual(self.win.settings["element_spaces"][key], 30)
        slider.setValue(0)                                       # 0 est retenu (different du defaut)
        self.assertEqual(self.win.settings["element_spaces"][key], 0)
        slider.setValue(self.win.TABLE_SPACE[False])             # la valeur par defaut ne l'est pas
        self.assertNotIn(key, self.win.settings["element_spaces"])

    @lent
    def test_space_above_a_title_separates_it_from_its_sibling(self):
        node = next(n for n in self.win.findChildren(v2._LazyNode) if n.node.title == "Paragraphes")
        prev = node._head._box_prev
        self.assertIsNotNone(prev)
        _menu, slider = self._slider(node._head.head)              # clic droit sur le titre
        slider.setValue(20)
        self.assertEqual(node._space_above_px, 20)
        self.assertFalse(node._head._touches(prev, "top"))

    @lent
    def test_space_above_any_other_element_of_the_window(self):
        """Hors tableaux et titres (barre d'onglets, pied de fenetre...) : le clic droit que personne
        ne prend arrive a la fenetre, qui propose aussi l'espace ; retrouve par son chemin."""
        from PySide6.QtWidgets import QPushButton
        from settings_widgets import widget_at_path
        button = next(b for b in self.win.findChildren(QPushButton)
                      if b.isVisible() and self.win._space_element(b) is not None
                      and not isinstance(self.win._space_element(b), (_TableFrame, v2._LazyNode)))
        element = self.win._space_element(button)
        _menu, slider = self._slider(button)
        slider.setValue(12)
        key = self.win._space_key(element)
        self.assertTrue(key.startswith("ui:"))
        self.assertEqual(element._space_above_px, 12)
        self.assertIs(widget_at_path(self.win, key[3:]), element)
        self.assertEqual(self.win.settings["element_spaces"][key], 12)

    @lent
    def test_folder_reorder_row_in_the_columns_table(self):
        spec = next(sp for sp in v2.CATALOG["G Colonnes"] if sp.key == "folder_reorder_enabled")
        self.assertEqual((spec.label, spec.kind, spec.default), ("Permettre le replacement des dossiers", "bool", True))
        self.assertIn("folder_reorder_enabled", _DEFAULTS)

    @lent
    def test_space_target_and_paths(self):
        """Moteur commun (fenetre principale et reglages) : element empile verticalement sous le clic,
        chemin stable aller-retour."""
        from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget
        from settings_widgets import set_space_above, space_target, widget_at_path, widget_path
        root = QWidget()
        col = QVBoxLayout(root)
        top, block = QLabel("haut"), QWidget()
        row = QHBoxLayout(block)
        left, right = QLabel("g"), QLabel("d")
        row.addWidget(left)
        row.addWidget(right)
        col.addWidget(top)
        col.addWidget(block)
        self.assertIs(space_target(right, root), block)          # dans une ligne : la ligne entiere
        self.assertIs(space_target(top, root), top)
        self.assertIs(widget_at_path(root, widget_path(block, root)), block)
        set_space_above(block, 18)
        self.assertEqual(col.itemAt(1).spacerItem().sizeHint().height(), 18)

    @lent
    def test_saved_spaces_come_back(self):
        frame = next(f for f in self.win.findChildren(_TableFrame) if f.dimsKey() == "TITRES/Polices#0")
        key = self.win._space_key(frame)
        saved = copy.deepcopy(_DEFAULTS)
        saved["element_spaces"] = {key: 44}
        with mock.patch.object(v2, "load_settings", lambda: copy.deepcopy(saved)):
            again = build()
        self.addCleanup(again.close)
        twin = next(f for f in again.findChildren(_TableFrame) if f.dimsKey() == "TITRES/Polices#0")
        self.assertEqual(twin._space_above_px, 44)


class FreeColumnsTest(WindowTestCase):
    """Colonnes libres : aucune colonne n'est contrainte par une autre ; le TABLEAU change de largeur."""

    def setUp(self):
        self.win = build()
        self.win.resize(1300, 900)
        self.win.show()
        for _ in range(5):
            app.processEvents()
        self.addCleanup(self.win.close)
        self.frame = next(f for f in self.win.findChildren(_TableFrame) if f.dimsKey() == "TITRES/Paragraphes#0")
        self.head = self.frame._flat_head

    def _outer(self):
        m = self.frame.layout().contentsMargins()
        return m.left() + m.right()

    @lent
    def test_no_stretch_column_and_table_is_the_sum_of_its_columns(self):
        self.assertTrue(all(self.head._widths))
        self.assertEqual(self.frame.width(), sum(self.head._widths) + self._outer())
        self.assertFalse(self.frame._grip.isVisible())

    @lent
    def test_widening_a_column_widens_the_table_only(self):
        before, width = list(self.head._widths), self.frame.width()
        self.head.beginDrag((0, 1), 500)
        self.head.dragTo(560)
        self.head.endDrag()
        app.processEvents()
        self.assertEqual(self.head._widths[0], before[0] + 60)
        self.assertEqual(self.head._widths[1:], before[1:])            # les autres ne bougent pas
        self.assertEqual(self.frame.width(), width + 60)

    @lent
    def test_selected_columns_are_not_limited_by_the_table(self):
        self.head._selected = {0, 1}
        start = self.head._widths[0]
        self.head.beginDrag((0, 1), 500)
        self.head.dragTo(500 + 900)                                    # bien au-dela de l'ancienne limite
        self.head.endDrag()
        self.assertEqual(self.head._widths[0], start + 900)
        self.assertEqual(self.head._widths[1], start + 900)
        self.assertEqual(self.frame.width(), sum(self.head._widths) + self._outer())

    @lent
    def test_widening_a_sub_cell_widens_its_column(self):
        split = next(sp for sp in self.frame.findChildren(cells.SplitCell) if len(sp._cells) == 5)
        split.snap_provider = None
        column = self.head._widths[1]
        split._drag = (2, 100, split._cells[2].width())
        split._move(0, 100 + column, split)                            # plus que toute la colonne
        split._end_drag()
        self.assertGreater(self.head._widths[1], column)
        self.assertGreaterEqual(self.head._widths[1], split.minimumSizeHint().width())

    @lent
    def test_selected_columns_get_exactly_the_same_width(self):
        """4 colonnes selectionnees, de largeurs differentes : apres redimensionnement elles ont
        EXACTEMENT la meme largeur reelle (entete ET cellules de chaque ligne)."""
        frame = next(f for f in self.win.findChildren(_TableFrame) if f.dimsKey().startswith("TITRES/Polices"))
        head = frame._flat_head
        for i, w in zip((1, 2, 3, 4), (300, 95, 140, 210)):
            head._set_width(i, w)
        head._selected = {1, 2, 3, 4}
        head.beginDrag((2, 1), 500)
        head.dragTo(530)
        head.endDrag()
        for _ in range(3):
            app.processEvents()
        self.assertEqual(len({head._widths[i] for i in (1, 2, 3, 4)}), 1)
        self.assertEqual(len({head._cells[i].width() for i in (1, 2, 3, 4)}), 1)
        for row in frame.findChildren(_TableRow):
            widths = {c.width() for c in row.findChildren(cells._Cell) if c.parentWidget() is row
                      and frame._extra_dims.head is head}
            self.assertTrue(widths)
        state = frame._extra_dims
        for r in range(5):
            self.assertEqual(len({state.cells[f"r{r}c{c}"].width() for c in (1, 2, 3, 4)}), 1)

    @lent
    def test_selected_sub_cells_get_exactly_the_same_width(self):
        """4 sous-cellules selectionnees : MEME largeur reelle, meme si leurs contenus different ;
        les autres (et la colonne du tableau) s'adaptent."""
        split = next(sp for sp in self.frame.findChildren(cells.SplitCell) if len(sp._cells) == 5)
        split.snap_provider = None
        split._selected = {1, 2, 3, 4}
        split._drag = (2, 100, split._cells[2].width())
        for x in (130, 90, 40):                                        # elargir puis retrecir
            split._move(0, x, split)
            for _ in range(3):
                app.processEvents()
            self.assertEqual(len({split._cells[k].width() for k in (1, 2, 3, 4)}), 1, x)
        split._end_drag()
        self.assertGreaterEqual(self.head._widths[1], split.minimumSizeHint().width())

    @lent
    def test_cell_contents_never_constrain_a_column(self):
        """Le contenu des cellules ne contraint plus la largeur d'une colonne : les cellules divisees
        s'y plient (sous-cellules reglees reduites du meme facteur, egales entre elles), puis
        RETROUVENT leurs largeurs reglees quand la colonne s'elargit a nouveau."""
        split = next(sp for sp in self.frame.findChildren(cells.SplitCell) if len(sp._cells) == 5)
        split.setWidths([0, 200, 200, 200, 200])
        self.head._set_width(1, split.naturalWidth() + 40)
        app.processEvents()
        self.assertEqual(split._shown, [0, 200, 200, 200, 200])
        wide = self.head._widths[1]
        self.head.beginDrag((1, 1), 1000)
        self.head.dragTo(1000 - wide + 150)                            # bien plus etroit que le contenu
        self.assertEqual(self.head._widths[1], 150)
        self.assertEqual(len(set(split._shown[1:])), 1)                # pliees, toujours egales
        self.assertLess(split._shown[1], 200)
        self.assertEqual(split.widths(), [0, 200, 200, 200, 200])      # largeurs reglees intactes
        self.head.dragTo(1000)                                         # on reelargit
        self.head.endDrag()
        app.processEvents()
        self.assertEqual(split._shown, [0, 200, 200, 200, 200])        # elles reviennent
        self.assertEqual([split._cells[k].width() for k in range(1, 5)], [200] * 4)

    @lent
    def test_last_sub_cell_has_a_right_border_when_it_stops_short(self):
        """Derniere sous-cellule reglee, plus etroite que la colonne : son bord droit a un filet et se tire."""
        split = next(sp for sp in self.frame.findChildren(cells.SplitCell) if len(sp._cells) == 5)
        split.setWidths([0, 0, 0, 0, 150])
        self.head._set_width(1, self.head._widths[1] + 150)
        for _ in range(3):
            app.processEvents()
        right = split._right_edge()
        self.assertIsNotNone(right)
        self.assertEqual(split._edge_at(right), split._order[-1])
        # Redimensionnable a la souris, saisie depuis la zone vide a sa droite.
        split.snap_provider = None
        y = split.height() // 2
        send_mouse(split, QEvent.MouseButtonPress, QPoint(right + 2, y))
        send_mouse(split, QEvent.MouseMove, QPoint(right + 32, y), Qt.LeftButton)
        send_mouse(split, QEvent.MouseButtonRelease, QPoint(right + 32, y), Qt.NoButton)
        self.assertEqual(split.widths()[split._order[-1]], 180)
        split.setWidths([0] * 5)
        app.processEvents()
        self.assertIsNone(split._right_edge())                         # libre : elle va jusqu'au bord

    @lent
    def test_old_stretch_width_is_converted(self):
        cols = list(self.head._widths)
        cols[1] = 0                                                   # ancienne colonne extensible
        dims = self.frame._legacy_dims({"cols": cols, "width": 900})
        self.assertGreater(dims["cols"][1], 0)


class SelectionEqualWidthAndSnapTest(WindowTestCase):
    """Plusieurs colonnes / sous-cellules selectionnees = meme largeur en direct ; aimantation ;
    justification des titres."""

    @classmethod
    def setUpClass(cls):
        cls.win = build("theme")  # aspect generique : fenetre Theme (etape 6 de fm_theme)
        cls.win.resize(1300, 900)
        cls.win.show()
        for _ in range(5):
            app.processEvents()
        cls.frames = cls.win.findChildren(_TableFrame)

    @classmethod
    def tearDownClass(cls):
        cls.win.close()

    def test_selecting_several_columns_makes_them_resize_together(self):
        frame = next(f for f in self.frames
                     if getattr(f, "_flat_head", None) is not None and sum(1 for w in f._flat_head._widths if w) >= 3)
        head = frame._flat_head
        fixed = [i for i, w in enumerate(head._widths) if w][:2]
        head._selected = set()
        head._select_click(fixed[0], False)
        head._select_click(fixed[1], True)
        self.assertEqual(head._selected, set(fixed))
        self.assertFalse(any(hasattr(t, "toggled") for t in head._equal_toggles))      # plus de toggle d'entete
        head.beginDrag((fixed[0], 1), 500)
        head.dragTo(530)
        head.endDrag()
        self.assertEqual(head._widths[fixed[0]], head._widths[fixed[1]])
        head._selected = set()

    def test_split_cell_captions_are_selectable_and_resize_together(self):
        split = next(s for s in self.win.findChildren(cells.SplitCell) if len(s._cells) >= 4 and s.isVisible())
        split.snap_provider = None
        split._selected = set()
        split._select_click(0, False)
        split._select_click(1, True)
        self.assertEqual(split.selected(), {0, 1})
        split._drag = (0, 100, split._cells[0].width())
        split._move(0, 140, split)
        split._drag = None
        widths = split.widths()
        self.assertEqual(widths[0], widths[1])
        self.assertGreater(widths[0], 0)
        split._selected = set()
        split.setWidths([0] * len(widths))

    def test_split_cell_edge_snaps_to_borders_of_other_rows(self):
        split = next(s for s in self.win.findChildren(cells.SplitCell) if len(s._cells) >= 3 and s.isVisible())
        left = split._cells[0].mapToGlobal(QPoint(0, 0)).x()
        split.snap_provider = lambda: [left + 200]
        self.assertEqual(split._snapped(0, 195), 200)
        self.assertEqual(split._snapped(0, 150), 150)
        split.snap_provider = None

    def test_width_badge_while_resizing(self):
        """Pendant un redimensionnement : un ENCART par colonne / sous-cellule concernee (le titre ne
        change pas), qui affiche la largeur REELLE de chacune, y compris en multiselection."""
        from settings_widgets import _WidthBadge
        v2.expand_all(self.win.stack.currentWidget())
        for _ in range(3):
            app.processEvents()
        frame = next(f for f in self.win.findChildren(_TableFrame)
                     if getattr(f, "_flat_head", None) is not None and f.isVisible())
        head = frame._flat_head
        i = 0
        if not head._widths[i]:
            head._set_width(i, 160)
        title = head._cells[i].text()
        head.beginDrag((i, 1), 500)
        head.dragTo(510)
        badges = [b for b in head.findChildren(_WidthBadge) if b.isVisible()]
        self.assertEqual(len(badges), 1)
        self.assertEqual(head._cells[i].text(), title)
        self.assertEqual(badges[0].text(), f"{head._cells[i].width()} px")
        self.assertTrue(head._cells[i].geometry().contains(badges[0].geometry().center()))
        head.endDrag()
        self.assertFalse([b for b in head.findChildren(_WidthBadge) if b.isVisible()])

        split = next(s for s in self.win.findChildren(cells.SplitCell) if len(s._cells) >= 3 and s.isVisible())
        split.snap_provider = None
        split._selected = {0, 1}                        # multiselection : un encart chacune, sa vraie largeur
        split._drag = (0, 100, split._cells[0].width())
        split._move(0, 104, split)
        app.processEvents()
        shown = sorted((b for b in split.findChildren(_WidthBadge) if b.isVisible()), key=lambda b: b.x())
        self.assertEqual(len(shown), 2)
        self.assertEqual([c.text() for c in split._cap_labels], split._cap_texts)
        self.assertEqual({b.text() for b in shown}, {f"{split._cells[k].width()} px" for k in (0, 1)})
        split._end_drag()
        self.assertFalse([b for b in split.findChildren(_WidthBadge) if b.isVisible()])
        split._selected = set()
        split.setWidths([0] * len(split._cells))

    def test_columns_can_be_moved_and_the_order_is_kept(self):
        frame = next(f for f in self.frames if f.dimsKey() == "Tableaux#0")
        head = frame._flat_head
        state = frame._extra_dims
        first = frame.findChildren(_TableRow)[0]
        before = [c.text() for c in head._cells]
        head.setOrder([1, 0])
        for _ in range(3):
            app.processEvents()
        layout = frame.findChildren(_TableRow)[0].layout()
        self.assertIs(layout.itemAt(0).widget(), state.cells["r0c1"])
        self.assertEqual(frame.collectDims()["col_order"], [1, 0])
        head.setOrder([0, 1])
        frame.applyDims({"col_order": [1, 0]})
        self.assertEqual(head.order(), [1, 0])
        frame.applyDims({})
        self.assertEqual(head.order(), [0, 1])
        self.assertEqual([c.text() for c in head._cells], before)

    def test_dragging_a_title_moves_the_column_with_visual_targets(self):
        frame = next(f for f in self.frames if f.dimsKey() == "Tableaux#0")
        head = frame._flat_head
        spans = head._column_spans()
        press = QPoint((spans[0][0] + spans[0][1]) // 2, 10)
        ctrl = mock.patch.object(QApplication, "keyboardModifiers", lambda: Qt.ControlModifier)   # Ctrl + glisser
        ctrl.start()
        self.addCleanup(ctrl.stop)
        send_mouse(head, QEvent.MouseButtonPress, press)
        send_mouse(head, QEvent.MouseMove, QPoint(spans[1][1] - 4, 10))
        self.assertIsNotNone(head._reorder)
        self.assertEqual(head._reorder.target, 2)
        send_mouse(head, QEvent.MouseButtonRelease, QPoint(spans[1][1] - 4, 10))
        self.assertEqual(head.order(), [1, 0])
        head.setOrder([0, 1])

    def test_sub_cells_can_be_moved_like_columns_and_the_order_is_kept(self):
        frame, key, split = next((f, k, cells.split_of(c.content())) for f in self.frames
                                 for k, c in f._extra_dims.cells.items()
                                 if cells.split_of(c.content()) and len(cells.split_of(c.content())._cells) >= 3
                                 and cells.split_of(c.content()).isVisible())
        split.snap_provider = None
        spans = split._column_spans()
        press = QPoint((spans[0][0] + spans[0][1]) // 2, 8)
        drop = QPoint(spans[1][1] - 4, 8)
        ctrl = mock.patch.object(QApplication, "keyboardModifiers", lambda: Qt.ControlModifier)   # Ctrl + glisser
        ctrl.start()
        self.addCleanup(ctrl.stop)
        send_mouse(split, QEvent.MouseButtonPress, press)
        send_mouse(split, QEvent.MouseMove, drop)
        self.assertIsNotNone(split._reorder)
        self.assertEqual(split._reorder.target, 2)
        send_mouse(split, QEvent.MouseButtonRelease, drop)
        self.assertEqual(split.order()[:3], [1, 0, 2])
        for _ in range(3):
            app.processEvents()
        self.assertLess(split._cells[1].x(), split._cells[0].x())
        dims = frame.collectDims()
        self.assertEqual(dims["split_order"][key][:3], [1, 0, 2])
        split.setOrder(list(range(len(split._cells))), notify=False)
        frame.applyDims(dims)
        self.assertEqual(split.order()[:3], [1, 0, 2])
        frame.applyDims({})
        self.assertEqual(split.order(), list(range(len(split._cells))))

    def test_header_titles_are_justified_and_kept(self):
        frame = next(f for f in self.frames if f.dimsKey() == "Tableaux#0")
        state = frame._extra_dims
        default = state.head_aligns()[0]
        state.set_head_align(0, "center")
        dims = frame.collectDims()
        self.assertEqual(dims["head_align"], {"0": "center"})
        state.set_head_align(0, default, notify=False)
        frame.applyDims(dims)
        self.assertEqual(state.head_aligns()[0], "center")
        state.set_head_align(0, default, notify=False)

    def test_split_cell_captions_are_justified_and_kept(self):
        frame, key, split = next((f, k, cells.split_of(c.content())) for f in self.frames
                                 for k, c in f._extra_dims.cells.items() if cells.split_of(c.content()))
        split.setCapAlign(0, "left")
        dims = frame.collectDims()
        self.assertEqual(dims["split_head_align"][key][0], "left")
        split.setCapAlign(0, "center", notify=False)
        frame.applyDims(dims)
        self.assertEqual(split.capAligns()[0], "left")
        split.setCapAlign(0, "center", notify=False)

    def test_header_titles_are_renamed_in_place_and_kept(self):
        frame = next(f for f in self.frames if f.dimsKey() == "Tableaux#0")
        state, head = frame._extra_dims, frame._extra_dims.head
        original = head._cells[0].text()
        edit = cells.rename_inline(head._cells[0], lambda text: state.set_head_title(0, text))
        self.assertIs(edit.parentWidget(), head)
        edit.setText("Réglage")
        edit.editingFinished.emit()                       # Entree
        self.assertEqual(head._cells[0].text(), "RÉGLAGE")
        dims = frame.collectDims()
        self.assertEqual(dims["head_titles"], {"0": "RÉGLAGE"})
        state.set_head_title(0, "", notify=False)         # vide = titre d'origine
        self.assertEqual(head._cells[0].text(), original)
        frame.applyDims(dims)
        self.assertEqual(head._cells[0].text(), "RÉGLAGE")
        frame.applyDims({})
        self.assertEqual(head._cells[0].text(), original)
        self.assertNotIn("head_titles", frame.collectDims())

    def test_split_cell_captions_are_renamed_and_kept(self):
        frame, key, split = next((f, k, cells.split_of(c.content())) for f in self.frames
                                 for k, c in f._extra_dims.cells.items() if cells.split_of(c.content()))
        original = split.capTexts()[0]
        menu = QMenu()
        split.populate_caption_menu(menu, 0)
        rename = next(a for a in menu.actions() if a.text().startswith("Renommer"))
        rename.trigger()
        edit = split.findChild(QLineEdit, "RenameInline")
        edit.setText("gauche")
        edit.editingFinished.emit()
        self.assertEqual(split._cap_labels[0].text(), "GAUCHE")
        dims = frame.collectDims()
        self.assertEqual(dims["split_titles"][key], {"0": "GAUCHE"})
        frame.applyDims({})
        self.assertEqual(split.capTexts()[0], original)
        frame.applyDims(dims)
        self.assertEqual(split.capTexts()[0], "GAUCHE")
        split.setCapText(0, "", notify=False)
        # Echap : rien ne change.
        edit = cells.rename_inline(split._cap_labels[0], lambda text: split.setCapText(0, text))
        edit.setText("autre")
        QTest.keyClick(edit, Qt.Key_Escape)
        self.assertEqual(split.capTexts()[0], original)


class PresetDoesNotClobberLiveStateTest(WindowTestCase):
    def test_default_preset_keeps_dims_ranges_and_custom_toggles(self):
        import settings_store as store
        raw = {"default_preset": "p", "table_dims": {"A#0": {"width": 321}},
               "slider_ranges": {"k": [1, 2]}, "toggle_custom_styles": [{"key": "toggle3", "name": "x"}],
               "toggle3_coche_skin": "text"}
        preset = {"table_dims": {"A#0": {"width": 1}}, "slider_ranges": {}, "toggle_custom_styles": []}
        with mock.patch.object(store, "_PER_USER_PATH") as path, \
                mock.patch.object(store, "_load_presets", lambda: {"p": preset}):
            path.is_file.return_value = True
            path.read_text.return_value = __import__("json").dumps(raw)
            loaded = store.load_settings()
        self.assertEqual(loaded["table_dims"]["A#0"]["width"], 321)
        self.assertEqual(loaded["slider_ranges"], {"k": [1, 2]})
        self.assertEqual(loaded["toggle_custom_styles"][0]["key"], "toggle3")
        self.assertEqual(loaded["toggle3_coche_skin"], "text")


class RowMoveTest(WindowTestCase):
    """Tableaux > « Permettre le deplacement des lignes » : Ctrl + glisser la 1re cellule d'une ligne la
    deplace ; l'ordre est enregistre (row_order) et retrouve."""

    def setUp(self):
        self.win = build()
        self.win.resize(1300, 900)
        self.win.show()
        for _ in range(5):
            app.processEvents()
        self.addCleanup(self.win.close)
        self.addCleanup(lambda: cells._ROWS_MOVABLE.__setitem__("enabled", True))
        self.frame = next(f for f in self.win.findChildren(_TableFrame) if f.dimsKey() == "Tableaux#0")
        self.mover = self.frame._extra_dims.rows

    def _first_label(self, r):
        cell = self.mover.cells[r][self.mover.head.order()[0]]
        return cell.content()

    def _drag(self, r, to_row, modifiers=Qt.ControlModifier):
        from PySide6.QtCore import QEvent
        label = self._first_label(r)
        start = label.mapToGlobal(label.rect().center())
        target_row = self.mover.rows[to_row]
        end = target_row.mapToGlobal(QPoint(10, target_row.height() - 3))

        def send(kind, gpos, buttons):
            local = label.mapFromGlobal(gpos)
            event = QMouseEvent(kind, QPointF(local), QPointF(gpos), Qt.LeftButton, buttons, modifiers)
            QApplication.sendEvent(label, event)

        send(QEvent.MouseButtonPress, start, Qt.LeftButton)
        for k in range(1, 11):
            send(QEvent.MouseMove, start + (end - start) * k / 10, Qt.LeftButton)
        overlay = self.mover._overlay
        send(QEvent.MouseButtonRelease, end, Qt.NoButton)
        app.processEvents()
        return overlay

    @lent
    def test_ctrl_drag_on_the_first_cell_moves_the_row_and_it_is_kept(self):
        rows = list(self.mover.rows)
        overlay = self._drag(0, 2)
        self.assertIsNotNone(overlay)
        self.assertEqual(overlay.axis, "y")
        self.assertEqual(self.mover.order[:3], [1, 2, 0])
        layout = self.frame.layout()
        shown = sorted(rows, key=layout.indexOf)
        self.assertEqual(shown[:3], [rows[1], rows[2], rows[0]])
        dims = self.frame.collectDims()
        self.assertEqual(dims["row_order"][:3], [1, 2, 0])
        self.frame.applyDims({})
        self.assertEqual(self.mover.order, list(range(len(rows))))
        self.frame.applyDims(dims)
        self.assertEqual(self.mover.order[:3], [1, 2, 0])

    @lent
    def test_without_ctrl_or_when_disabled_nothing_moves(self):
        self._drag(0, 2, modifiers=Qt.NoModifier)
        self.assertEqual(self.mover.order, sorted(self.mover.order))
        cells._ROWS_MOVABLE["enabled"] = False
        self._drag(0, 2)
        self.assertEqual(self.mover.order, sorted(self.mover.order))
        self.assertIn("table_rows_movable", [sp.key for sp in v2.CATALOG["Tableaux"]])

    @lent
    def test_same_opacities_for_columns_split_cells_and_rows(self):
        from settings_layout import _ReorderOverlay
        self.assertEqual((_ReorderOverlay.GHOST_OPACITY, _ReorderOverlay.ORIGIN_OPACITY), (0.75, 0.25))
        # Colonnes et sous-cellules passent par la meme couche (axe x), les lignes par l'axe y.
        head = self.frame._flat_head
        head._begin_reorder(head._column_spans()[0][0] + 5)
        self.assertIsInstance(head._reorder, _ReorderOverlay)
        head._reorder.follow(head._column_spans()[1][1] - 2)
        self.assertEqual(head._reorder.target, 2)
        head._end_reorder()


class ColorPaletteFollowsTest(WindowTestCase):
    """Menus des couleurs (pastilles de l'appli) : toujours la palette de la section Couleurs, meme
    apres l'avoir modifiee fenetre ouverte, ou apres un changement de preset (signale)."""

    @classmethod
    def setUpClass(cls):
        cls.win = build("theme")  # aspect generique : fenetre Theme (etape 6 de fm_theme)

    @classmethod
    def tearDownClass(cls):
        cls.win.close()

    def _fields(self):
        from settings_sections import _CompactAppOrCustomColorField
        fields = self.win.findChildren(_CompactAppOrCustomColorField)
        self.assertGreater(len(fields), 20)
        return fields

    def test_live_palette_edit_reaches_every_color_menu(self):
        widget = next(w for store in self.win.stores.values() for spec, w in store.get("specs", ())
                      if getattr(spec, "params", {}).get("real_key") == "void")
        widget.setValue("#ff0000")
        widget.changed.emit()                                         # comme un choix de l'utilisateur
        app.processEvents()
        self.win._flush_live()
        stale = [f for f in self._fields() if (f._colors.get("void") or "").lower() != "#ff0000"]
        self.assertEqual(stale, [])
        self.win._apply_look(self.win._original_settings)            # Annuler : palette d'origine
        self.assertTrue(all(f._colors.get("void") == self.win._original_settings["colors"]["void"]
                            for f in self._fields()))

    def test_external_values_palette_reaches_every_color_menu(self):
        colors = dict(self.win.settings["colors"], window="#00ff00")
        self.win.external_values({"colors": colors})
        self.assertTrue(all(f._colors.get("window") == "#00ff00" for f in self._fields()))


class QuickStyleWindowTest(WindowTestCase):
    """« Changement de style a la volee » : fenetre reutilisable, valeurs en direct, mise en forme du
    tableau et plages des curseurs enregistrees seules et retrouvees."""

    def setUp(self):
        import settings_quick_style as qs
        self.qs = qs
        self.disk = copy.deepcopy(_DEFAULTS)
        patches = [mock.patch.object(qs, "load_settings", lambda: copy.deepcopy(self.disk)),
                   mock.patch.object(qs, "save_settings", lambda s: self.disk.update(copy.deepcopy(s))),
                   mock.patch.object(qs, "save_live_state", lambda k, v: self.disk.update({k: copy.deepcopy(v)})),
                   mock.patch.dict(qs._POSITIONS, clear=True)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def _window(self):
        win = self.qs.QuickStyleWindow("Essai", self.qs.font_padding_specs("demo"), {"demo_font_size": 12},
                                       title="Essai")
        win.show()
        for _ in range(3):
            app.processEvents()
        self.addCleanup(lambda: shiboken6.isValid(win) and win.close())    # deja fermee (detruite) : rien
        return win

    def test_opens_centered_on_the_current_screen(self):
        win = self._window()
        area = (QApplication.screenAt(win.frameGeometry().center()) or QApplication.primaryScreen()).availableGeometry()
        center = win.frameGeometry().center()
        self.assertLessEqual(abs(center.x() - area.center().x()), 2)
        self.assertLessEqual(abs(center.y() - area.center().y()), 2)

    def test_reopens_where_it_was_closed(self):
        win = self._window()
        area = (QApplication.screenAt(win.frameGeometry().center()) or QApplication.primaryScreen()).availableGeometry()
        target = area.topLeft() + QPoint(37, 53)
        win.move(target)
        win.close()
        self.assertEqual(self.disk["quick_style_positions"]["Essai"], [target.x(), target.y()])
        self.qs._POSITIONS.clear()                             # relu des reglages, comme a un relancement
        again = self._window()
        self.assertEqual(again.pos(), target)
        for _ in range(5):
            app.processEvents()
        self.assertEqual(again.pos(), target)                  # pas recentree pendant que sa taille se pose

    def test_live_values_and_saved_layout(self):
        win = self._window()
        received = []
        win.styleChanged.connect(received.append)
        fields = dict((spec.key, widget) for spec, widget in win._fields)
        fields["demo_font_family"]._v2_parts["size"].setValue(15)
        self.assertEqual(received[-1]["demo_font_size"], 15)
        self.assertIn("demo_padding", received[-1])
        head = win.table._flat_head
        head._set_width(0, head._widths[0] + 41)
        win._dims_timer.timeout.emit()
        key = "Changement de style à la volée/Essai#0"
        self.assertEqual(self.disk["table_dims"][key]["cols"][0], head._widths[0])
        win._on_range("demo_font_family", 2, 99)          # cle de plage = celle de la ligne (un seul curseur)
        self.assertEqual(self.disk["slider_ranges"]["demo_font_family"], [2, 99])
        again = self._window()
        self.assertEqual(again.table._flat_head._widths[0], head._widths[0])
        size = dict((spec.key, widget) for spec, widget in again._fields)["demo_font_family"]._v2_parts["size"]
        self.assertEqual(size._max, 99)

    def _gaps(self, win):
        from PySide6.QtCore import QPoint
        top_left = win.table.mapTo(win, QPoint(0, 0))
        bar = max(win.titlebar.sizeHint().height(), win.titlebar.minimumHeight())
        return (top_left.x(), top_left.y() - bar, win.width() - top_left.x() - win.table.width(),
                win.height() - top_left.y() - win.table.height())

    def test_table_is_bound_to_the_window_with_equal_margins(self):
        win = self._window()
        self.assertEqual(win.minimumHeight(), win.maximumHeight())          # hauteur = contenu
        margins = self._gaps(win)
        self.assertEqual(len(set(margins)), 1, margins)                    # meme marge sur les 4 cotes
        head, last = win._last_column()
        before = head._widths[last]
        win.resize(win.width() + 70, win.height())                         # bord de la fenetre tire
        app.processEvents()
        self.assertEqual(head._widths[last], before + 70)                  # la derniere colonne suit
        self.assertEqual(self._gaps(win), margins)
        width = win.width()
        head._set_width(0, head._widths[0] + 30)                           # colonne elargie
        app.processEvents()
        self.assertEqual(win.width(), width + 30)                          # la fenetre suit
        self.assertEqual(self._gaps(win), margins)
        win.resize(40, win.height())                                       # jamais sous le minimum
        app.processEvents()
        self.assertEqual(head._widths[last], head._FREE_MIN)
        self.assertEqual(self._gaps(win), margins)


class SliderDragAnchorTest(WindowTestCase):
    """Un curseur que le reglage en direct deplace sous la souris (ex. padding gauche d'un titre qui
    decale le tableau) garde sa valeur tant que la souris ne bouge pas : plus d'a-coups en arriere."""

    def _mouse(self, kind, local, global_x, buttons=Qt.LeftButton):
        return QMouseEvent(kind, QPointF(local, 5), QPointF(global_x, 5), Qt.LeftButton, buttons, Qt.NoModifier)

    def test_value_follows_screen_motion_not_widget_position(self):
        from PySide6.QtWidgets import QWidget
        from settings_widgets import _MiniSlider
        parent = QWidget()
        slider = _MiniSlider(0, 100, 0, width=200, parent=parent)
        slider.move(10, 0)
        QApplication.sendEvent(slider, self._mouse(QEvent.MouseButtonPress, 100, 110))
        self.assertEqual(slider.value(), 50)
        slider.move(40, 0)                       # le tableau se decale de 30 px sous la souris
        QApplication.sendEvent(slider, self._mouse(QEvent.MouseMove, 70, 110))     # souris immobile
        self.assertEqual(slider.value(), 50)
        QApplication.sendEvent(slider, self._mouse(QEvent.MouseMove, 90, 130))     # +20 px a l'ecran
        self.assertEqual(slider.value(), 60)
        QApplication.sendEvent(slider, self._mouse(QEvent.MouseButtonRelease, 90, 130, Qt.NoButton))


if __name__ == "__main__":
    unittest.main()
