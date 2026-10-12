"""Ombres (lignes « Ombres » : lier les 4 | G | H | B | D | Taille) : moteur (settings_widgets.paint_shadow,
modele en 9 morceaux), lignes dans les sections a images et Tableaux, sous-couche des widgets
(ShadowUnderlay), images de la visionneuse. Jamais les reglages reels."""
import os as _os, sys as _sys  # jamais les vrais reglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import copy
import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QRect, QRectF, QSizeF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QWidget

APP = QApplication.instance() or QApplication([])

import settings_widgets as sw
import ui_state
from settings_store import DEFAULT_SETTINGS, SHADOW_PREFIXES


def canvas(w=300, h=240):
    image = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)
    return image


def alpha(image, x, y):
    return image.pixelColor(x, y).alpha()


def look(sides=("top", "right", "bottom", "left"), size=16, color="#ff000000"):
    values = {"s_enabled": {k: k in sides for k in ("top", "right", "bottom", "left")},
              "s": {k: color for k in ("top", "right", "bottom", "left")}, "s_size": size}
    return sw.shadow_look(values, "s")


class EngineTest(unittest.TestCase):
    def paint(self, rect, radius, shadow, image=None):
        image = image or canvas()
        painter = QPainter(image)
        sw.paint_shadow(painter, rect, radius, shadow)
        painter.end()
        return image

    def test_nothing_without_sides_or_size(self):
        self.assertIsNone(look(sides=()))
        self.assertIsNone(look(size=0))

    def test_soft_outside_empty_inside(self):
        image = self.paint(QRect(60, 60, 160, 100), 8, look())
        self.assertEqual(alpha(image, 140, 110), 0)                       # sous la forme : rien
        near, mid, far = alpha(image, 140, 162), alpha(image, 140, 168), alpha(image, 140, 180)
        self.assertGreater(near, mid)                                     # degrade...
        self.assertGreater(mid, far)
        self.assertEqual(far, 0)                                          # ... jusqu'a la taille
        self.assertGreater(alpha(image, 140, 56), 0)                      # tous les cotes
        self.assertGreater(alpha(image, 56, 110), 0)

    def test_one_side_only(self):
        for radius in (0, 10):
            image = self.paint(QRect(60, 60, 160, 100), radius, look(sides=("bottom",)))
            self.assertGreater(alpha(image, 140, 163), 0)
            self.assertEqual(alpha(image, 140, 57), 0)                    # pas en haut
            for y in range(60, 175):                                      # RIEN a gauche ni a droite,
                self.assertEqual(alpha(image, 57, y), 0, (radius, y))     # meme pres du coin du bas
                self.assertEqual(alpha(image, 222, y), 0, (radius, y))

    def test_shadow_fades_towards_a_side_without_shadow(self):
        for sides in (("bottom",), ("bottom", "right")):
            image = self.paint(QRectF(40, 40, 240, 160), 6, look(sides=sides, size=30))
            y = 212                                                       # dans l'ombre du bas
            end, mid = alpha(image, 42, y), alpha(image, 160, y)
            self.assertGreater(mid, 0, sides)
            self.assertLess(end, mid * 0.2, sides)                        # quasi rien au bout gauche...
            self.assertLess(alpha(image, 50, y), alpha(image, 62, y))     # ... puis ca monte doucement
            self.assertLess(alpha(image, 62, y), mid)

    def test_two_neighbour_sides_fill_their_corner(self):
        image = self.paint(QRect(60, 60, 160, 100), 0, look(sides=("bottom", "right")))
        self.assertGreater(alpha(image, 222, 162), 0)                     # coin bas droit rempli
        self.assertEqual(alpha(image, 57, 162), 0)                        # coin bas gauche : rien

    def test_nine_slices_match_a_direct_render(self):
        # Grande forme (9 morceaux d'un modele) = meme profil qu'une petite rendue a sa taille exacte.
        big = self.paint(QRect(40, 40, 200, 150), 6, look())
        small = canvas()
        painter = QPainter(small)
        sw.paint_shadow(painter, QRect(40, 40, 18, 18), 6, look())        # trop petite : rendu direct
        painter.end()
        self.assertAlmostEqual(alpha(big, 140, 195), alpha(small, 49, 63), delta=3)

    def test_any_size_costs_no_new_render(self):
        sw._SHADOW_CACHE.clear()
        for w in (300, 600, 1200, 2400):
            image = canvas(10, 10)
            painter = QPainter(image)
            sw.paint_shadow(painter, QRectF(10, 10, w, w * 0.6), 12, look())
            painter.end()
        self.assertEqual(len(sw._SHADOW_CACHE), 1)                        # un seul modele

    def test_strength_fades(self):
        full = self.paint(QRect(60, 60, 160, 100), 0, look())
        image = canvas()
        painter = QPainter(image)
        sw.paint_shadow(painter, QRect(60, 60, 160, 100), 0, look(), strength=0.5)
        painter.end()
        self.assertLess(alpha(image, 140, 162), alpha(full, 140, 162))


