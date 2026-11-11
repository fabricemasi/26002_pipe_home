"""fm_taches : cœur sans Qt ni SQLite (ordre, arbre, vues intelligentes, validation)."""
import _isolate  # noqa: F401

import unittest
from datetime import date

from fm_taches.core import ordering, smart
from fm_taches.core.model import TaskRecord


def task(tid, pos, parent=None, **kw):
    return TaskRecord(id=tid, list_id="L", position=pos, parent_id=parent, **kw)


class OrderingTest(unittest.TestCase):
    def test_between_and_renumber(self):
        self.assertEqual(ordering.between(None, None), ordering.STEP)
        self.assertEqual(ordering.between(1024, None), 2048)
        self.assertEqual(ordering.between(None, 1024), 0)
        self.assertEqual(ordering.between(1024, 2048), 1536)
        self.assertTrue(ordering.needs_renumber(1.0, 1.0 + 1e-9))
        self.assertEqual(ordering.renumber(3), [1024, 2048, 3072])

    def test_flatten_tree_done_last_collapsed_and_orphans(self):
        tasks = [task("a", 2), task("b", 1, done=True), task("a1", 2, "a"), task("a0", 1, "a"),
                 task("orphan", 3, "absent")]
        flat = [(t.id, d) for t, d in ordering.flatten(tasks)]
        self.assertEqual(flat, [("b", 0), ("a", 0), ("a0", 1), ("a1", 1), ("orphan", 0)])
        flat = [t.id for t, _ in ordering.flatten(tasks, done_last=True)]
        self.assertEqual(flat, ["a", "a0", "a1", "orphan", "b"])
        flat = [t.id for t, _ in ordering.flatten(tasks, collapsed={"a"})]
        self.assertEqual(flat, ["b", "a", "orphan"])

    def test_cycle_never_loops_and_keeps_tasks_visible(self):
        tasks = [task("x", 1, "y"), task("y", 2, "x")]
        self.assertEqual(sorted(t.id for t, _ in ordering.flatten(tasks)), ["x", "y"])
        self.assertEqual([t.id for t in ordering.descendants("x", tasks)], ["y"])

    def test_depth_and_descendants(self):
        tasks = [task("a", 1), task("b", 1, "a"), task("c", 1, "b")]
        by_id = {t.id: t for t in tasks}
        self.assertEqual(ordering.depth_of("c", by_id), 2)
        self.assertEqual({t.id for t in ordering.descendants("a", tasks)}, {"b", "c"})


class SmartAndModelTest(unittest.TestCase):
    def test_smart_views(self):
        today = date(2026, 11, 11)
        tasks = [task("late", 1, due_date="2026-11-01"), task("now", 2, due_date="2026-11-11", due_time="09:00"),
                 task("later", 3, due_date="2026-12-01", flagged=True), task("free", 4),
                 task("done", 5, done=True, completed_at=10, due_date="2026-11-11")]
        ids = lambda view: [t.id for t in smart.select(view, tasks, today)]   # noqa: E731
        self.assertEqual(ids("today"), ["late", "now"])
        self.assertEqual(ids("overdue"), ["late"])
        self.assertEqual(ids("planned"), ["late", "now", "later"])
        self.assertEqual(ids("flagged"), ["later"])
        self.assertEqual(ids("all"), ["late", "now", "later", "free"])
        self.assertEqual(ids("done"), ["done"])

    def test_validate(self):
        self.assertEqual(task("t", 1).validate(), [])
        self.assertIn("échéance invalide", task("t", 1, due_date="2026-13-40").validate())
        self.assertIn("heure sans date d'échéance", task("t", 1, due_time="10:00").validate())
        self.assertIn("heure d'échéance invalide", task("t", 1, due_date="2026-11-11", due_time="25:00").validate())
        self.assertIn("priorité invalide", task("t", 1, priority=7).validate())


if __name__ == "__main__":
    unittest.main()
