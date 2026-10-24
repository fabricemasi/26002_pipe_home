"""Paragraphes de la fenetre de reglages v2 reordonnes en TIRANT leur titre : le paragraphe suit le
curseur (_ReorderOverlay), son ordre est applique (layout, accordeon, voisins des boites), retenu
(`title_order`) et repris a la reouverture ; un simple clic replie / deplie toujours."""
import os as _os, sys as _sys  # jamais les vrais reglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import copy
import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

import settings_window_v2 as v2
from settings_layout import _ReorderOverlay
from settings_store import DEFAULT_SETTINGS as _DEFAULTS
from settings_widgets import set_space_above, set_space_below

v2.AUTOSAVE = False


def send(widget, kind, pos: QPoint, button=Qt.LeftButton, buttons=Qt.LeftButton):
    event = QMouseEvent(kind, QPointF(pos), QPointF(widget.mapToGlobal(pos)), button, buttons, Qt.NoModifier)
    QApplication.sendEvent(widget, event)


class TitleReorderTest(unittest.TestCase):
    def setUp(self):
        self._real = v2.load_settings
        self.settings = copy.deepcopy(_DEFAULTS)
        v2.load_settings = lambda: copy.deepcopy(self.settings)
        self.addCleanup(setattr, v2, "load_settings", self._real)
        self.win = self._open()

    def _open(self):
        win = v2.SettingsWindowV2()
        win.resize(1300, 900)
        win.show()
        for _ in range(5):
            app.processEvents()
        self.addCleanup(win.close)
        return win

    def _sections(self, win):
        inner = win.stack.widget(0).findChild(v2._WideScrollArea).widget()
        return inner._title_stack

    def _drag(self, header, start: QPoint, dy: int, watch=None):
        # Deplacer = Ctrl + glisser (partout dans l'appli).
        from unittest import mock
        from PySide6.QtWidgets import QApplication
        ctrl = mock.patch.object(QApplication, "keyboardModifiers", return_value=Qt.ControlModifier)
        ctrl.start()
        self.addCleanup(ctrl.stop)
        send(header, QEvent.MouseButtonPress, start)
        steps = 8
        for k in range(1, steps + 1):
            send(header, QEvent.MouseMove, start + QPoint(0, dy * k // steps), Qt.NoButton)
            app.processEvents()
            if watch is not None and k == steps // 2:
                watch()
        send(header, QEvent.MouseButtonRelease, start + QPoint(0, dy), buttons=Qt.NoButton)
        app.processEvents()

    def test_drag_moves_a_paragraph_and_is_remembered(self):
        stack = self._sections(self.win)
        titles = [n.node.title for n in stack.nodes]
        first, second = stack.nodes[0], stack.nodes[1]
        header = first.head
        start = QPoint(30, header.height() // 2)
        seen = []

        def watch():
            overlays = stack.container.findChildren(_ReorderOverlay)
            seen.append(bool(overlays) and overlays[0].isVisible())
        # Tirer le 1er titre sous le 2e (un peu plus bas que la hauteur des deux titres replies).
        self._drag(header, start, first.height() + second.height() // 2 + 6, watch)
        self.assertEqual(seen, [True])                                   # le paragraphe suit le curseur
        self.assertFalse(stack.container.findChildren(_ReorderOverlay))  # ... et la couche disparait
        expected = [titles[1], titles[0]] + titles[2:]
        self.assertEqual([n.node.title for n in stack.nodes], expected)
        layout = stack.container.layout()
        self.assertLess(layout.indexOf(stack.nodes[0]), layout.indexOf(stack.nodes[1]))
        self.assertIs(stack.nodes[0]._head._box_prev, None)              # voisins des boites a jour
        self.assertIs(stack.nodes[1]._head._box_prev, stack.nodes[0]._head)
        self.assertTrue(first.is_collapsed())                           # un deplacement ne deplie rien
        self.assertEqual(self.win.settings["title_order"]["General|"], expected)
        # Reouverture : meme ordre.
        self.settings["title_order"] = dict(self.win.settings["title_order"])
        again = self._open()
        self.assertEqual([n.node.title for n in self._sections(again).nodes], expected)

    def test_plain_click_still_toggles(self):
        node = self._sections(self.win).nodes[0]
        pos = QPoint(30, node.head.height() // 2)
        self.assertTrue(node.is_collapsed())
        send(node.head, QEvent.MouseButtonPress, pos)
        send(node.head, QEvent.MouseButtonRelease, pos, buttons=Qt.NoButton)
        app.processEvents()
        self.assertFalse(node.is_collapsed())

    def test_sub_paragraphs_reorder_inside_their_parent(self):
        node = next(n for n in self._sections(self.win).nodes if n.node.title == "TITRES")
        node.set_collapsed(False)
        app.processEvents()
        stack = node._child_wrap._title_stack
        titles = [n.node.title for n in stack.nodes]
        first = stack.nodes[0]
        self._drag(first.head, QPoint(30, first.head.height() // 2), first.height() + stack.nodes[1].height() // 2 + 6)
        self.assertEqual([n.node.title for n in stack.nodes], [titles[1], titles[0]])
        self.assertEqual(self.win.settings["title_order"]["General|TITRES"], [titles[1], titles[0]])

    def test_above_and_below_spaces_move_with_their_sections(self):
        stack = self._sections(self.win)
        first, second = stack.nodes[:2]
        set_space_above(first, 13)
        set_space_below(first, 27)
        set_space_above(second, 41)
        set_space_below(second, 55)

        layout = stack.container.layout()
        trailing_stretch = layout.itemAt(layout.count() - 1).spacerItem()
        stack.apply([second, first, *stack.nodes[2:]])
        self.assertIs(layout.itemAt(layout.count() - 1).spacerItem(), trailing_stretch)
        for node, above, below in ((second, 41, 55), (first, 13, 27)):
            index = layout.indexOf(node)
            self.assertIs(layout.itemAt(index - 1).spacerItem(), node._space_above_item)
            self.assertEqual(layout.itemAt(index - 1).spacerItem().sizeHint().height(), above)
            self.assertIs(layout.itemAt(index + 1).spacerItem(), node._space_below_item)
            self.assertEqual(layout.itemAt(index + 1).spacerItem().sizeHint().height(), below)


if __name__ == "__main__":
    unittest.main()
