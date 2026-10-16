import _isolate  # noqa: F401 -- aucune écriture dans les réglages réels
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import unittest
import copy
from unittest.mock import ANY, patch
from PySide6.QtCore import QPoint, QRect, Qt, QEvent
from PySide6.QtGui import QImage, QKeyEvent, QPainter, QFont
from PySide6.QtWidgets import QStyleOptionViewItem
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget, QLabel, QListWidget, QListWidgetItem, QPushButton, QHBoxLayout, QLineEdit
from pipeline_browser import _InterfaceMoveFrame, _InterfaceMoveMode, Column, ROLE_PATH
from browser_core import ROLE_MEDIA_COUNTS
from interface_edit_targets import PaintedTarget
import settings_cells

app = QApplication.instance() or QApplication([])


class ColumnFixture(Column):
    """Colonne sans scan disque, avec la géométrie partagée par le délégué."""
    def __init__(self, parent):
        QWidget.__init__(self, parent)
        self.style_title = "Type"
        self.list = QListWidget(self)
        self.list.setGeometry(0, 35, 240, 220)
        item = QListWidgetItem("exemple")
        item.setData(ROLE_PATH, "exemple")
        self.list.addItem(item)
        self.list._edit_geometry = {"exemple": {
            "row": QRect(0, 0, 238, 28), "text": QRect(15, 4, 65, 20)}}


