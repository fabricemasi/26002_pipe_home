"""fm_taches : saisie rapide, panneau (vues, création, clavier, glisser), réglages et branchement."""
import _isolate  # noqa: F401

import shutil
import tempfile
import unittest
from datetime import date
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QPointF
from PySide6.QtWidgets import QApplication, QWidget

from fm_taches.core import quickadd

TODAY = date(2026, 11, 11)                 # un mercredi


class QuickAddTest(unittest.TestCase):
    LISTS = [("a", "Studio"), ("b", "Mes tâches"), ("c", "Courses")]

    def p(self, text):
        return quickadd.parse(text, self.LISTS, TODAY)

    def test_everything_at_once(self):
        q = self.p("Appeler Paul demain à 14h #Studio !! *")
        self.assertEqual((q.title, q.due_date, q.due_time, q.list_id, q.priority, q.flagged),
                         ("Appeler Paul", "2026-11-12", "14:00", "a", 2, True))

    def test_bare_number_is_not_a_time_and_unknown_list_stays(self):
        self.assertEqual(self.p("Rendu plan 12").title, "Rendu plan 12")
        self.assertIsNone(self.p("Rendu plan 12").due_time)
        q = self.p("Voir #inconnu")
        self.assertEqual((q.title, q.list_id), ("Voir #inconnu", None))

    def test_dates(self):
        self.assertEqual(self.p("Revue le 12/11 10h30").due_date, "2026-11-12")
        self.assertEqual(self.p("Livraison 20 nov 2026").title, "Livraison")
        self.assertEqual(self.p("Pain lundi prochain").due_date, "2026-11-16")
        self.assertEqual(self.p("Point mercredi").due_date, "2026-11-18")          # jamais aujourd'hui
        self.assertEqual(self.p("Réunion dans 2 semaines").due_date, "2026-11-25")
        self.assertEqual(self.p("Appel 9:30").due_date, "2026-11-11")             # heure seule = aujourd'hui
        self.assertEqual(self.p("#mes_taches trier").list_id, "b")
        self.assertEqual(self.p("#cour pain").list_id, "c")                        # début du nom


class PaneTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        QApplication.instance() or QApplication([])

    def setUp(self):
        from fm_taches.services.tasks import TaskService
        from fm_taches.ui.pane import TasksPane
        self.tmp = Path(tempfile.mkdtemp(prefix="taches_ui_"))
        self.s = TaskService({"taches_backup_daily": False}, path=self.tmp / "t.sqlite3")
        self.host = QWidget()
        self.host.resize(1300, 700)
        self.pane = TasksPane(self.s, self.host, settings={"taches_confirm_delete": False,
                                                           "taches_start_view": "today"})
        self.lid = self.s.default_list().id

    def tearDown(self):
        self.pane.shutdown()
        self.host.deleteLater()
        self.s.flush()
        QCoreApplication.processEvents()
        self.s.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def titles(self):
        self.pane.refresh()                      # dans l'appli : au tour de boucle qui suit la modification
        return [r.task.title for r in self.pane.list.rows]

    def test_quick_add_in_today_view_dates_today_and_selects(self):
        self.pane.quick_add("Rappeler le client !!!")
        self.assertEqual(self.titles(), ["Rappeler le client"])
        task = self.s.get(self.pane.list.current)
        self.assertEqual((task.due_date, task.priority), (date.today().isoformat(), 3))
        self.assertEqual(self.pane.sidebar.smart_counts["today"], 1)

    def test_inline_entry_is_continuous_and_keyboard_actions(self):
        self.pane.set_view(("list", self.lid))
        self.pane.list.begin_new()
        self.pane.list.editor.setText("Première")
        self.pane.list._commit_edit()
        self.assertTrue(self.pane.list.editing())                         # ligne suivante ouverte
        self.pane.list.editor.setText("Seconde")
        self.pane.list._commit_edit()
        self.pane.list.cancel_edit()
        self.assertEqual(self.titles(), ["Première", "Seconde"])
        second = self.pane.list.current
        self.pane._key_action("indent")
        self.assertEqual(self.s.get(second).parent_id, self.pane.list.rows[0].task.id)
        self.pane._key_action("toggle")
        self.assertTrue(self.s.get(second).done)
        self.pane._key_action("delete")
        self.assertEqual(self.titles(), ["Première"])
        self.pane.undo()
        self.pane.refresh()
        self.assertEqual(self.titles(), ["Première", "Seconde"])

    def test_drop_targets_before_after_into(self):
        self.pane.set_view(("list", self.lid))
        a = self.s.create_task(self.lid, "A")
        b = self.s.create_task(self.lid, "B")
        c = self.s.create_task(self.lid, "C")
        self.pane.refresh()
        lv = self.pane.list
        rh = lv.row_h
        lv._drag = {"id": c, "pos": QPointF(50, 0), "target": None}
        self.assertEqual(lv._drop_target(QPointF(50, 2))[:3], (None, None, True))          # avant A
        self.assertEqual(lv._drop_target(QPointF(50, rh * 1.9))[:3], (None, b, False))     # après B
        self.assertEqual(lv._drop_target(QPointF(50, rh * 1.5))[:3], (b, None, False))     # dans B
        self.assertIsNone(lv._drop_target(QPointF(50, rh * 2.5)))                          # sur elle-même
        lv._drag = None
        self.pane._drop_move(c, None, None, True)
        self.pane.refresh()                                                # (sinon au tour de boucle suivant)
        self.assertEqual(self.titles(), ["C", "A", "B"])
        self.pane._drop_move(a, b, None, False)
        self.pane.refresh()
        self.assertEqual([(r.task.title, r.depth) for r in lv.rows], [("C", 0), ("B", 0), ("A", 1)])

    def test_collapse_search_and_views(self):
        self.pane.set_view(("list", self.lid))
        a = self.s.create_task(self.lid, "Parent")
        self.s.create_task(self.lid, "Enfant caché", parent_id=a)
        self.pane.refresh()
        self.assertTrue(self.pane.list.rows[0].has_kids)
        self.pane.toggle_collapse(a)
        self.assertEqual(self.titles(), ["Parent"])
        self.pane.header.search.edit.setText("caché")
        self.pane._run_search()
        self.assertEqual(self.titles(), ["Enfant caché"])
        self.pane.clear_search()
        self.assertEqual(self.s.pref("collapsed"), [a])

    def test_details_edit_and_move_to_list(self):
        other = self.s.create_list("Studio")
        self.pane.set_view(("list", self.lid))
        tid = self.s.create_task(self.lid, "T")
        self.pane.refresh()
        self.pane.list.select(tid)
        d = self.pane.details
        d.show()
        d.show_task(self.s.get(tid), self.s.lists())
        d.due.setText("demain")
        d._due_done()
        self.assertEqual(self.s.get(tid).due_date, date.fromordinal(date.today().toordinal() + 1).isoformat())
        d.time.setText("9h")
        d._time_done()
        self.assertEqual(self.s.get(tid).due_time, "09:00")
        d._list_done("Studio")
        self.assertEqual(self.s.get(tid).list_id, other.id)

    def test_apply_settings_live(self):
        self.pane.apply_settings({"taches_theme": "clair", "taches_show_notes": False})
        self.assertFalse(self.pane.holder.t.dark)
        self.assertFalse(self.pane.list.show_notes)


class SettingsTest(unittest.TestCase):
    def test_catalog_defaults_and_module_window(self):
        import settings_window_v2 as v2
        from settings_store import DEFAULT_SETTINGS
        from fm_taches.settings import TACHES_TAB
        from fm_taches.settings_defaults import TACHES_DEFAULTS
        for key, value in TACHES_DEFAULTS.items():
            self.assertEqual(DEFAULT_SETTINGS[key], value)
        self.assertEqual(v2.MODULE_SCOPES["taches"], [(TACHES_TAB, None)])
        self.assertEqual(v2.MODULE_TITLES["taches"], "Tâches")
        self.assertIn("navbar_taches", v2.NAVBAR_ICON_COLORS)


if __name__ == "__main__":
    unittest.main()