class RowsTest(unittest.TestCase):
    def test_rows_in_image_sections_and_tables(self):
        import settings_window_v2 as v2
        expected = {"G Apercu": "item_image_shadow_enabled", "Image": "item_image_shadow_enabled",
                    "Focus : Image": "preview_shadow_enabled", "Tableaux": "table_shadow_enabled",
                    "Visionneuse : Tableau": "viewer_film_table_shadow_enabled",
                    "Visionneuse : Cellule image": "viewer_film_image_shadow_enabled",
                    "Visionneuse : Focus": "viewer_focus_image_shadow_enabled",
                    "Menu contextuel : Menu": "ctx_menu_shadow_enabled"}
        for group, key in expected.items():
            spec = next(sp for sp in v2.CATALOG[group] if sp.key == key)
            self.assertEqual(spec.kind, "shadow", group)
            self.assertTrue(spec.label.startswith("Ombres"), group)
            self.assertEqual(spec.params["thickness_label"], "Taille")
            for k in (spec.key, *spec.extra_keys, f"{spec.key}_linked"):
                self.assertIn(k, DEFAULT_SETTINGS, k)
        for prefix in SHADOW_PREFIXES:
            if prefix in ("ctx_menu_shadow", "extra_window_shadow"):
                # Menus, fenetres additionnelles : leur ombre remplace celle de Windows -> allumee par defaut.
                self.assertIsNotNone(sw.shadow_look(DEFAULT_SETTINGS, prefix))
                continue
            self.assertIsNone(sw.shadow_look(DEFAULT_SETTINGS, prefix))   # coupees par defaut

    def test_field_reads_back_the_shadow_keys(self):
        import settings_window_v2 as v2
        spec = next(sp for sp in v2.CATALOG["Tableaux"] if sp.key == "table_shadow_enabled")
        values = copy.deepcopy(DEFAULT_SETTINGS)
        values["table_shadow_size"] = 23
        scope = v2.ScopeValues(values, None)
        field = v2.make_field(spec, scope, values["colors"], None)
        read = v2.read_spec(spec, field)
        self.assertEqual(read["table_shadow_size"], 23)
        self.assertIn("table_shadow", read)
        self.assertIn("table_shadow_enabled_linked", read)

    def test_one_toggle_per_side_then_one_color_then_size(self):
        import settings_window_v2 as v2
        from settings_cells import SplitCell
        spec = next(sp for sp in v2.CATALOG["Tableaux"] if sp.key == "table_shadow_enabled")
        values = copy.deepcopy(DEFAULT_SETTINGS)
        scope = v2.ScopeValues(values, None)
        field = v2.make_field(spec, scope, values["colors"], None)
        split = field if isinstance(field, SplitCell) else field.findChild(SplitCell)
        captions = [caption for caption, _widgets in split._parts] if hasattr(split, "_parts") else None
        if captions is not None:
            self.assertEqual(captions[1:], ["G", "H", "B", "D", "Couleur", "Taille"])
        color = field._v2_parts["color"]
        color.setValue("#ff112233")
        color.changed.emit("#ff112233")
        read = v2.read_spec(spec, field)
        self.assertEqual(set(read["table_shadow"].values()), {"#ff112233"})   # une couleur pour les 4


