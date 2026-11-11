"""fm_taches dans l'Agenda : tâches datées montrées dans les vues de l'agenda par les HOOKS du panneau (l'agenda
n'importe pas fm_taches), journée ou à l'heure, cochées depuis l'agenda, ouvertes dans le module Tâches, jamais
glissées, dupliquées ni supprimées par l'agenda, masquées par le réglage `agenda_show_tasks`."""
from _agenda_case import AgendaCase, settle

import shutil
import tempfile
from datetime import date, timedelta
from pathlib import Path

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QWidget

import fm_agenda.ui.pane as agenda_pane


class TasksInAgendaTest(AgendaCase):
    def setUp(self):
        super().setUp()
        from fm_taches.services.tasks import TaskService
        self.ttmp = Path(tempfile.mkdtemp(prefix="taches_agenda_"))
        self.tasks = TaskService({"taches_backup_daily": False}, path=self.ttmp / "t.sqlite3")
        self.lid = self.tasks.default_list().id
        self.opened = []
        self._saved = dict(agenda_pane.HOOKS)
        agenda_pane.HOOKS.update(tasks_due=self._due, toggle_task=self._toggle, open_task=self.opened.append)
        self.host = QWidget()
        self.host.resize(1400, 800)
        self.pane = agenda_pane.AgendaPane(self.service, self.host, settings=dict(self.settings))

    def tearDown(self):
        agenda_pane.HOOKS.clear()
        agenda_pane.HOOKS.update(self._saved)
        self.pane.shutdown()
        self.host.deleteLater()
        self.tasks.flush()
        QCoreApplication.processEvents()
        self.tasks.close()
        shutil.rmtree(self.ttmp, ignore_errors=True)
        super().tearDown()

    # même forme que main_window/tasks_module._taches_due_for_agenda
    def _due(self, start, end):
        return [{"id": t.id, "title": t.title, "date": t.due, "time": t.due_time, "done": t.done, "color": "vert",
                 "list": "Mes tâches", "notes": bool(t.notes)} for t in self.tasks.due_between(start, end)]

    def _toggle(self, task_id):
        self.tasks.set_done(task_id, not self.tasks.get(task_id).done)

    def week(self):
        days = self.pane.days_shown()
        return self.pane._occurrences(days[0], days[-1] + timedelta(days=1))

    def test_dated_tasks_appear_all_day_or_timed_and_toggle(self):
        monday = date(2026, 11, 9)
        self.pane._goto(monday, "semaine")
        a = self.tasks.create_task(self.lid, "Rendu plan 12", due_date="2026-11-10")
        self.tasks.create_task(self.lid, "Appeler Paul", due_date="2026-11-12", due_time="14:00")
        self.tasks.create_task(self.lid, "Sans date")
        occs = [o for o in self.week() if o.external]
        by_title = {o.title: o for o in occs}
        self.assertEqual(set(by_title), {"Rendu plan 12", "Appeler Paul"})
        self.assertTrue(by_title["Rendu plan 12"].all_day)
        self.assertEqual(by_title["Rendu plan 12"].days(), [date(2026, 11, 10)])
        timed = by_title["Appeler Paul"]
        self.assertFalse(timed.all_day)
        self.assertEqual((timed.start.hour, timed.start.minute), (14, 0))
        self.assertTrue(timed.read_only and timed.is_task)
        self.pane._toggle_done(by_title["Rendu plan 12"])               # case cochée dans l'agenda
        self.assertTrue(self.tasks.get(a).done)
        self.pane.edit_occurrence(by_title["Rendu plan 12"])            # double-clic : ouvert dans Tâches
        self.assertEqual(self.opened, [a])
        self.pane.duplicate(by_title["Rendu plan 12"])                  # jamais dupliquée / supprimée ici
        self.pane.delete_occurrence(by_title["Rendu plan 12"])
        self.assertIsNotNone(self.tasks.get(a))
        self.pane.refresh()                                             # vues peintes sans erreur
        for view in ("jour", "mois", "planning"):
            self.pane._goto(date(2026, 11, 10), view)
        settle(self.service)

    def test_setting_hides_them_and_events_untouched(self):
        self.pane._goto(date(2026, 11, 9), "semaine")
        self.tasks.create_task(self.lid, "T", due_date="2026-11-10")
        self.assertEqual(len([o for o in self.week() if o.external]), 1)
        self.pane.apply_settings({"agenda_show_tasks": False})
        self.assertEqual([o for o in self.week() if o.external], [])
        self.assertEqual(self.pane._occurrences(date(2026, 11, 9), date(2026, 11, 16)),
                         self.service.occurrences(date(2026, 11, 9), date(2026, 11, 16)))
