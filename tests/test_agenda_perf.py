"""fm_agenda : mesures de volume (LENT) — 100, 1 000, 10 000, 50 000 événements (sur dix ans, + 50 séries) :
ouverture de la base, semaine / mois à froid et en cache, vue Année, peinture de la semaine, latence d'un
glisser (mouvement -> peinture), ouverture de l'éditeur, enregistrement local, mémoire du cache.

`python tests/run.py fm_agenda --lent -v` affiche le tableau ; les seuils sont larges (machine lente, bureau à
distance) et protègent seulement contre une régression grossière (une vue qui chargerait tout l'historique)."""
from _agenda_case import AgendaCase, paris, settle

import random
import time
import tracemalloc
import unittest
from datetime import date, datetime, timedelta

from PySide6.QtCore import QCoreApplication, QPointF, QRect

from _lent import lent
from fm_agenda.core import timeutil as tu
from fm_agenda.core.model import EventRecord, new_id

TZ = "Europe/Paris"
RESULTS: list[tuple] = []


def bulk_insert(service, n: int, seed: int = 7) -> float:
    """`n` événements simples sur 2020-2029 + 50 séries hebdomadaires, en UNE transaction (fil d'écriture)."""
    rnd = random.Random(seed)
    cals = [c.id for c in service.calendars()]
    tz = tu.get_tz(TZ)
    rows = []
    first = date(2020, 1, 1)
    span = (date(2030, 1, 1) - first).days
    for i in range(n):
        d = first + timedelta(days=rnd.randrange(span))
        if rnd.random() < 0.1:
            ev = EventRecord(id=new_id(), calendar_id=rnd.choice(cals), title=f"Jalon {i}", all_day=True,
                             start_date=d, end_date=d + timedelta(days=rnd.choice((1, 1, 2, 3))), tzid=TZ)
        else:
            start = tu.localize(datetime(d.year, d.month, d.day, rnd.randrange(7, 20), rnd.choice((0, 15, 30, 45))), tz)
            ev = EventRecord(id=new_id(), calendar_id=rnd.choice(cals), title=f"Revue projet {i}", start=start,
                             end=start + timedelta(minutes=rnd.choice((30, 60, 60, 90, 120, 180))), tzid=TZ,
                             project=f"26{rnd.randrange(100):03d}", reminders=[15] if rnd.random() < 0.2 else [])
        ev.version, ev.created_at, ev.updated_at = 1, 1, 1
        rows.append(ev)
    for i in range(50):
        start = tu.localize(datetime(2022, 1, 3 + i % 5, 9 + i % 8, 0), tz)
        rows.append(EventRecord(id=new_id(), calendar_id=rnd.choice(cals), title=f"Série {i}", start=start,
                                end=start + timedelta(hours=1), tzid=TZ, rrule="FREQ=WEEKLY;BYDAY=" +
                                tu.RRULE_DAYS[start.weekday()], version=1))
    t0 = time.perf_counter()

    def task(repo):
        for ev in rows:
            repo.insert_event(ev)
    service.writer.submit(task)
    service.flush(120)
    return time.perf_counter() - t0


