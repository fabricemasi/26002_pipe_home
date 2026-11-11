"""fm_taches : synchronisation Google Tasks contre un faux serveur en mémoire (`_fake_gtasks.py`) : première
réception, envoi sans doublon, modifications et suppressions des deux côtés, fusion à trois voies, liste locale
envoyée, sous-tâches et déplacements, hors ligne, liste disparue, déconnexion."""
import _isolate  # noqa: F401

import shutil
import tempfile
import time
import unittest
from pathlib import Path

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication

from _fake_gtasks import FakeGoogleTasks, FakeTokens

ACCOUNT = {"id": "acc1", "provider": "google", "email": "moi@exemple.fr", "display_name": "moi@exemple.fr",
           "status": "connected", "created_at": 1}


class SyncCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        QApplication.instance() or QApplication([])

    def setUp(self):
        from fm_taches.services.tasks import TaskService
        from fm_taches.sync.google_tasks import GoogleTasksProvider
        from fm_taches.sync.manager import TasksSyncManager
        self.tmp = Path(tempfile.mkdtemp(prefix="taches_sync_"))
        self.fake = FakeGoogleTasks()
        self.s = TaskService({"taches_backup_daily": False, "taches_sync_on_change": False,
                              "taches_sync_auto": False}, path=self.tmp / "t.sqlite3")
        self.m = TasksSyncManager(
            self.s, provider_factory=lambda acc: GoogleTasksProvider(FakeTokens(), self.fake, sleep=lambda _s: None,
                                                                     max_retries=0),
            clock=self.fake.clock)
        self.s.sync = self.m
        self.s.save_account(dict(ACCOUNT))
        self.m.start()

    def tearDown(self):
        self.m.stop()
        self.s.flush()
        QCoreApplication.processEvents()
        self.s.sync = None
        self.s.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def sync(self, rounds: int = 1):
        for _ in range(rounds):
            got = []
            self.m.finished.connect(got.append)
            self.m.sync_now()
            end = time.perf_counter() + 15
            while not got and time.perf_counter() < end:
                QCoreApplication.processEvents()
                time.sleep(0.003)
            self.m.finished.disconnect(got.append)
            self.assertTrue(got, "passage de synchronisation non terminé")
            self.s.flush()
            QCoreApplication.processEvents()
            self.fake.now += 5
        return got[0]

    def glist(self, name="Mes tâches Google"):
        return next(lst for lst in self.s.lists() if lst.name == name)

    def titles(self, list_id):
        return sorted(t.title for t in self.s.tasks_in(list_id))


class FirstSyncTest(SyncCase):
    def test_remote_lists_and_tasks_arrive_with_subtasks_dates_and_done(self):
        lid = self.fake.remote_list("Mes tâches Google")
        a = self.fake.remote_task(lid, "Rendu 26014", due="2026-11-20T00:00:00.000Z", notes="passe lumière")
        self.fake.remote_task(lid, "Normales", parent=a, status="completed", completed="2026-11-10T09:00:00.000Z")
        self.sync()
        lst = self.glist()
        self.assertTrue(lst.synced and lst.is_google)
        tasks = {t.title: t for t in self.s.tasks_in(lst.id)}
        self.assertEqual(set(tasks), {"Rendu 26014", "Normales"})
        self.assertEqual((tasks["Rendu 26014"].due_date, tasks["Rendu 26014"].notes), ("2026-11-20", "passe lumière"))
        self.assertEqual(tasks["Normales"].parent_id, tasks["Rendu 26014"].id)
        self.assertTrue(tasks["Normales"].done)
        self.assertEqual(tasks["Normales"].sync_state, "synced")
        self.assertEqual(self.s.outbox_count(), 0)                      # rien de reçu n'est renvoyé
        self.assertFalse(self.s.can_undo())                             # la réception n'est pas annulable

    def test_many_tasks_over_several_pages(self):
        self.fake.page_size = 7
        lid = self.fake.remote_list("Mes tâches Google")
        for i in range(30):
            self.fake.remote_task(lid, f"T{i:02d}")
        self.sync()
        self.assertEqual(len(self.s.tasks_in(self.glist().id)), 30)


