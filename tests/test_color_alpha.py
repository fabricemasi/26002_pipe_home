"""Opacite d'une couleur de l'appli (demande de l'utilisateur) : « @slot/75 » = la pastille a 75 %, toujours
liee a la palette ; resolue en #aarrggbb partout (reglages, appli, couleurs d'entete au nom nu)."""
import os as _os, sys as _sys  # jamais les vrais reglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

import app_style
import settings_menu as sm
import settings_window_v2 as v2
from app_style import join_color_ref, split_color_ref, with_alpha
from settings_sections import _CompactAppOrCustomColorField
from settings_store import _SLOT_REAL, _resolve_color_value
from settings_widgets import _SliderField

SLOT, REAL = next((slot, real) for slot, real, _label in app_style.SEMANTIC_COLOR_SLOTS)


class ColorAlphaTest(unittest.TestCase):
    def test_format(self):
        self.assertEqual(split_color_ref("@accent/75"), ("@accent", 75))
        self.assertEqual(split_color_ref("@accent"), ("@accent", 100))
        self.assertEqual(split_color_ref("#80112233"), ("#80112233", 100))
        self.assertEqual(join_color_ref("@accent", 100), "@accent")
        self.assertEqual(join_color_ref("@accent", 40), "@accent/40")
        self.assertEqual(with_alpha("#ff0000", 50), "#80ff0000")
        self.assertEqual(with_alpha("#80ff0000", 50), "#40ff0000")      # opacite deja presente : multipliee

    def test_resolved_everywhere(self):
        colors = {REAL: "#204060"}
        self.assertEqual(_resolve_color_value(f"@{SLOT}/50", colors), "#80204060")
        self.assertEqual(_resolve_color_value(f"@{SLOT}", colors), "#204060")
        self.assertEqual(v2._head_hex(colors, f"{SLOT}/50"), "#80204060")
        self.assertEqual(app_style.resolve_color_ref(f"@{SLOT}/50"),
                         with_alpha(app_style.C[app_style._SEMANTIC_TO_REAL[SLOT]], 50))

    def test_menu_slider_sets_the_opacity_and_keeps_it_across_slots(self):
        field = _CompactAppOrCustomColorField(f"@{SLOT}", {REAL: "#204060"})
        values = []
        field.changed.connect(values.append)
        field._set_alpha(60)
        self.assertEqual(field.value(), f"@{SLOT}/60")
        other = next(slot for slot, _r, _l in app_style.SEMANTIC_COLOR_SLOTS if slot != SLOT)
        field._select_slot(other)
        self.assertEqual(field.value(), f"@{other}/60")
        self.assertEqual(values[-1], f"@{other}/60")
        # Le menu des pastilles a bien sa ligne « Opacite » (curseur a la valeur courante).
        shown = []
        original = sm.Menu.exec
        sm.Menu.exec = lambda menu, *a, **k: shown.append(menu)
        try:
            field._open_menu()
        finally:
            sm.Menu.exec = original
        row = next(a.defaultWidget() for a in shown[0].actions() if sm.item_id(a) == "row:Opacité")
        self.assertEqual(row.control.findChild(_SliderField).value() if not isinstance(row.control, _SliderField)
                         else row.control.value(), 60)


if __name__ == "__main__":
    unittest.main()
