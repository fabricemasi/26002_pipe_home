"""fm_agenda : rappels (dus une seule fois, manqués, reportés, séries, journée), iCalendar (lecture, écriture,
aller-retour, réimport sans doublon), migration de schéma avec sauvegarde."""
from _agenda_case import AgendaCase, paris, settle

import sqlite3
import unittest
from datetime import date, datetime, timedelta

from fm_agenda.core import ics
from fm_agenda.core import timeutil as tu
from fm_agenda.services import ics_io
from fm_agenda.services.reminders import ReminderScheduler, compute_due
from fm_agenda.store import database as db
from fm_agenda.store import schema

SAMPLE = """BEGIN:VCALENDAR\r
VERSION:2.0\r
PRODID:-//Test//FR\r
BEGIN:VEVENT\r
UID:abc-123@example.com\r
DTSTART;TZID=Europe/Paris:20261102T093000\r
DTEND;TZID=Europe/Paris:20261102T103000\r
RRULE:FREQ=WEEKLY;BYDAY=MO;COUNT=4\r
EXDATE;TZID=Europe/Paris:20261109T093000\r
SUMMARY:Point de prod hebdo\\, équipe\r
DESCRIPTION:Ligne 1\\nLigne 2 avec une description assez longue pour être repliée sur plusieurs lig\r
 nes par le client\r
LOCATION:Salle 2\r
ATTENDEE;CN="Léa Martin";PARTSTAT=ACCEPTED:mailto:lea@example.com\r
BEGIN:VALARM\r
ACTION:DISPLAY\r
TRIGGER:-PT15M\r
END:VALARM\r
END:VEVENT\r
BEGIN:VEVENT\r
UID:abc-123@example.com\r
RECURRENCE-ID;TZID=Europe/Paris:20261116T093000\r
DTSTART;TZID=Europe/Paris:20261116T140000\r
DTEND;TZID=Europe/Paris:20261116T150000\r
SUMMARY:Point de prod (décalé)\r
END:VEVENT\r
BEGIN:VEVENT\r
UID:conges@example.com\r
DTSTART;VALUE=DATE:20261224\r
DTEND;VALUE=DATE:20270101\r
SUMMARY:Fermeture de fin d'année\r
TRANSP:TRANSPARENT\r
END:VEVENT\r
BEGIN:VEVENT\r
UID:utc@example.com\r
DTSTART:20261105T130000Z\r
DURATION:PT1H30M\r
SUMMARY:Visio client\r
END:VEVENT\r
END:VCALENDAR\r
"""


class IcsTest(AgendaCase):
    def month(self, start=date(2026, 11, 1), end=date(2026, 12, 1)):
        return self.service.occurrences(start, end, visible_only=False)

    def test_parse_sample(self):
        events, warnings = ics.read_events(SAMPLE, "cal", "Europe/Paris")
        self.assertEqual(warnings, [])
        first = events[0].record
        self.assertEqual(first.title, "Point de prod hebdo, équipe")
        self.assertIn("lignes par le client", first.description)
        self.assertEqual(first.reminders, [15])
        self.assertEqual(first.attendees[0].name, "Léa Martin")
        self.assertEqual(first.exdates, ["20261109T083000Z"])
        self.assertEqual(events[1].recurrence_id, "20261116T083000Z")
        self.assertTrue(events[2].record.all_day)
        self.assertEqual(events[3].record.end - events[3].record.start, timedelta(minutes=90))

    def test_import_series_exception_and_reimport_without_duplicates(self):
        cal = self.cal("Personnel").id
        report = ics_io.import_text(self.service, SAMPLE, cal)
        self.assertEqual((report.created, report.updated), (4, 0))
        settle(self.service)
        occs = [(o.start.day, o.start.hour, o.title) for o in self.month() if not o.all_day and o.recurring]
        self.assertEqual(occs, [(2, 9, "Point de prod hebdo, équipe"), (16, 14, "Point de prod (décalé)"),
                                (23, 9, "Point de prod hebdo, équipe")])
        report = ics_io.import_text(self.service, SAMPLE, cal)
        self.assertEqual((report.created, report.updated), (0, 4))
        settle(self.service)
        self.assertEqual(len(self.month()), 4)          # 3 occurrences + visio (fermeture en décembre) : pas de doublon
        self.service.undo()                             # l'import entier est UNE commande
        self.service.undo()
        settle(self.service)
        self.assertEqual(self.month(), [])

    def test_export_roundtrip(self):
        cal = self.cal("Personnel").id
        ics_io.import_text(self.service, SAMPLE, cal)
        settle(self.service)
        text, count = ics_io.export_text(self.service, calendar_ids=[cal])
        self.assertEqual(count, 3)
        self.assertTrue(all(len(line.encode("utf-8")) <= 75 for line in text.split("\r\n")))
        other = self.cal("Rendus").id
        report = ics_io.import_text(self.service, text, other)
        self.assertEqual(report.created, 4)
        settle(self.service)
        a = sorted((o.title, o.start, o.end) for o in self.month() if o.calendar_id == cal)
        b = sorted((o.title, o.start, o.end) for o in self.month() if o.calendar_id == other)
        self.assertEqual(a, b)

    def test_escape_fold_and_duration(self):
        self.assertEqual(ics.unescape(ics.escape("a; b, c\\d\ne")), "a; b, c\\d\ne")
        self.assertEqual(ics.parse_duration("-P1DT2H"), -timedelta(days=1, hours=2))
        self.assertEqual(ics.format_duration(-timedelta(minutes=15)), "-PT15M")
        folded = ics.fold("DESCRIPTION:" + "é" * 80)
        self.assertTrue(all(len(part.encode("utf-8")) <= 75 for part in folded.split("\r\n")))


