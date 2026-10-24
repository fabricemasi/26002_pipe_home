"""Rangee des boutons de la visionneuse / planche (masquer, planche, filtre, PureRef) : Ctrl + glisser un
bouton le deplace (bouton en curseur a 75 %, un seul emplacement en surbrillance), ordre retenu
(`viewer_button_order`) ; sans Ctrl, le clic garde son sens. Dossier temporaire ; reglages jamais ecrits."""
import os as _os, sys as _sys  # jamais les vrais reglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

APP = QApplication.instance() or QApplication([])

import app_style
import browser_core
import pipeline_browser as pb
import settings_store
import ui_state
from browser_core import ROLE_PATH
from settings_layout import _ReorderOverlay


def select(column, name):
    for i in range(column.list.count()):
        item = column.list.item(i)
        if Path(item.data(ROLE_PATH)).name == name:
            column.list.setCurrentItem(item)
            APP.processEvents()
            return
    raise AssertionError(f"{name} absent de {column.column_title}")


def settle(seconds=0.6):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        APP.processEvents()
        time.sleep(0.01)


class ButtonRowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app_style.apply_style(APP)

    def setUp(self):
        for module in (settings_store, pb, browser_core):
            for name in ("save_settings", "_save_window_geometry", "save_layout_settings", "_update_layout_setting"):
                if hasattr(module, name):
                    patcher = mock.patch.object(module, name, lambda *a, **k: None)
                    patcher.start()
                    self.addCleanup(patcher.stop)
        self.saved = []
        patcher = mock.patch.object(settings_store, "save_live_state", lambda k, v: self.saved.append((k, v)))
        patcher.start()
        self.addCleanup(patcher.stop)
        applied = ui_state.APPLIED_SETTINGS
        self.addCleanup(setattr, ui_state, "APPLIED_SETTINGS", applied)
        ui_state.APPLIED_SETTINGS = settings_store.load_settings()
        ui_state.APPLIED_SETTINGS["viewer_button_order"] = []
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)
        folder = self.root / "3d/projA/sp1/in"
        folder.mkdir(parents=True)
        for name in ("a.png", "b.png"):
            image = QImage(64, 48, QImage.Format_RGB32)
            image.fill(QColor("red"))
            image.save(str(folder / name))

    def order(self, win):
        return [key for key, _b in win._viewer_row_items()]

    def xs(self, win):
        return [b.mapTo(win, QPoint(0, 0)).x() for _k, b in win._viewer_row_items()]

    def test_navigation_bar_height_keeps_title_and_buttons_at_top(self):
        ui_state.APPLIED_SETTINGS["navbar_height"] = 90
        win = pb.PipelineBrowser(self.root)
        win._idle_preview_scheduler.timer.stop()
        self.addCleanup(win.deleteLater)
        win.show()
        APP.processEvents()
        self.assertEqual(win.titlebar.height(), app_style.scaled(90))
        self.assertEqual(win.titlebar.title_label.y(), 0)
        self.assertEqual(win.titlebar.btn_min.y(), 0)
        self.assertEqual(win.titlebar.btn_close.y(), 0)

    def test_ctrl_drag_moves_a_button_and_keeps_the_order(self):
        win = pb.PipelineBrowser(self.root)
        win._idle_preview_scheduler.timer.stop()
        win.resize(1500, 850)
        win.show()
        self.addCleanup(win.deleteLater)
        settle(0.2)
        select(win.columns[0], "3d")
        select(win.columns[1], "projA")
        select(win.columns[2], "sp1")
        column = next(c for c in win.group_columns if c._group_kind == "in")
        select(column, "a.png")
        settle()
        win._view_in_viewer(self.root / "3d/projA/sp1/in/a.png")
        settle()
        self.assertTrue(win._project_columns_hidden)
        win._open_focus_gallery()
        settle()
        # Plus de bouton image / planche (demande de l'utilisateur) ; « Récursif » est une icone.
        self.assertEqual(self.order(win), ["filter", "recursive"])
        self.assertIsNone(win.image_preview_columns[0].gallery_btn)
        self.assertEqual(win._recursive_btn._kind, "recursive")
        xs = self.xs(win)
        self.assertEqual(xs, sorted(xs))                                  # de gauche a droite, dans l'ordre
        button = win._recursive_btn
        clicked = []
        button.clicked.connect(lambda: clicked.append(True))
        first = win._viewer_row_items()[0][1]
        target = first.mapTo(win, QPoint(0, 0)) - button.mapTo(win, QPoint(0, 0)) + QPoint(2, 5)
        with mock.patch.object(QApplication, "keyboardModifiers", return_value=Qt.ControlModifier):
            QTest.mousePress(button, Qt.LeftButton, Qt.ControlModifier, QPoint(5, 5))
            QTest.mouseMove(button, QPoint(20, 5))
            overlay = win._button_drag.overlay
            self.assertIsInstance(overlay, _ReorderOverlay)               # bouton en curseur, a 75 %
            self.assertEqual(overlay.GHOST_OPACITY, 0.75)
            QTest.mouseMove(button, target)
            self.assertEqual(overlay.target, 0)                            # un seul emplacement : le premier
            QTest.mouseRelease(button, Qt.LeftButton, Qt.ControlModifier, target)
        settle(0.1)
        self.assertEqual(clicked, [])                                      # Ctrl + glisser : pas de clic
        self.assertEqual(self.order(win), ["recursive", "filter"])
        self.assertEqual(self.saved[-1], ("viewer_button_order", ["recursive", "filter"]))
        xs = self.xs(win)
        self.assertEqual(xs, sorted(xs))
        # Tous les boutons sont dans le cadre « Visionneuse » de la barre de navigation (demande de l'utilisateur).
        pc = win.image_preview_columns[0]
        self.assertIsNone(pc.toggle_btn)
        self.assertIsNone(pc.hide_btn)
        group = win.titlebar.viewer_group()
        self.assertTrue(group.isVisible())
        self.assertTrue(all(b.parentWidget() is group for _k, b in win._viewer_row_items()))
        self.assertTrue(group.rect().contains(win._filter_btn.geometry()))
        # Sans Ctrl : clic normal (la fenetre des filtres s'ouvre).
        with mock.patch("settings_quick_style.save_settings"):
            QTest.mouseClick(win._filter_btn, Qt.LeftButton)
            self.assertIsNotNone(win._filter_window)
            win._filter_window.close()
        # Retour aux colonnes : les boutons repartent chez eux, le cadre se cache.
        win._set_columns_hidden(False, animate=False)
        settle(0.2)
        self.assertTrue(group.isHidden())
        self.assertIs(win._filter_btn.parentWidget(), win.scroll.viewport())


if __name__ == "__main__":
    unittest.main()
