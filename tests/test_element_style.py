"""« Override settings » (settings_element_style) : partout ou il y a les lignes d'espace, clic droit =
style PROPRE a l'element (tableau, texte, toggle, titre, colonne), enregistre aussitot (seulement ce qui
differe du general), garde au restylage general, repris a la reconstruction, retire a la demande ; les
deux espaces de l'element sont aussi dans la fenetre d'override. Reglages en memoire, jamais le disque."""
import os as _os, sys as _sys  # jamais les vrais reglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import copy
import os
import sys
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication, QLabel, QMenu, QVBoxLayout, QWidget

app = QApplication.instance() or QApplication([])

import settings_element_style as es
import settings_layout
import settings_quick_style
import settings_window_v2 as v2
from settings_store import DEFAULT_SETTINGS
from settings_widgets import ELEMENT_LOOKS, _Toggle, make_space_actions


class _Base(unittest.TestCase):
    def setUp(self):
        self.disk = copy.deepcopy(DEFAULT_SETTINGS)
        self.disk["table_radius"] = 0
        load = lambda *a, **k: copy.deepcopy(self.disk)
        save = lambda settings: self.disk.update(copy.deepcopy(settings))
        for target in (es, settings_quick_style):
            for name, fake in (("load_settings", load), ("save_settings", save)):
                patcher = mock.patch.object(target, name, fake)
                patcher.start()
                self.addCleanup(patcher.stop)
        v2.seed_window_look(self.disk)
        self.addCleanup(ELEMENT_LOOKS.clear)
        self.addCleanup(self._close_windows)

    @staticmethod
    def _close_windows():
        for window in list(es._OPEN.values()):
            try:
                window.close()
            except RuntimeError:
                pass
        es._OPEN.clear()

    def _table(self, key: str):
        frame = v2._flat_cells_table([("Nom", QLabel("a"), None), ("Taille", QLabel("b"), None)])
        frame._dims_key = key
        frame.show()
        app.processEvents()
        self.addCleanup(frame.deleteLater)
        return frame

    @staticmethod
    def _set(window, key, value):
        values = window.style()
        values[key] = value
        window.styleChanged.emit(values)
        app.processEvents()

    @staticmethod
    def _of(targets, kind):
        return next(t for t in targets if isinstance(t, kind))


class TableOverrideTest(_Base):
    def test_override_applies_to_this_table_only_and_is_saved(self):
        mine, other = self._table("Essai/A#0"), self._table("Essai/B#0")
        target = self._of(es.targets_for(mine.findChild(QLabel)), es.TableTarget)
        window = es.open_override(target)
        self._set(window, "table_radius", 9)
        self.assertEqual(self.disk["element_style_overrides"], {"table:Essai/A#0": {"table_radius": 9}})
        self.assertEqual((mine._radius, other._radius), (9, 0))
        # Restylage general : l'override tient, l'autre tableau suit.
        settings_layout._set_flat_tables_style(radius=3)
        self.assertEqual((mine._radius, other._radius), (9, 3))
        settings_layout._set_flat_tables_style(radius=0)
        # Tableau reconstruit (meme cle) : il reprend son style a l'affichage.
        es.load(self.disk)
        again = self._table("Essai/A#0")
        self.assertEqual(again._radius, 9)
        target = self._of(es.targets_for(again.findChild(QLabel)), es.TableTarget)
        self.assertTrue(target.has_override())
        es.remove_override(target)
        self.assertEqual(self.disk["element_style_overrides"], {})
        self.assertEqual(again._radius, 0)

    def test_colours_are_overridden_key_by_key(self):
        frame = self._table("Essai/C#0")
        window = es.open_override(self._of(es.targets_for(frame), es.TableTarget))
        row_key = next(k for k in window.style() if k.startswith("colors:") and k.endswith("table_row"))
        self._set(window, row_key, "#204060")
        self.assertEqual(self.disk["element_style_overrides"]["table:Essai/C#0"], {"colors": {"table_row": "#204060"}})
        self.assertEqual(frame._look_state["M"]["table_row_a"], "#204060")


