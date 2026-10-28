"""Fenetre de reglages v2 gardee en memoire : creee cachee au lancement, sections construites en fond, rouverte telle
quelle (remise a jour des reglages changes dehors) ; jetee si l'on a annule des modifications."""
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

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication

APP = QApplication.instance() or QApplication([])

import pipeline_browser as pb
import settings_window_v2 as v2


def settle(seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        APP.processEvents()
        time.sleep(0.005)


class PreloadTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)
        (self.root / "a").mkdir()
        self.win = pb.PipelineBrowser(self.root)
        self.win._idle_preview_scheduler.timer.stop()
        self.addCleanup(self.win.deleteLater)
        self.win.show()
        settle(0.2)

    def _watch(self, used=False):
        """Releve d'activite branche, horloge d'entree simulee (jamais celle de la vraie machine)."""
        win = self.win
        patch = mock.patch.object(pb.PipelineBrowser, "_app_used_recently", lambda _self: used)
        patch.start()
        self.addCleanup(patch.stop)
        with mock.patch("main_window.settings_link.settings_window_v2_preload_enabled", lambda: True):
            win._start_settings_idle_watch()
        self.addCleanup(win._settings_idle_timer.stop)
        self.addCleanup(win._stop_settings_idle_load)
        # Fenetre preparee DETRUITE avec le test (processEvents ne traite pas les deleteLater) : ses ~24 000 widgets
        # ralentissaient les tests suivants (restylages de toutes les zones de saisie inscrites...).
        def destroy():
            dialog = getattr(win, "_settings_dialog_v2", None)
            if dialog is not None:
                dialog.deleteLater()
                win._settings_dialog_v2 = None
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.addCleanup(destroy)

    def _fast_prebuild(self):
        v2.SettingsWindowV2.PREBUILD_GAP_MS = 0
        v2.SettingsWindowV2.PREBUILD_DUTY = 1.0
        v2.SettingsWindowV2.PREBUILD_UNATTENDED_DUTY = 1.0
        v2.SettingsWindowV2.PREBUILD_IDLE_MS = 0
        self.addCleanup(setattr, v2.SettingsWindowV2, "PREBUILD_DUTY", 0.25)
        self.addCleanup(setattr, v2.SettingsWindowV2, "PREBUILD_UNATTENDED_DUTY", 0.5)
        self.addCleanup(setattr, v2.SettingsWindowV2, "PREBUILD_IDLE_MS", 600)
        self.addCleanup(setattr, v2.SettingsWindowV2, "PREBUILD_GAP_MS", 25)

    def test_nothing_is_loaded_before_a_minute_without_activity(self):
        win = self.win
        self._watch()
        win._settings_idle_tick()
        self.assertIsNone(getattr(win, "_settings_dialog_v2", None))  # rien au lancement
        win._app_input_at -= 59
        win._settings_idle_tick()
        self.assertIsNone(getattr(win, "_settings_dialog_v2", None))
        win._app_input_at -= 2
        win._settings_idle_tick()
        self.assertTrue(win._settings_idle_loading)
        self.assertIsNotNone(win._settings_dialog_v2)
        self.assertTrue(win.titlebar._load_bar.isVisible())          # barre « Réglages n % »

    def test_user_input_stops_the_loading_at_once(self):
        win = self.win
        self._watch()
        win._app_input_at -= 61
        win._settings_idle_tick()
        self.assertTrue(win._settings_idle_loading)
        from PySide6.QtCore import QEvent
        event = mock.Mock()
        event.type.return_value = QEvent.KeyPress
        event.spontaneous.return_value = True
        win._idle_input_watch.eventFilter(win, event)                 # l'utilisateur revient
        self.assertFalse(win._settings_idle_loading)
        self.assertFalse(win.titlebar._load_bar.isVisible())
        self.assertTrue(win._settings_prebuild_hold())                 # preparation suspendue
        self.assertLess(time.monotonic() - win._app_input_at, 1)      # la minute est recomptee

    def test_no_loading_while_a_module_is_open(self):
        win = self.win
        self._watch()
        win._md_open = True
        self.addCleanup(setattr, win, "_md_open", False)
        win._app_input_at -= 120
        win._settings_idle_tick()
        self.assertFalse(win._settings_idle_loading)
        self.assertIsNone(getattr(win, "_settings_dialog_v2", None))
        win._md_open = False                                          # fermee : la minute repart de la
        win._settings_idle_tick()
        self.assertFalse(win._settings_idle_loading)
        win._app_input_at -= 61
        win._settings_idle_tick()
        self.assertTrue(win._settings_idle_loading)
        win._board = object()                                         # un module s'ouvre pendant le chargement
        self.addCleanup(setattr, win, "_board", None)
        win._settings_idle_tick()
        self.assertFalse(win._settings_idle_loading)

    def test_dialog_is_prepared_hidden_then_reused(self):
        win = self.win
        self._watch()
        self._fast_prebuild()
        win._app_input_at -= 61
        win._settings_idle_tick()
        dialog = win._settings_dialog_v2
        self.assertFalse(dialog.isVisible())                          # cachee
        seen = []
        bar = win.titlebar._load_bar
        end = time.monotonic() + 90
        while time.monotonic() < end and not dialog.prebuild_finished():
            APP.processEvents()
            if bar.isVisible():
                seen.append(bar.value())
        self.assertTrue(dialog.prebuild_finished())
        self.assertTrue(all(n._built for n in dialog.findChildren(v2._LazyNode)))   # construite sans etre affichee
        self.assertEqual(seen, sorted(seen))                          # avancement croissant
        self.assertGreater(len(set(seen)), 3)
        self.assertFalse(bar.isVisible())                             # tout est pret : la barre disparait
        self.assertFalse(win._settings_idle_loading)
        win.open_settings_v2()
        self.assertIs(win._settings_dialog_v2, dialog)                # la meme fenetre, rien de reconstruit
        self.assertTrue(dialog.isVisible())
        dialog.reject()                                               # fermee sans rien changer
        self.assertFalse(dialog.isVisible())
        win.open_settings_v2()
        self.assertIs(win._settings_dialog_v2, dialog)                # reutilisee encore
        dialog.reject()

    def test_reopen_takes_changes_made_outside(self):
        win = self.win
        win.open_settings_v2()
        dialog = win._settings_dialog_v2
        dialog.reject()
        import settings_store
        settings = settings_store.load_settings()
        settings["viewer_filmstrip_enabled"] = not settings.get("viewer_filmstrip_enabled", True)
        with mock.patch.object(settings_store, "load_settings", return_value=settings), \
                mock.patch.object(v2, "load_settings", return_value=settings):
            win.open_settings_v2()
        self.assertIs(win._settings_dialog_v2, dialog)
        self.assertEqual(dialog.settings["viewer_filmstrip_enabled"], settings["viewer_filmstrip_enabled"])
        self.assertFalse(dialog._dirty)
        dialog.reject()

    def test_cancelling_modifications_discards_the_dialog(self):
        win = self.win
        win.open_settings_v2()
        dialog = win._settings_dialog_v2
        dialog._mark_dirty()
        dialog.reject()
        self.assertTrue(dialog.discard_on_reopen())
        win.open_settings_v2()
        self.assertIsNot(win._settings_dialog_v2, dialog)             # champs a valeurs annulees : refaite
        win._settings_dialog_v2.reject()


if __name__ == "__main__":
    unittest.main()