class PushTest(SyncCase):
    def setUp(self):
        super().setUp()
        self.rlid = self.fake.remote_list("Mes tâches Google")
        self.sync()
        self.lid = self.glist().id

    def test_local_task_created_once_with_its_subtask_then_edited(self):
        a = self.s.create_task(self.lid, "Appeler Paul", due_date="2026-11-12", due_time="14:00", priority=2)
        self.s.create_task(self.lid, "Préparer le devis", parent_id=a)
        self.sync(2)
        live = self.fake.live(self.rlid)
        self.assertEqual(sorted(t["title"] for t in live), ["Appeler Paul", "Préparer le devis"])
        parent = self.fake.by_title(self.rlid, "Appeler Paul")
        self.assertEqual(parent["due"], "2026-11-12T00:00:00.000Z")     # la date seule (Google n'a pas l'heure)
        self.assertEqual(self.fake.by_title(self.rlid, "Préparer le devis")["parent"], parent["id"])
        self.assertEqual(self.s.get(a).due_time, "14:00")               # l'heure reste ici
        self.assertEqual(self.s.get(a).sync_state, "synced")
        self.assertEqual(self.s.outbox_count(), 0)
        self.s.update_task(a, title="Appeler Paul (devis)")
        self.s.set_done(a, True)
        self.sync(2)
        live = self.fake.live(self.rlid)
        self.assertEqual(len(live), 2)                                  # jamais de doublon
        self.assertEqual(self.fake.by_title(self.rlid, "Appeler Paul (devis)")["status"], "completed")
        self.assertEqual(self.fake.by_title(self.rlid, "Préparer le devis")["status"], "completed")

    def test_local_delete_and_move_reach_google(self):
        a = self.s.create_task(self.lid, "A")
        b = self.s.create_task(self.lid, "B")
        self.sync()
        self.s.move(b, parent_id=a)                                     # B devient sous-tâche de A
        self.sync()
        rb = self.fake.by_title(self.rlid, "B")
        self.assertEqual(rb.get("parent"), self.fake.by_title(self.rlid, "A")["id"])
        self.s.delete_task(a)
        self.sync()
        self.assertEqual(self.fake.live(self.rlid), [])
        self.assertEqual(self.s.outbox_count(), 0)

    def test_remote_edit_delete_and_three_way_merge(self):
        a = self.s.create_task(self.lid, "Titre")
        b = self.s.create_task(self.lid, "À supprimer")
        self.sync()
        ra = self.s.get(a).remote_id
        self.fake.remote_edit(self.rlid, ra, title="Titre (téléphone)")
        self.fake.remote_delete(self.rlid, self.s.get(b).remote_id)
        self.s.update_task(a, notes="note du PC")                       # l'autre champ, changé ici
        self.sync(2)
        t = self.s.get(a)
        self.assertEqual((t.title, t.notes), ("Titre (téléphone)", "note du PC"))
        self.assertIsNone(self.s.get(b))
        self.assertEqual(self.fake.by_title(self.rlid, "Titre (téléphone)").get("notes"), "note du PC")
        # même champ changé des deux côtés : la modification la plus récente l'emporte (ici Google, plus tard)
        self.s.update_task(a, title="Titre PC")
        self.fake.now += 10
        self.fake.remote_edit(self.rlid, ra, title="Titre Google")
        self.sync(2)
        self.assertEqual(self.s.get(a).title, "Titre Google")
        self.assertEqual(self.fake.by_title(self.rlid, "Titre Google")["id"], ra)

    def test_offline_keeps_changes_until_back(self):
        self.s.create_task(self.lid, "Hors ligne")
        self.fake.offline = True
        self.sync()
        self.assertTrue(self.m.state["offline"])
        self.assertEqual(self.s.outbox_count(), 1)
        self.fake.offline = False
        self.sync()
        self.assertEqual([t["title"] for t in self.fake.live(self.rlid)], ["Hors ligne"])
        self.assertEqual(self.s.outbox_count(), 0)


class ListsTest(SyncCase):
    def test_local_list_published_with_nested_tasks(self):
        lst = self.s.create_list("Studio")
        a = self.s.create_task(lst.id, "Parent")
        b = self.s.create_task(lst.id, "Enfant", parent_id=a)
        self.s.create_task(lst.id, "Petit-enfant", parent_id=b)       # aplati à un niveau pour Google
        self.assertTrue(self.s.publish_list(lst.id, ACCOUNT))
        self.sync(2)
        rlid = next(k for k, v in self.fake.lists.items() if v["title"] == "Studio")
        self.assertEqual(self.s.get_list(lst.id).remote_id, rlid)
        parent = self.fake.by_title(rlid, "Parent")
        self.assertEqual({self.fake.by_title(rlid, n).get("parent") for n in ("Enfant", "Petit-enfant")},
                         {parent["id"]})
        self.assertEqual(self.s.outbox_count(), 0)
        self.s.update_list(lst.id, name="Studio 26014")
        self.sync()
        self.assertEqual(self.fake.lists[rlid]["title"], "Studio 26014")
        self.s.delete_list(lst.id)
        self.sync()
        self.assertNotIn(rlid, self.fake.lists)

    def test_remote_list_removed_becomes_local_and_disconnect_keeps_lists(self):
        keep = self.fake.remote_list("Courses")
        self.fake.remote_task(keep, "Pain")
        gone = self.fake.remote_list("Ancienne")
        self.fake.remote_task(gone, "Vieux")
        self.sync()
        del self.fake.lists[gone]
        del self.fake.tasks[gone]
        self.sync()
        old = self.glist("Ancienne")
        self.assertFalse(old.synced)
        self.assertEqual(self.titles(old.id), ["Vieux"])
        got = []
        self.m.disconnect("acc1", keep_tasks=True, on_done=got.append)
        end = time.perf_counter() + 10
        while not got and time.perf_counter() < end:
            QCoreApplication.processEvents()
            time.sleep(0.003)
        self.assertEqual(self.s.accounts(), [])
        courses = self.glist("Courses")
        self.assertEqual((courses.source, courses.remote_id), ("local", None))
        self.assertEqual(self.titles(courses.id), ["Pain"])


class MappingTest(unittest.TestCase):
    def test_body_and_fields(self):
        from fm_taches.core.model import TaskRecord
        from fm_taches.sync import mapping as mp
        t = TaskRecord(id="x", list_id="L", title="T", done=True, completed_at=1_800_000_000, due_date="2026-11-12")
        body = mp.body_for(t)
        self.assertEqual((body["status"], body["due"]), ("completed", "2026-11-12T00:00:00.000Z"))
        self.assertTrue(body["completed"].startswith("2027-01-15T"))
        self.assertEqual(mp.remote_fields({"title": "T", "status": "completed", "due": "2026-11-12T00:00:00.000Z"}),
                         {"title": "T", "notes": "", "done": True, "due_date": "2026-11-12"})
        self.assertEqual(mp.changed_fields(t, {"title": "T", "notes": "", "done": False, "due_date": "2026-11-12"}),
                         {"done"})


if __name__ == "__main__":
    unittest.main()
