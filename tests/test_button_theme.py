"""Tous les boutons de l'appli prennent leur aspect de fm_theme (demande de l'utilisateur, 2026-11-12 : « je ne veux
pas un seul bouton avec des styles orphelins, tout doit venir de fm_theme ») : la variante du type « bouton » que l'appli
utilise (QSS commun + ombre), `theme_button` pour la géométrie seule, `painted_button_look` pour les boutons dessinés.

Garde : un QSS avec un sélecteur `QPushButton` / `QToolButton` n'est permis QUE dans les fichiers listés ci-dessous
(avec leur nombre exact et leur raison) ; tout nouveau style de bouton ailleurs fait échouer le test."""
import os as _os, sys as _sys  # jamais les vrais reglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import os
import re
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

APP = QApplication.instance() or QApplication([])

ROOT = Path(__file__).resolve().parent.parent
_SKIP_DIRS = {".venv", "data", "tests", "archive", "_FM", "in", "__pycache__", ".git", "files", "icons", "docs"}
_SELECTOR = re.compile(r"Q(?:Push|Tool)Button\s*(?::[a-z]+)?\s*\{")

# Fichier -> (occurrences permises, raison). Tout le reste : 0.
ALLOWED = {
    "fm_theme/style.py": (11, "le thème lui-même (QSS commun, variantes, theme_button = géométrie seule)"),
    "fm_theme/widgets.py": (4, "champs (liste de choix = aspect des zones de saisie, pastille de couleur), un commentaire"),
    "fm_theme/layout.py": (4, "tabs de fm_theme (section Tabs), un commentaire"),
    "fm_theme/window.py": (6, "barre de titre des fenêtres de fm_theme (section Fenêtres additionnelles)"),
    "main_window/title_bar.py": (2, "boutons de la fenêtre : section Barre de navigation : Boutons fenetre"),
    "pipeline_browser.py": (2, "icônes de la barre de navigation : section Barre de navigation (appli)"),
    "settings_v2_app.py": (2, "aperçus d'icônes de logiciels (images, pas de vrais boutons)"),
    "column_config.py": (2, "flèches ▲ ▼ d'un champ numérique (champ, pas un bouton)"),
}


def _sources():
    for path in ROOT.rglob("*.py"):
        rel = path.relative_to(ROOT)
        if any(part in _SKIP_DIRS or part.startswith(".") for part in rel.parts[:-1]):
            continue
        yield rel.as_posix(), path


class NoOrphanButtonStyleTest(unittest.TestCase):
    def test_button_selectors_only_where_allowed(self):
        found = {}
        for rel, path in _sources():
            count = len(_SELECTOR.findall(path.read_text(encoding="utf-8", errors="replace")))
            if count:
                found[rel] = count
        unexpected = {rel: n for rel, n in found.items() if n != ALLOWED.get(rel, (0, ""))[0]}
        self.assertEqual(unexpected, {}, "style de bouton hors fm_theme (ou ALLOWED à mettre à jour, avec la raison)")