class ReminderTest(AgendaCase):
    def test_due_once_then_never_again(self):
        start = paris(2026, 11, 6, 15)
        self.new_event("Livraison V2", start, start + timedelta(hours=1), reminders=[15, 30, 60])
        settle(self.service)
        clock = [start.timestamp() - 14 * 60]
        sched = ReminderScheduler(self.service, clock=lambda: clock[0])
        fired = []
        sched.fired.connect(fired.append)
        due = sched.check()
        # 15 min : dû ; 30 min : manqué de 16 min (rattrapé, fenêtre de 30 min) ; 60 min : trop ancien.
        self.assertEqual(sorted(d.minutes for d in due), [15, 30])
        self.assertEqual({d.minutes: d.missed for d in due}, {15: False, 30: True})
        self.assertEqual(sched.check(), [])            # jamais deux fois (mémoire, puis base)
        settle(self.service)
        sched2 = ReminderScheduler(self.service, clock=lambda: clock[0])
        self.assertEqual(sched2.check(), [])           # ni après une « relance »
        sched.stop()
        sched2.stop()

    def test_missed_window_and_series_and_all_day(self):
        start = paris(2026, 11, 2, 9, 30)
        self.new_event("Hebdo", start, start + timedelta(hours=1), reminders=[10], rrule="FREQ=WEEKLY;BYDAY=MO")
        draft = self.service.new_draft(date(2026, 11, 10), date(2026, 11, 11), all_day=True)
        draft.title = "Jalon"
        draft.reminders = [1440]
        self.service.create(draft)
        settle(self.service)
        tz = tu.get_tz("Europe/Paris")
        # Lundi 16 à 9:21 : le rappel (9:20) de la 3e occurrence de la série est dû.
        now = paris(2026, 11, 16, 9, 21).timestamp()
        due, upcoming = compute_due(self.service, now, 120, 36 * 3600)
        self.assertEqual([(d.occ.start.day, d.minutes) for d in due], [(16, 10)])
        # Journée : « 1 jour avant » = la veille à 9:00.
        due, _u = compute_due(self.service, paris(2026, 11, 9, 9, 0, ).timestamp() + 30, 120, 36 * 3600)
        self.assertEqual([d.occ.title for d in due], ["Jalon"])
        # Rattrapage : 20 min de retard est montré si la fenêtre est de 30 min, pas si elle est de 5 min.
        late = paris(2026, 11, 16, 9, 40).timestamp()
        self.assertEqual(len(compute_due(self.service, late, 30 * 60, 3600)[0]), 1)
        self.assertEqual(len(compute_due(self.service, late, 5 * 60, 3600)[0]), 0)
        self.assertIsNotNone(upcoming)

    def test_snooze(self):
        start = paris(2026, 11, 6, 15)
        self.new_event("Visio", start, start + timedelta(hours=1), reminders=[5])
        settle(self.service)
        clock = [start.timestamp() - 4 * 60]
        sched = ReminderScheduler(self.service, clock=lambda: clock[0])
        (first,) = sched.check()
        sched.snooze(first, 5)
        self.assertEqual(sched.check(), [])
        clock[0] += 5 * 60 + 1
        self.assertEqual(len(sched.check()), 1)
        sched.stop()


class MigrationTest(unittest.TestCase):
    def test_v1_database_is_migrated_with_a_backup(self):
        import tempfile
        from pathlib import Path
        tmp = Path(tempfile.mkdtemp())
        path = tmp / "agenda.sqlite3"
        conn = sqlite3.connect(str(path))
        for statement in db._statements(schema.MIGRATIONS[0][1]):
            conn.execute(statement)
        conn.execute("PRAGMA user_version = 1")
        conn.execute("INSERT INTO calendars(id, name) VALUES('c1', 'Ancien')")
        conn.commit()
        conn.close()
        conn, report = db.open_database(path)
        self.assertEqual(report.migrated_from, 1)
        self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], schema.LATEST)
        self.assertEqual(conn.execute("SELECT name FROM calendars").fetchone()[0], "Ancien")
        self.assertTrue(list((tmp / "backups").glob("agenda-avant-v*.sqlite3")))
        db.close_database(conn, path)


if __name__ == "__main__":
    unittest.main()
