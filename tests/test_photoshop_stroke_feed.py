"""Module Photoshop : file des points du curseur entre les évènements et le moteur de trait (`stroke_feed.py`, tranches de
temps). Le cercle de brosse doit suivre le curseur même quand le moteur est en retard (grande page au zoom d'ajustement :
4 fois plus de pixels de document par seconde, jusqu'à 15 ms par tampon) ; le trait rattrape ensuite, sans rien perdre."""
import os as _os, sys as _sys  # jamais les vrais réglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import math
import os
import sys
import unittest
from unittest import mock

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from _photoshop_case import PsCase, settle  # noqa: E402
from fm_photoshop import canvas as canvas_module  # noqa: E402
from fm_photoshop.brush import Stroke  # noqa: E402
from fm_photoshop.stroke_feed import MIN_SPLIT_PX, StrokeFeed  # noqa: E402


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class FakeEngine:
    """Moteur factice : coûte `ms_per_px` par pixel de chemin ; garde les points reçus."""

    def __init__(self, clock, ms_per_px, start=(0.0, 0.0)):
        self.clock, self.ms_per_px = clock, ms_per_px
        self.at = start
        self.points = []

    def __call__(self, x, y, pressure, t):
        walked = math.hypot(x - self.at[0], y - self.at[1])
        self.clock.now += walked * self.ms_per_px / 1000.0
        self.at = (x, y)
        self.points.append((x, y, pressure, t))


def feed_with(ms_per_px, start=(0.0, 0.0)):
    clock = FakeClock()
    feed = StrokeFeed(clock)
    feed.start(start[0], start[1], 0.5, 0.0)
    return feed, FakeEngine(clock, ms_per_px, start), clock


class StrokeFeedTest(unittest.TestCase):
    def test_light_load_gives_every_point_whole_and_in_order(self):
        feed, engine, _clock = feed_with(0.001)
        path = [(10.0, 0.0), (20.0, 5.0), (35.0, 5.0), (60.0, 20.0)]
        for i, (x, y) in enumerate(path):
            feed.push(x, y, 0.5 + i * 0.1, i + 1.0)
        self.assertTrue(feed.run(engine, 4.0))
        self.assertEqual([(p[0], p[1]) for p in engine.points], path)         # mêmes points, même ordre : comportement d'avant
        self.assertEqual([p[3] for p in engine.points], [1.0, 2.0, 3.0, 4.0])
        self.assertEqual(feed.splits, 0)

    def test_a_heavy_segment_is_cut_into_sub_segments_on_the_same_line(self):
        feed, engine, _clock = feed_with(0.5)                                   # 0,5 ms par pixel : 100 px = 50 ms
        feed.push(10.0, 0.0, 0.5, 1.0)
        feed.run(engine, 4.0)                                                   # première mesure du coût
        self.assertAlmostEqual(feed.px_ms, 0.5, places=6)
        engine.points.clear()
        feed.push(110.0, 50.0, 1.0, 2.0)                                        # 111,8 px : ~56 ms de travail
        runs = 0
        while not feed.run(engine, 4.0):
            runs += 1
            self.assertLess(runs, 200)
        self.assertGreater(runs, 5)                                             # rendu plusieurs fois à la boucle d'évènements
        self.assertGreater(feed.splits, 5)
        x, y, p, t = engine.points[-1]
        self.assertEqual((x, y, p, t), (110.0, 50.0, 1.0, 2.0))                 # le point d'arrivée est EXACT
        previous = (10.0, 0.0, 0.5, 1.0)
        for point in engine.points:
            # sur la droite (10, 0) -> (110, 50) ; pression et horodatage interpolés linéairement, croissants
            frac = (point[0] - 10.0) / 100.0
            self.assertAlmostEqual(point[1], 50.0 * frac, places=9)
            self.assertAlmostEqual(point[2], 0.5 + 0.5 * frac, places=9)
            self.assertAlmostEqual(point[3], 1.0 + frac, places=9)
            self.assertGreaterEqual(point[3], previous[3])
            self.assertGreaterEqual(point[0], previous[0])
            previous = point

    def test_every_call_makes_progress_even_with_a_tiny_budget(self):
        feed, engine, _clock = feed_with(1.0)
        feed.push(5.0, 0.0, 0.5, 0.1)
        feed.run(engine, 4.0)
        feed.push(500.0, 0.0, 0.5, 0.2)
        before = len(engine.points)
        feed.run(engine, 0.0001)
        self.assertGreater(len(engine.points), before)                          # au moins un pas : jamais de boucle sans fin
        self.assertTrue(feed.pending())

    def test_draining_without_budget_feeds_everything_unsplit(self):
        feed, engine, _clock = feed_with(1.0)
        feed.push(5.0, 0.0, 0.5, 0.1)
        feed.run(engine, 4.0)
        engine.points.clear()
        for i in range(1, 6):
            feed.push(5.0 + 200.0 * i, 0.0, 0.5, 0.1 + i)
        self.assertTrue(feed.run(engine, None))                                 # relâchement : tout est posé, sans coupe
        self.assertEqual(len(engine.points), 5)
        self.assertEqual(feed.splits, 0)
        self.assertFalse(feed.pending())

    def test_short_segments_are_never_split(self):
        feed, engine, _clock = feed_with(5.0)                                   # très lent : tout dépasse le budget
        feed.push(10.0, 0.0, 0.5, 0.1)
        feed.run(engine, 4.0)
        engine.points.clear()
        for i in range(1, 6):
            feed.push(10.0 + (MIN_SPLIT_PX - 0.5) * i, 0.0, 0.5, 0.1 + i * 0.01)
        while not feed.run(engine, 1.0):
            pass
        self.assertEqual(feed.splits, 0)
        self.assertEqual(len(engine.points), 5)

    def test_lag_estimate_follows_the_queue(self):
        feed, engine, _clock = feed_with(0.2)
        self.assertEqual(feed.lag_ms(), 0.0)
        feed.push(20.0, 0.0, 0.5, 0.1)
        feed.run(engine, 4.0)
        feed.push(120.0, 0.0, 0.5, 0.2)
        feed.push(120.0, 100.0, 0.5, 0.3)
        self.assertAlmostEqual(feed.lag_ms(), 200.0 * 0.2, places=6)
        feed.clear()
        self.assertEqual(feed.lag_ms(), 0.0)

    def test_note_moves_the_starting_point_of_the_next_cut(self):
        feed, engine, _clock = feed_with(1.0)
        feed.push(5.0, 0.0, 0.5, 0.1)
        feed.run(engine, 4.0)
        feed.note(300.0, 0.0, 0.5, 0.2)                                         # un point donné en direct au moteur
        feed.push(400.0, 0.0, 0.5, 0.3)
        engine.at = (300.0, 0.0)
        engine.points.clear()
        feed.run(engine, 4.0)
        self.assertGreaterEqual(engine.points[0][0], 300.0)                     # la coupe part de 300, pas de 5


