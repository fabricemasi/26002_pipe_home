"""fm_agenda : parcours complets du service (création -> base -> réouverture), séries, annuler / rétablir,
stockage (migrations, sauvegardes, récupération après corruption)."""
from _agenda_case import AgendaCase, paris, settle

import sqlite3
import unittest
from datetime import date, timedelta

from fm_agenda.core import timeutil as tu
from fm_agenda.store import database as db
from fm_agenda.store import schema


class CrudPersistenceTest(AgendaCase):
    def test_default_calendars_like_the_mockup(self):
        names = [c.name for c in self.service.calendars()]
        self.assertEqual(names[:5], ["Projets et revues", "Rendus", "Livraisons et jalons", "Équipe", "Tâches"])

    def test_created_event_is_visible_at_once_then_persisted_and_reloaded(self):
        eid = self.new_event("Revue client", paris(2026, 11, 3, 10), paris(2026, 11, 3, 11))
        occs = self.service.occurrences(date(2026, 11, 2), date(2026, 11, 9))
        self.assertEqual([o.title for o in occs], ["Revue client"])   # avant même l'écriture sur le disque
        self.reopen()
        occs = self.service.occurrences(date(2026, 11, 2), date(2026, 11, 9))
        self.assertEqual([(o.event_id, o.title) for o in occs], [(eid, "Revue client")])
        self.assertEqual(occs[0].start, paris(2026, 11, 3, 10))

    def test_update_delete_undo_redo_survive_reopen(self):
        eid = self.new_event("Point", paris(2026, 11, 4, 15), paris(2026, 11, 4, 16))
        occ = self.service.occurrences(date(2026, 11, 4), date(2026, 11, 5))[0]
        draft = self.service.draft_for(occ)
        draft.title = "Point équipe 3D"
        draft.location = "Salle 2"
        self.service.save_draft(occ, draft)
        self.reopen()
        ev = self.service.get_event(eid)
        self.assertEqual((ev.title, ev.location, ev.version), ("Point équipe 3D", "Salle 2", 2))
        occ = self.service.occurrences(date(2026, 11, 4), date(2026, 11, 5))[0]
        self.service.delete_occurrence(occ)
        self.assertEqual(self.service.occurrences(date(2026, 11, 4), date(2026, 11, 5)), [])
        self.assertTrue(self.service.undo())
        self.assertEqual(len(self.service.occurrences(date(2026, 11, 4), date(2026, 11, 5))), 1)
        self.assertTrue(self.service.redo())
        self.reopen()
        self.assertIsNone(self.service.get_event(eid))

    def test_move_and_resize(self):
        self.new_event("Rendu", paris(2026, 11, 5, 14), paris(2026, 11, 5, 17))
        occ = self.service.occurrences(date(2026, 11, 5), date(2026, 11, 6))[0]
        self.service.move_occurrence(occ, paris(2026, 11, 6, 9), paris(2026, 11, 6, 13))
        settle(self.service)
        self.assertEqual(self.service.occurrences(date(2026, 11, 5), date(2026, 11, 6)), [])
        moved = self.service.occurrences(date(2026, 11, 6), date(2026, 11, 7))[0]
        self.assertEqual((moved.start.hour, moved.end.hour), (9, 13))
        self.service.undo()
        self.assertEqual(self.service.occurrences(date(2026, 11, 5), date(2026, 11, 6))[0].start.hour, 14)

    def test_all_day_multi_day_and_duplicate(self):
        draft = self.service.new_draft(date(2026, 11, 2), date(2026, 11, 5), all_day=True)
        draft.title = "Congés — Léa"
        self.service.create(draft)
        week = self.service.occurrences(date(2026, 11, 2), date(2026, 11, 9))
        self.assertEqual(week[0].days(), [date(2026, 11, 2), date(2026, 11, 3), date(2026, 11, 4)])
        copy_id = self.service.duplicate(week[0], days=7)
        settle(self.service)
        self.assertEqual(self.service.get_event(copy_id).start_date, date(2026, 11, 9))

    def test_hidden_calendar_keeps_its_events(self):
        self.new_event("Visible", paris(2026, 11, 3, 10), paris(2026, 11, 3, 11))
        cal = self.cal()
        self.service.set_visible(cal.id, False)
        self.assertEqual(self.service.occurrences(date(2026, 11, 2), date(2026, 11, 9)), [])
        self.assertEqual(len(self.service.occurrences(date(2026, 11, 2), date(2026, 11, 9), visible_only=False)), 1)
        self.reopen()
        self.assertFalse(self.cal().visible)

    def test_search_and_year_counts(self):
        self.new_event("Livraison V2 — 26014 Teaser", paris(2026, 11, 6, 15), paris(2026, 11, 6, 16),
                       project="26014 Teaser")
        self.new_event("Revue lookdev", paris(2026, 11, 4, 11), paris(2026, 11, 4, 12))
        settle(self.service)
        self.assertEqual([o.title for o in self.service.search("teaser")], ["Livraison V2 — 26014 Teaser"])
        self.assertEqual([o.title for o in self.service.search("revue look")], ["Revue lookdev"])
        counts = self.service.day_counts(2026)
        self.assertEqual(counts[date(2026, 11, 6)], 1)

    def test_write_failure_reverts_and_reports(self):
        import fm_agenda.services.agenda as agenda
        messages = []
        self.service.message.connect(lambda level, text: messages.append((level, text)))
        original = agenda._write_change
        agenda._write_change = lambda *a, **k: (_ for _ in ()).throw(sqlite3.OperationalError("disque plein"))
        try:
            self.new_event("Perdu ?", paris(2026, 11, 3, 10), paris(2026, 11, 3, 11))
            settle(self.service)
        finally:
            agenda._write_change = original
        self.assertEqual(self.service.occurrences(date(2026, 11, 2), date(2026, 11, 9)), [])
        self.assertTrue(any(level == "erreur" and "disque plein" in text for level, text in messages))


