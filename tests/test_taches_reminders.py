"""fm_taches : rappels (rappel choisi, heure d'échéance, une seule fois même après relance, rattrapage au lancement,
report, tâches terminées ignorées, réglages) et choix du rappel dans le panneau de détails."""
import _isolate  # noqa: F401

import shutil
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication

SETTINGS = {"taches_backup_daily": False, "taches_missed_minutes": 60}


class RemindersTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="taches_rappels_"))
        self.now = datetime(2026, 11, 11, 14, 0).timestamp()
        self.open()

    def open(self):
        from fm_taches.services.reminders import TaskReminders
        from fm_taches.services.tasks import TaskService
        self.s = TaskService(dict(SETTINGS), path=self.tmp / "t.sqlite3")
        self.r = TaskReminders(self.s, clock=lambda: self.now)
        self.lid = self.s.default_list().id

    def close(self):
        self.r.stop()
        self.s.flush()
        QCoreApplication.processEvents()
        self.s.close()

    def tearDown(self):
        self.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def titles(self, due):
        return [d.task.title for d in due]

    def test_chosen_reminder_fires_once_even_after_restart(self):
        self.s.create_task(self.lid, "Appeler Paul", reminder_at=int(self.now - 30))
        self.s.create_task(self.lid, "Plus tard", reminder_at=int(self.now + 600))
        due = self.r.check()
        self.assertEqual(self.titles(due), ["Appeler Paul"])
        self.assertFalse(due[0].missed)
        self.assertEqual(self.r.check(), [])
        self.close()
        self.open()
        self.assertEqual(self.r.check(), [])                                # reminder_log
        self.now += 601
        self.assertEqual(self.titles(self.r.check()), ["Plus tard"])

    def test_due_time_done_tasks_and_setting(self):
        self.s.create_task(self.lid, "Rendu", due_date="2026-11-11", due_time="13:59")
        self.s.set_done(self.s.create_task(self.lid, "Déjà fait", due_date="2026-11-11", due_time="13:58"), True)
        self.s.create_task(self.lid, "Sans heure", due_date="2026-11-11")
        self.s.settings["taches_remind_at_due"] = False
        self.assertEqual(self.r.check(), [])
        self.s.settings["taches_remind_at_due"] = True
        self.assertEqual(self.titles(self.r.check()), ["Rendu"])

    def test_missed_at_launch_and_snooze(self):
        self.s.create_task(self.lid, "Manqué", reminder_at=int(self.now - 40 * 60))
        self.s.create_task(self.lid, "Trop vieux", reminder_at=int(self.now - 3 * 3600))
        due = self.r.check()
        self.assertEqual(self.titles(due), ["Manqué"])
        self.assertTrue(due[0].missed)
        self.r.snooze(due[0], 10)
        self.now += 11 * 60
        self.assertEqual(self.titles(self.r.check()), ["Manqué"])

    def test_details_reminder_choices(self):
        from fm_taches.ui.details import DetailsPanel
        from fm_taches.ui.theme import from_settings
        from fm_agenda.ui.widgets import ThemeHolder
        tid = self.s.create_task(self.lid, "T", due_date="2026-11-20", due_time="10:00")
        panel = DetailsPanel(ThemeHolder(from_settings({})))
        panel.edited.connect(lambda task_id, fields: self.s.update_task(task_id, **fields))
        panel.show_task(self.s.get(tid), self.s.lists())
        self.assertTrue(panel.reminder.value().startswith("À l'échéance (automatique"))
        panel._reminder_done("15 min avant")
        self.assertEqual(self.s.get(tid).reminder_at, int(datetime(2026, 11, 20, 9, 45).timestamp()))
        panel.show_task(self.s.get(tid), self.s.lists())
        self.assertTrue(panel.reminder.value().startswith("Rappel : 20 novembre 2026"))
        panel._reminder_done("Retirer le rappel")
        self.assertIsNone(self.s.get(tid).reminder_at)
        panel.deleteLater()


if __name__ == "__main__":
    unittest.main()
