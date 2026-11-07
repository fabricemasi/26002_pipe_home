"""PIPE FMZ COMPLET avec l'agenda (lent : fenêtre principale entière, réglages isolés) : bouton « Agenda » de la
barre, ouverture plein cadre, cadre « Agenda » de la barre de navigation, événement créé puis retrouvé après
fermeture / relance de la fenêtre, autre module qui range l'agenda, réglages de l'agenda, fermeture sans plantage."""
import os as _os, sys as _sys  # jamais les vrais réglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import os
import tempfile
import time
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from _lent import lent  # noqa: E402


def _pump(app, seconds):
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        app.processEvents()
        time.sleep(0.005)


@lent
class AgendaAppTest(unittest.TestCase):
    def _window(self, root):
        from PySide6.QtWidgets import QApplication
        from settings_store import load_settings
        import pipeline_browser as pb
        settings = load_settings()
        pb.apply_all_settings(settings)
        app = QApplication.instance() or QApplication([])
        win = pb.PipelineBrowser(root)
        win.resize(1500, 950)
        win.show()
        _pump(app, 0.4)
        return app, win

    def _close(self, app, win):
        from PySide6.QtCore import QEvent
        from PySide6.QtWidgets import QApplication
        win.close()
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        win.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        _pump(app, 0.2)

    def test_agenda_opens_from_the_navigation_bar_and_keeps_events(self):
        tmp = Path(tempfile.mkdtemp(prefix="agenda_app_"))
        root = tmp / "racine"
        (root / "26014_Teaser").mkdir(parents=True)
        app, win = self._window(root)
        self.assertTrue(hasattr(win, "btn_agenda"))
        self.assertTrue(win.btn_agenda.isEnabled())
        win.btn_agenda.click()                                          # bouton « Agenda » de la barre
        _pump(app, 0.2)
        pane = win._agenda
        self.assertIsNotNone(pane)
        self.assertTrue(pane.isVisible())
        self.assertFalse(win.scroll.widget().isVisible())               # colonnes masquées sous l'agenda
        self.assertTrue(win.titlebar.agenda_group().isVisible())        # cadre « Agenda » de la barre
        self.assertEqual(len(win._agenda_buttons), 5)
        service = win._agenda_service
        tz = service.display_tz
        from fm_agenda.core import timeutil as tu
        day = date.today() + timedelta(days=1)
        draft = service.new_draft(tu.localize(datetime(day.year, day.month, day.day, 10), tz))
        draft.title = "Revue client — test de l'appli"
        draft.project = "26014 Teaser"
        service.create(draft)
        pane.set_view("planning")
        _pump(app, 0.2)
        titles = [r[2].title for r in pane.planning.rows if r[1] == "item"]
        self.assertIn("Revue client — test de l'appli", titles)
        self.assertEqual(win._agenda_project_folder("26014 Teaser"), str(root / "26014_Teaser"))
        win.open_module_settings("agenda")                              # fenêtre « Réglages : Agenda »
        _pump(app, 0.5)
        dialog = win._module_settings["agenda"]
        self.assertTrue(dialog.isVisible())
        dialog.close()
        win.btn_agenda.click()                                          # second clic : l'agenda se range
        _pump(app, 0.1)
        self.assertFalse(pane.isVisible())
        self.assertTrue(win.scroll.widget().isVisible())
        self.assertFalse(win.titlebar.agenda_group().isVisible())
        self.assertTrue(win._open_agenda())
        self.assertTrue(win._leave_agenda())                            # un autre module le range
        self.assertFalse(pane.isVisible())
        self._close(app, win)
        app, win = self._window(root)                                   # « relance » : la base est retrouvée
        self.assertTrue(win._open_agenda())
        win._agenda.set_view("planning")
        _pump(app, 0.2)
        titles = [r[2].title for r in win._agenda.planning.rows if r[1] == "item"]
        self.assertIn("Revue client — test de l'appli", titles)
        self._close(app, win)


    def test_agenda_is_prepared_while_the_app_is_idle(self):
        """Fluidité : imports dans un fil de fond, puis service, panneau caché et éditeur préparés une étape par
        tick d'inactivité ; rien tant que l'utilisateur agit ; le premier clic montre le panneau déjà construit."""
        from unittest import mock
        tmp = Path(tempfile.mkdtemp(prefix="agenda_idle_"))
        root = tmp / "racine"
        root.mkdir(parents=True)
        app, win = self._window(root)
        win._agenda_idle_timer.stop() if getattr(win, "_agenda_idle_timer", None) else None
        win._start_agenda_background()
        win._agenda_idle_timer.stop()                                   # étapes pilotées par le test
        win._agenda_warm.join(30)
        with mock.patch.object(type(win), "_app_used_recently", lambda self: True):
            win._agenda_idle_step()
        self.assertEqual(win._agenda_steps[0], "service")               # l'utilisateur agit : rien
        with mock.patch.object(type(win), "_app_used_recently", lambda self: False):
            for _ in range(3):
                win._agenda_idle_step()
        self.assertIsNotNone(win._agenda_service)
        pane = win._agenda
        self.assertIsNotNone(pane)
        self.assertFalse(pane.isVisible())                              # préparé caché
        self.assertIsNotNone(pane._editor)
        import time as _t
        t0 = _t.perf_counter()
        win.btn_agenda.click()
        app.processEvents()
        self.assertLess(_t.perf_counter() - t0, 0.25)
        self.assertIs(win._agenda, pane)
        self.assertTrue(pane.isVisible())
        self._close(app, win)


if __name__ == "__main__":
    unittest.main()
