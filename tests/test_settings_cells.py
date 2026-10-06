"""Tests des tableaux a cellules de la fenetre de reglages v2 (settings_cells.py) :
entete partout, toggles type 2 sans texte, justification par cellule (clic droit),
bordures de colonnes saisissables sur les cellules, filets verticaux qui suivent,
plage des curseurs, enregistrement en temps reel."""
import copy
import os
import sys
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

import settings_cells as cells
import settings_window_v2 as v2
from settings_widgets import _SliderField, _Toggle, _TableFrame, _TableRow

v2.AUTOSAVE = False
# Isolation : jamais les vrais reglages de l'utilisateur (dimensions, justifications enregistrees...).
from settings_store import DEFAULT_SETTINGS as _DEFAULTS
_real_load_settings = v2.load_settings


def setUpModule():
    v2.load_settings = lambda: copy.deepcopy(_DEFAULTS)


def tearDownModule():
    v2.load_settings = _real_load_settings


def build():
    win = v2.SettingsWindowV2()
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


class TablesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.win = build()
        cls.frames = cls.win.findChildren(_TableFrame)

    def test_every_table_has_a_header(self):
        self.assertTrue(self.frames)
        for frame in self.frames:
            self.assertIsNotNone(getattr(frame, "_flat_head", None), frame.dimsKey())

    def test_toggles_in_tables_are_type_2_without_text(self):
        toggles = [t for f in self.frames for t in f.findChildren(_Toggle)]
        self.assertGreater(len(toggles), 30)
        for toggle in toggles:
            self.assertEqual(toggle._style_override, "toggle2")
            self.assertFalse(toggle._show_label)

    def test_corners_rows_are_called_border_radius(self):
        labels = {sp.label for specs in v2.CATALOG.values() for sp in specs if sp.kind == "corners"}
        self.assertEqual(labels, {"Border radius"})

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
        frame = next(f for f in self.frames if f.dimsKey().startswith("TITRE/Polices"))
        titles = [c.text() for c in frame._flat_head._cells]
        self.assertEqual(titles, ["NIVEAU", "POLICE", "GRAS", "ITALIQUE", "HAUTEUR", "NIVEAU DE LISSAGE", "COULEUR"])
        self.assertEqual(len(frame.findChildren(_TableRow)), 5)


class CellsBehaviourTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.win = build()
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
        titles = [a.text() for a in menu.actions()]
        self.assertEqual(titles, ["Justification horizontale", "Justification verticale"])
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


class SplitCellTest(unittest.TestCase):
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


class RowHeightTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.win = build()
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


class AccordionTest(unittest.TestCase):
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


class GapsTableTest(unittest.TestCase):
    def test_gaps_table_matches_the_v1_one(self):
        win = build()
        frame = next(f for f in win.findChildren(_TableFrame) if f.dimsKey().startswith("TITRE/Espacements"))
        titles = [c.text() for c in frame._flat_head._cells]
        self.assertEqual(titles, ["NIVEAU", "TITRE REPLIÉ", "TITRE DÉPLIÉ", "AVEC LE NIVEAU SUIVANT"])
        self.assertEqual(len(frame.findChildren(_TableRow)), 5)


class ToggleStylesTest(unittest.TestCase):
    def setUp(self):
        self.win = build()
        self.addCleanup(self.win.close)

    def test_coche_has_a_skin_row_with_text_and_icon_choices(self):
        labels = [sp.label for sp in v2.CATALOG["toggle1 : Coche"]]
        for wanted in ("Habillage", "Texte", "Police du texte", "Icône", "Couleur de l'icône"):
            self.assertIn(wanted, labels)

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

    def test_menu_of_the_style_cell_offers_a_new_toggle(self):
        from PySide6.QtWidgets import QMenu
        picker = self.win.findChildren(v2._ToggleStylePicker)[0]
        cell = picker.parentWidget()
        while not isinstance(cell, cells._Cell):
            cell = cell.parentWidget()
        menu = QMenu()
        cell.populate_menu(menu)
        self.assertIn("Ajouter un nouveau toggle…", [a.text() for a in menu.actions()])

    def test_adding_a_toggle_creates_its_subsection_card_and_settings(self):
        picker = self.win.findChildren(v2._ToggleStylePicker)[0]
        cards_before = len(picker._cards)
        key = self.win.add_toggle_style("Mon toggle")
        self.assertEqual(key, "toggle3")
        self.assertEqual(self.win.settings["toggle_custom_styles"], [{"key": "toggle3", "name": "Mon toggle"}])
        self.assertIn("toggle3_outer_width", self.win.settings)
        self.assertEqual(len(picker._cards), cards_before + 1)
        node = next(n for n in self.win.findChildren(v2._LazyNode) if n.node.title == "Mon toggle")
        self.assertEqual([c.node.title for c in node._head.findChildren(v2._LazyNode)] or ["Cadre", "Coche"],
                         ["Cadre", "Coche"])
        v2.expand_all(self.win.stack.currentWidget())
        values = self.win.wired_values()
        self.assertIn("toggle3_coche_skin", values)
        self.assertEqual(self.win.add_toggle_style("Autre"), "toggle4")

    def test_custom_style_keys_survive_loading(self):
        from settings_store import _DYNAMIC_KEY
        self.assertTrue(_DYNAMIC_KEY.match("toggle3_outer_width"))
        self.assertTrue(_DYNAMIC_KEY.match("toggle12_coche_skin"))
        self.assertFalse(_DYNAMIC_KEY.match("toggle1_outer_width"))


