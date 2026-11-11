"""fm_taches : parcours complets du service (création -> base -> réouverture), sous-tâches, déplacements,
annuler / rétablir, échéances pour l'Agenda, stockage."""
import _isolate  # noqa: F401

import shutil
import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication

SETTINGS = {"taches_backup_daily": False}


def settle(service, rounds: int = 3):
    for _ in range(rounds):
        service.flush()
        QCoreApplication.processEvents()


class TachesCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="taches_test_"))
        self.path = self.tmp / "taches.sqlite3"
        self.s = self.open_service()
        self.lid = self.s.default_list().id

    def open_service(self):
        from fm_taches.services.tasks import TaskService
        return TaskService(dict(SETTINGS), path=self.path)

    def reopen(self):
        settle(self.s)
        self.s.close()
        self.s = self.open_service()
        return self.s

    def tearDown(self):
        try:
            settle(self.s)
            self.s.close()
        finally:
            shutil.rmtree(self.tmp, ignore_errors=True)

    def titles(self, list_id=None, **kw):
        return [(t.title, d) for t, d in self.s.tasks_of(list_id or self.lid, **kw)]


class CrudTest(TachesCase):
    def test_default_list_and_create_persist_reopen(self):
        self.assertEqual([lst.name for lst in self.s.lists()], ["Mes tâches"])
        seen = []
        self.s.changed.connect(seen.append)
        tid = self.s.create_task(self.lid, "Rendu plan 12", due_date="2026-11-12", priority=3)
        self.assertEqual(self.titles(), [("Rendu plan 12", 0)])          # visible avant l'écriture
        self.assertEqual(seen, [{self.lid}])
        self.reopen()
        t = self.s.get(tid)
        self.assertEqual((t.title, t.due_date, t.priority, t.version, t.sync_state), ("Rendu plan 12", "2026-11-12",
                                                                                        3, 1, "local"))

    def test_update_done_cascade_delete_undo_redo(self):
        a = self.s.create_task(self.lid, "Parent")
        b = self.s.create_task(self.lid, "Enfant", parent_id=a)
        self.s.update_task(a, title="Parent renommé", due_date="2026-11-20", due_time="10:30")
        self.s.set_done(a, True)
        self.assertTrue(self.s.get(b).done)                              # cocher le parent coche l'enfant
        self.s.set_done(a, False)
        self.assertTrue(self.s.get(b).done)                              # décocher ne touche que lui
        self.s.delete_task(a)
        self.assertIsNone(self.s.get(b))
        self.assertTrue(self.s.undo())
        self.assertEqual(self.titles(done_last=False), [("Parent renommé", 0), ("Enfant", 1)])
        self.assertTrue(self.s.redo())
        self.reopen()
        self.assertEqual(self.s.count(), 0)

    def test_update_clears_time_without_date_and_rejects_invalid(self):
        tid = self.s.create_task(self.lid, "T", due_date="2026-11-20", due_time="09:00")
        self.s.update_task(tid, due_date=None)
        self.assertIsNone(self.s.get(tid).due_time)
        errors = []
        self.s.message.connect(lambda level, text: errors.append(text))
        self.assertFalse(self.s.update_task(tid, priority=9))
        self.assertEqual(self.s.get(tid).priority, 0)
        self.assertTrue(errors)


