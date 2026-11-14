"""Valeurs du grisé (fm_theme > Général : éléments d'interface `dimmed_opacity`, textes, icônes ; demande de
l'utilisateur 2026-11-12) : opacité de tout objet
non utilisable (réglage inactif, bouton désactivé de la barre), réglage du thème, appliquée en direct."""
import os as _os, sys as _sys  # jamais les vrais reglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication, QGraphicsOpacityEffect, QWidget  # noqa: E402

APP = QApplication.instance() or QApplication([])

import settings_store  # noqa: E402
import settings_window_v2 as v2  # noqa: E402
from fm_theme import presets as tp  # noqa: E402
from fm_theme import widgets as fw  # noqa: E402


class DimmedOpacityTest(unittest.TestCase):
    def test_setting_lives_in_theme_general(self):
        general = [s.key for s in v2.CATALOG["Thème : Général"]]
        # Éléments d'interface, textes, icônes ; et la couleur des icônes, déplacée ici (2026-11-12).
        for key in ("dimmed_opacity", "dimmed_text_opacity", "dimmed_icon_opacity", "navtool_icon_base_color"):
            self.assertIn(key, general)
            self.assertIn(key, tp.GENERAL_KEYS)                        # enregistré avec le preset de thème
            elsewhere = [g for g, specs in v2.CATALOG.items() if g != "Thème : Général" and key in [s.key for s in specs]]
            self.assertEqual(elsewhere, [], key)                       # seulement là
        for key in ("dimmed_opacity", "dimmed_text_opacity", "dimmed_icon_opacity"):
            self.assertEqual(settings_store.DEFAULT_SETTINGS[key], 20)
        self.assertNotIn("Icones : Couleur des icones", v2.CATALOG)

    def test_value_applies_to_greyed_objects_live(self):
        self.addCleanup(fw.set_dimmed_opacity, 20)
        fw.set_dimmed_opacity(20)
        widget = QWidget()
        self.addCleanup(widget.deleteLater)
        fw._set_dimmed(widget, True)
        self.assertAlmostEqual(widget.graphicsEffect().opacity(), 0.2)
        self.assertTrue(fw.set_dimmed_opacity(45))
        self.assertAlmostEqual(widget.graphicsEffect().opacity(), 0.45)   # déjà grisé : suit aussitôt
        self.assertFalse(fw.set_dimmed_opacity(45))                        # rien ne change : rien n'est refait
        other = QWidget()
        self.addCleanup(other.deleteLater)
        fw._set_dimmed(other, True)
        self.assertAlmostEqual(other.graphicsEffect().opacity(), 0.45)
        veil = QWidget()                                                   # voile d'un bouton de la barre
        self.addCleanup(veil.deleteLater)
        veil.setGraphicsEffect(QGraphicsOpacityEffect(veil))
        veil._unusable_veil = True
        fw.set_dimmed_opacity(30)
        self.assertAlmostEqual(veil.graphicsEffect().opacity(), 0.3)

    def test_disabled_buttons_take_the_grey_value(self):
        """Tous les boutons désactivés : fond, bordures et texte de l'aspect standard à la valeur du grisé."""
        from PySide6.QtWidgets import QPushButton
        from fm_theme import style
        self.addCleanup(fw.set_dimmed_values, 20, 20, 20)
        look = {"button_bg_color": "#ff0000", "button_font_color": "#00ff00",
                "button_border": {s: "#0000ff" for s in ("top", "right", "bottom", "left")}}
        self.assertTrue(fw.set_dimmed_values(40, 60, 30))
        self.assertAlmostEqual(style.disabled_alpha(), 0.4)
        self.assertAlmostEqual(fw.dimmed_text_opacity(), 0.6)
        self.assertAlmostEqual(fw.dimmed_icon_opacity(), 0.3)
        self.assertFalse(fw.set_dimmed_values(40, 60, 30))                  # rien ne change : rien n'est refait
        css = style.disabled_button_css(look)
        self.assertIn("background: rgba(255, 0, 0, 102);", css)             # éléments : 40 % de 255
        self.assertIn("border-left-color: rgba(0, 0, 255, 102);", css)
        self.assertIn("color: rgba(0, 255, 0, 153);", css)                  # textes : 60 %
        self.assertIn("QPushButton:disabled { " + css, style.variant_button_css(look))
        self.assertIn("QPushButton:disabled { " + style.disabled_button_css(style._CONTROL_LOOK), style.build_stylesheet())
        button = style.theme_button(QPushButton("x"))                       # QSS posé sur lui : suit la valeur
        self.addCleanup(button.deleteLater)
        fw.set_dimmed_values(60, 80, 30)
        self.assertIn(style.disabled_button_css(style._CONTROL_LOOK), button.styleSheet())
        self.assertIn("background: rgba(255, 0, 0, 153);", style.disabled_button_css(look))   # 60 %
        self.assertIn("color: rgba(0, 255, 0, 204);", style.disabled_button_css(look))        # 80 %
        host = QWidget()                                                    # ombre du thème : grisée aussi
        self.addCleanup(host.deleteLater)
        shadowed = QPushButton("o", host)
        shadow = {"standard": ({"on": {"top": False, "right": True, "bottom": True, "left": False},
                                "colors": {s: "#ff000000" for s in ("top", "right", "bottom", "left")}, "size": 4},
                               (0, 0))}
        style.apply_button_shadow(shadowed, shadow, "ombre")
        effect = shadowed.graphicsEffect()
        shadowed.setEnabled(False)
        effect._show(effect._state())
        self.assertEqual(effect._state(), "disabled")
        self.assertAlmostEqual(effect.color().alphaF(), 0.6, delta=0.01)

    def test_apply_all_settings_sets_it(self):
        from browser_core_parts.settings import apply_all_settings
        self.addCleanup(fw.set_dimmed_values, 20, 20, 20)
        apply_all_settings({**settings_store.DEFAULT_SETTINGS, "dimmed_opacity": 60, "dimmed_text_opacity": 50,
                            "dimmed_icon_opacity": 70})
        self.assertAlmostEqual(fw.dimmed_opacity(), 0.6)
        self.assertAlmostEqual(fw.dimmed_text_opacity(), 0.5)
        self.assertAlmostEqual(fw.dimmed_icon_opacity(), 0.7)


if __name__ == "__main__":
    unittest.main()
