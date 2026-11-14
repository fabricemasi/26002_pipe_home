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
from PySide6.QtGui import QColor
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


class PickerOpensOnCurrentColorTest(unittest.TestCase):
    """Demande de l'utilisateur (2026-11-11) : le sélecteur s'ouvre sur la couleur actuelle."""

    def test_any_color_the_swatch_can_paint_is_read(self):
        from settings_widgets import normalize_picker_color
        self.assertEqual(normalize_picker_color("#369"), "#336699")
        self.assertEqual(normalize_picker_color("red"), "#ff0000")
        self.assertEqual(normalize_picker_color("#80336699"), "#80336699")
        self.assertEqual(normalize_picker_color(""), "#000000")
        popup = _ColorPickerPopup("#369", "Couleur")
        self.addCleanup(popup.deleteLater)
        self.assertEqual(popup._before, "#336699")

    def test_choosing_a_hue_from_transparent_makes_it_visible(self):
        """Signalé le 2026-11-11 (fond du cadre de sélection des variantes) : partir de « #00000000 » gardait
        l'opacité à 0, la couleur choisie était enregistrée mais invisible."""
        popup = _ColorPickerPopup("#00000000", "Couleur")
        self.addCleanup(popup.deleteLater)
        self.assertEqual(popup._current_hex(), "#00000000")              # rien touché : reste transparent
        popup._s, popup._v = 1.0, 1.0
        popup._refresh_all()
        self.assertEqual(QColor(popup._current_hex()).alpha(), 255)
        popup._on_alpha(0.25)                                             # opacité réglée à la main : respectée
        popup._h = 0.5
        popup._refresh_all()
        self.assertEqual(QColor(popup._current_hex()).alpha(), round(0.25 * 255))
        popup._on_reset()
        self.assertEqual(popup._current_hex(), "#00000000")
        half = _ColorPickerPopup("#80336699", "Couleur")                 # couleur semi-transparente : inchangée
        self.addCleanup(half.deleteLater)
        half._s = 0.2
        half._refresh_all()
        self.assertEqual(QColor(half._current_hex()).alpha(), 0x80)

    def test_transparent_that_follows_the_theme_opens_on_the_shown_color(self):
        import settings_sections as ss
        from fm_theme import style
        field = ss._CompactAppOrCustomColorField("#00000000", {})
        self.addCleanup(field.deleteLater)
        self.assertEqual(field._picker_start(), "#00000000")             # sans couleur affichée connue : la valeur
        field.set_effective(lambda: style.button_shown_color("button_hover_color", {}))
        self.assertEqual(field._picker_start(), QColorName(style.C["btn_hover"]))
        field._open_custom_picker()
        popup = field._popup
        self.addCleanup(popup.deleteLater)
        popup.committed.emit(popup._before)                               # valider sans changer : reste transparent
        self.assertEqual(field.value(), "#00000000")
        popup.committed.emit("#123456")
        self.assertEqual(field.value(), "#123456")

    def test_every_button_state_has_a_shown_color(self):
        from fm_theme import style
        import settings_window_v2 as v2
        for spec in v2.CATALOG["Bouton"]:
            if not isinstance(spec, str) and spec.key.startswith("button_") and spec.key.endswith("_color") \
                    and spec.default == "#00000000":
                self.assertTrue(style.button_shown_color(spec.key, {}), spec.key)


def QColorName(value: str) -> str:
    from PySide6.QtGui import QColor
    return QColor(value).name()


if __name__ == "__main__":
    unittest.main()
