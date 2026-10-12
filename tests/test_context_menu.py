"""Menus contextuels (settings_menu) : habillage de Reglages > Menu contextuel, lignes alignees en colonnes
(texte des lignes a controles au x du texte des lignes simples, controles au meme x et a la meme largeur,
avec ou sans icones / cases a cocher), disposition retenue par menu (ordre, separateurs, libelles, icones),
deplacement a la souris et edition au clic droit."""
import os as _os, sys as _sys  # jamais les vrais reglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

app = QApplication.instance() or QApplication([])

import settings_menu as sm
from settings_widgets import _SelectField, _SliderField


class _Base(unittest.TestCase):
    def setUp(self):
        self.values = {}
        self.layouts = {}
        sm.install(values=lambda: self.values, load_layouts=lambda: self.layouts,
                   save_layouts=self._save)
        self.addCleanup(sm.install)
        self.host = QWidget()
        self.addCleanup(self.host.deleteLater)

    def _save(self, layouts):
        self.layouts = layouts

    def menu(self, checkable=False, icon=False):
        m = sm.Menu(self.host)
        m.addAction("Ouvrir")
        a = m.addAction("Afficher l'apercu")
        a.setCheckable(checkable)
        if icon:
            pix = QPixmap(32, 32)
            pix.fill(QColor("#ff00ff"))
            m.addAction(QIcon(pix), "Avec icone")
        sm.menu_row(m, "Taille de l'icone", _SliderField(0, 64, 22, slider_width=120, box_width=60))
        sm.menu_row(m, "Ajouter une espace au-dessus", _SliderField(0, 200, 0, slider_width=140, box_width=60))
        sm.menu_row(m, "Style du toggle", _SelectField(["A", "B"], "A", width=160))
        m.addSeparator()
        m.addAction("Copier le chemin")
        return m

    def show(self, m):
        m.popup(QPoint(200, 200))
        for _ in range(3):
            app.processEvents()
        self.addCleanup(m.close)
        return m

    def names(self, m):
        out = []
        for kind, value, _a in sm._entries(m):
            out.append({"item": value, "sep": "|", "label": f"#{value}"}.get(kind, value) if kind != "item" else value)
        return out


def _text_x(menu, action) -> int:
    """Premier pixel de texte (clair) de la ligne d'une action simple."""
    img = menu.grab().toImage()
    r = menu.actionGeometry(action)
    for x in range(r.left(), r.right()):
        for y in range(r.top(), r.bottom()):
            c = QColor(img.pixel(x, y))
            if c.red() > 150 and c.green() > 150 and c.blue() > 150:
                return x
    return -1


class AlignTest(_Base):
    def _check(self, **kw):
        m = self.show(self.menu(**kw))
        plain = m.actions()[0]
        rows = [a.defaultWidget() for a in m.actions() if isinstance(a.defaultWidget() if hasattr(a, "defaultWidget") else None, sm._MenuRow)]
        self.assertEqual(len(rows), 3)
        text_x = _text_x(m, plain)
        label_x = {r.label.mapTo(m, QPoint(0, 0)).x() for r in rows}
        # Le texte d'une ligne a controle commence la ou commence celui des lignes simples (1 px de jeu :
        # approche de la premiere lettre).
        self.assertEqual(len(label_x), 1)
        self.assertLessEqual(abs(label_x.pop() - text_x), 1, kw)
        controls = {(r.control.mapTo(m, QPoint(0, 0)).x(), r.control.width()) for r in rows}
        self.assertEqual(len(controls), 1, controls)          # meme x, meme largeur

    def test_plain_menu(self):
        self._check()

    def test_with_checkable_item(self):
        self._check(checkable=True)

    def test_with_icon(self):
        self._check(icon=True)

    def test_with_hover_margin_and_border(self):
        self.values = {"ctx_menu_hover_margin": {"top": 2, "right": 6, "bottom": 2, "left": 6},
                       "ctx_menu_hover_border_enabled": {"top": True, "right": True, "bottom": True, "left": True},
                       "ctx_menu_hover_border_thickness": 2}
        self._check(checkable=True)

    def test_text_does_not_move_on_hover(self):
        self.values = {"ctx_menu_hover_border_enabled": {"top": True, "right": True, "bottom": True, "left": True},
                       "ctx_menu_hover_border_thickness": 3, "ctx_menu_hover_color": "#000000"}
        m = self.show(self.menu())
        plain = m.actions()[0]
        before = _text_x(m, plain)
        m.setActiveAction(plain)
        app.processEvents()
        self.assertEqual(_text_x(m, plain), before)

    def test_hover_settings_reach_the_style(self):
        self.values = {"ctx_menu_hover_radius": {"top_left": 4, "top_right": 4, "bottom_right": 4, "bottom_left": 4},
                       "ctx_menu_hover_margin": {"top": 1, "right": 5, "bottom": 1, "left": 5},
                       "ctx_menu_hover_border_enabled": {"top": False, "right": False, "bottom": False, "left": True},
                       "ctx_menu_hover_border": {"left": "#ff0000"}, "ctx_menu_hover_border_thickness": 2}
        qss = self.show(self.menu()).styleSheet()
        self.assertIn("margin: 1px 5px 1px 5px", qss)
        self.assertIn("border-top-left-radius: 4px", qss)
        self.assertIn("border-left: 2px solid transparent", qss)
        self.assertIn("border-left-color: #ff0000", qss)

    def test_row_icon_reserves_the_icon_column_for_every_line(self):
        m = self.menu()
        icon = Path(tempfile.mkdtemp()) / "i.png"
        pix = QPixmap(16, 16)
        pix.fill(QColor("#ff00ff"))
        pix.save(str(icon))
        self.layouts = {"QWidget": {"icons": {"row:Taille de l'icone": str(icon)}}}
        m = self.show(m)
        row = next(a.defaultWidget() for a in m.actions() if sm.item_id(a) == "row:Taille de l'icone")
        self.assertLessEqual(abs(row.label.mapTo(m, QPoint(0, 0)).x() - _text_x(m, m.actions()[0])), 1)
        self.assertGreater(row.icon.width(), 0)