class SeriesTest(AgendaCase):
    def make_series(self, rule="FREQ=WEEKLY;BYDAY=MO", start=None, hours=1):
        start = start or paris(2026, 11, 2, 9, 30)
        return self.new_event("Point de prod hebdo", start, start + timedelta(hours=hours), rrule=rule)

    def month(self):
        return self.service.occurrences(date(2026, 11, 1), date(2026, 12, 1))

    def test_weekly_series_expands_across_daylight_saving(self):
        self.make_series(start=paris(2026, 10, 19, 9, 30))
        occs = self.service.occurrences(date(2026, 10, 19), date(2026, 11, 3))
        self.assertEqual([(o.start.day, o.start.hour, o.start.minute) for o in occs],
                         [(19, 9, 30), (26, 9, 30), (2, 9, 30)])

    def test_this_occurrence_only(self):
        self.make_series()
        occ = self.month()[1]                          # lundi 9
        draft = self.service.draft_for(occ)
        draft.title = "Point de prod (décalé)"
        draft.start, draft.end = paris(2026, 11, 10, 14), paris(2026, 11, 10, 15)
        self.service.save_draft(occ, draft, "this")
        self.reopen()
        titles = [(o.start.day, o.title) for o in self.month()]
        self.assertIn((10, "Point de prod (décalé)"), titles)
        self.assertNotIn(9, [d for d, _t in titles])
        self.assertEqual(len(titles), 5)

    def test_delete_this_following_and_all(self):
        self.make_series()
        occs = self.month()
        self.service.delete_occurrence(occs[1], "this")
        self.assertEqual([o.start.day for o in self.month()], [2, 16, 23, 30])
        self.service.delete_occurrence(self.month()[2], "following")       # le 23 et après
        self.reopen()
        self.assertEqual([o.start.day for o in self.month()], [2, 16])
        self.service.delete_occurrence(self.month()[0], "all")
        self.assertEqual(self.month(), [])
        self.service.undo()
        self.assertEqual([o.start.day for o in self.month()], [2, 16])

    def test_following_splits_the_series(self):
        sid = self.make_series()
        occ = self.month()[2]                          # le 16
        draft = self.service.draft_for(occ)
        draft.start, draft.end = paris(2026, 11, 16, 11), paris(2026, 11, 16, 12)
        draft.title = "Point de prod (nouvel horaire)"
        new_id = self.service.save_draft(occ, draft, "following")
        self.reopen()
        got = [(o.start.day, o.start.hour, o.title) for o in self.month()]
        self.assertEqual(got[:2], [(2, 9, "Point de prod hebdo"), (9, 9, "Point de prod hebdo")])
        self.assertEqual(got[2:], [(16, 11, "Point de prod (nouvel horaire)"), (23, 11, "Point de prod (nouvel horaire)"),
                                   (30, 11, "Point de prod (nouvel horaire)")])
        self.assertNotEqual(new_id, sid)
        self.assertIn("UNTIL=", self.service.get_event(sid).rrule)

    def test_all_shifts_series_and_keeps_exceptions(self):
        self.make_series()
        self.service.delete_occurrence(self.month()[1], "this")             # le 9 supprimé
        occ = self.month()[0]
        draft = self.service.draft_for(occ)
        draft.start, draft.end = paris(2026, 11, 2, 10, 30), paris(2026, 11, 2, 11, 30)
        self.service.save_draft(occ, draft, "all")
        self.reopen()
        self.assertEqual([(o.start.day, o.start.hour) for o in self.month()], [(2, 10), (16, 10), (23, 10), (30, 10)])

    def test_count_series_split_keeps_total(self):
        self.make_series(rule="FREQ=DAILY;COUNT=6", start=paris(2026, 11, 2, 8))
        occ = self.month()[3]
        draft = self.service.draft_for(occ)
        draft.title = "Suite"
        self.service.save_draft(occ, draft, "following")
        settle(self.service)
        occs = self.month()
        self.assertEqual(len(occs), 6)
        self.assertEqual([o.title for o in occs][3:], ["Suite"] * 3)

    def test_recurring_task_done_only_this_occurrence(self):
        self.make_series(rule="FREQ=DAILY;COUNT=3")
        occ = self.month()[0]
        self.service.set_done(occ, True)
        settle(self.service)
        self.assertEqual([o.done for o in self.month()], [True, False, False])

    def test_year_counts_include_series(self):
        self.make_series(rule="FREQ=DAILY;COUNT=10", start=paris(2026, 11, 2, 8))
        settle(self.service)
        counts = self.service.day_counts(2026)
        self.assertEqual(sum(counts.values()), 10)