class MenuAndSpacesTest(_Base):
    def test_space_lines_bring_the_override_line_and_the_window_has_both_spaces(self):
        frame = self._table("Essai/D#0")
        label = next(lb for lb in frame.findChildren(QLabel) if lb.text() == "a")
        spaces = {"above": 0, "below": 0}
        menu = QMenu()
        make_space_actions(menu, 4, 0, lambda v: spaces.__setitem__("above", v),
                           lambda v: spaces.__setitem__("below", v), widget=label)
        sub = next(a.menu() for a in menu.actions() if a.menu() is not None)
        self.assertEqual(sub.title(), "Override settings")
        self.assertEqual([a.text() for a in sub.actions()], ["Texte « a »…", "Tableau Essai › D"])
        scopes = sub.actions()[1].menu()             # portee : cellule / ligne / colonne / tableau entier
        next(a for a in scopes.actions() if a.text() == "Tableau entier sauf entête…").trigger()
        window = es._OPEN["table:Essai/D#0"]
        keys = [spec.key for spec, _w in window._fields]
        self.assertEqual(keys[-2:], ["__space_above", "__space_below"])
        self.assertEqual(window.style()["__space_above"], 4)
        self._set(window, "__space_below", 30)
        self.assertEqual(spaces["below"], 30)
        self.assertNotIn("table:Essai/D#0", self.disk.get("element_style_overrides") or {})   # espaces : pas un style


class TextOverrideTest(_Base):
    @staticmethod
    def _size(label):
        font = label.font()
        return font.pointSizeF() if font.pointSizeF() > 0 else font.pixelSize()

    def test_text_font_colour_and_padding_then_reset(self):
        host = QWidget()
        lay = QVBoxLayout(host)
        label = QLabel("Bonjour")
        lay.addWidget(label)
        host.show()
        self.addCleanup(host.deleteLater)
        target = self._of(es.targets_for(label), es.TextTarget)
        window = es.open_override(target)
        values = window.style()
        values.update({"text_font_size": 22, "text_font_color": "#ff8800"})
        window.styleChanged.emit(values)
        app.processEvents()
        saved = self.disk["element_style_overrides"][target.element]
        self.assertEqual((saved["text_font_size"], saved["text_font_color"]), (22, "#ff8800"))
        self.assertIn("#ff8800", label.styleSheet())
        self.assertGreater(self._size(label), 18)
        # Reconstruction : reappliquee par son chemin dans la fenetre.
        label._look_values = None
        label.setFont(app.font())
        es.apply_saved(host, self.disk)
        self.assertGreater(self._size(label), 18)
        es.remove_override(target)
        self.assertNotIn("#ff8800", label.styleSheet())

    def test_text_style_override_supports_border_radius_and_background(self):
        host = QWidget()
        label = QLabel("Texte", host)
        label.setGeometry(0, 0, 100, 24)
        host.show()
        self.addCleanup(host.deleteLater)
        target = self._of(es.targets_for(label), es.TextTarget)
        window = es.open_override(target)
        values = window.style()
        values.update({
            "text_border_enabled": {"top": True, "right": False, "bottom": True, "left": False},
            "text_border": {"top": "#ff0000", "right": "#00000000",
                            "bottom": "#00ff00", "left": "#00000000"},
            "text_border_thickness": 2,
            "text_border_radius": {"top_left": 3, "top_right": 4, "bottom_right": 5, "bottom_left": 6},
            "text_background_enabled": True,
            "text_background_color": "#203040",
        })
        window.styleChanged.emit(values)
        app.processEvents()
        self.assertIn("border-top: 2px solid #ff0000", label.styleSheet())
        self.assertIn("border-top-left-radius: 3px", label.styleSheet())
        self.assertIn("background: #203040", label.styleSheet())
        self.assertEqual(self.disk["element_style_overrides"][target.element]["text_border_thickness"], 2)


class ToggleOverrideTest(_Base):
    def test_toggle_gets_its_own_hidden_style(self):
        host = QWidget()
        lay = QVBoxLayout(host)
        mine, other = _Toggle(True, show_label=False), _Toggle(True, show_label=False)
        mine.style_id, other.style_id = "Essai|a#0", "Essai|b#0"
        lay.addWidget(mine)
        lay.addWidget(other)
        host.show()
        self.addCleanup(host.deleteLater)
        target = self._of(es.targets_for(mine), es.ToggleTarget)
        prefix = target.prefix
        window = es.open_override(target)
        self._set(window, f"{prefix}_outer_width", 61)
        self.assertEqual(self.disk["element_style_overrides"]["toggle:Essai|a#0"], {f"{prefix}_outer_width": 61})
        self.assertEqual(mine._style()["outer_w"], 61)
        self.assertNotEqual(other._style()["outer_w"], 61)
        self.assertNotIn(prefix + "x", str(self.disk.get("toggle_styles")))     # aucun style nomme cree
        es.remove_override(target)
        self.assertNotEqual(mine._style()["outer_w"], 61)


