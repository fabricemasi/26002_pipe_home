"""Settings > Icones > « Couleur des dossiers » : l'icone (blanche) des dossiers est teintee selon leur sorte —
standard, raccourci, Lightroom ; blanc = icone telle quelle ; jamais les icones de logiciel. Colonnes Texte | Couleur
icone | Couleur du texte : couleur du texte par sorte (Texte coupe = couleur de la colonne ; « Couleur icone » =
celle de l'icone) ; plus de couleur dediee aux raccourcis."""
import os as _os, sys as _sys  # jamais les vrais reglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import os
import shiboken6
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPixmap, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

import ui_state
from fm_theme import cells
import row_delegates
from browser_core import ROLE_IS_SHORTCUT, ROLE_LIGHTROOM_SHORTCUT, apply_folder_icon_colors, tinted_icon
from settings_store import DEFAULT_SETTINGS
from settings_window_v2 import CATALOG


def white_icon() -> QPixmap:
    pix = QPixmap(8, 8)
    pix.fill(Qt.transparent)
    from PySide6.QtGui import QPainter
    p = QPainter(pix)
    p.fillRect(2, 2, 4, 4, QColor("#ffffff"))
    p.end()
    return pix


class FolderIconColorTest(unittest.TestCase):
    def setUp(self):
        self.addCleanup(setattr, ui_state, "FOLDER_ICON_COLORS", dict(ui_state.FOLDER_ICON_COLORS))
        self.addCleanup(setattr, ui_state, "FOLDER_TEXT_COLORS", dict(ui_state.FOLDER_TEXT_COLORS))

    def test_tint_keeps_transparency_and_white_is_untouched(self):
        icon = white_icon()
        self.assertIs(tinted_icon(icon, "#ffffff"), icon)                  # blanc : rien a calculer
        red = tinted_icon(icon, "#ff0000").toImage()
        self.assertEqual(red.pixelColor(3, 3).name(), "#ff0000")
        self.assertEqual(red.pixelColor(0, 0).alpha(), 0)                   # le fond reste transparent
        self.assertIs(tinted_icon(icon, "#ff0000"), tinted_icon(icon, "#ff0000"))   # cache

    def test_kind_by_row_and_settings_declared(self):
        apply_folder_icon_colors({"folder_icon_color_standard": "#00ff00", "folder_icon_color_shortcut": "#0000ff",
                                  "folder_icon_color_lightroom": "#ff0000"})
        model = QStandardItemModel()
        rows = []
        for shortcut, lightroom in ((False, False), (True, False), (True, True)):
            item = QStandardItem("d")
            item.setData(shortcut, ROLE_IS_SHORTCUT)
            item.setData(lightroom, ROLE_LIGHTROOM_SHORTCUT)
            model.appendRow(item)
            rows.append((item.index(), shortcut))
        colors = [row_delegates._tint_folder_icon(white_icon(), index, shortcut).toImage().pixelColor(3, 3).name()
                  for index, shortcut in rows]
        self.assertEqual(colors, ["#00ff00", "#0000ff", "#ff0000"])
        keys = {key for spec in CATALOG["Icones : Couleurs des dossiers"] for key in (spec.key, *spec.extra_keys)}
        for kind in ("standard", "shortcut", "lightroom"):
            for key in (f"folder_icon_color_{kind}", f"folder_text_color_{kind}_enabled",
                        f"folder_text_color_{kind}_from_icon", f"folder_text_color_{kind}"):
                self.assertIn(key, DEFAULT_SETTINGS)
                self.assertIn(key, keys)
        self.assertNotIn("shortcut_color", DEFAULT_SETTINGS)               # plus de couleur dediee aux raccourcis

    def test_text_color_only_when_its_toggle_is_on(self):
        settings = dict(DEFAULT_SETTINGS, folder_text_color_shortcut_enabled=True, folder_text_color_shortcut="#123456",
                        folder_text_color_lightroom="#ff0000",              # Lightroom : toggle coupe
                        folder_icon_color_standard="#00ff00", folder_text_color_standard_from_icon=True)
        apply_folder_icon_colors(settings)
        model = QStandardItemModel()
        for shortcut, lightroom in ((False, False), (True, False), (True, True)):
            item = QStandardItem("d")
            item.setData(shortcut, ROLE_IS_SHORTCUT)
            item.setData(lightroom, ROLE_LIGHTROOM_SHORTCUT)
            model.appendRow(item)
        colors = [row_delegates._folder_text_color(model.index(r, 0), r > 0, "#column") for r in range(3)]
        self.assertEqual(colors, ["#column", "#123456", "#column"])       # « Couleur icone » sans Texte : rien
        settings["folder_text_color_standard_enabled"] = True
        apply_folder_icon_colors(settings)
        self.assertEqual(row_delegates._folder_text_color(model.index(0, 0), False, "#column"), "#00ff00")
        import browser_core
        self.assertFalse(hasattr(browser_core._resolve_shortcut_font(), "__len__"))   # une police, plus de couleur

    def test_settings_group_builds_next_to_the_icon_table(self):
        import copy
        import settings_window_v2 as v2
        self.assertIn("Icones : General", v2.ICON_GROUPS)                  # le tableau d'icones reste intact
        values = v2.ScopeValues(copy.deepcopy(DEFAULT_SETTINGS), "General", None)
        fields = {}
        frame = v2.build_group("Icones : Couleurs des dossiers", values, {}, fields, {}, [])
        self.addCleanup(shiboken6.delete, frame)
        state = frame._extra_dims                       # une colonne par reglage, aucune cellule divisee
        self.assertEqual(sorted(state.cells), sorted(f"r{r}c{c}" for r in range(3) for c in range(5)))
        self.assertFalse(any(cells.split_of(c.content()) for c in state.cells.values()))
        enabled, from_icon = fields["folder_text_color_shortcut_enabled"], fields["folder_text_color_shortcut_from_icon"]
        color = fields["folder_text_color_shortcut"]
        self.assertFalse(color.isEnabled())                                 # Texte coupe : grisee
        enabled.setChecked(True)
        self.assertTrue(color.isEnabled() and from_icon.isEnabled())
        from_icon.setChecked(True)
        self.assertFalse(color.isEnabled())                                 # suit l'icone : grisee


if __name__ == "__main__":
    unittest.main()
