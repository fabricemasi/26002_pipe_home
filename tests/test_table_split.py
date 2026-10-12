"""« Split au-dessus » (clic droit sur une cellule d'un tableau) : le tableau est coupe au-dessus de la ligne,
avec un toggle et l'espace entre les deux parties ; chaque partie a sa bordure complete et ses coins
arrondis, les colonnes restent communes ; retenu dans les dimensions du tableau (`row_splits`) et suit sa
ligne quand on deplace les lignes."""
import os as _os, sys as _sys  # jamais les vrais reglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QWidget, QVBoxLayout

app = QApplication.instance() or QApplication([])

import settings_cells as cells
import settings_menu as sm
from settings_widgets import _SliderField, _Toggle


class TableSplitTest(unittest.TestCase):
    def setUp(self):
        # Style commun des tableaux tel que la fenetre de reglages le pose (coins arrondis 6 px).
        import settings_layout
        saved = dict(settings_layout._FLAT_TABLE_STYLE)
        settings_layout._FLAT_TABLE_STYLE["radius"] = 6
        self.addCleanup(settings_layout._FLAT_TABLE_STYLE.update, saved)
        self.host = QWidget()
        lay = QVBoxLayout(self.host)
        rows = [[QLabel(f"ligne {r}"), QLabel(f"valeur {r}")] for r in range(4)]
        self.frame, self.head, self.cells = cells.build_cells_table([("Parametre", 140), ("Valeur", 140)], rows)
        lay.addWidget(self.frame)
        self.host.resize(400, 400)
        self.host.show()
        app.processEvents()
        self.state = self.frame._extra_dims
        self.addCleanup(self.host.deleteLater)

    def rows(self):
        return self.state.rows.rows

    def test_split_opens_a_gap_and_two_closed_parts(self):
        self.state.set_split(2, True, 20)
        app.processEvents()
        gaps = self.frame._split_gaps()
        self.assertEqual(len(gaps), 1)
        top, bottom = gaps[0]
        self.assertEqual(bottom - top, 22)                       # 20 visibles + 1 px de bordure par partie
        self.assertTrue(self.rows()[2]._split_above)
        self.assertTrue(self.rows()[1]._split_below)
        self.assertTrue(self.rows()[2]._first_row)                # pas de filet au-dessus de la 2e partie
        self.assertEqual(self.rows()[2].y() - (self.rows()[1].y() + self.rows()[1].height()), 22)

    def test_toggle_off_keeps_the_value(self):
        self.state.set_split(1, True, 30)
        self.state.set_split(1, False, 30)
        app.processEvents()
        self.assertEqual(self.frame._split_gaps(), [])
        self.assertEqual(self.state.split_of_row(1), (False, 30))
        self.assertFalse(self.rows()[1]._split_above)

    def test_saved_and_restored_with_the_dimensions(self):
        self.state.set_split(3, True, 12)
        dims = self.state.collect()
        self.assertEqual(dims["row_splits"], {"3": 12})
        self.state.set_split(3, False, 12)
        self.state.apply(dims)
        app.processEvents()
        self.assertEqual(self.state.split_of_row(3), (True, 12))
        self.assertEqual(len(self.frame._split_gaps()), 1)

    def test_split_follows_its_row_when_rows_move(self):
        self.state.set_split(2, True, 10)
        self.state.rows.set_order([2, 0, 1, 3])                    # la ligne coupee passe en tete
        app.processEvents()
        self.assertEqual(self.frame._split_gaps(), [])            # rien au-dessus de la 1re affichee
        self.state.rows.set_order([0, 1, 3, 2])
        app.processEvents()
        self.assertEqual(len(self.frame._split_gaps()), 1)
        self.assertTrue(self.rows()[3]._split_below)

    def test_menu_offers_split_with_toggle_and_space(self):
        menu = sm.Menu(self.host)
        cell = self.state.cells["r2c1"]
        cell.populate_menu(menu)
        row = next(a.defaultWidget() for a in menu.actions() if sm.item_id(a) == "row:" + cells.SPLIT_TEXT)
        toggle = row.control.findChild(_Toggle)
        field = row.control.findChild(_SliderField)
        self.assertEqual(field.value(), cells.SPLIT_DEFAULT_SPACE)
        toggle.setChecked(True)
        app.processEvents()
        self.assertEqual(self.state.split_of_row(2), (True, cells.SPLIT_DEFAULT_SPACE))
        field.setValue(40)
        app.processEvents()
        self.assertEqual(self.state.split_of_row(2), (True, 40))

    def test_menu_split_toggle_receives_a_mouse_click(self):
        menu = sm.Menu(self.host)
        self.state.cells["r2c1"].populate_menu(menu)
        row = next(a.defaultWidget() for a in menu.actions()
                   if sm.item_id(a) == "row:" + cells.SPLIT_TEXT)
        toggle = row.control.findChild(_Toggle)
        menu.popup(self.host.mapToGlobal(QPoint(20, 20)))
        app.processEvents()
        # Clic au point visible dans le menu (et non appel direct du widget),
        # comme lors d'une utilisation réelle.
        point = toggle.mapTo(menu, toggle.rect().center())
        QTest.mouseClick(toggle, Qt.LeftButton)
        app.processEvents()
        self.assertTrue(toggle.isChecked())
        self.assertEqual(self.state.split_of_row(2), (True, cells.SPLIT_DEFAULT_SPACE))
        menu.close()

    def test_no_split_on_the_first_displayed_row(self):
        menu = sm.Menu(self.host)
        self.state.cells["r0c0"].populate_menu(menu)
        self.assertNotIn("row:" + cells.SPLIT_TEXT, [sm.item_id(a) for a in menu.actions()])


if __name__ == "__main__":
    unittest.main()
