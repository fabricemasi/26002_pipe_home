"""Menu contextuel des tableaux (demande de l'utilisateur) : « Supprimer l'entete » / « Afficher l'entete » et
« Ajouter un texte au-dessus… » (seulement quand rien n'est colle au-dessus de la ligne : 1re ligne d'un
tableau sans entete, ou ligne qui ouvre une partie « Split au-dessus ») ; police = Tableaux > Texte au dessus."""
import os as _os, sys as _sys  # jamais les vrais reglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication, QLabel, QMenu

app = QApplication.instance() or QApplication([])

import settings_cells as sc


def settle():
    for _ in range(5):
        app.processEvents()


class HeadAndTextAboveTest(unittest.TestCase):
    def build(self):
        frame, head, cells = sc.build_cells_table(
            [("Paramètre", 140), ("Valeur", 200)],
            [[QLabel(f"Ligne {i}"), QLabel(f"valeur {i}")] for i in range(3)])
        frame.resize(frame.sizeHint())
        frame.show()
        self.addCleanup(frame.deleteLater)
        settle()
        self.frame, self.head, self.cells, self.state = frame, head, cells, frame._extra_dims
        return frame

    def menu_texts(self, r, c=1):
        menu = QMenu()
        self.cells[r][c].populate_menu(menu)
        return [a.text() for a in menu.actions() if a.text()]

    def test_remove_and_restore_the_header(self):
        self.build()
        self.assertIn("Supprimer l'entête", self.menu_texts(0))
        self.state.set_head_hidden(True)
        settle()
        self.assertTrue(self.head.isHidden())
        self.assertEqual(self.frame.collectDims().get("head_hidden"), True)
        self.assertIn("Afficher l'entête", self.menu_texts(0))
        self.state.set_head_hidden(False)
        self.assertFalse(self.head.isHidden())
        self.assertNotIn("head_hidden", self.frame.collectDims())

    def test_text_above_only_where_nothing_is_glued_above(self):
        self.build()
        st = self.state
        self.assertFalse(st.can_text_above(0))                  # l'entete est colle au-dessus
        self.assertFalse(st.can_text_above(1))                  # la ligne 0 aussi
        self.assertNotIn("Ajouter un texte au-dessus…", self.menu_texts(1))
        st.set_split(1, True, 15)
        self.assertTrue(st.can_text_above(1))
        self.assertIn("Ajouter un texte au-dessus…", self.menu_texts(1))
        st.set_head_hidden(True)
        self.assertTrue(st.can_text_above(0))
        # Textes poses dans l'espace au-dessus de leur ligne, hors des lignes.
        st.set_above_text(1, "Deuxième partie")
        st.set_above_text(0, "Première partie")
        settle()
        rows = st.rows.rows
        for r, text in ((0, "Première partie"), (1, "Deuxième partie")):
            label = st._above_labels[r]
            self.assertTrue(label.isVisible())
            self.assertEqual(label.text(), text)
            self.assertLessEqual(label.geometry().bottom(), rows[r].y() - 1)
            if r:
                self.assertGreaterEqual(label.y(), rows[r - 1].geometry().bottom())
            else:
                self.assertGreaterEqual(label.y(), 0)
        self.assertIn("Modifier le texte au-dessus…", self.menu_texts(1))
        # Coupe eteinte : le texte n'a plus de place (garde, cache).
        st.set_split(1, False, 15)
        settle()
        self.assertFalse(st._above_labels[1].isVisible())
        st.set_split(1, True, 15)
        settle()
        self.assertTrue(st._above_labels[1].isVisible())
        # Enregistre avec le tableau, repris par un tableau identique.
        dims = self.frame.collectDims()
        self.assertEqual(dims["above_texts"], {"0": "Première partie", "1": "Deuxième partie"})
        self.build()
        self.frame.applyDims(dims)
        settle()
        self.assertTrue(self.head.isHidden())
        self.assertEqual(self.state._above_labels[0].text(), "Première partie")
        self.assertTrue(self.state._above_labels[1].isVisible())
        # Texte vide = retire.
        self.state.set_above_text(0, "")
        settle()
        self.assertFalse(self.state._above_labels[0].isVisible())
        self.assertNotIn("0", self.frame.collectDims().get("above_texts", {}))

    def test_tables_section_has_the_text_row(self):
        import settings_window_v2 as v2
        import settings_store
        spec = next(s for s in v2.CATALOG["Tableaux"] if s.label == "Texte au dessus")
        self.assertEqual(spec.key, "table_above_text_font_family")
        values = settings_store.load_settings()
        read = v2.read_spec(spec, v2.make_field(spec, v2.ScopeValues(values, None), values["colors"]))
        self.assertTrue(set(read) <= set(settings_store.DEFAULT_SETTINGS), read)


if __name__ == "__main__":
    unittest.main()