class ThemeButtonTest(unittest.TestCase):
    def test_theme_button_keeps_only_geometry(self):
        from fm_theme.style import is_theme_button, theme_button
        button = QPushButton("+")
        button.setFlat(True)
        button.setStyleSheet("QPushButton { background: red; }")
        theme_button(button, compact=True)
        from fm_theme.style import _themed_button_css
        self.assertEqual(button.styleSheet(), _themed_button_css() + "\nQPushButton { padding: 0px; }")
        self.assertNotIn("red", button.styleSheet())
        self.assertFalse(button.isFlat())
        self.assertTrue(button._fm_theme_button)

        class Sub(QPushButton):
            pass
        sub = theme_button(Sub("Ok"))
        self.assertEqual(sub.styleSheet(), _themed_button_css())
        self.assertTrue(is_theme_button(sub))                            # ombre du thème aussi

    def test_a_container_sheet_never_wins_over_the_theme(self):
        """Vu le 2026-11-12 : un conteneur « background: … » sans sélecteur imposait son fond à ses boutons."""
        from PySide6.QtGui import QColor
        from PySide6.QtWidgets import QHBoxLayout, QWidget
        from fm_theme import style
        saved = style._CONTROL_LOOK
        self.addCleanup(style.set_control_look, saved)
        style._CONTROL_LOOK = {"button_bg_color": "#2050a0", "button_border_enabled": False}
        style.build_stylesheet()
        host = QWidget()
        self.addCleanup(host.deleteLater)
        host.setStyleSheet("background: #ff0000;")
        layout = QHBoxLayout(host)
        button = style.theme_button(QPushButton("   "))
        layout.addWidget(button)
        host.resize(200, 60)
        host.show()
        APP.processEvents()
        center = button.geometry().center()
        self.assertEqual(QColor(host.grab().toImage().pixel(center)).name(), "#2050a0")
        style._CONTROL_LOOK = {"button_bg_color": "#30a040", "button_border_enabled": False}
        style.build_stylesheet()                                         # thème changé : reposé sur le bouton
        APP.processEvents()
        self.assertEqual(QColor(host.grab().toImage().pixel(center)).name(), "#30a040")

    def test_settings_buttons_carry_no_look_of_their_own(self):
        from fm_theme.widgets import _Btn
        from fm_theme.style import _themed_button_css
        button = _Btn("Enregistrer", "#ff0000", "#00ff00", "#0000ff", "#ffffff")
        self.assertEqual(button.styleSheet(), _themed_button_css())
        self.assertTrue(button._fm_theme_button)
        self.assertTrue(_Btn("x", align_left=True).styleSheet().endswith("QPushButton { text-align: left; }"))

    def test_checked_and_disabled_come_from_the_theme(self):
        from fm_theme import style
        sheet = style.build_stylesheet()
        self.assertIn("QPushButton:checked {", sheet)
        self.assertIn("QPushButton:disabled {", sheet)

    def test_text_offset_moves_the_text_not_the_button(self):
        """Demande de l'utilisateur (2026-11-12) : Bouton > Décalage du texte (X, Y) : marge asymétrique, même largeur."""
        from fm_theme import style
        saved = style._CONTROL_LOOK
        self.addCleanup(style.set_control_look, saved)
        self.assertEqual(style.button_padding_css({}), "padding: 0px 12px;")
        look = {"button_text_offset_x": 3, "button_text_offset_y": -2}
        self.assertEqual(style.button_padding_css(look), "padding: 0px 9px 4px 15px;")
        self.assertEqual(style.button_padding_css(look, base_x=0), "padding: 0px 0px 4px 6px;")
        self.assertEqual(style.button_text_offset({"button_text_offset_x": 99}), (10, 0))   # borné à ±10
        style._CONTROL_LOOK = look
        self.assertIn("padding: 0px 9px 4px 15px;", style.build_stylesheet().split("QPushButton {")[1])
        button = style.theme_button(QPushButton("+"), compact=True)
        self.assertTrue(button.styleSheet().endswith("QPushButton { padding: 0px 0px 4px 6px; }"))
        self.assertEqual(style.painted_button_look()["text_offset"], (3, -2))
        style._CONTROL_LOOK = {"button_text_offset_x": -1}
        style.build_stylesheet()                                         # thème changé : marge compacte recalculée
        self.assertTrue(button.styleSheet().endswith("QPushButton { padding: 0px 2px 0px 0px; }"))

    def test_no_theme_shadow_inside_a_widget_that_has_an_effect(self):
        """Qt ne peint pas un effet DANS un effet : les icônes de l'entête des colonnes (carte aux coins arrondis =
        effet graphique) disparaissaient sous l'ombre du thème (signalé 2026-11-12)."""
        import time
        from PySide6.QtWidgets import QGraphicsOpacityEffect, QWidget
        from fm_theme import style
        look = {"standard": ({"on": {"top": False, "right": True, "bottom": True, "left": False},
                              "colors": {s: "#80000000" for s in ("top", "right", "bottom", "left")}, "size": 4},
                             (0, 0))}
        card = QWidget()
        card.setGraphicsEffect(QGraphicsOpacityEffect(card))
        self.addCleanup(card.deleteLater)
        inner = QPushButton("+", card)
        style.apply_button_shadow(inner, look, "ombre")
        self.assertIsNone(inner.graphicsEffect())                 # posé à sa place : pas d'ombre
        free = QPushButton("+")
        self.addCleanup(free.deleteLater)
        style.apply_button_shadow(free, look, "ombre")
        self.assertIsNotNone(free.graphicsEffect())               # hors d'un effet : l'ombre reste
        late = QPushButton("+")                                   # créé AVANT d'être posé dans la carte
        style.apply_button_shadow(late, look, "ombre")
        self.assertIsNotNone(late.graphicsEffect())
        late.setParent(card)
        card.resize(100, 40)
        card.show()
        late.show()
        end = time.monotonic() + 2
        while late.graphicsEffect() is not None and time.monotonic() < end:
            APP.processEvents()
            time.sleep(0.01)
        self.assertIsNone(late.graphicsEffect())                  # retiré après sa première peinture

    def test_painted_buttons_use_the_theme_look(self):
        from fm_theme import style
        saved = style._CONTROL_LOOK
        try:
            style._CONTROL_LOOK = {"button_bg_color": "#112233", "button_font_color": "#445566",
                                   "button_border": dict.fromkeys(("top", "right", "bottom", "left"), "#778899"),
                                   "button_corner_radius": 5, "button_hover_ovr_color": True,
                                   "button_hover_color": "#abcdef"}
            rest = style.painted_button_look()
            self.assertEqual((rest["bg"].name(), rest["fg"].name(), rest["line"].name(), rest["radius"]),
                             ("#112233", "#445566", "#778899", 5))
            self.assertEqual(style.painted_button_look("hover")["bg"].name(), "#abcdef")
        finally:
            style._CONTROL_LOOK = saved


if __name__ == "__main__":
    unittest.main()
