"""Clic droit > « Positionner au bas de la colonne » : les lignes marquees passent apres les autres,
empilees contre le bas de la colonne (vide ROLE_BOTTOM_GAP au-dessus de la premiere, recalcule au
redimensionnement), le vide n'est pas cliquable, et le choix est enregistre (`item_bottom`)."""
import os as _os, sys as _sys  # jamais les vrais reglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

import browser_core
from column import Column


class BottomPinTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)
        for name in ("Alpha", "Bravo", "Charlie", "Delta"):
            (self.root / name).mkdir()

    def _column(self, height=500):
        column = Column(self.root, "Type")
        column.resize(240, height)
        column.show()
        column.refresh()
        self.addCleanup(column.deleteLater)
        app.processEvents()
        return column

    def _names(self, column):
        return [column.list.item(i).text() for i in range(column.list.count())]

    def test_pinned_rows_stack_at_the_bottom(self):
        column = self._column()
        column.set_item_bottom(column.list.item(0), True)        # Alpha
        column.set_item_bottom(column.list.item(0), True)        # Bravo (Alpha est passee en bas)
        app.processEvents()
        self.assertEqual(self._names(column), ["Charlie", "Delta", "Alpha", "Bravo"])
        lst = column.list
        last = lst.visualItemRect(lst.item(3))
        self.assertEqual(last.bottom() + 1, lst.viewport().height())          # colle au bas
        gap = int(lst.item(2).data(browser_core.ROLE_BOTTOM_GAP) or 0)
        self.assertGreater(gap, 0)
        # Le vide n'est pas une ligne : ni clic ni menu.
        self.assertIsNone(lst.itemAt(QPoint(20, lst.visualItemRect(lst.item(2)).top() + 2)))
        self.assertIs(lst.itemAt(QPoint(20, last.center().y())), lst.item(3))
        saved = json.loads((self.root / ".pipeline_layout.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["item_bottom"], ["Alpha", "Bravo"])

        # Plus haute : toujours collees en bas.
        column.resize(240, 700)
        app.processEvents()
        self.assertEqual(lst.visualItemRect(lst.item(3)).bottom() + 1, lst.viewport().height())

        again = self._column()
        self.assertEqual(self._names(again), ["Charlie", "Delta", "Alpha", "Bravo"])
        again.set_item_bottom(again.list.item(2), False)          # Alpha revient a sa place
        app.processEvents()
        self.assertEqual(self._names(again), ["Alpha", "Charlie", "Delta", "Bravo"])

    def test_no_gap_when_the_column_is_full(self):
        column = self._column(height=60)
        column.set_item_bottom(column.list.item(0), True)
        app.processEvents()
        self.assertEqual(self._names(column)[-1], "Alpha")
        self.assertEqual(int(column.list.item(3).data(browser_core.ROLE_BOTTOM_GAP) or 0), 0)


if __name__ == "__main__":
    unittest.main()
