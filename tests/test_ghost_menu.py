"""Options FANTOMES des menus contextuels : presentes seulement au clic droit fait avec Ctrl+Maj, texte a la couleur
« Couleur des options fantomes » (Menu contextuel > Lignes). Premiere : « Modifier le texte… » d'une cellule de
tableau, texte retenu dans les dimensions du tableau."""
import os as _os, sys as _sys  # jamais les vrais reglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import os
import shiboken6
import sys
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication, QLabel, QLineEdit, QStyleOptionMenuItem

app = QApplication.instance() or QApplication([])

from fm_theme import cells, menu as fm_menu
from settings_store import DEFAULT_SETTINGS
import settings_window_v2 as v2


def ghosts(on: bool):
    return mock.patch.object(fm_menu, "ghost_wanted", return_value=on)


class GhostMenuTest(unittest.TestCase):
    def test_ghost_action_only_with_ctrl_shift_and_drawn_as_ghost(self):
        menu = fm_menu.Menu()
        self.addCleanup(shiboken6.delete, menu)
        with ghosts(False):
            self.assertIsNone(fm_menu.ghost_action(menu, "Cachée"))
        with ghosts(True):
            action = fm_menu.ghost_action(menu, "Fantôme")
        normal = menu.addAction("Normale")
        option = QStyleOptionMenuItem()
        menu.initStyleOption(option, action)
        self.assertEqual(option.menuItemType, QStyleOptionMenuItem.DefaultItem)   # QMenu::item:default
        menu.initStyleOption(option, normal)
        self.assertNotEqual(option.menuItemType, QStyleOptionMenuItem.DefaultItem)
        look = fm_menu.menu_look()
        self.assertIn(f"QMenu::item:default {{ color: {look['ghost']}; }}", fm_menu._qss(look))
        self.assertIn("ctx_menu_ghost_color", DEFAULT_SETTINGS)
        self.assertIn("ctx_menu_ghost_color", {s.key for s in v2.CATALOG["Menu contextuel : Lignes"]})


class CurrentItemTest(unittest.TestCase):
    """Element EN COURS (`mark_current`) : fond « Couleur de l'element en cours », distinct du survol, sur toute la
    ligne (ni marge ni arrondi), texte au meme endroit que les autres lignes."""

    def test_current_item_band(self):
        from PySide6.QtCore import QPoint
        values = dict(DEFAULT_SETTINGS, ctx_menu_hover_margin={"top": 0, "right": 4, "bottom": 0, "left": 4},
                      ctx_menu_current_color="#ff0000ff")
        with mock.patch.dict(fm_menu._STATE, {"values": lambda: values}):
            menu = fm_menu.Menu()
            self.addCleanup(shiboken6.delete, menu)
            normal = menu.addAction("Normale")
            current = menu.addAction("En cours")
            fm_menu.mark_current(current)
            menu.popup(QPoint(50, 50))
            for _ in range(5):
                app.processEvents()
            image = menu.grab().toImage()
            menu.close()
        rect = menu.actionGeometry(current)
        y = rect.center().y()
        self.assertEqual(image.pixelColor(rect.left(), y).name(), "#0000ff")        # des le bord : pas de marge
        self.assertEqual(image.pixelColor(rect.right(), y).name(), "#0000ff")

        def text_x(action):
            r = menu.actionGeometry(action)
            bg = image.pixelColor(r.right() - 1, r.center().y())
            return next(x for x in range(r.left(), r.right())
                        if any(image.pixelColor(x, yy) != bg for yy in range(r.top() + 3, r.bottom() - 3)))
        self.assertEqual(text_x(current), text_x(normal))                           # le texte ne bouge pas


class CellTextTest(unittest.TestCase):
    def test_modify_cell_text_is_a_ghost_option_kept_in_dims(self):
        label = QLabel("Origine")
        frame, _head, _cells = cells.build_cells_table([("Paramètre", 150), ("Valeur", 100)],
                                                       [[(label, "left", "center"), (QLabel("x"), "left", "center")]])
        self.addCleanup(shiboken6.delete, frame)
        cell = frame._extra_dims.cells["r0c0"]
        with ghosts(False):
            menu = fm_menu.Menu()
            cell.populate_menu(menu)
            self.assertNotIn("Modifier le texte…", [a.text() for a in menu.actions()])
        with ghosts(True):
            menu = fm_menu.Menu()
            cell.populate_menu(menu)
        action = next(a for a in menu.actions() if a.text() == "Modifier le texte…")
        self.assertTrue(action.property("ctxGhost"))
        action.trigger()
        edit = cell.findChild(QLineEdit, "RenameInline")
        edit.setText("Nouveau")
        edit.editingFinished.emit()
        self.assertEqual(label.text(), "Nouveau")
        dims = frame.collectDims()
        self.assertEqual(dims["cell_texts"], {"r0c0:0": "Nouveau"})
        frame.applyDims({})
        self.assertEqual(label.text(), "Origine")
        self.assertNotIn("cell_texts", frame.collectDims())
        frame.applyDims(dims)
        self.assertEqual(label.text(), "Nouveau")


if __name__ == "__main__":
    unittest.main()