class EditScopeTest(unittest.TestCase):
    def setUp(self):
        self.main = QWidget()
        self.main.resize(700, 500)
        self.main.show()
        self.patch = patch("pipeline_browser.load_settings", return_value={})
        self.patch.start()
        self.mode = _InterfaceMoveMode(self.main)
        self.mode._edit_sync.stop()
        self.mode._toggle()
        app.processEvents()

    def tearDown(self):
        self.mode._deactivate()
        self.mode._position_save_timer.stop()
        app.removeEventFilter(self.mode)
        app.aboutToQuit.disconnect(self.mode._flush_positions)
        self.main.close()
        self.main.deleteLater()
        self.patch.stop()
        app.processEvents()

    def test_selection_is_limited_to_text_and_arrow_moves_only_that_text(self):
        col = ColumnFixture(self.main)
        col.setGeometry(30, 100, 240, 280)
        col.show()
        app.processEvents()
        QTest.mouseClick(col.list.viewport(), Qt.LeftButton, pos=QPoint(25, 10))
        selected = self.mode.selected[0]
        self.assertIsInstance(selected, PaintedTarget)
        self.assertEqual(selected.part, "text")
        self.assertEqual(self.mode._selection_path(col.list.viewport().mapToGlobal(QPoint(25, 10))),
                         [selected])
        before = selected.pos()
        QTest.keyClick(col.list, Qt.Key_Right)
        self.assertEqual(selected.pos(), before + QPoint(1, 0))
        self.assertEqual(col.list._edit_offsets["exemple"]["text"], QPoint(1, 0))
        self.assertNotIn("row", col.list._edit_offsets["exemple"])

    def test_lightroom_media_counts_are_selectable_above_row_text(self):
        col = ColumnFixture(self.main)
        col.setGeometry(30, 100, 240, 280)
        col.list._edit_geometry["exemple"].update({
            "text": QRect(15, 0, 220, 28),
            "media-photo": QRect(190, 0, 42, 12),
            "media-video": QRect(190, 10, 42, 12),
        })
        col.show()
        app.processEvents()
        QTest.mouseClick(col.list.viewport(), Qt.LeftButton, pos=QPoint(210, 5))
        self.assertEqual(self.mode.selected[0].part, "media-photo")
        QTest.mouseClick(col.list.viewport(), Qt.LeftButton, pos=QPoint(210, 11))
        self.assertEqual(self.mode.selected[0].part, "media-video")
        before = self.mode.selected[0].pos()
        QTest.keyClick(col.list, Qt.Key_Left)
        self.assertEqual(self.mode.selected[0].pos(), before + QPoint(-1, 0))

    def test_media_count_edit_scope_targets_same_indicator_type_in_column(self):
        import settings_element_style as styles
        col = ColumnFixture(self.main)
        col.setGeometry(30, 100, 240, 280)
        col.list.item(0).setData(ROLE_MEDIA_COUNTS, (8, 2))
        col.list.addItem(QListWidgetItem("autre"))
        col.list.item(1).setData(ROLE_PATH, "autre")
        col.list.item(1).setData(ROLE_MEDIA_COUNTS, (4, 1))
        col.list._edit_geometry["exemple"]["media-photo"] = QRect(190, 0, 42, 12)
        col.show()
        app.processEvents()
        target = PaintedTarget(col.list, "exemple", "media-photo", QRect(190, 0, 42, 12))
        options = self.mode._text_scope_options(target)
        self.assertEqual([title for title, _ in options], [
            "Cette indication seulement", "Toutes les indications IMG de cette colonne",
            "Toutes les indications IMG pour toutes les colonnes"])
        self.assertEqual(len(options[1][1]), 2)
        self.assertTrue(all(isinstance(item, styles.RowMediaTextTarget) for item in options[1][1]))
        self.assertTrue(all(item.element.startswith("row-media:photo:Type:") for item in options[1][1]))
        self.assertEqual(options[2][1][0].element, "row-media-global:photo")

    def test_moving_row_name_does_not_move_photo_or_video_indicators(self):
        from app_style import column_style_for
        from row_delegates import _paint_unified_row

        def paint(name_offset):
            option = QStyleOptionViewItem()
            option.rect = QRect(0, 0, 300, 30)
            option._edit_parts = {}
            option._edit_offsets = {}
            option._edit_text_offset = QPoint(name_offset, 0)
            image = QImage(320, 40, QImage.Format_ARGB32)
            image.fill(Qt.transparent)
            painter = QPainter(image)
            _paint_unified_row(painter, option.rect, option, column_style_for("Type"),
                               "Dossier", None, None, QFont(), "#ffffff", False,
                               media_counts=(1322, 0))
            painter.end()
            return option._edit_parts

        original = paint(0)
        moved_name = paint(18)
        self.assertEqual(original["media-photo"], moved_name["media-photo"])
        self.assertEqual(original["media-video"], moved_name["media-video"])

    def test_shift_adds_and_middle_click_deselects_only_clicked_item(self):
        first = QLabel("Premier", self.main)
        second = QLabel("Second", self.main)
        third = QLabel("Troisième", self.main)
        for i, widget in enumerate((first, second, third)):
            widget.setGeometry(20 + i * 100, 30, 80, 24)
            widget.show()
        app.processEvents()
        QTest.mouseClick(first, Qt.LeftButton)
        QTest.mouseClick(second, Qt.LeftButton, Qt.ShiftModifier)
        self.assertEqual(self.mode.selected, [first, second])
        QTest.mouseClick(second, Qt.MiddleButton)
        self.assertEqual(self.mode.selected, [first])
        QTest.mouseClick(third, Qt.LeftButton)
        self.assertEqual(self.mode.selected, [third])

    def test_keyboard_move_uses_selected_text_scope(self):
        first = QLabel("Premier", self.main)
        second = QLabel("Second", self.main)
        first.setGeometry(20, 140, 80, 24)
        second.setGeometry(120, 140, 80, 24)
        first.show()
        second.show()
        app.processEvents()
        self.mode._select(first)
        self.mode.style_scope = ("table", "Tous les textes du tableau")
        self.mode._scope_options_widget = None
        with patch.object(self.mode, "_text_scope_options",
                          return_value=[("Ce texte seulement", [first]),
                                        ("Tous les textes du tableau", [first, second])]):
            self.assertEqual(self.mode._movement_scope_targets(), [first, second])
            self.mode._move_selected(QPoint(5, 0))
        self.assertEqual(first.pos(), QPoint(25, 140))
        self.assertEqual(second.pos(), QPoint(125, 140))
        self.assertEqual(len(self.mode.undo_stack[-1]), 2)

    def test_shift_click_toggles_member_without_clearing_other_selection(self):
        first = QLabel("Premier", self.main)
        second = QLabel("Second", self.main)
        first.setGeometry(20, 30, 80, 24)
        second.setGeometry(120, 30, 80, 24)
        first.show()
        second.show()
        app.processEvents()
        QTest.mouseClick(first, Qt.LeftButton)
        QTest.mouseClick(second, Qt.LeftButton, Qt.ShiftModifier)
        QTest.mouseClick(second, Qt.LeftButton, Qt.ShiftModifier)
        self.assertEqual(self.mode.selected, [first])

    def test_style_button_stays_on_first_text_and_opens_group_override(self):
        import settings_element_style as styles
        first = QLabel("Premier", self.main)
        second = QLabel("Second", self.main)
        first.setGeometry(20, 30, 80, 24)
        second.setGeometry(120, 30, 80, 24)
        first.show()
        second.show()
        app.processEvents()
        self.mode._select(first)
        self.mode._add_selection(second)
        self.mode._sync_selection_tools()
        button = self.mode.style_buttons[self.main]
        self.assertTrue(button.isVisible())
        self.assertEqual(button.y(), first.y())
        with patch.object(styles, "open_override") as opened:
            self.mode._open_selected_text_style()
        target = opened.call_args.args[0]
        self.assertIsInstance(target, styles.TextGroupTarget)
        self.assertEqual([item.widget for item in target.targets], [first, second])

    def test_table_text_override_includes_cell_look_for_each_text_scope(self):
        import settings_element_style as styles
        import settings_window_v2 as v2
        frame = v2._flat_cells_table([("Nom", QLabel("a"), None), ("Taille", QLabel("b"), None)])
        frame._dims_key = "Edit/Cellules#0"
        frame.setParent(self.main)
        frame.setGeometry(30, 90, 420, 160)
        frame.show()
        app.processEvents()
        label = next(lb for lb in frame.findChildren(QLabel) if lb.text() == "a")
        target = self.mode._make_text_target(label, "Ce texte seulement")
        self.assertIsInstance(target, styles.TableTextTarget)
        keys = {spec.key for spec in target.specs()}
        self.assertIn("table_cell_padding", keys)
        self.assertIn("table_cell_border_enabled", keys)
        self.assertTrue(any(spec.params and spec.params.get("real_key") == "table_row"
                            for spec in target.specs()))
        row_target = self.mode._make_text_target(
            label, "Tous les textes de la ligne (y compris sous-cellules)")
        self.assertEqual(row_target.cell_target.part, ("row", 0))
        table_target = self.mode._make_text_target(label, "Tous les textes du tableau")
        self.assertIsInstance(table_target.cell_target, styles.TableTarget)

        disk = {}
        def save(settings):
            disk.clear()
            disk.update(copy.deepcopy(settings))
        with patch.object(styles, "load_settings", side_effect=lambda: copy.deepcopy(disk)), \
             patch.object(styles, "save_settings", side_effect=save):
            window = styles.open_override(target, parent=self.main)
            values = window.style()
            bg_key = next(spec.key for spec in target.specs()
                          if spec.params and spec.params.get("real_key") == "table_row")
            values[bg_key] = "#204060"
            values["table_cell_padding"] = {"left": 6, "top": 4, "right": 6, "bottom": 4}
            values["table_cell_border_enabled"] = {
                "top": True, "right": False, "bottom": True, "left": False}
            values["table_cell_border"] = {"top": "#ff0000", "bottom": "#00ff00"}
            values["table_cell_border_thickness"] = 2
            window.styleChanged.emit(values)
            window.close()
            app.processEvents()
        cell_saved = disk[styles.KEY][target.cell_target.element]
        self.assertEqual(cell_saved["table_cell_padding"]["left"], 6)
        self.assertEqual(cell_saved["table_cell_border_thickness"], 2)
        self.assertEqual(cell_saved["colors"]["tableRow"], "#204060")
        self.assertEqual(cell_saved["table_cell_border_enabled"]["top"], True)

    def test_ctrl_backslash_toggles_edit_mode(self):
        self.mode._deactivate()
        event = QKeyEvent(QEvent.KeyPress, Qt.Key_Backslash, Qt.ControlModifier)
        self.assertTrue(self.mode.eventFilter(self.main, event))
        self.assertTrue(self.mode.active)

    def test_close_button_exits_edit_mode(self):
        button = self.mode.close_edit_button
        self.assertEqual(button.height(), button.width())
        self.assertEqual(button.y(), self.mode.edit_button.y())
        QTest.mouseClick(button, Qt.LeftButton)
        self.assertFalse(self.mode.active)

    def test_editing_only_text_color_keeps_its_original_pixel_size(self):
        import settings_element_style as styles
        from app_style import font
        label = QLabel("Lisible", self.main)
        label.setFont(font(18))
        label.show()
        target = styles.TextTarget("test:font-size", label, "Lisible")
        before = label.font().pixelSize()
        with patch.object(styles, "load_settings", return_value={}):
            values = target.general({})
            self.assertEqual(values["text_font_size"], 18)
            values["text_font_color"] = "#ffcc00"
            target.preview(values)
        self.assertEqual(label.font().pixelSize(), before)

    def test_style_override_closes_when_its_selection_is_cleared(self):
        from PySide6.QtWidgets import QDialog
        import settings_element_style as styles
        selected = QLabel("Cible", self.main)
        replacement = QLabel("Autre", self.main)
        selected.setGeometry(20, 30, 80, 24)
        replacement.setGeometry(120, 30, 80, 24)
        selected.show()
        replacement.show()
        app.processEvents()
        dialog = QDialog(self.main)
        dialog.show()
        key = "test-interface-edit-selection"
        styles._OPEN[key] = dialog
        dialog._interface_selection_owner = self.mode
        dialog._interface_selection_anchor = selected
        self.addCleanup(styles._OPEN.pop, key, None)
        self.mode._select(selected)
        self.mode._sync_selection_tools()
        self.assertTrue(dialog.isVisible())
        self.mode._select(replacement)
        self.mode._sync_selection_tools()
        app.processEvents()
        self.assertFalse(dialog.isVisible())

    def test_prompt_placeholder_gets_style_button_and_column_scope(self):
        prompt = QLineEdit(self.main)
        prompt.setPlaceholderText("Invitez une valeur…")
        prompt.setGeometry(20, 70, 180, 28)
        prompt.show()
        app.processEvents()
        self.mode._select(prompt)
        self.mode._sync_selection_tools()
        self.assertTrue(self.mode._has_display_text(prompt))
        self.assertTrue(self.mode.style_buttons[self.main].isVisible())
        self.assertEqual(self.mode._text_value(prompt), "Invitez une valeur…")

    def test_column_text_has_scope_and_row_style_target(self):
        import settings_element_style as styles
        import ui_state
        col = ColumnFixture(self.main)
        col.setGeometry(30, 100, 240, 280)
        col.show()
        app.processEvents()
        target = PaintedTarget(col.list, "exemple", "text", QRect(15, 4, 65, 20))
        self.mode._select(target)
        options = self.mode._text_scope_options(target)
        self.assertEqual([title for title, _members in options], [
            "Ce texte seulement", "Les éléments de ce type dans toute la colonne"])
        row_target = self.mode._make_text_target(target)
        self.assertIsInstance(row_target, styles.RowTextTarget)
        with patch.object(styles, "load_settings", return_value={}):
            values = styles.merged(row_target.general({}), {"text_font_size": 26,
                                                            "text_font_color": "#ff0000"})
            row_target.apply(values)
        self.assertEqual(ui_state.ROW_TEXT_OVERRIDES[row_target.element]["text_font_size"], 26)
        index = col.list.model().index(0, 0)
        from row_delegates import _row_text_look
        look = _row_text_look(col, index, col.list.font(), "#ffffff")
        self.assertEqual(look["_color"], "#ff0000")
        self.assertEqual(look["_font"].pixelSize(), 26)
        self.mode._sync_selection_tools()
        self.assertTrue(self.mode.scope_button.isVisible())

    def test_column_text_override_window_updates_the_row_and_saves(self):
        import settings_element_style as styles
        import ui_state
        from row_delegates import _row_text_look
        col = ColumnFixture(self.main)
        col.setGeometry(30, 100, 240, 280)
        col.show()
        app.processEvents()
        painted = PaintedTarget(col.list, "exemple", "text", QRect(15, 4, 65, 20))
        target = self.mode._make_text_target(painted)
        disk = {}
        def save(settings):
            disk.clear()
            disk.update(copy.deepcopy(settings))
        with patch.object(styles, "load_settings", side_effect=lambda: copy.deepcopy(disk)), \
             patch.object(styles, "save_settings", side_effect=save):
            window = styles.open_override(target, parent=self.main)
            values = window.style()
            values.update({"text_font_size": 20, "text_font_color": "#ff2211"})
            window.styleChanged.emit(values)
            self.assertEqual(ui_state.ROW_TEXT_OVERRIDES[target.element]["text_font_color"], "#ff2211")
            window.close()  # vide la sauvegarde temporisée
            self.assertEqual(disk[styles.KEY][target.element]["text_font_size"], 20)
        index = col.list.model().index(0, 0)
        self.assertEqual(_row_text_look(col, index, col.list.font(), "#ffffff")["_color"], "#ff2211")

    def test_gallery_text_and_image_expose_the_requested_scopes_and_style_controls(self):
        import settings_element_style as styles
        from focus import FocusGallery
        gallery = FocusGallery(self.main, [], None)
        gallery.setGeometry(20, 100, 300, 260)
        gallery.show()
        self.addCleanup(gallery.deleteLater)
        path = "C:/images/airplane.png"
        item = QListWidgetItem("airplane.png")
        item.setData(Qt.UserRole, path)
        item.setData(Qt.UserRole + 2, "PNG · 4 Mo")
        gallery.addItem(item)
        name = PaintedTarget(gallery, path, "gallery-name", QRect(0, 0, 80, 20))
        scopes = self.mode._text_scope_options(name)
        self.assertEqual([title for title, _members in scopes], [
            "Cette cellule seulement", "Toutes les cellules pour ce type de texte",
            "Toutes les cellules pour tous les textes"])
        text_target = self.mode._make_text_target(name)
        self.assertIsInstance(text_target, styles.GalleryStyleTarget)
        image = PaintedTarget(gallery, path, "gallery-image", QRect(0, 0, 80, 80))
        image_target = self.mode._make_text_target(image)
        self.assertIsInstance(image_target, styles.GalleryStyleTarget)
        image_keys = {spec.key for spec in image_target.specs()}
        self.assertIn("viewer_film_image_border_radius", image_keys)
        self.assertIn("viewer_film_image_shadow_enabled", image_keys)
        self.assertEqual([title for title, _members in self.mode._text_scope_options(image)], [
            "Cette cellule seulement", "Toutes les cellules du tableau"])
        cell = PaintedTarget(gallery, path, "gallery-cell", QRect(0, 0, 100, 100))
        cell_keys = {spec.key for spec in self.mode._make_text_target(cell).specs()}
        self.assertTrue({"gallery_cell_bg", "gallery_cell_padding", "gallery_cell_border_enabled"}
                        <= cell_keys)
        text_keys = {spec.key for spec in text_target.specs()}
        self.assertIn("gallery_cell_bg", text_keys)

    def test_gallery_info_style_applies_to_the_lower_text_and_can_move(self):
        import settings_element_style as styles
        import ui_state
        from focus import FocusGallery
        gallery = FocusGallery(self.main, [], None)
        gallery.setGeometry(20, 100, 300, 260)
        gallery.show()
        app.processEvents()
        self.addCleanup(gallery.deleteLater)
        path = "C:/images/airplane.png"
        item = QListWidgetItem("airplane.png")
        item.setData(Qt.UserRole, path)
        item.setData(Qt.UserRole + 2, "PNG · 4 Mo")
        gallery.addItem(item)
        target = PaintedTarget(gallery, path, "gallery-info", QRect(30, 50, 40, 12))
        gallery._edit_geometry = {path: {"gallery-info": QRect(30, 50, 40, 12),
                                         "gallery-text-bounds": QRect(20, 40, 100, 40),
                                         "gallery-cell": QRect(0, 0, 150, 100)}}
        old = getattr(ui_state, "GALLERY_STYLE_OVERRIDES", None)
        self.addCleanup(setattr, ui_state, "GALLERY_STYLE_OVERRIDES", old)
        ui_state.GALLERY_STYLE_OVERRIDES = {}
        with patch.object(styles, "load_settings", return_value={}):
            style = styles.GalleryStyleTarget(target, path, "info")
            values = style.general({})
            values.update({"text_font_size": 18, "text_font_color": "#ff2200"})
            style.preview(values)
        look = gallery.film_look_for(path)
        self.assertEqual(look["rank_font"][0].pixelSize(), 18)
        self.assertEqual(look["rank_font"][1].name(), "#ff2200")
        self.assertEqual(self.mode._bounded_position(target, QPoint(31, 50)), QPoint(31, 50))
        self.mode._select(target)
        QTest.keyClick(gallery, Qt.Key_Right)
        self.assertEqual(gallery._edit_offsets[path]["gallery-info"], QPoint(1, 0))

    def test_gallery_all_text_scope_styles_name_and_lower_info(self):
        import settings_element_style as styles
        import ui_state
        from focus import FocusGallery
        gallery = FocusGallery(None, [], None)
        self.addCleanup(gallery.deleteLater)
        path = "C:/images/airplane.png"
        item = QListWidgetItem("airplane.png")
        item.setData(Qt.UserRole, path)
        item.setData(Qt.UserRole + 2, "PNG · 4 Mo")
        gallery.addItem(item)
        name = PaintedTarget(gallery, path, "gallery-name", QRect(0, 0, 80, 20))
        old = getattr(ui_state, "GALLERY_STYLE_OVERRIDES", None)
        self.addCleanup(setattr, ui_state, "GALLERY_STYLE_OVERRIDES", old)
        ui_state.GALLERY_STYLE_OVERRIDES = {}
        members = self.mode._text_scope_options(name)[2][1]
        with patch.object(styles, "load_settings", return_value={}):
            group = styles.TextGroupTarget(members, "all-gallery-text")
            values = group.general({})
            values.update({"text_font_size": 17, "text_font_color": "#ee4400"})
            group.preview(values)
        look = gallery.film_look_for(path)
        self.assertEqual(look["name_font"][0].pixelSize(), 17)
        self.assertEqual(look["rank_font"][0].pixelSize(), 17)
        self.assertEqual(look["name_font"][1].name(), "#ee4400")
        self.assertEqual(look["rank_font"][1].name(), "#ee4400")

    def test_gallery_text_color_scope_does_not_color_image_background(self):
        import settings_element_style as styles
        import ui_state
        from focus import FocusGallery
        gallery = FocusGallery(None, [], None)
        self.addCleanup(gallery.deleteLater)
        paths = ["C:/images/one.png", "C:/images/two.png"]
        for path in paths:
            item = QListWidgetItem(path.rsplit("/", 1)[-1])
            item.setData(Qt.UserRole, path)
            item.setData(Qt.UserRole + 2, "PNG")
            gallery.addItem(item)
        anchor = PaintedTarget(gallery, paths[0], "gallery-name", QRect(0, 0, 80, 20))
        members = self.mode._text_scope_options(anchor)[2][1]
        old = getattr(ui_state, "GALLERY_STYLE_OVERRIDES", None)
        self.addCleanup(setattr, ui_state, "GALLERY_STYLE_OVERRIDES", old)
        ui_state.GALLERY_STYLE_OVERRIDES = {}
        with patch.object(styles, "load_settings", return_value={}):
            group = styles.TextGroupTarget(members, "gallery-color")
            values = styles._normalized(group.specs(), group.values({}))
            values["text_font_color"] = "#e04020"
            group.preview(values)
        for path in paths:
            for part in ("name", "info"):
                saved = ui_state.GALLERY_STYLE_OVERRIDES[f"gallery-{part}:{path}"]
                self.assertEqual(saved["text_font_color"], "#e04020")
                self.assertNotIn("gallery_cell_bg", saved)
            look = gallery.film_look_for(path)
            self.assertIsNone(look.get("cell"))
        disk = {}
        with patch.object(styles, "load_settings", return_value={}), \
             patch.object(styles, "save_settings", side_effect=lambda settings: disk.update(settings)) as save:
            group.save(values)
        self.assertEqual(save.call_count, 1)
        self.assertNotIn("gallery_cell_bg", disk[styles.KEY][f"gallery-name:{paths[0]}"])
        with patch.object(styles, "load_settings", return_value={}):
            values["colors:table_row"] = "#203040"
            group.preview(values)
        self.assertEqual(ui_state.GALLERY_STYLE_OVERRIDES[f"gallery-name:{paths[0]}"]["gallery_cell_bg"],
                         "#203040")

    def test_reset_button_restores_painted_text_and_four_buttons_stack_evenly(self):
        col = ColumnFixture(self.main)
        col.setGeometry(30, 100, 240, 280)
        col.show()
        app.processEvents()
        text = PaintedTarget(col.list, "exemple", "text", QRect(15, 4, 65, 20))
        self.mode._select(text)
        self.mode._move_selected(QPoint(8, 0))
        self.assertEqual(col.list._edit_offsets["exemple"]["text"], QPoint(8, 0))
        buttons = [self.mode.edit_button, self.mode.reset_button,
                   self.mode.reset_all_button, self.mode.debug_button]
        self.assertEqual(len({button.width() for button in buttons}), 1)
        self.assertEqual([button.y() for button in buttons], sorted(button.y() for button in buttons))
        for button in (self.mode.reset_button, self.mode.reset_all_button):
            self.assertIn("background: rgba(255,0,0,128)", button.styleSheet())
            self.assertIn("background: rgba(255,0,0,175)", button.styleSheet())
            self.assertIn("background: rgba(255,0,0,96)", button.styleSheet())
        self.assertIn("background: rgba(180,125,20,230)", self.mode.debug_button.styleSheet())
        self.assertIn("background: rgba(180,125,20,255)", self.mode.debug_button.styleSheet())
        QTest.mouseClick(self.mode.reset_button, Qt.LeftButton)
        self.assertEqual(text.pos(), QPoint(15, 4))
        self.assertNotIn("text", col.list._edit_offsets["exemple"])
        self.assertNotIn(self.mode._position_key(text), self.mode.position_overrides)

    def test_layout_control_uses_free_object_slot_and_survives_resize(self):
        frame, _head, cells = settings_cells.build_cells_table(
            [("Nom", 120), ("Valeur", 220)],
            [[QLabel("Interrupteur"), QPushButton("toggle")]],
        )
        frame.resize(frame.sizeHint())
        frame.show()
        self.addCleanup(frame.deleteLater)
        app.processEvents()
        self.mode._include_open_windows()
        button = cells[0][1].findChild(QPushButton)
        cell = cells[0][1]
        QTest.mouseClick(button, Qt.LeftButton)
        self.assertEqual(self.mode.selected, [button])
        self.mode._move_selected(QPoint(28, 6))
        app.processEvents()
        self.assertIsNotNone(button._float_slot)
        key, record = next(iter(frame._extra_dims.objects.items()))
        self.assertEqual(record[:2], [28, 6])
        before = button.mapTo(cell, QPoint(0, 0)) - button._float_slot.mapTo(cell, QPoint(0, 0))
        cell.setFixedWidth(cell.width() + 70)
        app.processEvents()
        after = button.mapTo(cell, QPoint(0, 0)) - button._float_slot.mapTo(cell, QPoint(0, 0))
        self.assertEqual(before, QPoint(28, 6))
        self.assertEqual(after, before)
        self.mode._undo()
        app.processEvents()
        self.assertIsNone(getattr(button, "_float_slot", None))
        self.assertNotIn(key, frame._extra_dims.objects)

    def test_non_table_control_uses_same_float_slot_and_can_be_reset(self):
        window = QWidget()
        layout = QHBoxLayout(window)
        button = QPushButton("action")
        button.setFixedSize(70, 24)
        layout.addWidget(button)
        window.resize(300, 100)
        window.show()
        self.addCleanup(window.deleteLater)
        app.processEvents()
        self.mode._include_open_windows()
        QTest.mouseClick(button, Qt.LeftButton)
        self.assertEqual(self.mode.selected, [button])
        home = button.mapToGlobal(QPoint(0, 0))
        self.mode._move_selected(QPoint(24, 4))
        app.processEvents()
        self.assertIsNotNone(button._float_slot)
        self.assertEqual(button.mapToGlobal(QPoint(0, 0)) - home, QPoint(24, 4))
        self.assertTrue(any(key.startswith("@free|") for key in self.mode.position_overrides))
        before_resize = button.mapTo(window, QPoint(0, 0)) - button._float_slot.mapTo(window, QPoint(0, 0))
        window.resize(360, 120)
        app.processEvents()
        after_resize = button.mapTo(window, QPoint(0, 0)) - button._float_slot.mapTo(window, QPoint(0, 0))
        self.assertEqual(before_resize, QPoint(24, 4))
        self.assertEqual(after_resize, before_resize)
        self.mode._reset_current()
        app.processEvents()
        self.assertIsNone(getattr(button, "_float_slot", None))
        self.assertFalse(any(key.startswith("@free|") for key in self.mode.position_overrides))

    def test_new_windows_are_excluded_until_the_button_adds_them(self):
        from settings_widgets import _MiniSlider
        slider = _MiniSlider(0, 100, 40, width=180, parent=self.main)
        slider.move(30, 40)
        slider.show()
        app.processEvents()
        QTest.mouseClick(slider, Qt.LeftButton, pos=QPoint(70, slider.height() // 2))
        self.assertEqual(self.mode.selected, [slider])

        secondary = QWidget()
        label = QLabel("Style secondaire", secondary)
        label.setGeometry(20, 20, 130, 24)
        secondary.show()
        app.processEvents()
        self.assertFalse(self.mode._editable_window(secondary))
        self.assertTrue(self.mode.secondary_windows_button.isEnabled())
        self.mode.secondary_windows_button.click()
        self.assertTrue(self.mode._editable_window(secondary))
        self.mode._select(label)
        self.assertTrue(self.mode.style_buttons[secondary].isVisible())
        later = QWidget()
        later.show()
        app.processEvents()
        self.assertFalse(self.mode._editable_window(later))
        self.mode._deactivate()
        self.mode._toggle()
        self.assertTrue(self.mode._editable_window(later))
        self.assertTrue(self.mode._editable_window(secondary))
        secondary.close()
        secondary.deleteLater()
        later.close()
        later.deleteLater()

    def test_edit_appearance_is_saved_when_override_settings_change(self):
        with patch("pipeline_browser.save_live_state") as save:
            self.mode._apply_edit_settings({
                "edit_selection_background": "#30ff0000",
                "edit_selection_border_thickness": 5,
                "edit_selection_border_radius": {"top_left": 8, "top_right": 8,
                                                   "bottom_right": 8, "bottom_left": 8},
            })
        save.assert_called_once()
        key, appearance = save.call_args.args
        self.assertEqual(key, "interface_edit_appearance")
        self.assertEqual(appearance["selection_border_width"], 5)
        self.assertEqual(appearance["selection_radius"], 8)

    def test_selection_frame_has_antialiased_rounded_corners(self):
        self.mode.selection_radius = 12
        frame = _InterfaceMoveFrame(self.main, self.mode, debug=False)
        frame.resize(48, 40)
        frame.show()
        app.processEvents()
        image = frame.grab().toImage()
        self.assertEqual(image.pixelColor(0, 0).alpha(), 0)
        self.assertGreater(image.pixelColor(20, 1).alpha(), 0)
        frame.deleteLater()

    def test_reset_object_removes_text_style_and_ctrl_z_restores_it(self):
        import copy
        import settings_element_style as styles
        label = QLabel("Texte modifié", self.main)
        label.setGeometry(30, 30, 130, 24)
        label.show()
        element = f"text:{type(self.main).__name__}:{styles.widget_path(label, self.main)}"
        disk = {styles.KEY: {element: {"text_font_size": 22, "text_font_color": "#ff8800"}}}

        def save(settings):
            disk.clear()
            disk.update(copy.deepcopy(settings))

        with patch.object(styles, "load_settings", side_effect=lambda: copy.deepcopy(disk)), \
                patch.object(styles, "save_settings", side_effect=save):
            styles.apply_text_look(label, {"text_font_size": 22, "text_font_color": "#ff8800"})
            self.mode._select(label)
            self.mode._reset_current()
            self.assertNotIn(element, disk[styles.KEY])
            self.assertIsNone(label._look_values)
            self.mode._undo()
            self.assertEqual(disk[styles.KEY][element]["text_font_size"], 22)
            self.assertEqual(label._look_values["text_font_size"], 22)

    def test_text_style_overrides_are_highlighted_by_debug_and_removed_when_cleared(self):
        import settings_element_style as styles
        label = QLabel("Texte stylé", self.main)
        label.setGeometry(30, 30, 130, 24)
        label.show()
        app.processEvents()
        element = f"text:{type(self.main).__name__}:{styles.widget_path(label, self.main)}"
        self.mode.debug_enabled = True

        self.mode._on_text_style_saved(styles.KEY, {element: {"text_font_size": 22}})
        self.assertIn(label, self.mode.debug_frames)
        self.assertIn(label, self.mode.text_modified)

        self.mode._on_text_style_saved(styles.KEY, {})
        self.assertNotIn(label, self.mode.debug_frames)
        self.assertNotIn(label, self.mode.text_modified)

    def test_edit_buttons_fit_text_and_style_button_aligns_to_selection(self):
        from app_style import scaled
        label = QLabel("Texte à styliser", self.main)
        label.setGeometry(70, 90, 130, 24)
        label.show()
        app.processEvents()
        self.mode._select(label)
        app.processEvents()

        for button in (self.mode.edit_button, self.mode.reset_button, self.mode.reset_all_button,
                       self.mode.debug_button, self.mode.secondary_windows_button):
            self.assertEqual(button.width(), scaled(220))
            self.assertIn("color: black", button.styleSheet())
        self.assertEqual(self.mode.scope_button.width(), scaled(220))
        self.assertGreater(self.mode.scope_button.height(), scaled(22))
        self.assertIn("rgba(64,67,71,255)", self.mode.scope_button.styleSheet())
        self.assertIn("color: black", self.mode.scope_button.styleSheet())
        style = self.mode.style_buttons[self.main]
        self.assertEqual(style.height(), scaled(16))
        self.assertEqual(style.y(), label.y())
        self.assertIn("color: black", style.styleSheet())
        self.mode._sync_selection_tools()
        self.assertTrue(style.isVisible())
        with patch("settings_element_style.open_override") as open_override:
            QTest.mouseClick(style, Qt.LeftButton)
        open_override.assert_called_once()

    def test_scope_dropdown_shows_the_selected_option(self):
        label = QLabel("Texte", self.main)
        label.setGeometry(40, 60, 80, 24)
        label.show()
        self.mode._select(label)
        options = [("Ce texte seulement", [label]), ("Tous les textes du tableau", [label])]
        with patch.object(self.mode, "_text_scope_options", return_value=options):
            self.mode._scope_menu_signature = None
            self.mode._sync_selection_tools()
            self.assertEqual(self.mode.scope_button.text(), "Portée : Texte seul")
            menu = self.mode.scope_button.menu()
            self.assertTrue(menu.actions()[0].isChecked())
            menu.actions()[1].trigger()
            self.assertEqual(self.mode.scope_button.text(), "Portée : Textes + entête")
            self.assertTrue(self.mode.scope_button.menu().actions()[1].isChecked())

    def test_reset_all_removes_only_visible_text_overrides(self):
        import copy
        import settings_element_style as styles
        visible = QLabel("Visible", self.main)
        visible.setGeometry(30, 70, 100, 24)
        visible.show()
        class ClosedTestWindow(QWidget):
            pass
        closed_window = ClosedTestWindow()
        closed = QLabel("Fenêtre fermée", closed_window)
        closed.setGeometry(10, 10, 120, 24)
        closed_window.show()
        app.processEvents()
        visible_key = f"text:{type(self.main).__name__}:{styles.widget_path(visible, self.main)}"
        closed_key = f"text:{type(closed_window).__name__}:{styles.widget_path(closed, closed_window)}"
        disk = {styles.KEY: {visible_key: {"text_font_size": 21},
                             closed_key: {"text_font_size": 23}}}

        def save(settings):
            disk.clear()
            disk.update(copy.deepcopy(settings))

        with patch.object(styles, "load_settings", side_effect=lambda: copy.deepcopy(disk)), \
                patch.object(styles, "save_settings", side_effect=save):
            styles.apply_text_look(visible, {"text_font_size": 21})
            styles.apply_text_look(closed, {"text_font_size": 23})
            closed_window.close()
            self.mode._reset_all()
            self.assertNotIn(visible_key, disk[styles.KEY])
            self.assertIn(closed_key, disk[styles.KEY])
        closed_window.deleteLater()

    def test_closed_window_keeps_override_while_visible_window_resets(self):
        other = QWidget()
        other.setWindowTitle("Autre fenêtre")
        other.setGeometry(800, 50, 300, 200)
        label = QLabel("Texte", other)
        label.setGeometry(20, 20, 60, 20)
        other.show()
        app.processEvents()
        self.mode._include_open_windows()
        self.mode._select(label)
        self.mode._move_selected(QPoint(4, 0))
        key = self.mode._position_key(label)
        self.mode._sync_windows()
        self.assertIs(self.mode.frames[label].parentWidget(), other)
        self.assertIn(other, self.mode.window_frames)
        other.close()
        self.mode._reset_all()
        self.assertEqual(label.x(), 24)
        self.assertIn(key, self.mode.position_overrides)
        other.show()
        app.processEvents()
        self.mode._reset_all()
        self.assertEqual(label.x(), 20)
        self.assertNotIn(key, self.mode.position_overrides)
        other.close()
        other.deleteLater()

    def test_destroyed_window_restores_offset_then_visible_reset_removes_it(self):
        def make_window():
            window = QWidget()
            window.setWindowTitle("Réglages persistants")
            window.setGeometry(800, 50, 300, 200)
            text = QLabel("Texte", window)
            text.setGeometry(30, 40, 80, 20)
            window.show()
            app.processEvents()
            return window, text
        other, label = make_window()
        self.mode._select(label)
        self.mode._move_selected(QPoint(7, 0))
        key = self.mode._position_key(label)
        other.close()
        other.deleteLater()
        app.sendPostedEvents(None, QEvent.DeferredDelete)
        self.mode._sync_windows()
        self.mode._reset_all()
        self.assertIn(key, self.mode.position_overrides)
        other, label = make_window()
        self.mode._include_open_windows()
        self.mode._sync_windows()
        self.assertEqual(label.pos(), QPoint(37, 40))
        self.mode._reset_all()
        self.assertEqual(label.pos(), QPoint(30, 40))
        self.assertNotIn(key, self.mode.position_overrides)
        other.close()
        other.deleteLater()