class LookTest(_Base):
    def test_settings_drive_the_style(self):
        self.values = {"ctx_menu_bg": "#112233", "ctx_menu_hover_color": "#445566", "ctx_menu_sep_thickness": 3,
                       "ctx_menu_item_padding": {"top": 2, "right": 30, "bottom": 2, "left": 30},
                       "ctx_menu_icon_size": 24}
        m = self.show(self.menu())
        qss = m.styleSheet()
        self.assertIn("#112233", qss)
        self.assertIn("#445566", qss)
        self.assertIn("height: 3px", qss)
        self.assertIn("padding: 2px 30px 2px 30px", qss)
        self.assertEqual(m._ctx_style.icon_size, 24)

    def test_rounded_menu_is_translucent(self):
        self.values = {"ctx_menu_border_radius": 8}
        m = self.show(self.menu())
        self.assertTrue(m.testAttribute(Qt.WA_TranslucentBackground))


class LayoutTest(_Base):
    def test_stored_order_with_separator_and_label(self):
        self.layouts = {"QWidget": {"order": [
            {"label": "Fichier"}, {"item": "Copier le chemin"}, {"sep": True}, {"item": "Ouvrir"}]}}
        m = self.show(self.menu())
        kinds = [(k, v) for k, v, _a in sm._entries(m)]
        self.assertEqual(kinds[:4], [("label", "Fichier"), ("item", "Copier le chemin"), ("sep", None),
                                     ("item", "Ouvrir")])
        # Les elements absents de la disposition restent a la suite de leur predecesseur d'origine.
        self.assertEqual(kinds[4], ("item", "Afficher l'apercu"))

    def test_label_disappears_when_its_items_are_absent(self):
        self.layouts = {"QWidget": {"order": [{"item": "Ouvrir"}, {"label": "Rendu"}, {"item": "Rendu low"}]}}
        m = self.show(self.menu())
        self.assertNotIn("label", [k for k, _v, _a in sm._entries(m)])

    def test_merge_keeps_items_of_other_variants(self):
        old = [{"item": "A"}, {"item": "B"}, {"item": "C"}]
        merged = sm._merge([{"item": "C"}, {"item": "A"}], old)
        self.assertEqual([e["item"] for e in merged], ["C", "A", "B"])

    def test_icon_is_applied_and_removed(self):
        icon = Path(tempfile.mkdtemp()) / "i.png"
        pix = QPixmap(16, 16)
        pix.fill(QColor("#ff00ff"))
        pix.save(str(icon))
        self.layouts = {"QWidget": {"icons": {"Ouvrir": str(icon)}}}
        m = self.show(self.menu())
        self.assertFalse(m.actions()[0].icon().isNull())
        m.close()
        self.layouts = {}
        m.popup(QPoint(200, 200))
        app.processEvents()
        self.assertTrue(m.actions()[0].icon().isNull())


