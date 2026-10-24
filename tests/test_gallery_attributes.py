import _isolate  # noqa: F401 -- aucune ecriture dans les reglages reels
import os
import shutil
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QImage, QKeyEvent, QPixmap, QMouseEvent, QTextCursor
from PySide6.QtWidgets import QApplication, QWidget

import file_attributes
import focus

_app = QApplication.instance() or QApplication([])


class GalleryAttributesTest(unittest.TestCase):
    """Planche : cases non divisees (image centree), attributs appliques dessines sur chaque case,
    barre de survol pour noter / colorer / marquer / ajouter un mot cle."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.paths = []
        for i in range(6):
            path = self.dir / f"img_{i}.png"
            image = QImage(400, 300, QImage.Format_RGB32)
            image.fill(0xFF406080)
            image.save(str(path))
            self.paths.append(path)
        self.host = QWidget()
        self.host.resize(1200, 800)
        self.host.show()
        self.addCleanup(self.host.deleteLater)
        self.gallery = focus.FocusGallery(self.host, self.paths, str(self.paths[0]))
        self.gallery.setGeometry(self.host.rect())
        self.gallery.show()
        self.gallery.reveal_current()
        self.gallery._ripple_origin = None

    def _rect(self, row: int):
        return self.gallery.visualRect(self.gallery.model().index(row, 0))

    def _hover(self, row: int):
        viewport = self.gallery.viewport()
        pos = self._rect(row).center()
        event = QMouseEvent(QEvent.MouseMove, QPointF(pos), QPointF(viewport.mapToGlobal(pos)),
                            Qt.NoButton, Qt.NoButton, Qt.NoModifier)
        QApplication.sendEvent(viewport, event)

    def test_cells_are_not_divided_and_image_is_centred(self):
        gallery = self.gallery
        self.assertEqual(gallery.label_height(), 0)
        cell, box = gallery.tile_boxes(self._rect(1))
        self.assertEqual(cell, box)                        # pas de sous-cellule texte
        self.assertIsNone(gallery._split_cell_at(QPoint(box.center().x(), box.bottom() + 1)))

    def test_only_applied_attributes_change_the_cell(self):
        gallery = self.gallery
        index = gallery.model().index(2, 0)
        size = gallery.gridSize()
        plain = gallery.cell_pixmap(index, size).toImage()
        self.assertEqual(gallery.attr_values(str(self.paths[2])), {})
        file_attributes.update(self.paths[2], rating=3, keywords=["ciel"])
        gallery.__dict__.get("_attr_values", {}).clear()
        rated = gallery.cell_pixmap(index, size).toImage()
        self.assertEqual(gallery.attr_values(str(self.paths[2])), {"rating": 3, "keywords": ["ciel"]})
        self.assertNotEqual(plain, rated)                  # bande des attributs dessinee

    def _click_in(self, row: int, kind: str, value=None):
        """Clic sur l'element d'attribut (genre, valeur) de la case `row`, sur la photo."""
        gallery = self.gallery
        cell = self._rect(row)
        key = str(self.paths[row])
        room = gallery.photo_room(key, cell)
        layout = focus.attr_layout(room)
        target = {"star": lambda: layout["stars"][value - 1], "color": lambda: layout["colors"][value - 1],
                  "flag": lambda: layout["flags"][value], "plus": lambda: layout["plus"]}[kind]()
        pos = cell.topLeft() + target.center()
        viewport = gallery.viewport()
        for kind_, button in ((QEvent.MouseMove, Qt.NoButton), (QEvent.MouseButtonPress, Qt.LeftButton),
                              (QEvent.MouseButtonRelease, Qt.LeftButton)):
            QApplication.sendEvent(viewport, QMouseEvent(kind_, QPointF(pos), QPointF(viewport.mapToGlobal(pos)),
                                                         button, button, Qt.NoModifier))

    def test_attribute_controls_sit_in_the_corners_of_the_slide(self):
        room = self.gallery.photo_room(str(self.paths[0]), self._rect(0))      # coins de la diapo
        layout = focus.attr_layout(room)
        gap = focus.attr_inset()
        for rect in layout["colors"] + list(layout["flags"].values()):
            self.assertEqual(rect.top(), room.top() + gap)               # en haut, a l'ecart du bord
        for rect in layout["stars"] + [layout["plus"]]:
            self.assertEqual(rect.bottom() + 1, room.bottom() + 1 - gap)   # en bas
        self.assertEqual(layout["colors"][0].left(), room.left() + gap)      # couleurs / note : coin gauche
        self.assertEqual(layout["stars"][0].left(), room.left() + gap)
        self.assertEqual(layout["flags"]["delete"].right(), room.right() - gap)   # drapeaux / « + » : coin droit
        self.assertEqual(layout["plus"].right(), room.right() - gap)
        self.assertLessEqual(layout["unit"], focus.scaled(16))         # petits
        cell = self._rect(0)
        for rect in layout["colors"] + layout["stars"]:
            self.assertTrue(QRect(QPoint(0, 0), cell.size()).contains(rect))   # reste dans la case

    def test_the_photo_is_fitted_between_the_two_bands(self):
        gallery = self.gallery
        index = gallery.model().index(0, 0)
        gallery.cell_pixmap(index, gallery.gridSize())
        # Calques paralleles : le padding des icones ne change pas la place de la photo, ni l'inverse.
        gallery._photo_rects.clear()
        before = gallery.image_rect_in(gallery.viewport(), str(self.paths[0]), QPixmap(300, 200))
        import ui_state
        applied = ui_state.APPLIED_SETTINGS
        self.addCleanup(setattr, ui_state, "APPLIED_SETTINGS", applied)
        ui_state.APPLIED_SETTINGS = {**(applied or {}), "viewer_film_attr_padding": {"left": 30, "top": 30,
                                                                                    "right": 30, "bottom": 30}}
        gallery.film_look = focus._film_look()
        after = gallery.image_rect_in(gallery.viewport(), str(self.paths[0]), QPixmap(300, 200))
        self.assertEqual(before, after)
        self.assertEqual(gallery.photo_band(), 0)
        # Padding du fond : image et icones se decalent avec lui.
        ui_state.APPLIED_SETTINGS = {**ui_state.APPLIED_SETTINGS, "viewer_film_attr_padding": {},
                                     "viewer_film_bg_padding": {"left": 12, "top": 12, "right": 12, "bottom": 12}}
        gallery.film_look = focus._film_look()
        gallery._photo_rects.clear()
        shifted = gallery.image_rect_in(gallery.viewport(), str(self.paths[0]), QPixmap(300, 200))
        self.assertNotEqual(shifted, before)
        frame = gallery.photo_room(str(self.paths[0]), self._rect(0))
        gallery.film_look["bg_padding"] = {k: 0 for k in ("left", "top", "right", "bottom")}
        gallery._photo_rects.clear()
        plain = gallery.photo_room(str(self.paths[0]), self._rect(0))
        self.assertEqual((frame.left() - plain.left(), frame.top() - plain.top()), (12, 12))

    def test_hover_controls_edit_rating_color_and_flag_on_the_photo(self):
        self._click_in(1, "star", 4)
        self._click_in(1, "color", 2)
        self._click_in(1, "flag", "keep")
        saved = file_attributes.get(self.paths[1])
        self.assertEqual((saved["rating"], saved["color"], saved["status"]), (4, 2, "keep"))
        self.assertEqual(self.gallery.attr_values(str(self.paths[1]))["rating"], 4)     # case a jour aussitot
        self._click_in(1, "star", 4)                                                   # re-clic : aucune note
        self._click_in(1, "flag", "keep")
        saved = file_attributes.get(self.paths[1])
        self.assertEqual((saved["rating"], saved["status"]), (0, ""))
        self.assertIsNone(self.gallery.currentItem() and None)                         # pas de fenetre flottante
        self.assertFalse(hasattr(self.gallery, "attr_bar"))

    def test_clicking_a_control_does_not_choose_the_image(self):
        chosen = []
        self.gallery.chosen.connect(chosen.append)
        self._click_in(2, "star", 3)
        self.assertEqual(chosen, [])

    def test_keywords_window_has_one_keyword_per_line(self):
        file_attributes.update(self.paths[3], keywords=["ciel", "nuit sans lune"])
        self.gallery.__dict__.get("_attr_values", {}).clear()
        self._click_in(3, "plus")
        window = self.gallery._keywords_window
        self.assertIsNotNone(window)
        self.assertEqual(window.field.toPlainText().splitlines(), ["ciel", "nuit sans lune"])   # une par ligne
        window.field.setPlainText("ciel%smontagne%s%s  Ciel  " % (chr(10), chr(10), chr(10)))   # doublon et ligne vide
        self.assertEqual(window.field.lines(), ["ciel", "montagne"])
        window._accept()
        self.assertEqual(file_attributes.get(self.paths[3])["keywords"], ["ciel", "montagne"])   # « nuit… » enleve
        self.assertEqual(self.gallery.attr_values(str(self.paths[3]))["keywords"], ["ciel", "montagne"])

    def test_plus_opens_the_window_every_time(self):
        # Signale : la fenetre ne s'ouvrait qu'une fois, ensuite « il ne se passe rien » (reference restee
        # sur une fenetre detruite).
        gallery = self.gallery
        for round_ in range(3):
            self._click_in(2, "plus")
            window = gallery._keywords_window
            self.assertIsNotNone(window, f"ouverture {round_ + 1}")
            self.assertTrue(window.isVisible(), f"ouverture {round_ + 1}")
            window.field.setPlainText("mot%d" % round_)
            window._accept()                                       # fermee (et detruite) comme au clic ailleurs
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            self.assertIsNone(gallery._keywords_window)
        self.assertEqual(file_attributes.get(self.paths[2])["keywords"], ["mot2"])
        # Escape ferme sans rien changer, et on peut rouvrir apres.
        self._click_in(2, "plus")
        window = gallery._keywords_window
        window.field.setPlainText("jamais")
        QApplication.sendEvent(window, QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier))
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.assertEqual(file_attributes.get(self.paths[2])["keywords"], ["mot2"])
        self._click_in(2, "plus")
        self.assertTrue(gallery._keywords_window.isVisible())
        gallery._keywords_window.close()

    def _press(self, target, global_pos):
        local = target.mapFromGlobal(global_pos) if hasattr(target, "mapFromGlobal") else QPoint(0, 0)
        QApplication.sendEvent(target, QMouseEvent(QEvent.MouseButtonPress, QPointF(local), QPointF(global_pos),
                                                   Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))

    def test_clicking_inside_the_keywords_window_keeps_it_open(self):
        # Signale : un clic dans la fenetre la faisait disparaitre (impossible de saisir un mot cle).
        self._click_in(1, "plus")
        window = self.gallery._keywords_window
        window.field.setPlainText("ciel")
        inside = window.field.mapToGlobal(window.field.rect().center())
        for target in (window.field.viewport(), window.field, window, window.windowHandle()):
            self._press(target, inside)                    # le clic arrive aussi au niveau de la fenetre native
            self.assertTrue(window.isVisible())
            self.assertIs(self.gallery._keywords_window, window)
        title_spot = window.mapToGlobal(QPoint(window.width() // 2, 4))
        self._press(window, title_spot)                    # bord / titre de la fenetre : aussi dedans
        self.assertTrue(window.isVisible())
        window.field.insertPlainText(chr(10) + "nuit")     # on peut continuer a saisir
        self.assertEqual(window.field.lines(), ["ciel", "nuit"])

    def test_clicking_outside_saves_and_closes(self):
        self._click_in(1, "plus")
        window = self.gallery._keywords_window
        window.field.setPlainText("ciel" + chr(10) + "nuit")
        outside = self.host.mapToGlobal(QPoint(self.host.width() - 6, self.host.height() - 6))
        self.assertFalse(window.geometry().contains(outside))
        self._press(self.host, outside)
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.assertEqual(file_attributes.get(self.paths[1])["keywords"], ["ciel", "nuit"])
        self.assertIsNone(self.gallery._keywords_window)

    def test_enter_adds_a_line_and_ctrl_enter_saves(self):
        self._click_in(1, "plus")
        window = self.gallery._keywords_window
        window.field.setPlainText("ciel")
        window.field.moveCursor(QTextCursor.End)
        QApplication.sendEvent(window.field, QKeyEvent(QEvent.KeyPress, Qt.Key_Return, Qt.NoModifier, chr(13)))
        self.assertEqual(window.field.toPlainText(), "ciel" + chr(10))          # Entree = nouvelle ligne
        window.field.insertPlainText("nuit")
        QApplication.sendEvent(window.field, QKeyEvent(QEvent.KeyPress, Qt.Key_Return, Qt.ControlModifier, chr(13)))
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.assertEqual(file_attributes.get(self.paths[1])["keywords"], ["ciel", "nuit"])

    def test_keywords_are_written_on_the_photo_only_when_i_is_pressed(self):
        gallery = self.gallery
        file_attributes.update(self.paths[4], keywords=["ciel", "nuit"])
        gallery.__dict__.get("_attr_values", {}).clear()
        index = gallery.model().index(4, 0)
        size = gallery.gridSize()
        self.addCleanup(setattr, focus, "SHOW_KEYWORDS", False)
        hidden = gallery.cell_pixmap(index, size).toImage()
        QApplication.sendEvent(gallery, QKeyEvent(QEvent.KeyPress, Qt.Key_I, Qt.NoModifier, "i"))
        self.assertTrue(focus.SHOW_KEYWORDS)
        shown = gallery.cell_pixmap(index, size).toImage()
        self.assertNotEqual(hidden, shown)
        QApplication.sendEvent(gallery, QKeyEvent(QEvent.KeyPress, Qt.Key_I, Qt.NoModifier, "i"))
        self.assertFalse(focus.SHOW_KEYWORDS)
        self.assertEqual(hidden, gallery.cell_pixmap(index, size).toImage())


if __name__ == "__main__":
    unittest.main()