@lent
class VolumeTest(AgendaCase):
    def measure(self, n: int) -> dict:
        out = {"n": n}
        out["insert_s"] = bulk_insert(self.service, n)
        self.reopen()
        t0 = time.perf_counter()
        self.service.close()
        self.service = self.open_service()
        out["open_ms"] = (time.perf_counter() - t0) * 1000
        s = self.service
        week = date(2026, 11, 2)
        t0 = time.perf_counter()
        occs = s.occurrences(week, week + timedelta(days=7))
        out["week_cold_ms"] = (time.perf_counter() - t0) * 1000
        out["week_events"] = len(occs)
        t0 = time.perf_counter()
        s.occurrences(week + timedelta(days=7), week + timedelta(days=14))
        out["week_next_ms"] = (time.perf_counter() - t0) * 1000
        t0 = time.perf_counter()
        s.occurrences(date(2027, 3, 1), date(2027, 4, 12))
        out["month_cold_ms"] = (time.perf_counter() - t0) * 1000
        t0 = time.perf_counter()
        s.day_counts(2025)
        out["year_ms"] = (time.perf_counter() - t0) * 1000
        tracemalloc.start()
        s.invalidate()
        for m in range(1, 13):
            s.occurrences(date(2026, m, 1), tu.add_months(date(2026, m, 1), 1))
        current, _peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        out["cache_12_months_mb"] = current / 1e6
        # Interface : semaine affichée, peinture, glisser, éditeur.
        from fm_agenda.ui.pane import AgendaPane
        pane = AgendaPane(s, settings=dict(self.settings))
        pane.resize(1280, 820)
        pane.show()
        pane.cur = week
        t0 = time.perf_counter()
        pane.set_view("mois")
        pane.set_view("semaine")
        QCoreApplication.processEvents()
        out["view_switch_ms"] = (time.perf_counter() - t0) * 1000 / 2
        t0 = time.perf_counter()
        pane.step(1)
        QCoreApplication.processEvents()
        out["step_week_ms"] = (time.perf_counter() - t0) * 1000
        canvas = pane.week.canvas
        vp = pane.week.scroll.viewport()
        t0 = time.perf_counter()
        for _ in range(10):
            canvas.repaint(QRect(0, pane.week.scroll.verticalScrollBar().value(), canvas.width(), vp.height()))
        out["paint_week_ms"] = (time.perf_counter() - t0) * 1000 / 10
        boxes = [b for b in canvas.boxes if not b[1].read_only]
        if boxes:
            rect, occ = boxes[0][0], boxes[0][1]
            from test_agenda_ui import mouse
            mouse(canvas, "press", rect.center())
            mouse(canvas, "move", QPointF(rect.center().x(), rect.center().y() + 10))
            t0 = time.perf_counter()
            for i in range(30):
                mouse(canvas, "move", QPointF(rect.center().x() + i, rect.center().y() + 10 + i * 2))
                canvas.repaint()
            out["drag_move_ms"] = (time.perf_counter() - t0) * 1000 / 30
            canvas._press = canvas._gesture = None
        pane.prebuild_editor()
        occ = next((o for o in pane.week.timed), None)
        if occ is not None:
            t0 = time.perf_counter()
            pane._editor.fill(occ, s.draft_for(occ), False)
            out["editor_open_ms"] = (time.perf_counter() - t0) * 1000
        t0 = time.perf_counter()
        draft = s.new_draft(paris(2026, 11, 5, 10), paris(2026, 11, 5, 11))
        draft.title = "Mesure"
        s.create(draft)
        out["create_visible_ms"] = (time.perf_counter() - t0) * 1000
        s.flush()
        out["create_disk_ms"] = (time.perf_counter() - t0) * 1000
        pane.shutdown()
        pane.close()
        pane.deleteLater()
        QCoreApplication.processEvents()
        RESULTS.append(out)
        return out

    def test_volumes(self):
        for n in (100, 1000, 10000, 50000):
            out = self.measure(n)
            self.assertLess(out["week_cold_ms"], 400, out)
            self.assertLess(out["step_week_ms"], 400, out)
            self.assertLess(out["create_visible_ms"], 60, out)
            self.service.close()
            import shutil
            shutil.rmtree(self.tmp, ignore_errors=True)
            self.tmp.mkdir(parents=True, exist_ok=True)
            self.service = self.open_service()
        keys = [k for k in RESULTS[0] if k != "n"]
        print("\n" + "indicateur".ljust(22) + "".join(f"{r['n']:>11}" for r in RESULTS))
        for k in keys:
            print(k.ljust(22) + "".join(f"{r.get(k, 0):>11.1f}" for r in RESULTS))


if __name__ == "__main__":
    unittest.main()
