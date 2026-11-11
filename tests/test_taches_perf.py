"""fm_taches : mesures de volume (LENT : 10 000 tâches sur 20 listes, ~10 s). `-v` affiche le tableau.

Seuils larges (machine lente, antivirus) : ils attrapent un retour en arrière d'un ordre de grandeur, pas une
variation de quelques millisecondes. Valeurs de référence : docs/agents/fm_taches.md, « Mesures »."""
import _isolate  # noqa: F401

import shutil
import tempfile
import time
import unittest
from datetime import date, timedelta
from pathlib import Path

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication, QWidget

from _lent import lent

N = 10_000
LISTS = 20


def _ms(fn, repeat: int = 1) -> float:
    t0 = time.perf_counter()
    for _ in range(repeat):
        fn()
    return (time.perf_counter() - t0) * 1000 / repeat


@lent
class TachesVolumeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        QApplication.instance() or QApplication([])
        from fm_taches.core.model import TaskRecord, new_id
        from fm_taches.services.tasks import TaskService
        cls.tmp = Path(tempfile.mkdtemp(prefix="taches_perf_"))
        cls.path = cls.tmp / "t.sqlite3"
        s = TaskService({"taches_backup_daily": False}, path=cls.path)
        lists = [s.default_list().id] + [s.create_list(f"Liste {i}").id for i in range(LISTS - 1)]
        s.flush()
        QCoreApplication.processEvents()

        def fill(repo):
            for i in range(N):
                due = (date(2026, 1, 1) + timedelta(days=i % 700)).isoformat() if i % 3 else None
                repo.save_task(TaskRecord(id=new_id(), list_id=lists[i % LISTS], title=f"Tâche {i}",
                                          position=float(i), due_date=due, done=(i % 4 == 0),
                                          due_time="10:00" if i % 7 == 0 and due else None,
                                          notes="note" if i % 5 == 0 else ""))
        s.writer.submit(fill)
        s.flush()
        s.close()
        cls.lists = lists
        cls.rows = []

    @classmethod
    def tearDownClass(cls):
        if cls.rows and unittest.main is not None:
            print("\n  mesure                                   ms")
            for name, value in cls.rows:
                print(f"  {name:<40} {value:8.2f}")
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        from fm_taches.services.tasks import TaskService
        t0 = time.perf_counter()
        self.s = TaskService({"taches_backup_daily": False}, path=self.path)
        self.open_ms = (time.perf_counter() - t0) * 1000

    def tearDown(self):
        self.s.flush()
        QCoreApplication.processEvents()
        self.s.close()

    def record(self, name, value, limit):
        type(self).rows.append((name, value))
        self.assertLess(value, limit, name)

    def test_service_reads_and_writes(self):
        s, lid = self.s, self.lists[3]
        self.record("ouverture du service (10 000)", self.open_ms, 600)
        s.tasks_of(lid)
        self.record("liste de 500, en cache", _ms(lambda: s.tasks_of(lid), 50), 1)
        task = s.tasks_of(lid)[5][0]
        self.record("cocher (visible)", _ms(lambda: s.set_done(task.id, not s.get(task.id).done)), 10)
        self.record("liste de 500 après modification", _ms(lambda: s.tasks_of(lid)), 15)
        self.record("semaine (Agenda)", _ms(lambda: s.due_between(date(2026, 3, 2), date(2026, 3, 9)), 20), 2)
        self.record("année (Agenda)", _ms(lambda: s.due_between(date(2026, 1, 1), date(2027, 1, 1))), 30)
        s._smart.clear()
        self.record("vue Aujourd'hui (à froid)", _ms(lambda: s.smart("today", date(2026, 6, 1))), 30)
        self.record("compteurs du panneau latéral", _ms(lambda: (setattr(s, "_counts", None), s.counts())), 30)
        self.record("recherche", _ms(lambda: s.search("tâche 99")), 40)
        now = time.time()
        self.record("rappels (calcul de 36 h)", _ms(lambda: s.reminder_candidates(now - 3600, now + 36 * 3600)), 20)

    def test_pane_refresh_and_paint(self):
        from fm_taches.ui.pane import TasksPane
        host = QWidget()
        host.resize(1400, 800)
        t0 = time.perf_counter()
        pane = TasksPane(self.s, host, settings={"taches_start_view": "all"})
        self.record("construction du panneau (vue Toutes)", (time.perf_counter() - t0) * 1000, 800)
        self.record("changer de liste", _ms(lambda: pane.set_view(("list", self.lists[5]))), 60)
        self.record("rafraîchir la liste ouverte", _ms(pane.refresh, 5), 60)
        pane.list.resize(900, pane.list.height())
        self.record("peindre la liste (zone visible)", _ms(lambda: pane.list.grab(pane.list.rect().adjusted(
            0, 0, 0, -max(0, pane.list.height() - 800))), 5), 40)
        pane.shutdown()
        host.deleteLater()


if __name__ == "__main__":
    unittest.main()
