"""Sélections des tableaux (fm_theme/table_selection.py) : une sous-cellule / une colonne choisie SANS Maj désélectionne
toutes les autres (autres lignes, entête, autres tableaux) ; Maj garde la sélection multiple ; un clic en dehors de la
sélection désélectionne tout ; le filtre d'application n'est posé que tant qu'une sélection existe."""
import os as _os, sys as _sys  # jamais les vrais reglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import shiboken6
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QWidget, QVBoxLayout

APP = QApplication.instance() or QApplication([])

from fm_theme import cells, table_selection  # noqa: E402


def split_row() -> QWidget:
    split = cells.SplitCell([("A", [QLabel("a")]), ("B", [QLabel("b")]), ("C", [QLabel("c")])])
    return cells.wrap_split(split)


class TableSelectionTest(unittest.TestCase):
    def setUp(self):
        self.host = QWidget()
        self.addCleanup(lambda: (table_selection.clear_all(), shiboken6.delete(self.host)))
        layout = QVBoxLayout(self.host)
        self.frame, self.head, _cells = cells.build_cells_table(
            [("Paramètre", 120), ("Valeur", 240)],
            [[QLabel("ligne 1"), split_row()], [QLabel("ligne 2"), split_row()]])
        layout.addWidget(self.frame)
        self.outside = QLabel("ailleurs")
        layout.addWidget(self.outside)
        self.host.resize(500, 300)
        self.host.show()
        APP.processEvents()
        self.split1, self.split2 = sorted(self.frame.findChildren(cells.SplitCell), key=lambda s: s.mapTo(self.frame, QPoint()).y())

    def test_one_selection_per_table_without_shift(self):
        self.split1._select_click(0, False)
        self.split1._select_click(1, True)                  # Maj : multiple dans la meme cellule
        self.assertEqual(self.split1.selected(), {0, 1})
        self.split2._select_click(2, True)                  # Maj : une autre ligne s'ajoute
        self.assertEqual((self.split1.selected(), self.split2.selected()), ({0, 1}, {2}))
        self.split2._select_click(0, False)                 # sans Maj : toutes les autres se deselectionnent
        self.assertEqual((self.split1.selected(), self.split2.selected()), (set(), {0}))
        self.head._select_click(1, False)                   # une colonne : la sous-cellule aussi
        self.assertEqual((self.split2.selected(), self.head._selected), (set(), {1}))
        self.split1._select_click(2, False)                 # et inversement
        self.assertEqual((self.head._selected, self.split1.selected()), (set(), {2}))

    def test_click_outside_clears_everything_and_the_filter_goes_away(self):
        self.head._select_click(0, False)
        self.split1._select_click(1, True)
        self.assertIsNotNone(table_selection._FILTER)
        caption = self.split2.mapToGlobal(QPoint(5, 5))      # legende d'une autre ligne : elle decide elle-meme
        self.assertTrue(self.split2.owns_press(caption))
        QTest.mouseClick(self.outside, Qt.LeftButton)
        self.assertEqual((self.head._selected, self.split1.selected()), (set(), set()))
        self.assertIsNone(table_selection._FILTER)          # jamais de filtre permanent

    def test_dragging_a_selected_border_keeps_the_selection(self):
        self.split1._select_click(0, False)
        self.split1._select_click(1, True)
        edge = self.split1._edges()[0]
        press = self.split1.mapToGlobal(QPoint(edge, self.split1.height() - 2))
        self.assertTrue(self.split1.owns_press(press))
        body = self.split1.mapToGlobal(QPoint(edge + 15, self.split1.height() - 2))
        self.assertFalse(self.split1.owns_press(body))       # dans le contenu : en dehors de la selection


if __name__ == "__main__":
    unittest.main()