class RoundTripTest(unittest.TestCase):
    """Ce que l'utilisateur dimensionne est retrouve a la reouverture."""

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
        frame.setTableWidth(900)
        split_frame = next(f for f in first.findChildren(_TableFrame) if f.findChildren(cells.SplitCell))
        split = split_frame.findChildren(cells.SplitCell)[0]
        split.setSubAlign(1, "right", "top")
        first._on_range("item_column_width", 50, 777)
        expected_col = frame._flat_head._widths[0]
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
        self.assertEqual(again.tableWidth(), 900)
        key = split_frame.dimsKey()
        same = next(f for f in second.findChildren(_TableFrame) if f.dimsKey() == key)
        self.assertEqual(same.findChildren(cells.SplitCell)[0].aligns()[1], ("right", "top"))
        field = next(w for sp, w in second.stores["General"]["specs"]
                     if not isinstance(sp, str) and sp.key == "item_column_width")
        self.assertEqual((field.slider._min, field.slider._max), (50, 777))
        second.close()


class SliderRangeTest(unittest.TestCase):
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


class AutosaveTest(unittest.TestCase):
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

    def test_window_size_is_saved(self):
        self.win._persist_now()
        self.assertTrue(self.geometry)
        self.assertEqual(self.geometry[-1][0], v2.GEOMETRY_KEY)

    def test_table_dims_are_saved_without_validating(self):
        frame = next(f for f in self.win.findChildren(_TableFrame) if f.dimsKey() == "Tableaux#0")
        head = frame._flat_head
        head._set_width(0, head._widths[0] + 33)
        frame._extra_dims.cells["r0c1"].setAlign("center", "top")
        self.win._persist_now()
        saved = self.written[-1]["table_dims"]["Tableaux#0"]
        self.assertEqual(saved["cols"][0], head._widths[0])
        self.assertEqual(saved["align"]["r0c1"], "center,top")

    def test_a_resize_arms_the_debounced_save(self):
        self.win._persist_timer.stop()
        self.win.resize(self.win.width() + 20, self.win.height())
        app.processEvents()
        self.assertTrue(self.win._persist_timer.isActive())


class SelectionEqualWidthAndSnapTest(unittest.TestCase):
    """Plusieurs colonnes / sous-cellules selectionnees = meme largeur en direct ; aimantation ;
    justification des titres."""

    @classmethod
    def setUpClass(cls):
        cls.win = build()
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

    def test_width_is_shown_in_the_title_while_resizing(self):
        frame = next(f for f in self.frames
                     if getattr(f, "_flat_head", None) is not None and sum(1 for w in f._flat_head._widths if w) >= 2)
        head = frame._flat_head
        i = next(i for i, w in enumerate(head._widths) if w)
        title = head._cells[i].text()
        head.beginDrag((i, 1), 500)
        head.dragTo(510)
        self.assertTrue(head._cells[i].text().endswith(" px"))
        head.endDrag()
        self.assertEqual(head._cells[i].text(), title)
        split = next(s for s in self.win.findChildren(cells.SplitCell) if len(s._cells) >= 3 and s.isVisible())
        split.snap_provider = None
        split._drag = (0, 100, split._cells[0].width())
        split._move(0, 120, split)
        self.assertTrue(split._cap_labels[0].text().endswith(" px"))
        split._end_drag()
        self.assertEqual(split._cap_labels[0].text(), split._cap_texts[0])
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


class PresetDoesNotClobberLiveStateTest(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