class OrderTest(TachesCase):
    def test_insert_after_on_top_and_indent_outdent(self):
        a = self.s.create_task(self.lid, "A")
        c = self.s.create_task(self.lid, "C")
        self.s.create_task(self.lid, "B", after_id=a)
        self.s.create_task(self.lid, "Z", on_top=True)
        self.assertEqual([t for t, _ in self.titles()], ["Z", "A", "B", "C"])
        self.assertTrue(self.s.indent(c))                                # C sous B
        self.assertEqual(self.titles()[-1], ("C", 1))
        self.assertTrue(self.s.outdent(c))
        self.assertEqual(self.titles()[-1], ("C", 0))
        self.s.undo()
        self.assertEqual(self.titles()[-1], ("C", 1))

    def test_many_inserts_at_same_place_renumber(self):
        a = self.s.create_task(self.lid, "A")
        self.s.create_task(self.lid, "Z")
        for i in range(60):
            self.s.create_task(self.lid, f"x{i}", after_id=a)
        titles = [t for t, _ in self.titles()]
        self.assertEqual(titles[0], "A")
        self.assertEqual(titles[1], "x59")
        self.assertEqual(titles[-1], "Z")
        positions = [t.position for t, _ in self.s.tasks_of(self.lid)]
        self.assertEqual(len(set(positions)), len(positions))

    def test_move_to_other_list_with_subtasks_and_no_cycle(self):
        other = self.s.create_list("Studio", "vert")
        a = self.s.create_task(self.lid, "A")
        b = self.s.create_task(self.lid, "B", parent_id=a)
        self.assertFalse(self.s.move(a, parent_id=b))                   # sous sa propre descendance
        self.assertTrue(self.s.move(a, list_id=other.id))
        self.assertEqual(self.titles(other.id), [("A", 0), ("B", 1)])
        self.assertEqual(self.s.counts().get(self.lid, 0), 0)
        self.assertEqual(self.s.counts()[other.id], 2)
        self.s.undo()
        self.assertEqual(self.titles(), [("A", 0), ("B", 1)])

    def test_synced_list_allows_one_level_only(self):
        lst = self.s.get_list(self.lid).copy()
        lst.source, lst.sync_enabled = "google:moi@exemple.fr", True
        self.s._commit("test", [("list", lst.id, self.s.get_list(self.lid), lst)], record=False)
        a = self.s.create_task(self.lid, "A")
        b = self.s.create_task(self.lid, "B", parent_id=a)
        self.assertIsNone(self.s.create_task(self.lid, "C", parent_id=b))
        self.assertEqual(self.s.get(a).sync_state, "dirty")
        settle(self.s)
        outbox = self.s.writer.repo.outbox()
        self.assertEqual({row["entity_id"] for row in outbox if row["entity"] == "task"}, {a, b})


class ListsAndQueriesTest(TachesCase):
    def test_delete_list_and_undo_restores_tasks(self):
        other = self.s.create_list("Courses")
        self.s.create_task(other.id, "Pain")
        self.s.delete_list(other.id)
        self.assertIsNone(self.s.get_list(other.id))
        self.s.undo()
        self.assertEqual(self.titles(other.id), [("Pain", 0)])
        self.reopen()
        self.assertEqual(self.titles(other.id), [("Pain", 0)])

    def test_due_between_smart_search_and_hidden_done(self):
        self.s.create_task(self.lid, "Hier", due_date="2026-11-10")
        self.s.create_task(self.lid, "Midi", due_date="2026-11-11", due_time="12:00")
        self.s.create_task(self.lid, "Matin", due_date="2026-11-11", due_time="08:00")
        late = self.s.create_task(self.lid, "Loin", due_date="2027-06-01")
        week = self.s.due_between(date(2026, 11, 9), date(2026, 11, 16))
        self.assertEqual([t.title for t in week], ["Hier", "Matin", "Midi"])
        self.assertEqual([t.title for t in self.s.due_between(date(2020, 1, 1), date(2030, 1, 1))][-1], "Loin")
        self.assertEqual([t.title for t in self.s.smart("today", date(2026, 11, 11))], ["Hier", "Matin", "Midi"])
        self.s.set_done(late, True)
        self.assertEqual([t.title for t in self.s.search("loin")], ["Loin"])
        self.assertNotIn("Loin", [t for t, _ in self.titles(show_done=False)])
        self.s.update_task(late, due_date="2026-11-12")
        self.assertIn("Loin", [t.title for t in self.s.due_between(date(2026, 11, 9), date(2026, 11, 16))])

    def test_prefs_and_database_location(self):
        self.s.set_pref("view", "today")
        self.s.create_task(self.lid, "Journalisée")
        self.reopen()
        self.assertEqual(self.s.pref("view"), "today")
        conn = sqlite3.connect(str(self.path))
        try:
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 1)
            self.assertGreater(conn.execute("SELECT COUNT(*) FROM changes").fetchone()[0], 0)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