class TablePartsTest(_Base):
    """Sur une cellule : le menu demande la portee (cellule / ligne / colonne en cours, tableau entier) ;
    fond, padding et police propres, cellule > ligne > colonne > tableau, gardes au restylage."""

    def setUp(self):
        super().setUp()
        from settings_widgets import PART_LOOKS
        self.addCleanup(PART_LOOKS.clear)
        self.frame = self._table("Essai/P#0")
        self.labels = {lb.text(): lb for lb in self.frame.findChildren(QLabel) if lb.text() in ("Nom", "a", "Taille", "b")}

    def _target(self, text, kind):
        return next(t for t in es.targets_for(self.labels[text]) if getattr(t, "kind", "") == kind)

    def test_menu_asks_for_the_scope(self):
        menu = QMenu()
        es.add_override_actions(self.labels["a"], menu)
        sub = next(a.menu() for a in menu.actions() if a.menu() is not None and a.text() == "Override settings")
        # Le texte clique est aussi un element : les portees du tableau sont dans son sous-menu.
        table = next(a.menu() for a in sub.actions() if a.menu() is not None and a.text().startswith("Tableau"))
        texts = [a.text() for a in table.actions() if a.text()]
        for scope in ("Cellule en cours…", "Ligne en cours…", "Colonne en cours sauf entête…",
                      "Tableau entier sauf entête…"):
            self.assertIn(scope, texts)
        self.assertNotIn("Entête entier…", texts)          # pas dans l'entete

    def test_header_scope_and_header_kept_out_of_column_and_table(self):
        head = self.frame._flat_head
        titles = [lb for lb in head.findChildren(QLabel) if lb.text()]
        head._menu_column = -1                      # clic dans l'entete, hors d'un titre
        menu = QMenu()
        es.add_override_actions(head, menu)
        head._menu_column = None
        sub = next(a.menu() for a in menu.actions() if a.menu() is not None and a.text() == "Override settings")
        texts = [a.text() for a in sub.actions() if a.text()]
        self.assertEqual(texts[:2], ["Entête entier…", "Tableau entier sauf entête…"])
        # Colonne et tableau entier : l'entete garde sa police et sa couleur.
        sizes = [lb.font().pixelSize() for lb in titles]
        self._set(es.open_override(self._target("a", "Colonne")), "table_text_font_size", 23)
        self._set(es.open_override(self._target("a", "Tableau")), "table_text_font_size", 19)
        self.assertEqual([lb.font().pixelSize() for lb in titles], sizes)
        table = es.open_override(self._target("a", "Tableau"))
        self.assertFalse(any(k.endswith("table_head") or k == "table_head_color" for k in table.style()))
        # Entete entier : sa police et sa couleur de fond, sans toucher aux cellules.
        target = next(t for t in es.targets_for(head) if t.kind == "Entête")
        window = es.open_override(target)
        values = window.style()
        head_key = next(k for k in values if k.startswith("colors:") and k.endswith("table_head"))
        values.update({"table_text_font_size": 27, head_key: "#40a020"})
        window.styleChanged.emit(values)
        app.processEvents()
        self.assertTrue(all(lb.font().pixelSize() == 27 for lb in titles))
        self.assertEqual(self.labels["Nom"].font().pixelSize(), 19)
        self.assertEqual(self.frame._look_state["M"]["table_head_bg"], "#40a020")
        saved = self.disk["element_style_overrides"]["table:Essai/P#0::head"]
        self.assertEqual((saved["table_text_font_size"], saved["colors"]), (27, {"table_head": "#40a020"}))
        es.remove_override(target)
        self.assertEqual([lb.font().pixelSize() for lb in titles], sizes)

    def test_header_cell_scope(self):
        head = self.frame._flat_head
        titles = head._cells
        head._menu_column = 1                       # clic droit sur le 2e titre
        menu = QMenu()
        es.add_override_actions(head, menu)
        sub = next(a.menu() for a in menu.actions() if a.menu() is not None and a.text() == "Override settings")
        texts = [a.text() for a in sub.actions() if a.text()]
        self.assertEqual(texts[:3], ["Cellule en cours…", "Entête entier…", "Tableau entier sauf entête…"])
        cell = next(t for t in es.targets_for(head) if t.kind == "Cellule d'entête")
        head._menu_column = None
        self.assertEqual(cell.element, "table:Essai/P#0::head:c1")
        whole = next(t for t in es.targets_for(head) if t.kind == "Entête")
        self._set(es.open_override(whole), "table_text_font_italic", True)
        window = es.open_override(cell)
        values = window.style()
        head_key = next(k for k in values if k.startswith("colors:") and k.endswith("table_head"))
        values.update({"table_text_font_size": 25, head_key: "#a02040"})
        window.styleChanged.emit(values)
        app.processEvents()
        self.assertEqual(titles[1].font().pixelSize(), 25)
        self.assertNotEqual(titles[0].font().pixelSize(), 25)           # seulement CE titre
        self.assertTrue(titles[0].font().italic() and titles[1].font().italic())   # entete entier dessous
        self.assertIn("#a02040", titles[1].styleSheet())
        self.assertNotIn("#a02040", titles[0].styleSheet())
        self.assertIn("padding", titles[1].styleSheet())                 # padding de l'entete garde
        es.remove_override(cell)
        self.assertNotEqual(titles[1].font().pixelSize(), 25)
        self.assertNotIn("#a02040", titles[1].styleSheet())

    def test_cell_background_padding_and_font(self):
        cells = self.frame._extra_dims.cells
        window = es.open_override(self._target("a", "Cellule"))
        values = window.style()
        values.update({"colors:table_row": "#ff0000", "table_text_font_size": 22,
                       "table_cell_padding": {"left": 30, "top": 2, "right": 30, "bottom": 2}})
        window.styleChanged.emit(values)
        app.processEvents()
        saved = self.disk["element_style_overrides"]["table:Essai/P#0::cell:r0c1"]
        self.assertEqual(saved["colors"], {"table_row": "#ff0000"})
        self.assertEqual(saved["table_text_font_size"], 22)
        self.assertEqual(self.labels["a"].font().pixelSize(), 22)
        self.assertNotEqual(self.labels["b"].font().pixelSize(), 22)       # seulement CETTE cellule
        self.assertNotEqual(self.labels["Nom"].font().pixelSize(), 22)
        self.assertEqual(cells["r0c1"].layout().contentsMargins().left(), 30)
        self.assertNotEqual(cells["r1c1"].layout().contentsMargins().left(), 30)
        cell = cells["r0c1"]
        row = cell.parentWidget()
        image = row.grab().toImage()
        self.assertEqual(image.pixelColor(cell.x() + 3, row.height() // 2).name(), "#ff0000")
        # Restylage general des textes : la police propre tient.
        from settings_theme import _refresh_text_roles
        _refresh_text_roles(self.frame)
        self.assertEqual(self.labels["a"].font().pixelSize(), 22)
        es.remove_override(self._target("a", "Cellule"))
        self.assertNotEqual(self.labels["a"].font().pixelSize(), 22)
        self.assertIsNone(cell._part_look)

    def test_zero_padding_leaves_no_space(self):
        """Padding 0 = la ligne colle au texte : aucune marge ni hauteur plancher en plus."""
        self._set(es.open_override(self._target("a", "Ligne")), "table_cell_padding",
                  {"left": 0, "top": 0, "right": 0, "bottom": 0})
        app.processEvents()
        cell = self.frame._extra_dims.cells["r0c1"]
        row = cell.parentWidget()
        self.assertEqual(tuple(cell.layout().contentsMargins().__getattribute__(n)() for n in
                               ("left", "top", "right", "bottom")), (0, 0, 0, 0))
        inner = row.layout().contentsMargins()
        need = max(c.sizeHint().height() for c in row.findChildren(QWidget) if c.objectName() == "TableCell")
        self.assertLessEqual(row.minimumHeight(), need + inner.top() + inner.bottom())
        self.assertLessEqual(inner.top() + inner.bottom(), 2)               # seulement le filet du haut

    def test_row_column_and_whole_table_font(self):
        es.open_override(self._target("Taille", "Ligne"))
        self._set(es._OPEN["table:Essai/P#0::row:1"], "table_text_font_bold", True)
        self.assertTrue(self.labels["Taille"].font().bold() and self.labels["b"].font().bold())
        self.assertFalse(self.labels["a"].font().bold())
        self._set(es.open_override(self._target("a", "Colonne")), "table_text_font_italic", True)
        self.assertTrue(self.labels["a"].font().italic() and self.labels["b"].font().italic())
        self.assertFalse(self.labels["Nom"].font().italic())
        table = self._target("a", "Tableau")
        self.assertEqual(table.scope_label, "Tableau entier sauf entête")
        self._set(es.open_override(table), "table_text_font_size", 19)
        self.assertTrue(all(lb.font().pixelSize() == 19 for lb in self.labels.values()))
        self.assertTrue(self.labels["b"].font().bold())                      # la ligne garde son gras


if __name__ == "__main__":
    unittest.main()
