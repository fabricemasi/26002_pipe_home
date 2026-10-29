"""Diapositives de la visionneuse (focus.FocusFilmstrip) : une cellule par vignette, divisee en
sous-cellule image et sous-cellule texte dessous ; Ctrl + tirer la bordure entre les deux change leur
rapport de hauteur (`viewer_film_text_ratio`) ; habillage Reglages > Visionneuse > Tableau / Sous cellule
image / Sous cellule texte ; fenetre de reglages ouverte = ses tableaux reprennent les valeurs changees
ailleurs (`SettingsWindowV2.external_values`)."""
import os as _os, sys as _sys  # jamais les vrais reglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import copy
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

from fm_visionneuse import focus, gallery
import settings_window_v2 as v2
import ui_state
from settings_store import DEFAULT_SETTINGS


def solid(w, h):
    pix = QPixmap(w, h)
    pix.fill(QColor("#c08040"))
    return pix


class FilmCellsTest(unittest.TestCase):
    def setUp(self):
        self.old = ui_state.APPLIED_SETTINGS
        ui_state.APPLIED_SETTINGS = copy.deepcopy(DEFAULT_SETTINGS)
        self.addCleanup(setattr, ui_state, "APPLIED_SETTINGS", self.old)
        self.splits = []
        self.strip = focus.FocusFilmstrip(None, lambda path, side: solid(90, 60),
                                          on_split=lambda r, final: (self.splits.append((r, final)),
                                                                     ui_state.APPLIED_SETTINGS.update(
                                                                         viewer_film_text_ratio=r)))
        self.addCleanup(self.strip.deleteLater)
        self.strip.resize(900, self.strip.strip_height())
        self.strip.set_paths([Path(f"C:/x/image_{i:02d}.png") for i in range(12)], 5)
        self.strip.show()
        self.strip.reveal()
        self.strip._alpha = 1.0

    def centre_cell(self):
        return next(rect for i, rect in self.strip._cells() if i == 5)

    def test_text_sub_cell_is_under_the_image_with_the_ratio(self):
        ui_state.APPLIED_SETTINGS["viewer_film_text_ratio"] = 0.5
        image, text = self.strip._split(self.centre_cell())
        self.assertAlmostEqual(text.top(), image.bottom(), places=3)
        self.assertAlmostEqual(text.height() / image.height(), 0.5, places=3)
        short = self.strip.strip_height()
        ui_state.APPLIED_SETTINGS["viewer_film_text_ratio"] = 1.0
        self.assertGreater(self.strip.strip_height(), short)      # la bande suit la hauteur des cellules

    def test_ctrl_drag_of_the_border_changes_the_ratio(self):
        cell = self.centre_cell()
        line = self.strip._split(cell)[1].top()
        start = QPoint(round(cell.center().x()), round(line))
        self.assertIsNotNone(self.strip._split_at(QPointF(start)))
        QTest.mousePress(self.strip, Qt.LeftButton, Qt.ControlModifier, start)
        self.assertIsNotNone(self.strip._split_drag)
        QTest.mouseMove(self.strip, start - QPoint(0, 10))
        QTest.mouseRelease(self.strip, Qt.LeftButton, Qt.ControlModifier, start - QPoint(0, 10))
        self.assertTrue(self.splits and self.splits[-1][1], self.splits)   # fin du geste signalee
        self.assertGreater(self.splits[0][0], DEFAULT_SETTINGS["viewer_film_text_ratio"])

    def test_plain_click_on_the_border_still_chooses_the_file(self):
        chosen = []
        self.strip.chosen.connect(chosen.append)
        cell = self.centre_cell()
        QTest.mouseClick(self.strip, Qt.LeftButton, Qt.NoModifier,
                         QPoint(round(cell.center().x()), round(self.strip._split(cell)[1].top())))
        self.assertEqual(chosen, [5])
        self.assertIsNone(self.strip._split_drag)

    def test_paints_with_every_part_styled(self):
        applied = ui_state.APPLIED_SETTINGS
        for part in ("table", "image_cell", "image", "text_cell"):
            applied[f"viewer_film_{part}_border_enabled"] = True
            applied[f"viewer_film_{part}_border_thickness"] = 2
            applied[f"viewer_film_{part}_border_radius"] = 6
        applied["viewer_film_text_cell_bg"] = "#ff204060"
        applied["viewer_film_text_cell_font_size"] = 15
        self.assertFalse(self.strip.grab().isNull())

    def test_context_menu_goes_to_the_callback(self):
        asked = []
        self.strip._on_menu = asked.append
        self.strip.contextMenuEvent(type("E", (), {"globalPos": lambda s: QPoint(3, 4),
                                                   "accept": lambda s: None})())
        self.assertEqual(asked, [QPoint(3, 4)])


