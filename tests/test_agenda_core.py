"""fm_agenda : domaine sans Qt (dates et fuseaux, récurrences RFC 5545, changements d'heure, disposition)."""
import _isolate  # noqa: F401

import unittest
from datetime import date, datetime, timedelta

from fm_agenda.core import layout, recurrence as rec, timeutil as tu

PARIS = "Europe/Paris"


def paris(y, m, d, h=0, mi=0):
    return tu.localize(datetime(y, m, d, h, mi), tu.get_tz(PARIS))


class TimeUtilTest(unittest.TestCase):
    def test_paris_offsets_follow_daylight_saving(self):
        self.assertEqual(paris(2026, 1, 15, 10).utcoffset(), timedelta(hours=1))
        self.assertEqual(paris(2026, 7, 15, 10).utcoffset(), timedelta(hours=2))

    def test_nonexistent_spring_forward_hour_moves_after_the_gap(self):
        dt = paris(2026, 3, 29, 2, 30)                 # 2:30 n'existe pas ce jour-là
        self.assertEqual((dt.hour, dt.minute), (3, 30))

    def test_week_helpers(self):
        self.assertEqual(tu.week_start(date(2026, 11, 6)), date(2026, 11, 2))
        self.assertEqual(tu.week_start(date(2026, 11, 6), 6), date(2026, 11, 1))   # semaine du dimanche
        self.assertEqual(tu.iso_week(date(2026, 11, 6)), 45)
        grid = tu.month_grid(date(2026, 11, 1))
        self.assertEqual(len(grid), 6)
        self.assertEqual(grid[0][0], date(2026, 10, 26))

    def test_labels_like_the_mockup(self):
        self.assertEqual(tu.fmt_day_long(date(2026, 11, 6)), "Vendredi 6 novembre 2026")
        self.assertEqual(tu.fmt_time(datetime(2026, 1, 1, 9, 30)), "9:30")
        self.assertEqual(tu.fmt_time(datetime(2026, 1, 1, 14, 0), h24=False), "2:00 PM")

    def test_user_input_parsing(self):
        today = date(2026, 11, 6)
        self.assertEqual(tu.parse_user_date("12/11", today), date(2026, 11, 12))
        self.assertEqual(tu.parse_user_date("12.11.27", today), date(2027, 11, 12))
        self.assertEqual(tu.parse_user_date("demain", today), date(2026, 11, 7))
        self.assertEqual(tu.parse_user_date("3 déc 2026", today), date(2026, 12, 3))
        self.assertIsNone(tu.parse_user_date("n'importe", today))
        self.assertEqual(tu.parse_user_time("9h30"), (9, 30))
        self.assertEqual(tu.parse_user_time("1415"), (14, 15))
        self.assertEqual(tu.parse_user_time("2:30 pm"), (14, 30))
        self.assertIsNone(tu.parse_user_time("25:00"))

    def test_rid_roundtrip(self):
        dt = paris(2026, 11, 6, 15)
        rid = tu.rid_for_datetime(dt)
        self.assertEqual(rid, "20261106T140000Z")
        self.assertEqual(tu.parse_rid(rid, tu.get_tz(PARIS)), dt)


