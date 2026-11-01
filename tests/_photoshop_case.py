"""Aide commune aux tests d'intégration Photoshop : un Board réel (BoardPane), le VRAI chemin (icône de la barre des
modules -> barre du module -> fenêtre « Nouveau document » -> élément -> double-clic -> éditeur Standard)."""
import os as _os, sys as _sys  # jamais les vrais réglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QPoint, QPointF, Qt, QTimer  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

APP = QApplication.instance() or QApplication([])

from fm_board import serialization  # noqa: E402
from fm_board import ui as board_ui  # noqa: E402
from fm_photoshop.board_item import PsItem  # noqa: E402
from fm_photoshop.board_ui import NewDocumentDialog  # noqa: E402

_PANES = []


def settle(seconds=0.05):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        APP.processEvents()
        time.sleep(0.003)


class PsCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="photoshop_test_"))
        self.path = serialization.create_board_file(self.tmp / "essai.mro")
        self.make_pane(self.path)

    def make_pane(self, path):
        self.host = QWidget()
        self.host.resize(1400, 900)
        self.pane = board_ui.BoardPane(self.host)
        _PANES.append(self.pane)
        self.assertTrue(self.pane.open(path))
        self.pane.resize(1400, 900)
        self.host.show()
        self.pane.show()
        settle()
        return self.pane

    def tearDown(self):
        for pane in _PANES:
            try:
                std = getattr(pane, "_photoshop_standard", None)
                if std is not None:
                    std.close_pane()
                pane._autosave.stop()
                pane.deleteLater()
            except RuntimeError:
                pass
        _PANES.clear()
        self.host.deleteLater()
        settle(0.02)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def create_via_ui(self, w=64, h=48, name="Essai", background="Blanc"):
        if self.pane.module != "photoshop":                              # re-clic = aucun module
            self.pane._modulebar.rows["photoshop"].icon.click()
        settle()
        ctl = self.pane.photoshop
        self.assertIsNotNone(ctl)
        self.assertTrue(ctl.active and ctl.bar.isVisible())

        def fill():
            for widget in QApplication.topLevelWidgets():
                if isinstance(widget, NewDocumentDialog):
                    widget.name.setText(name)
                    widget.width_box.setValue(w)
                    widget.height_box.setValue(h)
                    widget.background.setCurrentText(background)
                    widget.accept()
        QTimer.singleShot(50, fill)
        ctl.buttons["new"].click()
        settle()
        items = [i for i in self.pane.scene.board_items() if isinstance(i, PsItem)]
        self.assertTrue(items)
        return items[-1]

    def open_standard_by_double_click(self, item):
        item.setSelected(True)
        view = self.pane.view
        w, h = item.size()
        pos = view.mapFromScene(item.mapToScene(QPointF(w / 2, h / 2)))
        QTest.mouseDClick(view.viewport(), Qt.LeftButton, Qt.NoModifier, pos)
        settle()
        return getattr(self.pane, "_photoshop_standard", None)

    def editor(self, w=64, h=48, name="Essai", background="Blanc", zoom=4.0):
        """Document neuf ouvert dans l'éditeur Standard, vue centrée au zoom donné."""
        item = self.create_via_ui(w, h, name, background)
        std = self.open_standard_by_double_click(item)
        self.assertIsNotNone(std)
        std.canvas.set_zoom(zoom)
        std.session.center = (w / 2.0, h / 2.0)
        settle()
        return item, std

    @staticmethod
    def at(canvas, x, y):
        """Position du widget (QPoint) du point (x, y) du document."""
        p = canvas.to_widget(x, y)
        return QPoint(round(p.x()), round(p.y()))

    @staticmethod
    def release_modifiers(widget):
        """QTest laisse les modificateurs d'un clic « tenus » pour l'application : on les relâche (sinon l'Alt d'un test
        isolerait un module au clic suivant)."""
        for key in (Qt.Key_Alt, Qt.Key_Control, Qt.Key_Shift):
            QTest.keyRelease(widget, key)

    def drag(self, canvas, points, modifiers=Qt.NoModifier):
        QTest.mousePress(canvas, Qt.LeftButton, modifiers, points[0])
        for p in points[1:]:
            QTest.mouseMove(canvas, p)
            APP.processEvents()
        QTest.mouseRelease(canvas, Qt.LeftButton, modifiers, points[-1])
        APP.processEvents()
        if modifiers != Qt.NoModifier:
            self.release_modifiers(canvas)

    def click(self, canvas, x, y, modifiers=Qt.NoModifier):
        QTest.mouseClick(canvas, Qt.LeftButton, modifiers, self.at(canvas, x, y))
        APP.processEvents()
        if modifiers != Qt.NoModifier:
            self.release_modifiers(canvas)
