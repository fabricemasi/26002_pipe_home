"""« Ajouter une espace en dessous » (pendant de « au-dessus ») : moteur commun (espaceur apres
l'element), lignes des colonnes (hauteur, dessin, enregistrement `item_spaces_below`), fenetre de
reglages v2 (`element_spaces_below`, les deux curseurs dans le menu)."""
import os as _os, sys as _sys  # jamais les vrais reglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import copy
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
from PySide6.QtWidgets import QApplication, QLabel, QMenu, QVBoxLayout, QWidget, QWidgetAction

app = QApplication.instance() or QApplication([])

import browser_core
import settings_window_v2 as v2
from column import Column
from settings_store import DEFAULT_SETTINGS as _DEFAULTS
from settings_widgets import SPACE_BELOW_TEXT, _SliderField, _TableFrame, set_space_below

v2.AUTOSAVE = False


class EngineTest(unittest.TestCase):
    def test_space_below_pushes_the_next_widget(self):
        host = QWidget()
        self.addCleanup(host.deleteLater)
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        first, second = QLabel("a"), QLabel("b")
        layout.addWidget(first)
        layout.addWidget(second)
        host.show()
        app.processEvents()
        y0, h0 = second.y(), layout.sizeHint().height()
        set_space_below(first, 25)
        layout.activate()
        self.assertEqual(second.y(), y0 + 25)
        self.assertEqual(first.y(), 0)
        self.assertEqual(layout.sizeHint().height(), h0 + 25)
        set_space_below(first, 0)
        self.assertEqual(layout.sizeHint().height(), h0)


class ColumnRowTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)
        for name in ("Alpha", "Bravo", "Charlie"):
            (self.root / name).mkdir()

    def _column(self):
        column = Column(self.root, "Type")
        column.resize(240, 400)
        column.show()
        column.refresh()
        self.addCleanup(column.deleteLater)
        app.processEvents()
        return column

    def test_space_below_a_row_is_shown_and_saved(self):
        column = self._column()
        item, after = column.list.item(1), column.list.item(2)
        top_after = column.list.visualItemRect(after).top()
        height = column.list.visualItemRect(item).height()
        column.set_item_space(item, 30, below=True)
        app.processEvents()
        self.assertEqual(column.list.visualItemRect(item).height(), height + 30)
        self.assertEqual(column.list.visualItemRect(after).top(), top_after + 30)
        column._save_item_spaces()
        saved = json.loads((self.root / ".pipeline_layout.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["item_spaces_below"]["Bravo"], 30)
        self.assertNotIn("Bravo", saved.get("item_spaces", {}))
        again = self._column()
        self.assertEqual(again.list.item(1).data(browser_core.ROLE_SPACE_BELOW), 30)
        self.assertEqual(int(again.list.item(1).data(browser_core.ROLE_SPACE_ABOVE) or 0), 0)


class SettingsWindowTest(unittest.TestCase):
    def setUp(self):
        self._real = v2.load_settings
        v2.load_settings = lambda: copy.deepcopy(_DEFAULTS)
        self.addCleanup(setattr, v2, "load_settings", self._real)
        self.win = v2.SettingsWindowV2()
        self.win.resize(1300, 900)
        self.win.show()
        page = self.win.stack.currentWidget()
        for node in page.findChildren(v2._LazyNode):
            if node.node.title == "TITRES":
                node.set_collapsed(False)
        for node in page.findChildren(v2._LazyNode):
            if node.node.title == "Polices":
                node.set_collapsed(False)
        for _ in range(5):
            app.processEvents()
        self.addCleanup(self.win.close)

    def test_menu_offers_both_spaces_and_below_is_saved(self):
        frame = next(f for f in self.win.findChildren(_TableFrame) if f.dimsKey() == "TITRES/Polices#0")
        cell = frame._extra_dims.cells["r0c0"]
        menu = QMenu()
        self.win.add_space_action(cell, menu)
        rows = [a.defaultWidget() for a in menu.actions() if isinstance(a, QWidgetAction)]
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1].findChild(QLabel).text(), SPACE_BELOW_TEXT)
        rows[1].findChild(_SliderField).setValue(20)
        for _ in range(3):
            app.processEvents()
        self.assertEqual(frame._space_below_px, 20)
        key = self.win._space_key(frame)
        self.assertEqual(self.win.settings["element_spaces_below"][key], 20)
        self.assertNotIn(key, self.win.settings.get("element_spaces") or {})


if __name__ == "__main__":
    unittest.main()