class DragTest(_Base):
    def test_dragging_an_item_moves_it_and_is_kept(self):
        m = self.show(self.menu())
        first = m.actions()[0]
        start = m.actionGeometry(first).center()
        last = m.actionGeometry(m.actions()[-1])
        # Sans Ctrl : rien ne bouge (deplacer = Ctrl + glisser, partout dans l'appli).
        QTest.mousePress(m, Qt.LeftButton, Qt.NoModifier, start)
        for y in range(start.y(), last.bottom() + 4, 6):
            QTest.mouseMove(m, QPoint(start.x(), y))
        self.assertIsNone(m._ctx_editor._overlay)
        m._ctx_editor._press = None            # (pas de relachement : il declencherait la ligne)
        ctrl = mock.patch.object(QApplication, "keyboardModifiers", return_value=Qt.ControlModifier)
        ctrl.start()
        self.addCleanup(ctrl.stop)
        QTest.mousePress(m, Qt.LeftButton, Qt.ControlModifier, start)
        for y in range(start.y(), last.bottom() + 4, 6):
            QTest.mouseMove(m, QPoint(start.x(), y))
            app.processEvents()
        self.assertIsNotNone(m._ctx_editor._overlay)
        QTest.mouseRelease(m, Qt.LeftButton, Qt.NoModifier, QPoint(start.x(), last.bottom() + 3))
        app.processEvents()
        self.assertIsNone(m._ctx_editor._overlay)
        ids = [v for k, v, _a in sm._entries(m) if k == "item"]
        self.assertEqual(ids[-1], "Ouvrir")
        self.assertEqual(self.layouts["QWidget"]["order"][-1], {"item": "Ouvrir"})

    def test_a_click_still_triggers(self):
        m = self.show(self.menu())
        hits = []
        m.actions()[0].triggered.connect(lambda: hits.append(1))
        pos = m.actionGeometry(m.actions()[0]).center()
        QTest.mouseClick(m, Qt.LeftButton, Qt.NoModifier, pos)
        app.processEvents()
        self.assertEqual(hits, [1])

    def test_no_drag_when_customisation_is_off(self):
        self.values = {"ctx_menu_editable": False}
        m = self.show(self.menu())
        self.assertIsNone(getattr(m, "_ctx_editor", None))


class EditMenuTest(_Base):
    def _choose(self, m, action, text):
        class Fake(sm.Menu):
            def exec(self, *_a):
                for act in self.actions():
                    if act.text() == text:
                        return act
                    sub = act.menu()
                    if sub is not None:
                        for inner in sub.actions():
                            if inner.text() == text:
                                return inner
                return None

        with mock.patch.object(sm, "Menu", Fake):
            m._ctx_editor._edit_menu(action, QPoint(0, 0))
        app.processEvents()

    def test_separator_add_and_remove(self):
        m = self.show(self.menu())
        self._choose(m, m.actions()[0], "Ajouter un séparateur en dessous")
        kinds = [k for k, _v, _a in sm._entries(m)]
        self.assertEqual(kinds[:3], ["item", "sep", "item"])
        sep = next(a for k, _v, a in sm._entries(m) if k == "sep")
        self._choose(m, sep, "Supprimer le séparateur")
        self.assertEqual([k for k, _v, _a in sm._entries(m)][:2], ["item", "item"])

    def test_label_is_added_and_renamed_in_place(self):
        m = self.show(self.menu())
        self._choose(m, m.actions()[1], "Ajouter un libellé au-dessus…")
        entries = sm._entries(m)
        self.assertEqual(entries[1][0], "label")
        section = entries[1][2].defaultWidget()
        self.assertIsNotNone(section.edit)
        section.edit.setText("Affichage")
        QTest.keyClick(section.edit, Qt.Key_Return)
        app.processEvents()
        labels = [v for k, v, _a in sm._entries(m) if k == "label"]
        self.assertEqual(labels, ["Affichage"])
        self.assertIn({"label": "Affichage"}, self.layouts["QWidget"]["order"])
        # Libelle en capitales (reglage « Capitales », allume par defaut).
        section = next(a for k, _v, a in sm._entries(m) if k == "label").defaultWidget()
        self.assertEqual(section.label.text(), "AFFICHAGE")

    def test_reset_forgets_the_menu(self):
        m = self.show(self.menu())
        self._choose(m, m.actions()[0], "Ajouter un séparateur en dessous")
        self.assertIn("QWidget", self.layouts)
        self._choose(m, m.actions()[0], "Réinitialiser ce menu")
        self.assertNotIn("QWidget", self.layouts)


if __name__ == "__main__":
    unittest.main()
