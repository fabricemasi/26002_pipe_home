"""Menus contextuels (demande de l'utilisateur) : objets des lignes a controle deplaces / redimensionnes comme
dans les tableaux (Ctrl+Maj, Ctrl+Maj+Alt, Ctrl+Z), style des toggles au clic droit ; retenus dans la
disposition du menu (`context_menu_layouts`)."""
import os as _os, sys as _sys  # jamais les vrais reglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import os
import sys
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

app = QApplication.instance() or QApplication([])

import settings_cells as sc
import settings_menu as sm
from settings_widgets import _SliderField, _Toggle, _TOGGLE_STYLES

CTRL_SHIFT = Qt.ControlModifier | Qt.ShiftModifier


def settle():
    for _ in range(4):
        app.processEvents()


class MenuObjectsTest(unittest.TestCase):
    def setUp(self):
        # Touche X : jamais lue sur le vrai clavier pendant les tests (l'utilisateur tape peut-etre).
        p = mock.patch.object(sc, "resize_key_held", return_value=False)
        p.start()
        self.addCleanup(p.stop)
        self.layouts = {}
        sm.install(load_layouts=lambda: self.layouts, save_layouts=lambda d: self.layouts.update(d) or
                   [self.layouts.pop(k) for k in list(self.layouts) if k not in d])
        self.addCleanup(sm.install)
        self.owner = QWidget()
        self.addCleanup(self.owner.deleteLater)

    def menu(self):
        menu = sm.Menu(self.owner, key="EssaiMenu")
        self.slider = _SliderField(0, 100, 10, slider_width=120, box_width=50)
        self.toggle = _Toggle(True, show_label=False)
        sm.menu_row(menu, "Taille", self.slider)
        sm.menu_row(menu, "Actif", self.toggle)
        menu.addAction("Une action")
        sm.prepare_menu(menu)
        menu.popup(QPoint(100, 100))
        settle()
        self.addCleanup(menu.close)
        return menu

    def drag(self, menu, widget, start, delta, mods=CTRL_SHIFT):
        origin = menu.mapFromGlobal(widget.mapToGlobal(start))
        QTest.mousePress(widget, Qt.LeftButton, mods, start)
        QTest.mouseMove(menu, origin + QPoint(delta.x() // 2, delta.y() // 2))
        QTest.mouseMove(menu, origin + delta)
        QTest.mouseRelease(menu, Qt.LeftButton, mods, origin + delta)
        settle()

    def test_move_is_kept_replayed_and_undone(self):
        nosnap = mock.patch.object(sc, "OBJECT_SNAP", 0)     # deplacement LIBRE teste ici (aimantation : a part)
        nosnap.start()
        self.addCleanup(nosnap.stop)
        menu = self.menu()
        rail = self.slider.slider
        row = rail
        while not isinstance(row, sm._MenuRow):
            row = row.parentWidget()
        before = rail.mapTo(row, QPoint(0, 0))
        self.drag(menu, rail, QPoint(10, 4), QPoint(-25, 0))
        self.assertEqual(rail.mapTo(row, QPoint(0, 0)) - before, QPoint(-25, 0))
        objects = self.layouts["EssaiMenu"]["objects"]
        self.assertEqual(len(objects), 1)
        key = next(iter(objects))
        self.assertTrue(key.startswith("row:Taille|"))
        # Menu rouvert (nouvelles lignes) : meme place.
        menu.close()
        again = self.menu()
        rail2 = self.slider.slider
        row2 = rail2
        while not isinstance(row2, sm._MenuRow):
            row2 = row2.parentWidget()
        self.assertIsNotNone(getattr(rail2, "_float_slot", None))
        self.assertEqual(rail2.mapTo(row2, QPoint(0, 0)), before + QPoint(-25, 0))
        # Ctrl+Z (dans ce menu) : retour a sa place, retenu.
        self.drag(again, rail2, QPoint(10, 4), QPoint(15, 0))
        self.assertTrue(sc.undo_object_change(again))
        self.assertEqual(self.layouts["EssaiMenu"]["objects"][key][0], -25)
        # La case d'icone et l'ecart d'une ligne ne sont pas des objets.
        self.assertNotIn(row2.icon, sc._objects_in(row2, []))
        self.assertNotIn(row2.gap, sc._objects_in(row2, []))

    def test_text_field_is_resized_by_its_width(self):
        # Zone de saisie (peu haute) : un clic au milieu, a 20 px du bord droit, tire le bord DROIT (signale :
        # le bord haut / bas etait choisi, bloque par la hauteur de la ligne).
        from unittest import mock
        from settings_cells import _TextField
        menu = sm.Menu(self.owner, key="MenuTexte")
        field = _TextField("bonjour", width=120)
        sm.menu_row(menu, "Nom", field)
        sm.prepare_menu(menu)
        menu.popup(QPoint(100, 100))
        settle()
        self.addCleanup(menu.close)
        width = field.width()
        with mock.patch.object(sc, "resize_key_held", return_value=True):
            self.drag(menu, field, QPoint(field.width() - 20, field.height() // 2), QPoint(-30, 0))
        self.assertEqual(field.width(), width - 30)
        self.assertEqual(sc._edge_at(QPoint(5, 12), 200, 25), "left")
        self.assertEqual(sc._edge_at(QPoint(100, 3), 200, 25), "top")
        self.assertEqual(sc._edge_at(QPoint(150, 12), 200, 25), "right")

    def test_slider_value_box_is_one_object(self):
        # La case de valeur d'un curseur (cadre + champ + unite) se redimensionne ENTIERE (signale : seul le
        # champ transparent a l'interieur changeait, rien de visible).
        menu = self.menu()
        box = self.slider.box
        self.assertIs(sc._object_at(self.slider.value_label)[1], box)
        width, field_width = box.width(), self.slider.value_label.width()
        with mock.patch.object(sc, "resize_key_held", return_value=True):     # bord gauche : elargie vers la gauche
            self.drag(menu, self.slider.value_label, QPoint(2, 8) - QPoint(self.slider.value_label.x() - 2, 0),
                      QPoint(-30, 0))
        self.assertEqual(box.width(), width + 30)
        self.assertGreater(self.slider.value_label.width(), field_width)      # le champ suit sa case
        near_right = self.slider.value_label.mapFrom(box, QPoint(box.width() - 3, box.height() // 2))
        with mock.patch.object(sc, "resize_key_held", return_value=True):     # bord droit : retrecie
            self.drag(menu, self.slider.value_label, near_right, QPoint(-10, 0))
        self.assertEqual(box.width(), width + 20)

    def test_toggle_style_is_kept_per_menu_row(self):
        if len(_TOGGLE_STYLES) < 2:
            self.skipTest("un seul style de toggle")
        style = list(_TOGGLE_STYLES)[1]
        menu = self.menu()
        self.toggle.setStyleKey(style)
        from settings_widgets import TOGGLE_STYLE_LISTENERS
        for listener in list(TOGGLE_STYLE_LISTENERS):
            listener(self.toggle, style)
        toggles = self.layouts["EssaiMenu"]["toggles"]
        self.assertEqual(list(toggles.values()), [style])
        self.assertTrue(next(iter(toggles)).startswith("row:Actif|"))
        menu.close()
        self.menu()
        self.assertEqual(self.toggle._style_override, style)


if __name__ == "__main__":
    unittest.main()