class RecurrenceTest(unittest.TestCase):
    def test_parse_and_format_roundtrip(self):
        text = "FREQ=MONTHLY;INTERVAL=2;BYDAY=-1FR;UNTIL=20271231T225959Z;X-FOO=1"
        rule = rec.parse_rrule("RRULE:" + text)
        self.assertEqual(rule.interval, 2)
        self.assertEqual(rule.byday, ["-1FR"])
        self.assertEqual(rec.parse_rrule(rec.format_rrule(rule)), rule)

    def test_weekly_keeps_wall_clock_across_daylight_saving(self):
        start = paris(2026, 3, 23, 10)                  # lundi, heure d'hiver
        starts = rec.occurrence_starts("FREQ=WEEKLY;BYDAY=MO", start, PARIS, False,
                                       paris(2026, 3, 1), paris(2026, 4, 15), timedelta(hours=1))
        self.assertEqual([s.hour for s in starts], [10, 10, 10, 10])
        self.assertEqual(starts[0].utcoffset(), timedelta(hours=1))
        self.assertEqual(starts[1].utcoffset(), timedelta(hours=2))

    def test_count_until_and_window(self):
        start = paris(2026, 11, 2, 9)
        five = rec.occurrence_starts("FREQ=DAILY;COUNT=5", start, PARIS, False, paris(2026, 11, 1),
                                     paris(2026, 12, 1), timedelta(hours=1))
        self.assertEqual(len(five), 5)
        until = rec.occurrence_starts("FREQ=DAILY;UNTIL=20261104T225959Z", start, PARIS, False, paris(2026, 11, 1),
                                      paris(2026, 12, 1), timedelta(hours=1))
        self.assertEqual([s.day for s in until], [2, 3, 4])
        window = rec.occurrence_starts("FREQ=DAILY", start, PARIS, False, paris(2026, 11, 10), paris(2026, 11, 12),
                                       timedelta(hours=1))
        self.assertEqual([s.day for s in window], [10, 11])

    def test_occurrence_overlapping_window_start_is_kept(self):
        start = paris(2026, 11, 2, 23)                 # 23:00 -> 01:00 le lendemain
        got = rec.occurrence_starts("FREQ=DAILY", start, PARIS, False, paris(2026, 11, 5), paris(2026, 11, 6),
                                    timedelta(hours=2))
        self.assertEqual([s.day for s in got], [4, 5])

    def test_skip_ahead_matches_full_iteration(self):
        start = paris(2020, 1, 6, 8)
        for rule in ("FREQ=DAILY", "FREQ=DAILY;INTERVAL=3", "FREQ=WEEKLY;BYDAY=MO,TH", "FREQ=WEEKLY;INTERVAL=2"):
            fast = rec.occurrence_starts(rule, start, PARIS, False, paris(2026, 11, 1), paris(2026, 12, 1),
                                         timedelta(hours=1))
            from dateutil import rrule as du
            full = [tu.localize(w, tu.get_tz(PARIS)) for w in
                    du.rrulestr(rule, dtstart=datetime(2020, 1, 6, 8)).between(datetime(2026, 11, 1),
                                                                                datetime(2026, 12, 1), inc=True)]
            self.assertEqual(fast, full, rule)

    def test_all_day_yearly(self):
        got = rec.occurrence_starts("FREQ=YEARLY", date(2020, 2, 29), PARIS, True, date(2023, 1, 1),
                                    date(2029, 1, 1), timedelta(days=1))
        self.assertEqual(got, [date(2024, 2, 29), date(2028, 2, 29)])

    def test_last_end_and_count_before(self):
        start = paris(2026, 11, 2, 9)
        end = rec.last_end_ts("FREQ=DAILY;COUNT=3", start, PARIS, False, timedelta(hours=1))
        self.assertEqual(end, tu.to_ts(paris(2026, 11, 4, 10)))
        self.assertIsNone(rec.last_end_ts("FREQ=DAILY", start, PARIS, False, timedelta(hours=1)))
        self.assertEqual(rec.count_before("FREQ=DAILY;COUNT=10", start, PARIS, False, paris(2026, 11, 5, 9)), 3)

    def test_until_before_split(self):
        occ = paris(2026, 11, 10, 9)
        until = rec.until_before(occ, False)
        got = rec.occurrence_starts("FREQ=DAILY;UNTIL=" + until, paris(2026, 11, 2, 9), PARIS, False,
                                    paris(2026, 11, 1), paris(2026, 12, 1), timedelta(hours=1))
        self.assertEqual(got[-1].day, 9)

    def test_french_descriptions(self):
        self.assertEqual(rec.describe("FREQ=WEEKLY;BYDAY=MO,TH"), "Toutes les semaines le lundi et le jeudi")
        self.assertEqual(rec.describe("FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR"), "Tous les jours ouvrés")
        self.assertEqual(rec.describe("FREQ=MONTHLY;BYDAY=-1FR"), "Tous les mois le dernier vendredi")
        self.assertIn("jusqu'au 31 décembre 2026",
                      rec.describe("FREQ=DAILY;UNTIL=20261231T225959Z", tz=tu.get_tz(PARIS)))
        self.assertEqual(rec.describe("FREQ=DAILY;INTERVAL=2;COUNT=4"), "Tous les 2 jours, 4 fois")

    def test_presets_follow_start(self):
        labels = [label for label, _r in rec.presets(date(2026, 11, 27))]
        self.assertIn("Tous les mois le dernier vendredi", labels)


class LayoutTest(unittest.TestCase):
    def test_overlaps_get_lanes(self):
        placed = layout.lay_timed([(600, 660, "a"), (630, 690, "b"), (700, 720, "c"), (600, 720, "d")])
        by = {p.item: p for p in placed}
        self.assertEqual(by["d"].lane, 0)              # le plus long d'abord à début égal
        self.assertEqual(by["a"].lanes, 3)
        self.assertEqual(by["c"].lanes, 3)
        self.assertNotEqual(by["a"].lane, by["b"].lane)

    def test_spans_pack_in_rows(self):
        spans = [layout.Span("a", 0, 2), layout.Span("b", 1, 1), layout.Span("c", 3, 4)]
        self.assertEqual(layout.pack_spans(spans), 2)
        self.assertEqual([s.row for s in spans], [0, 1, 0])


if __name__ == "__main__":
    unittest.main()
