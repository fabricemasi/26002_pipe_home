"""Deplacement des elements de la colonne Type (FileListWidget, _ReorderOverlay) : geste souris
reel (QTest) sur une colonne construite dans un dossier temporaire, jamais sur les vrais dossiers."""
import os as _os, sys as _sys  # jamais les vrais reglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import copy
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

import browser_core
from settings_store import DEFAULT_SETTINGS

browser_core.apply_all_settings(copy.deepcopy(DEFAULT_SETTINGS))

from column import Column


class TypeReorderTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)
        for name in ("Alpha", "Bravo", "Charlie", "Delta"):
            (self.root / name).mkdir()

    def _column(self, title="Type"):
        column = Column(self.root, title)
        column.resize(240, 400)
        column.show()
        column.refresh()
        self.addCleanup(column.deleteLater)
        app.processEvents()
        return column

    @staticmethod
    def _names(column):
        return [column.list.item(i).text() for i in range(column.list.count())]

    def _drag(self, column, row, to_y, release=True):
        view = column.list.viewport()
        start = column.list.visualItemRect(column.list.item(row)).center()
        QTest.mousePress(view, Qt.LeftButton, Qt.ControlModifier, start)     # Ctrl + glisser = replacer
        step = 6 if to_y >= start.y() else -6
        for y in range(start.y(), to_y, step):
            QTest.mouseMove(view, QPoint(start.x(), y))
        if release:
            QTest.mouseRelease(view, Qt.LeftButton, Qt.NoModifier, QPoint(start.x(), to_y))
        app.processEvents()

    def test_drag_moves_the_item_and_the_order_is_kept(self):
        column = self._column()
        last = column.list.visualItemRect(column.list.item(3))
        self._drag(column, 0, last.top() - 6)          # Alpha entre Charlie et Delta
        self.assertEqual(self._names(column), ["Bravo", "Charlie", "Alpha", "Delta"])
        saved = json.loads((self.root / ".pipeline_layout.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["item_order"], ["Bravo", "Charlie", "Alpha", "Delta"])
        (self.root / "Aaa").mkdir()                     # nouveau dossier : apres l'ordre choisi
        self.assertEqual(self._names(self._column()), ["Bravo", "Charlie", "Alpha", "Delta", "Aaa"])

    def test_dragged_item_follows_the_cursor_with_slots(self):
        column = self._column()
        last = column.list.visualItemRect(column.list.item(3))
        self._drag(column, 0, last.bottom() + 2, release=False)
        overlay = column.list._reorder
        self.assertIsNotNone(overlay)
        # Emplacements possibles : tous sauf ceux qui laissent l'element a sa place.
        self.assertEqual([index for index, _y in overlay.slots()], [2, 3, 4])
        self.assertEqual(overlay.target, 4)
        QTest.mouseRelease(column.list.viewport(), Qt.LeftButton, Qt.NoModifier, QPoint(10, last.bottom() + 2))

    def test_escape_cancels(self):
        column = self._column()
        last = column.list.visualItemRect(column.list.item(3))
        self._drag(column, 0, last.bottom() + 2, release=False)
        QTest.keyClick(column.list, Qt.Key_Escape)
        QTest.mouseRelease(column.list.viewport(), Qt.LeftButton, Qt.NoModifier, QPoint(10, last.bottom() + 2))
        app.processEvents()
        self.assertEqual(self._names(column), ["Alpha", "Bravo", "Charlie", "Delta"])
        self.assertFalse((self.root / ".pipeline_layout.json").exists())

    def test_every_column_can_be_reordered_unless_the_setting_is_off(self):
        """Colonnes > « Permettre le replacement des dossiers » : toutes les colonnes (pas seulement
        Type) ; coupe, aucune."""
        column = self._column("Projets")
        self.assertTrue(column.list.reorderable())
        last = column.list.visualItemRect(column.list.item(3))
        self._drag(column, 0, last.top() - 6)
        self.assertEqual(self._names(column), ["Bravo", "Charlie", "Alpha", "Delta"])
        settings = copy.deepcopy(DEFAULT_SETTINGS)
        settings["folder_reorder_enabled"] = False
        browser_core.apply_all_settings(settings)
        self.addCleanup(browser_core.apply_all_settings, copy.deepcopy(DEFAULT_SETTINGS))
        self.assertFalse(self._column("Type").list.reorderable())

    def test_multi_source_column_keeps_its_own_order(self):
        """Colonne a plusieurs sources (IN/OVER/OUT, Logiciels) : ordre range dans la 1re source, sous
        une cle propre a la colonne (la source affichee ailleurs garde son propre ordre)."""
        other = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, other, True)
        (other / "Zulu").mkdir()
        column = Column(self.root, "IN", source_dirs=[self.root, other])
        column.resize(240, 400)
        column.show()
        column.refresh()
        self.addCleanup(column.deleteLater)
        app.processEvents()
        paths = [Path(column.list.item(i).data(browser_core.ROLE_PATH)) for i in range(column.list.count())]
        column.save_item_order([paths[-1]] + paths[:-1])
        self.assertEqual(self._names(column)[0], "Zulu")
        saved = json.loads((self.root / ".pipeline_layout.json").read_text(encoding="utf-8"))
        self.assertIn("item_order@IN", saved)
        self.assertNotIn("item_order", saved)

    def test_space_above_a_row_is_drawn_and_kept(self):
        """Clic droit > « Ajouter une espace au-dessus » sur une ligne : hauteur de la ligne en direct,
        enregistre dans le .pipeline_layout.json et retrouve au prochain affichage."""
        column = self._column()
        item = column.list.item(1)
        before = column.list.visualItemRect(item).height()
        column.set_item_space(item, 25)
        app.processEvents()
        self.assertEqual(column.list.visualItemRect(item).height(), before + 25)
        column._space_timer.stop()
        column._save_item_spaces()
        saved = json.loads((self.root / ".pipeline_layout.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["item_spaces"], {"Bravo": 25})
        again = self._column()
        self.assertEqual(again.list.item(1).data(browser_core.ROLE_SPACE_ABOVE), 25)


class SpaceInThumbnailColumnTest(unittest.TestCase):
    """Colonne a vignettes (Projets) : l'espace au-dessus d'une ligne s'ajoute a sa hauteur, il n'est
    pas pris sur la ligne (hauteurs uniformes de Qt coupees des qu'une ligne a un espace)."""

    def test_space_adds_height_in_the_projects_column(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, True)
        for name in ("abc", "caches", "demo"):
            (root / name).mkdir()
        column = Column(root, "Projets")
        column.resize(260, 400)
        column.show()
        column.refresh()
        self.addCleanup(column.deleteLater)
        app.processEvents()
        self.assertTrue(column.list.uniformItemSizes())
        plain = column.list.visualItemRect(column.list.item(1)).height()
        column.set_item_space(column.list.item(1), 20)
        app.processEvents()
        self.assertFalse(column.list.uniformItemSizes())
        self.assertEqual(column.list.visualItemRect(column.list.item(1)).height(), plain + 20)
        self.assertEqual(column.list.visualItemRect(column.list.item(2)).height(), plain)
        column._save_item_spaces()
        column.refresh()                       # reouverture : toujours pas uniforme
        app.processEvents()
        self.assertFalse(column.list.uniformItemSizes())
        self.assertEqual(column.list.visualItemRect(column.list.item(1)).height(), plain + 20)
        column.set_item_space(column.list.item(1), 0)
        self.assertTrue(column.list.uniformItemSizes())


class ItemTitleTest(unittest.TestCase):
    """Titre pose dans l'espace au-dessus d'une ligne : grise sans assez d'espace, enregistre, retrouve,
    clic droit dessus, style en direct (fenetre flottante Police | Padding)."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)
        for name in ("Alpha", "Bravo"):
            (self.root / name).mkdir()

    def _column(self):
        column = Column(self.root, "Type")
        column.resize(240, 400)
        column.show()
        column.refresh()
        self.addCleanup(column.deleteLater)
        app.processEvents()
        return column

    def test_title_needs_room_is_saved_and_styled(self):
        column = self._column()
        item = column.list.item(1)
        self.assertFalse(column.can_add_title(item))                # pas d'espace au-dessus
        column.set_item_space(item, 4)
        self.assertFalse(column.can_add_title(item))                # trop petit
        column.set_item_space(item, browser_core.item_title_min_height())
        self.assertTrue(column.can_add_title(item))
        column._save_item_spaces()
        key = column._item_key(item)
        column.set_item_title(key, {"text": "Section", "style": {}})
        saved = json.loads((self.root / ".pipeline_layout.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["item_titles"]["Bravo"]["text"], "Section")
        again = self._column()
        item = again.list.item(1)
        self.assertEqual(item.data(browser_core.ROLE_TITLE_ABOVE)["text"], "Section")
        self.assertFalse(again.can_add_title(item))                 # deja un titre
        rect = again.list.visualItemRect(item)
        self.assertTrue(again.title_area_hit(item, QPoint(10, rect.top() + 2)))
        self.assertFalse(again.title_area_hit(item, QPoint(10, rect.bottom() - 2)))
        # Le titre est dessine dans l'espace au-dessus de la ligne.
        image = again.list.viewport().grab().toImage()
        space = QRect(rect.x(), rect.y(), rect.width(), int(item.data(browser_core.ROLE_SPACE_ABOVE)))
        colors = {image.pixel(x, y) for x in range(space.left(), space.right(), 2)
                  for y in range(space.top(), space.bottom())}
        self.assertGreater(len(colors), 1)
        # Style : fenetre flottante, appliquee en direct, enregistree.
        again._open_title_style(key)
        window = again._title_style_window
        fields = dict((spec.key, widget) for spec, widget in window._fields)
        fields["title_font_family"]._v2_parts["size"].setValue(14)
        app.processEvents()
        self.assertEqual(item.data(browser_core.ROLE_TITLE_ABOVE)["style"]["title_font_size"], 14)
        again._save_item_titles()
        saved = json.loads((self.root / ".pipeline_layout.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["item_titles"]["Bravo"]["style"]["title_font_size"], 14)
        window.close()
        # Fermee (donc detruite), elle se rouvre : une 2e ouverture ne doit pas buter sur l'ancienne.
        from PySide6.QtCore import QCoreApplication, QEvent
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        app.processEvents()
        again._open_title_style(key)
        self.assertIsNot(again._title_style_window, window)
        self.assertTrue(again._title_style_window.isVisible())
        again._open_title_style(key)                 # deja ouverte : remplacee par une nouvelle
        self.assertTrue(again._title_style_window.isVisible())
        again._title_style_window.close()
        again.set_item_title(key, None)
        saved = json.loads((self.root / ".pipeline_layout.json").read_text(encoding="utf-8"))
        self.assertNotIn("Bravo", saved["item_titles"])