class UnderlayTest(unittest.TestCase):
    def test_follows_the_widget_and_paints_around_it(self):
        parent = QWidget()
        self.addCleanup(parent.deleteLater)
        parent.resize(300, 240)
        child = QWidget(parent)
        child.setGeometry(80, 70, 120, 80)
        state = {"look": look(size=12)}
        parent.show()
        underlay = sw.attach_shadow(child, lambda: state["look"], lambda: 4)
        APP.processEvents()
        self.assertTrue(underlay.isVisible())
        self.assertEqual(underlay.geometry(), QRect(68, 58, 144, 104))
        child.move(100, 90)
        APP.processEvents()
        APP.processEvents()
        self.assertEqual(underlay.geometry(), child.geometry().adjusted(-12, -12, 12, 12))
        image = parent.grab().toImage()
        self.assertNotEqual(image.pixelColor(child.geometry().center().x(), child.geometry().bottom() + 4),
                            image.pixelColor(5, 5))                        # ombre sous le widget
        state["look"] = None
        sw.ShadowUnderlay.refresh_all()
        self.assertFalse(underlay.isVisible())
        self.assertIs(sw.attach_shadow(child, lambda: None, lambda: 0), underlay)   # une seule


class ViewerTest(unittest.TestCase):
    def setUp(self):
        self.old = ui_state.APPLIED_SETTINGS
        ui_state.APPLIED_SETTINGS = copy.deepcopy(DEFAULT_SETTINGS)
        self.addCleanup(setattr, ui_state, "APPLIED_SETTINGS", self.old)

    def test_focus_image_shadow_and_hit_area(self):
        import focus
        s = ui_state.APPLIED_SETTINGS
        s["viewer_focus_image_shadow_enabled"] = {k: True for k in ("top", "right", "bottom", "left")}
        s["viewer_focus_image_shadow"] = {k: "#ffff0000" for k in ("top", "right", "bottom", "left")}
        s["viewer_focus_image_shadow_size"] = 20
        parent = QWidget()
        self.addCleanup(parent.deleteLater)
        parent.resize(800, 500)
        parent.setStyleSheet("background: #202020")
        parent.show()
        pix = QPixmap(600, 400)
        pix.fill(QColor("#3070c0"))
        target = focus.FocusOverlay.target_rect(pix, parent.rect())
        overlay = focus.FocusOverlay(parent, pix, target, target, 1.0, 1.0, duration_ms=10,
                                     on_double_click=lambda: None)
        overlay.finish_now()
        overlay.show()
        image = parent.grab().toImage()
        rect = target.toRect()
        below = image.pixelColor(rect.center().x(), rect.bottom() + 5)
        self.assertGreater(below.red(), 0x40)                             # ombre rouge sous l'image
        self.assertEqual(image.pixelColor(rect.center()).name(), "#3070c0")
        from PySide6.QtCore import QPoint
        self.assertTrue(overlay.mask().contains(QPoint(rect.center().x(), rect.bottom() + 5)))   # masque : ombre comprise

    def test_film_look_has_the_shadows(self):
        import focus
        s = ui_state.APPLIED_SETTINGS
        s["viewer_film_image_shadow_enabled"] = {"top": False, "right": False, "bottom": True, "left": False}
        look_ = focus._film_look()
        self.assertIsNotNone(look_["image_shadow"])
        self.assertIsNone(look_["table_shadow"])
        self.assertIsNone(look_["focus_shadow"])


if __name__ == "__main__":
    unittest.main()