def mouse_event(x, y):
    return QMouseEvent(QEvent.MouseMove, QPointF(x, y), QPointF(x + 100, y + 100), Qt.NoButton, Qt.LeftButton, Qt.NoModifier)


class CanvasFeedTest(PsCase):
    """Le VRAI chemin : évènements souris -> file -> moteur. Un moteur lent est simulé (horloge de la file factice).
    Tous les points sont donnés en coordonnées du DOCUMENT (convertis en coordonnées du widget)."""

    def _canvas(self, size=(480, 300)):
        _item, std = self.editor(*size, zoom=1.0, background="Blanc")
        canvas, s = std.canvas, std.session
        s.tool = "brush"
        s.brush.size, s.brush.hardness, s.brush.spacing = 12.0, 1.0, 0.2
        s.fg = (0, 0, 0)
        canvas.set_zoom(1.0)
        s.center = (size[0] / 2.0, size[1] / 2.0)
        settle(0.05)
        return canvas, s

    @staticmethod
    def _w(canvas, x, y):
        p = canvas.to_widget(x, y)
        return p.x(), p.y()

    def _press(self, canvas, x, y):
        wx, wy = self._w(canvas, x, y)
        QTest.mousePress(canvas, Qt.LeftButton, Qt.NoModifier, QPoint(round(wx), round(wy)))

    def _release(self, canvas, x, y):
        wx, wy = self._w(canvas, x, y)
        QTest.mouseRelease(canvas, Qt.LeftButton, Qt.NoModifier, QPoint(round(wx), round(wy)))

    def _move(self, canvas, x, y):
        wx, wy = self._w(canvas, x, y)
        canvas.mouseMoveEvent(mouse_event(wx, wy))
        return wx, wy

    def _slow_engine(self, canvas, ms_per_px):
        """Chaque `Stroke.move` fait avancer l'horloge de la file de `ms_per_px` par pixel parcouru (sans attendre)."""
        clock = FakeClock()
        canvas._feed.clock = clock
        original = Stroke.move
        last = {}

        def slow(stroke, x, y, pressure=1.0, t=None, air_now=None):
            prev = last.get(id(stroke), (x, y))
            clock.now += math.hypot(x - prev[0], y - prev[1]) * ms_per_px / 1000.0
            last[id(stroke)] = (x, y)
            return original(stroke, x, y, pressure, t, air_now)
        return mock.patch.object(Stroke, "move", slow), clock

    def test_the_ring_follows_the_cursor_while_the_engine_is_late(self):
        canvas, s = self._canvas()
        patch, _clock = self._slow_engine(canvas, 2.0)                          # 2 ms par pixel : 25 px = 50 ms
        with patch:
            self._press(canvas, 20, 150)
            backlog = False
            for i in range(1, 16):
                wx, wy = self._move(canvas, 20.0 + i * 25.0, 150.0 + (i % 3))
                self.assertEqual((canvas._hover.x(), canvas._hover.y()), (wx, wy))    # le cercle est DÉJÀ à la nouvelle position
                backlog = backlog or canvas._feed.pending()
            self.assertTrue(backlog)                                            # le moteur était en retard : des points attendent
            settle(0.5)                                                         # la boucle d'évènements rattrape par tranches
            self.assertFalse(canvas._feed.pending())
            self._release(canvas, 395, 150)
        end = C_flat(s.doc, (390, 145, 400, 155))
        self.assertTrue(end[..., 0].min() < 128)                                # le trait est allé jusqu'au bout

    def test_release_lays_every_pending_point_before_the_stroke_ends(self):
        canvas, s = self._canvas()
        patch, _clock = self._slow_engine(canvas, 2.0)
        with patch:
            self._press(canvas, 20, 100)
            for i in range(1, 12):
                self._move(canvas, 20.0 + i * 30.0, 100.0)
            self.assertTrue(canvas._feed.pending())
            self._release(canvas, 350, 100)                                     # aucune boucle d'évènements entre les deux
        self.assertFalse(canvas._feed.pending())
        self.assertIsNone(canvas._stroke)
        self.assertEqual(len(s.history.done), 1)                                # une seule étape d'annulation
        end = C_flat(s.doc, (344, 94, 352, 106))
        self.assertTrue(end[..., 0].min() < 128)                                # le dernier point est peint

    def test_a_late_stroke_matches_the_direct_stroke(self):
        points = [(20.0 + i * 22.0, 140.0) for i in range(1, 17)]
        results = []
        for late in (False, True):
            canvas, s = self._canvas()
            if late:
                patch, _clock = self._slow_engine(canvas, 2.0)
            else:
                patch = mock.patch.object(Stroke, "move", Stroke.move)
            with patch:
                canvas.begin_stroke(20.0, 140.0)
                for x, y in points:
                    if late:
                        self._move(canvas, x, y)
                    else:
                        canvas.extend_stroke(x, y)
                canvas.end_stroke(*points[-1])
            results.append(s.doc.layers[0].pix.read(s.doc.rect()).astype(int))
            if late:
                self.assertGreater(canvas._feed.splits, 3)                       # (le trait était bien coupé en sous-segments)
            self.tearDown(); self.setUp()
        diff = np.abs(results[0] - results[1])
        self.assertLessEqual(int(diff.max()), 1, f"{(diff > 0).sum()} pixels diffèrent")   # même droite, mêmes tampons

    def test_the_catch_up_never_exceeds_the_hard_limit(self):
        canvas, _s = self._canvas()
        patch, _clock = self._slow_engine(canvas, 3.0)
        with patch:
            self._press(canvas, 10, 100)
            worst = 0.0
            for i in range(1, 30):
                self._move(canvas, 10.0 + i * 15.0, 100.0 + (i % 2))
                worst = max(worst, canvas._feed.lag_ms())
            self._release(canvas, 445, 100)
        self.assertLessEqual(worst, canvas_module.FEED_LAG_HARD_MS + 120.0)     # retard borné (le relâchement ne bloque pas)
        self.assertGreater(worst, 0.0)                                          # (le moteur était bien en retard)

    def test_airbrush_and_pen_log_keep_the_exact_synchronous_path(self):
        from fm_photoshop.pen_log import PenLog
        canvas, s = self._canvas()
        canvas.pen_log = PenLog()
        self._press(canvas, 20, 100)
        self._move(canvas, 120.0, 100.0)
        self.assertFalse(canvas._feed.pending())                                # journal actif : mesure exacte, pas de file
        rows = [e for e in canvas.pen_log.events if e["kind"] == "move"]
        self.assertTrue(rows and "proc_ms" in rows[-1])                         # ce que le moteur en a fait est journalisé
        self._release(canvas, 120, 100)
        canvas.pen_log = None
        s.brush.airbrush = True
        self._press(canvas, 20, 200)
        self._move(canvas, 120.0, 200.0)
        self.assertFalse(canvas._feed.pending())                                # aérographe : horloge réelle, pas de file
        self._release(canvas, 120, 200)
        self.assertFalse(canvas._air_timer.isActive())

    def test_no_orphan_timer_after_the_stroke(self):
        canvas, _s = self._canvas()
        patch, _clock = self._slow_engine(canvas, 2.0)
        with patch:
            self._press(canvas, 20, 100)
            for i in range(1, 10):
                self._move(canvas, 20.0 + i * 30.0, 100.0)
            self._release(canvas, 290, 100)
        self.assertFalse(canvas._feed_timer.isActive())
        self.assertFalse(canvas._feed.pending())
        settle(0.1)                                                             # un tour tardif ne fait rien (trait terminé)
        self.assertIsNone(canvas._stroke)


def C_flat(doc, rect):
    from fm_photoshop import compose as C
    return C.flatten_u8(doc, rect)


if __name__ == "__main__":
    unittest.main()
