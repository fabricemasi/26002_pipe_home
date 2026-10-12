"""Tous les tableaux : glisser une pastille de couleur sur une autre lui COPIE sa couleur (pastille de l'appli
avec son opacite, ou couleur personnalisee). Pastille tiree a 75 % sous le curseur, pastille visee entouree."""
import os as _os, sys as _sys  # jamais les vrais reglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import os
import sys
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

import settings_sections as ss
import settings_window_v2 as v2
from settings_store import M

COLORS = dict(M)


class ColorDragTest(unittest.TestCase):
    def fields(self):
        source = ss._CompactAppOrCustomColorField("@accent/60", COLORS)
        target = ss._CompactAppOrCustomColorField("#123456", COLORS)
        for f in (source, target):
            f.show()
            self.addCleanup(f.deleteLater)
        return source, target

    def test_drag_starts_with_the_value_and_a_translucent_ghost(self):
        source, _target = self.fields()
        started = {}

        def fake_exec(drag, *_a):
            started["mime"] = bytes(drag.mimeData().data(ss._CompactAppOrCustomColorField.MIME)).decode()
            image = drag.pixmap().toImage()
            started["alpha"] = image.pixelColor(image.width() // 2, image.height() // 2).alpha()
            return Qt.CopyAction
        clicked = []
        source.swatch.clicked.connect(lambda: clicked.append(True))
        with mock.patch.object(ss.QDrag, "exec", fake_exec):
            QTest.mousePress(source.swatch, Qt.LeftButton, Qt.NoModifier, QPoint(3, 3))
            QTest.mouseMove(source.swatch, QPoint(15, 15))
            QTest.mouseRelease(source.swatch, Qt.LeftButton, Qt.NoModifier, QPoint(15, 15))
        self.assertEqual(started["mime"], "@accent/60")
        self.assertTrue(170 <= started["alpha"] <= 200, started["alpha"])     # 75 %
        self.assertEqual(clicked, [])                                          # glisser : pas de menu

    def test_drop_copies_the_value_and_signals_it(self):
        source, target = self.fields()
        got = []
        target.changed.connect(got.append)
        mime = QMimeData()
        mime.setData(ss._CompactAppOrCustomColorField.MIME, b"@accent/60")
        pos = QPointF(target.swatch.rect().center())
        enter = QDragEnterEvent(pos.toPoint(), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
        QApplication.sendEvent(target.swatch, enter)
        self.assertTrue(enter.isAccepted())
        self.assertTrue(target.swatch._drop_hover)                             # pastille visee entouree
        drop = QDropEvent(pos, Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
        QApplication.sendEvent(target.swatch, drop)
        self.assertFalse(target.swatch._drop_hover)
        self.assertEqual(target.value(), "@accent/60")
        self.assertTrue(target.app_toggle.isChecked())
        self.assertEqual(got, ["@accent/60"])

    def test_palette_swatches_of_the_colours_section(self):
        # Section Couleurs (pastilles de la palette, _ColorField) : meme glisser-copier (signale : rien ne se
        # passait). Une couleur de l'appli « @pastille » y devient une vraie couleur.
        import settings_colorpicker as scp
        from settings_v2_app import SemanticColorField
        target = SemanticColorField("#112233", "Fond")
        self.addCleanup(target.deleteLater)
        swatch = target.field.swatch
        got = []
        target.changed.connect(lambda: got.append(target.value()))
        mime = QMimeData()
        mime.setData(scp.COLOR_MIME, b"#ff00eb")
        pos = QPointF(swatch.rect().center())
        enter = QDragEnterEvent(pos.toPoint(), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
        QApplication.sendEvent(swatch, enter)
        self.assertTrue(enter.isAccepted())
        QApplication.sendEvent(swatch, QDropEvent(pos, Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier))
        self.assertEqual(target.value(), "#ff00eb")
        self.assertEqual(target.hex.text(), "#ff00eb")
        self.assertEqual(got, ["#ff00eb"])
        self.assertEqual(scp.COLOR_MIME, ss._CompactAppOrCustomColorField.MIME)   # copie entre les deux
        self.assertTrue(scp.plain_color("@accent").startswith("#"))
        # Tiree : sa valeur part avec elle.
        captured = []
        with mock.patch.object(scp.QDrag, "exec", lambda drag, *a: captured.append(
                bytes(drag.mimeData().data(scp.COLOR_MIME)).decode())):
            swatch._color_drag._press = QPointF(4, 4).toPoint()
            swatch._color_drag._start()
        self.assertEqual(captured, ["#ff00eb"])

    def test_header_colours_keep_their_bare_format(self):
        target = v2._CompactHeaderColor("skinN1", COLORS, "Entete")
        self.addCleanup(target.deleteLater)
        target.receive_color("@accent/60")
        self.assertEqual(target.value(), "accent/60")
        target.receive_color("#abcdef")
        self.assertEqual(target.value(), "#abcdef")


if __name__ == "__main__":
    unittest.main()