class StorageTest(AgendaCase):
    def test_schema_is_at_latest_version(self):
        conn = sqlite3.connect(str(self.path))
        self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], schema.LATEST)
        conn.close()

    def test_backup_rotation_and_corruption_recovery(self):
        self.new_event("Sauvé", paris(2026, 11, 3, 10), paris(2026, 11, 3, 11))
        settle(self.service)
        done = []
        self.service.backup_now(done.append)
        settle(self.service)
        self.assertTrue(done and done[0].is_file())
        settle(self.service)
        self.service.close()
        # Arrêt brutal simulé (témoin laissé) + base écrasée : mise de côté, sauvegarde restaurée.
        (self.path.parent / (self.path.name + ".open")).write_text("1")
        for side in ("-wal", "-shm"):
            p = self.path.with_name(self.path.name + side)
            if p.exists():
                p.unlink()
        self.path.write_bytes(b"pas une base sqlite" * 100)
        self.service = self.open_service()
        report = self.service.open_report
        self.assertIsNotNone(report.quarantined)
        self.assertIsNotNone(report.recovered_from)
        titles = [o.title for o in self.service.occurrences(date(2026, 11, 2), date(2026, 11, 9))]
        self.assertEqual(titles, ["Sauvé"])

    def test_preferences_persist(self):
        self.service.set_pref("view", "mois")
        self.reopen()
        self.assertEqual(self.service.pref("view"), "mois")


if __name__ == "__main__":
    unittest.main()
