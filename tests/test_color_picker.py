"""Selecteur de couleur (_ColorPickerPopup) : les valeurs se TAPENT (demande de l'utilisateur : les textes
n'etaient pas modifiables) — HEX, Teinte / Saturation / Luminosite, Rouge / Vert / Bleu, Alpha ; Entree
applique la valeur, le curseur et la couleur suivent ; une valeur hors bornes est ramenee dans les bornes."""
import os as _os, sys as _sys  # jamais les vrais reglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit, QWidget

app = QApplication.instance() or QApplication([])

from settings_widgets import _ColorPickerPopup


class ColorPickerTypingTest(unittest.TestCase):
    def setUp(self):
        self.host = QWidget()
        self.host.resize(200, 100)
        self.host.show()
        self.popup = _ColorPickerPopup("#336699", "Couleur", self.host)
        self.popup.show_near(self.host)
        app.processEvents()
        self.emitted = []
        self.popup.colorChanged.connect(self.emitted.append)
        self.addCleanup(self.popup.close)
        self.addCleanup(self.host.close)

    def type_into(self, edit: QLineEdit, text: str):
        self.assertTrue(edit.isEnabled() and not edit.isReadOnly())
        edit.setFocus()
        edit.selectAll()
        QTest.keyClicks(edit, text)
        QTest.keyClick(edit, Qt.Key_Return)
        app.processEvents()

    def test_every_value_box_is_an_editable_field(self):
        boxes = [v for _s, v in self.popup._hsl_rows] + [v for _s, v in self.popup._rgb_rows]
        boxes.append(self.popup._alpha_val)
        self.assertEqual(len(boxes), 7)
        for box in boxes:
            self.assertIsInstance(box, QLineEdit)
            self.assertFalse(box.isReadOnly())

    def test_hex_is_typed(self):
        self.type_into(self.popup.hex_edit, "#ff8000")
        self.assertEqual(self.popup._current_hex(), "#ff8000")
        self.assertEqual(self.emitted[-1], "#ff8000")

    def test_rgb_values_are_typed(self):
        red, _ = self.popup._rgb_rows[0][1], None
        self.type_into(red, "255")
        self.assertEqual(self.popup._current_hex()[:3], "#ff")
        self.assertEqual(self.popup._rgb_rows[0][1].text(), "255")

    def test_hue_and_alpha_are_typed_and_clamped(self):
        hue = self.popup._hsl_rows[0][1]
        self.type_into(hue, "120")
        self.assertEqual(round(self.popup._h), 120)
        self.type_into(self.popup._alpha_val, "50")
        self.assertEqual(self.popup._a, round(0.5 * 255))
        self.assertEqual(self.popup._alpha_val.text(), "50")
        # Le validateur refuse ce qui depasse les bornes : la valeur affichee reste valide.
        self.type_into(self.popup._hsl_rows[1][1], "999")
        self.assertLessEqual(int(self.popup._hsl_rows[1][1].text()), 100)


if __name__ == "__main__":
    unittest.main()
