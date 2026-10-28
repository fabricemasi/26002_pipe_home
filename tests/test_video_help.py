import _isolate
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import unittest
from unittest.mock import patch
from PySide6.QtWidgets import QApplication,QWidget,QSpinBox,QVBoxLayout
from PySide6.QtCore import Qt,QEvent,QPoint
from PySide6.QtGui import QKeyEvent,QCursor
from fm_video.help_ui import HelpController,Glossary,annotate
from fm_video.help_content import HELP,GLOSSARY,page

APP = QApplication.instance() or QApplication([])


class ColorHelpTest(unittest.TestCase):
    def setUp(self):
        self.root = QWidget()
        layout = QVBoxLayout(self.root)
        self.spin = QSpinBox(self.root)
        layout.addWidget(self.spin)
        annotate(self.spin,'palette')
        self.help = HelpController(self.root,dict(video_help_delay=0))
        self.root.show()
        APP.processEvents()

    def tearDown(self):
        self.help.dismiss()
        APP.removeEventFilter(self.help)
        self.help.popup.close()
        self.root.close()
        self.root.deleteLater()
        APP.processEvents()

    def test_inner_editor_resolves_to_annotated_spin(self):
        widget,key = self.help.resolve(self.spin.lineEdit())
        self.assertIs(widget,self.spin)
        self.assertEqual(key,'palette')

    def test_modifier_gesture_and_release(self):
        with patch.object(QApplication,'keyboardModifiers',return_value=Qt.ControlModifier|Qt.ShiftModifier), \
             patch.object(QApplication,'activeWindow',return_value=self.root), \
             patch.object(QApplication,'widgetAt',return_value=self.spin):
            event = QKeyEvent(QEvent.KeyPress,Qt.Key_Shift,Qt.ControlModifier|Qt.ShiftModifier)
            self.assertFalse(self.help.eventFilter(self.spin,event))
            self.assertTrue(self.help.timer.isActive())
            self.help._tick()
            self.assertTrue(self.help.popup.isVisible())
            self.assertIn('Palette chromatique',self.help.browser.toPlainText())
        with patch.object(QApplication,'keyboardModifiers',return_value=Qt.NoModifier):
            self.help._tick()
        self.assertFalse(self.help.popup.isVisible())
        self.assertFalse(self.help.timer.isActive())

    def test_disabled_or_inactive_help_does_not_show(self):
        self.help.settings['video_help_enabled'] = False
        self.help._tick()
        self.assertFalse(self.help.popup.isVisible())

    def test_held_modifiers_before_hover_and_popup_stays_on_screen(self):
        with patch.object(QApplication,'keyboardModifiers',return_value=Qt.ControlModifier|Qt.ShiftModifier), \
             patch.object(QApplication,'activeWindow',return_value=self.root), \
             patch.object(QApplication,'widgetAt',return_value=self.spin), \
             patch.object(QCursor,'pos',return_value=QPoint(10000,10000)):
            self.help.eventFilter(self.spin,QEvent(QEvent.Enter))
            self.assertTrue(self.help.timer.isActive())
            self.help._tick()
            area = QApplication.primaryScreen().availableGeometry()
            self.assertTrue(area.contains(self.help.popup.geometry()))

    def test_delay_and_f1(self):
        self.help.settings['video_help_delay'] = 2000
        with patch.object(QApplication,'keyboardModifiers',return_value=Qt.ControlModifier|Qt.ShiftModifier), \
             patch.object(QApplication,'activeWindow',return_value=self.root), \
             patch.object(QApplication,'widgetAt',return_value=self.spin):
            self.help._tick()
            self.assertFalse(self.help.popup.isVisible())
        with patch.object(QApplication,'focusWidget',return_value=self.spin):
            handled = self.help.eventFilter(self.spin,QKeyEvent(QEvent.KeyPress,Qt.Key_F1,Qt.NoModifier))
            self.assertTrue(handled)
            self.assertTrue(self.help.glossary.isVisible())
        self.help.glossary.close()
        self.help.settings['video_help_enabled'] = True
        with patch.object(QApplication,'keyboardModifiers',return_value=Qt.ControlModifier|Qt.ShiftModifier), \
             patch.object(QApplication,'activeWindow',return_value=None):
            self.help._tick()
        self.assertFalse(self.help.popup.isVisible())

    def test_no_application_wide_event_filter(self):
        # Un filtre sur toute l'application faisait passer chaque evenement de l'appli par du Python, une fois
        # par fenetre qui a l'aide (fenetre de reglages prechargee comprise).
        with patch.object(QApplication,'installEventFilter') as installed:
            other = QWidget()
            controller = HelpController(other)
            self.assertFalse(installed.called)
            controller.deleteLater()
            other.deleteLater()

    def test_watch_starts_the_gesture_only_while_the_window_is_shown(self):
        self.assertTrue(self.help.watch.isActive())
        with patch.object(QApplication,'keyboardModifiers',return_value=Qt.ControlModifier|Qt.ShiftModifier):
            self.help._watch()
        self.assertTrue(self.help.timer.isActive())
        self.help.dismiss()
        self.root.hide()
        APP.processEvents()
        self.assertFalse(self.help.watch.isActive())
        self.root.show()
        APP.processEvents()
        self.assertTrue(self.help.watch.isActive())

    def test_f1_shortcut_opens_the_glossary_on_the_focused_notion(self):
        with patch.object(QApplication,'focusWidget',return_value=self.spin.lineEdit()):
            self.help.f1.activated.emit()
        self.assertTrue(self.help.glossary.isVisible())
        self.assertIn('Palette chromatique',self.help.glossary.browser.toPlainText())
        self.help.glossary.close()

    def test_glossary_search_and_required_help_sections(self):
        glossary = Glossary(self.root,'matching')
        self.assertIn('Matching',glossary.browser.toPlainText())
        glossary.search.setText('regularisation')
        self.assertGreater(glossary.list.count(),0)
        glossary.search.setText('introuvable-xyz-123')
        self.assertEqual(glossary.list.count(),0)
        self.assertIn('Aucune notion',glossary.browser.toPlainText())
        self.assertGreaterEqual(len(GLOSSARY),35)
        for key in HELP:
            self.assertEqual(page(key).count('<h3>'),8)
        glossary.close()