class GalleryCellsTest(unittest.TestCase):
    """La planche : memes reglages (sous-cellule texte sous l'image) ; Ctrl + bordure = hauteur du texte."""

    def setUp(self):
        import tempfile
        self.old = ui_state.APPLIED_SETTINGS
        ui_state.APPLIED_SETTINGS = copy.deepcopy(DEFAULT_SETTINGS)
        self.addCleanup(setattr, ui_state, "APPLIED_SETTINGS", self.old)
        # Case DIVISEE (image | texte) : coupee dans la planche (focus.FocusGallery.SPLIT_CELLS), gardee ici.
        self.addCleanup(setattr, focus.FocusGallery, "SPLIT_CELLS", focus.FocusGallery.SPLIT_CELLS)
        focus.FocusGallery.SPLIT_CELLS = True
        # L'ancien padding de cellule (Reglages > Tableaux) n'existe plus dans la planche ; ces tests de la case
        # divisee en ont besoin.
        patcher = mock.patch.object(gallery, "_gallery_look", lambda: {"padding": {k: 8 for k in
                                                                                 ("left", "top", "right", "bottom")}})
        patcher.start()
        self.addCleanup(patcher.stop)
        focus._CELLS.clear()
        folder = Path(tempfile.mkdtemp())
        paths = []
        for i in range(4):
            path = folder / f"i{i}.png"
            solid(40, 30).save(str(path))
            paths.append(path)
        self.heights, self.menus = [], []

        def on_split(height, final):
            self.heights.append((height, final))
            ui_state.APPLIED_SETTINGS["viewer_gallery_text_height"] = height
            self.gallery.restyle()

        self.gallery = focus.FocusGallery(None, paths, str(paths[0]), on_split=on_split, on_menu=self.menus.append)
        self.addCleanup(self.gallery.deleteLater)
        self.gallery.resize(800, 600)
        self.gallery.show()
        self.gallery.reveal_current()

    def test_ctrl_drag_sets_the_text_height(self):
        gallery = self.gallery
        cell, box = gallery.tile_boxes(gallery.visualItemRect(gallery.item(0)))
        start = gallery.label_height()
        line = QPoint(cell.center().x(), box.bottom() + 1)
        QTest.mousePress(gallery.viewport(), Qt.LeftButton, Qt.ControlModifier, line)
        QTest.mouseMove(gallery.viewport(), line - QPoint(0, 25))
        QTest.mouseRelease(gallery.viewport(), Qt.LeftButton, Qt.ControlModifier, line - QPoint(0, 25))
        self.assertTrue(self.heights and self.heights[-1][1])
        self.assertGreater(gallery.label_height(), start)

    def test_image_override_border_paints_without_crashing(self):
        import settings_element_style as styles
        from interface_edit_targets import PaintedTarget
        from PySide6.QtCore import QRect
        gallery = self.gallery
        path = str(gallery.item(0).data(Qt.UserRole))
        old = getattr(ui_state, "GALLERY_STYLE_OVERRIDES", None)
        self.addCleanup(setattr, ui_state, "GALLERY_STYLE_OVERRIDES", old)
        ui_state.GALLERY_STYLE_OVERRIDES = {}
        widget = PaintedTarget(gallery, path, "gallery-image", QRect(0, 0, 50, 50))
        target = styles.GalleryStyleTarget(widget, path, "image")
        values = target.general(ui_state.APPLIED_SETTINGS)
        values.update({"viewer_film_image_border_enabled": {
                           "top": True, "right": True, "bottom": False, "left": False},
                       "viewer_film_image_border": {
                           "top": "#ffff0000", "right": "#ff00ff00",
                           "bottom": "#ff0000ff", "left": "#ff000000"},
                       "viewer_film_image_border_thickness": 3,
                       "viewer_film_image_border_radius": {corner: 4 for corner in
                                                           ("top_left", "top_right", "bottom_right", "bottom_left")}})
        target.apply(values)
        look = gallery.film_look_for(path)["image"]
        self.assertEqual(look["thick"], 3)
        self.assertEqual(look["colors"]["top"], "#ffff0000")
        # Meme trajet que la fenetre d'override ouverte pendant le mode edition.
        with mock.patch.object(styles, "load_settings", return_value=copy.deepcopy(ui_state.APPLIED_SETTINGS)), \
             mock.patch.object(styles, "save_settings"):
            window = styles.open_override(target, parent=gallery)
            edited = window.style()
            edited.update({key: values[key] for key in (
                "viewer_film_image_border_enabled", "viewer_film_image_border",
                "viewer_film_image_border_thickness", "viewer_film_image_border_radius")})
            window.styleChanged.emit(edited)
            window.close()
        image = gallery.viewport().grab().toImage()
        self.assertFalse(image.isNull())

    def test_cell_override_background_padding_and_border(self):
        import settings_element_style as styles
        from interface_edit_targets import PaintedTarget
        from PySide6.QtCore import QRect
        gallery = self.gallery
        path = str(gallery.item(0).data(Qt.UserRole))
        old = getattr(ui_state, "GALLERY_STYLE_OVERRIDES", None)
        self.addCleanup(setattr, ui_state, "GALLERY_STYLE_OVERRIDES", old)
        ui_state.GALLERY_STYLE_OVERRIDES = {}
        widget = PaintedTarget(gallery, path, "gallery-cell", QRect(0, 0, 80, 80))
        target = styles.GalleryStyleTarget(widget, path, "cell")
        values = target.general(ui_state.APPLIED_SETTINGS)
        values.update({"gallery_cell_bg": "#ff203040",
                       "gallery_cell_padding": {side: 5 for side in ("left", "top", "right", "bottom")},
                       "gallery_cell_border_enabled": {side: True for side in
                                                       ("top", "right", "bottom", "left")},
                       "gallery_cell_border": {side: "#ffff0000" for side in
                                               ("top", "right", "bottom", "left")},
                       "gallery_cell_border_thickness": 2})
        target.apply(values)
        look = gallery.film_look_for(path)
        self.assertEqual(look["cell"]["fill"], "#ff203040")
        rect = gallery.visualItemRect(gallery.item(0))
        outer, inner, _image = gallery.edited_cell_boxes(rect, look)
        self.assertEqual(inner.left() - outer.left(), 7)
        self.assertFalse(gallery.viewport().grab().toImage().isNull())

    def test_text_style_changes_the_cells(self):
        before = self.gallery.viewport().grab().toImage()
        ui_state.APPLIED_SETTINGS["viewer_film_text_cell_bg"] = "#ffaa2020"
        self.gallery.restyle()
        self.assertNotEqual(before, self.gallery.viewport().grab().toImage())

    def _focus_shot(self, **values):
        """Case en cours peinte en rouge opaque, avec ces reglages : (case, sous-cellules, image, test rouge)."""
        settings = ui_state.APPLIED_SETTINGS
        settings.update({"viewer_film_table_focus_color": "#ffff0000",
                         "table_cell_padding": {"left": 8, "top": 8, "right": 8, "bottom": 8},
                         "viewer_film_image_cell_border_radius": {"top_left": 12, "top_right": 12,
                                                                  "bottom_right": 0, "bottom_left": 0},
                         "viewer_film_text_cell_border_radius": {"top_left": 0, "top_right": 0,
                                                                 "bottom_right": 12, "bottom_left": 12},
                         "viewer_film_table_border_radius": {"top_left": 6, "top_right": 6,
                                                             "bottom_right": 6, "bottom_left": 6}})
        settings.update(values)
        gallery = self.gallery
        gallery._look = focus._gallery_look()
        gallery.restyle()
        rect = gallery.visualItemRect(gallery.item(0))
        cell, box = gallery.tile_boxes(rect)
        self.assertGreater(cell.left(), rect.left())          # le padding de la cellule existe
        image = gallery.viewport().grab().toImage()
        dpr = image.devicePixelRatio() or 1.0

        def red(x, y):
            color = image.pixelColor(round(x * dpr), round(y * dpr))
            return color.red() > 200 and color.green() < 60 and color.blue() < 60
        return rect, cell, box, red

    def _covers_sub_cells(self, cell, box, rect, red):
        self.assertTrue(red(cell.left() + 2, (box.bottom() + cell.bottom()) // 2))   # sous-cellule texte
        self.assertTrue(red(cell.center().x(), cell.top() + 1))                       # haut de l'image
        self.assertFalse(red(rect.left() + 2, cell.center().y()))                     # padding : non
        self.assertFalse(red(cell.left() + 1, cell.top() + 1))                        # coin haut arrondi (image)
        self.assertFalse(red(cell.right() - 1, cell.bottom() - 1))                    # coin bas arrondi (texte)

    def test_focus_covers_the_sub_cells_when_both_backgrounds_show(self):
        rect, cell, box, red = self._focus_shot(viewer_film_image_cell_bg="#ff202020",
                                                viewer_film_text_cell_bg="#ff202020")
        self._covers_sub_cells(cell, box, rect, red)                 # par-dessus leurs fonds opaques

    def test_focus_covers_the_cell_when_a_sub_cell_background_is_hidden(self):
        rect, cell, box, red = self._focus_shot(viewer_film_image_cell_bg="#ff202020",
                                                viewer_film_text_cell_bg="#00000000")
        self.assertTrue(red(rect.left() + 2, cell.center().y()))     # padding compris
        self.assertTrue(red(cell.left() + 1, cell.bottom() + 4))     # sous la sous-cellule texte
        self.assertFalse(red(rect.left(), rect.top()))               # border radius du tableau (6 px)...
        self.assertTrue(red(rect.right() - 1, rect.top()))           # ... au seul coin partage avec le tableau
        self.assertTrue(red(rect.left(), rect.bottom() - 1))
        self.assertTrue(red(rect.right() - 1, rect.bottom() - 1))
        gallery = self.gallery
        self.assertEqual((gallery._cols, gallery._rows), (2, 2))
        self.assertEqual([set(gallery.table_corners(i)) for i in range(4)],
                         [{"top_left"}, {"top_right"}, {"bottom_left"}, {"bottom_right"}])
        gallery._rows = 3                                            # derniere ligne incomplete (5 cases sur 6)
        self.assertEqual(gallery.table_corners(3), frozenset())
        self.assertEqual(gallery.table_corners(4), frozenset({"bottom_left"}))

    def test_focus_covers_the_sub_cells_on_a_bare_square_table(self):
        rect, cell, box, red = self._focus_shot(viewer_film_table_bg="#00000000",
                                                viewer_film_table_border_radius=0)
        self._covers_sub_cells(cell, box, rect, red)

    def test_focus_covers_the_sub_cells_when_the_table_shows_nothing(self):
        # Fond a 0, bordures coupees : le border radius du tableau ne se voit pas, il compte comme absent.
        rect, cell, box, red = self._focus_shot(
            viewer_film_table_bg="#00ffffff",
            viewer_film_table_border_enabled={"top": False, "right": False, "bottom": False, "left": False},
            viewer_film_table_border_radius={"top_left": 10, "top_right": 10, "bottom_right": 10, "bottom_left": 10})
        self._covers_sub_cells(cell, box, rect, red)

    def _inner_lines_shot(self, **values):
        """Pixels sur la frontiere entre deux lignes et entre deux colonnes : rouges ?"""
        settings = ui_state.APPLIED_SETTINGS
        settings.update({"viewer_film_table_bg": "#00000000", "viewer_film_table_focus_color": "#00000000",
                         "viewer_film_table_hover_color": "#00000000"})
        settings.update(values)
        gallery = self.gallery
        gallery.restyle()
        below = gallery.visualItemRect(gallery.item(gallery._cols))      # 1re case de la 2e ligne
        right = gallery.visualItemRect(gallery.item(1))
        image = gallery.viewport().grab().toImage()
        dpr = image.devicePixelRatio() or 1.0
        out = []
        for x, y in ((below.left() + 2, below.top()), (right.left(), right.top() + 2)):
            color = image.pixelColor(round(x * dpr), round(y * dpr))
            out.append(color.red() > 200 and color.green() < 60)
        return out

    def test_no_inner_lines_from_the_settings_tables(self):
        self.assertEqual(self._inner_lines_shot(
            table_inner_h_enabled=True, table_inner_h_color="#ffff0000", table_inner_h_thickness=3,
            table_inner_v_enabled=True, table_inner_v_color="#ffff0000", table_inner_v_thickness=3), [False, False])

    def test_inner_lines_from_the_viewer_table(self):
        lines = dict(viewer_film_table_inner_h_color="#ffff0000", viewer_film_table_inner_h_thickness=3,
                     viewer_film_table_inner_v_color="#ffff0000", viewer_film_table_inner_v_thickness=3)
        self.assertEqual(self._inner_lines_shot(**lines), [False, False])            # coupees par defaut
        self.assertEqual(self._inner_lines_shot(viewer_film_table_inner_h_enabled=True, **lines), [True, False])
        self.assertEqual(self._inner_lines_shot(viewer_film_table_inner_v_enabled=True, **lines), [True, True])

    def test_inner_border_rows_in_the_viewer_table(self):
        specs = {sp.key: sp for sp in v2.CATALOG["Visionneuse : Tableau"]}
        for axis in ("h", "v"):
            spec = specs[f"viewer_film_table_inner_{axis}_enabled"]
            self.assertEqual((spec.label, spec.kind), (f"Bordure intérieure {axis.upper()}", "inner_line"))
            reader = v2.FIELD_READERS["inner_line"]
            field = v2._f_inner_line(spec, type("V", (), {"seed": lambda s, k, d: ui_state.APPLIED_SETTINGS.get(k, d)})(), {})
            self.assertEqual(set(reader(spec, field)), {f"viewer_film_table_inner_{axis}_{k}"
                                                        for k in ("enabled", "color", "thickness")})

    def test_hover_has_its_own_color(self):
        ui_state.APPLIED_SETTINGS["viewer_film_table_hover_color"] = "#ff00ff00"
        self.gallery.restyle()
        self.assertEqual(self.gallery.film_look["hover"], QColor("#ff00ff00"))

    def test_context_menu_goes_to_the_callback(self):
        self.gallery.contextMenuEvent(type("E", (), {"globalPos": lambda s: QPoint(5, 6),
                                                     "accept": lambda s: None})())
        self.assertEqual(self.menus, [QPoint(5, 6)])


class FocusFrameTest(unittest.TestCase):
    """Image en focus : bordures et border radius de Reglages > Visionneuse > Focus."""

    def setUp(self):
        self.old = ui_state.APPLIED_SETTINGS
        ui_state.APPLIED_SETTINGS = copy.deepcopy(DEFAULT_SETTINGS)
        self.addCleanup(setattr, ui_state, "APPLIED_SETTINGS", self.old)

    def shot(self, dpr=1.0):
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QImage
        from PySide6.QtWidgets import QWidget
        parent = QWidget()
        self.addCleanup(parent.deleteLater)
        parent.resize(800, 500)
        parent.setStyleSheet("background: #202020")
        parent.show()
        image = QImage(1200, 800, QImage.Format_RGB32)
        image.fill(QColor("#3070c0"))
        image.setDevicePixelRatio(dpr)
        pix = QPixmap.fromImage(image)
        target = focus.FocusOverlay.target_rect(pix, parent.rect())
        overlay = focus.FocusOverlay(parent, pix, target, target, 1.0, 1.0, duration_ms=10)
        overlay.finish_now()
        overlay.show()
        return overlay, target.toRect(), parent

    def test_radius_and_border_on_the_focused_image(self):
        overlay, rect, parent = self.shot()
        image = parent.grab().toImage()
        self.assertEqual(image.pixelColor(rect.left() + 2, rect.top() + 2).name(), "#3070c0")   # rien par defaut
        settings = ui_state.APPLIED_SETTINGS
        settings["viewer_focus_image_border_radius"] = 40
        settings["viewer_focus_image_border_enabled"] = {k: True for k in ("top", "right", "bottom", "left")}
        settings["viewer_focus_image_border"] = {k: "#ffcc00" for k in ("top", "right", "bottom", "left")}
        settings["viewer_focus_image_border_thickness"] = 4
        for dpr in (1.0, 1.5):
            overlay, rect, parent = self.shot(dpr)
            image = parent.grab().toImage()
            self.assertEqual(image.pixelColor(rect.left() + 2, rect.top() + 2).name(), "#202020")   # coin arrondi
            self.assertEqual(image.pixelColor(rect.left() + 1, rect.center().y()).name(), "#ffcc00")  # bordure
            self.assertEqual(image.pixelColor(rect.center()).name(), "#3070c0")                      # image entiere

    def test_restyle_follows_the_settings(self):
        overlay, rect, parent = self.shot()
        ui_state.APPLIED_SETTINGS["viewer_focus_image_border_radius"] = 40
        overlay.restyle()
        overlay.repaint()
        image = parent.grab().toImage()
        self.assertEqual(image.pixelColor(rect.left() + 2, rect.top() + 2).name(), "#202020")


class FilmSettingsTest(unittest.TestCase):
    def test_visionneuse_hides_text_cell_settings(self):
        node = next(n for n in v2.GENERAL_TREE if n.title == "Visionneuse")
        self.assertEqual(node.group, "Visionneuse")
        self.assertEqual([c.title for c in node.children],
                         ["Tableau", "Cellules", "Focus", "Filtres", "Icônes"])
        self.assertNotIn("Visionneuse : Cellule texte", [group for _title, group in v2.VIEWER_FILM_GROUPS])
        self.assertEqual([sp.label for sp in v2.CATALOG["Visionneuse : Focus"]],
                         ["Bordures de l'image", "Border radius de l'image", "Ombres de l'image"])
        labels = [sp.label for sp in v2.CATALOG["Visionneuse : Cellule image"]]
        self.assertIn("Bordures de l'image", labels)
        self.assertIn("Border radius de l'image", labels)

    def test_app_font_role_is_resolved(self):
        # Choix « app » = un role de Polices principales : traduit en vraie famille (bug signale).
        import app_style
        old = ui_state.APPLIED_SETTINGS
        self.addCleanup(setattr, ui_state, "APPLIED_SETTINGS", old)
        saved = dict(app_style._ROLE_OVERRIDES)
        self.addCleanup(lambda: (app_style._ROLE_OVERRIDES.clear(), app_style._ROLE_OVERRIDES.update(saved)))
        app_style.set_role_font("code", "Courier New", 12, False)
        ui_state.APPLIED_SETTINGS = {**copy.deepcopy(DEFAULT_SETTINGS),
                                     "viewer_film_text_cell_font_family": app_style.ITEM_FONT_ROLE_LABELS["code"],
                                     "viewer_film_table_font_family": "Systeme"}
        look = focus._film_look()
        self.assertEqual(look["name_font"][0].family(), app_style.role_font("code", 11).family())
        self.assertNotEqual(look["name_font"][0].family(), app_style.ITEM_FONT_ROLE_LABELS["code"])
        self.assertNotEqual(look["rank_font"][0].family(), "Systeme")

    def test_scroll_toggle_is_type_1(self):
        from settings_cells import normalize_toggles
        from PySide6.QtWidgets import QWidget
        spec = next(sp for sp in v2.CATALOG["Visionneuse"] if sp.key == "viewer_scroll_animated")
        self.assertEqual(spec.label, "Scrolling animé")
        holder = QWidget()
        self.addCleanup(holder.deleteLater)
        toggle = v2._f_bool(spec, type("V", (), {"seed": lambda s, k, d: d})(), {})
        toggle.setParent(holder)
        normalize_toggles(holder)
        self.assertEqual(toggle._base_override, "toggle1")
        other = v2._f_bool(v2.CATALOG["Visionneuse"][0], type("V", (), {"seed": lambda s, k, d: d})(), {})
        other.setParent(holder)
        normalize_toggles(holder)
        self.assertEqual(other._base_override, "toggle2")             # les autres restent de type 2

    def test_quick_style_values_also_go_to_the_default_preset(self):
        # Le preset par defaut est rejoue PAR-DESSUS le fichier a chaque lancement : sans lui, les valeurs
        # a la volee (sous-cellules image / texte...) etaient perdues.
        from browser_core_parts import settings as core_settings
        import pipeline_browser as pb
        saved, presets = {}, {"fab": {"viewer_film_image_cell_bg": "#00000000"}}
        fake = type("W", (), {})()
        fake._film_style_pending = {"viewer_film_image_cell_bg": "#ff112233"}
        with mock.patch("main_window.viewer_chrome.load_settings", lambda: {"default_preset": "fab"}),                 mock.patch("main_window.viewer_chrome.save_settings", saved.update),                 mock.patch.object(core_settings, "_load_presets", lambda: presets),                 mock.patch.object(core_settings, "_save_presets", lambda p: None):
            pb.PipelineBrowser._flush_filmstrip_style(fake)
        self.assertEqual(saved["viewer_film_image_cell_bg"], "#ff112233")
        self.assertEqual(presets["fab"]["viewer_film_image_cell_bg"], "#ff112233")

    def test_every_key_has_a_default(self):
        for _title, group in (*v2.VIEWER_FILM_GROUPS, ("Focus", "Visionneuse : Focus")):
            for spec in v2.CATALOG[group]:
                for key in (spec.key, *spec.extra_keys):
                    self.assertIn(key, DEFAULT_SETTINGS, key)

    def test_open_window_takes_values_changed_elsewhere(self):
        settings = copy.deepcopy(DEFAULT_SETTINGS)
        with mock.patch.object(v2, "load_settings", lambda: copy.deepcopy(settings)):
            win = v2.SettingsWindowV2()
        self.addCleanup(win.deleteLater)
        page = win.stack.currentWidget()
        for title in ("Visionneuse", "Cellules"):     # les enfants naissent au depliage du parent
            for node in page.findChildren(v2._LazyNode):
                if node.node.title == title:
                    node.set_collapsed(False)
        self.assertEqual(win.wired_values()["viewer_film_image_cell_font_size"], 11)
        win.external_values({"viewer_film_image_cell_font_size": 17, "viewer_film_text_ratio": 0.6})
        values = win.wired_values()
        self.assertEqual(values["viewer_film_image_cell_font_size"], 17)
        self.assertEqual(win.settings["viewer_film_text_ratio"], 0.6)
        self.assertEqual(win._original_settings["viewer_film_image_cell_font_size"], 17)


if __name__ == "__main__":
    unittest.main()
