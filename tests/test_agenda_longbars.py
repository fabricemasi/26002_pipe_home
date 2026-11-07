"""fm_agenda : événements longs en barres fléchées (maquette Claude Design v10 + cote de l'utilisateur) — géométrie
(pointes sur le début et la fin, arrondis, relief), disposition (barre au bord de la colonne, blocs décalés, plus de
24 h dans la grille), encart au survol (suit le curseur) et épinglé au clic (reclic : retiré), poignées début / fin /
décaler, réglages."""
import _isolate  # noqa: F401

import unittest

from PySide6.QtCore import QPointF, Qt

from _agenda_case import app, paris, settle
from test_agenda_ui import PaneCase, mouse, pump

TITLE = "Rendu ferme — 26017 Packshot"      # samedi 7 nov. 10:00 – 15:00 (5 h), semaine de la maquette


def hover(widget, pos):
    mouse(widget, "move", pos, buttons=Qt.NoButton)


class GeometryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app()

    def test_tips_on_start_and_end_rounded_corners_and_grips(self):
        from fm_agenda.ui import longbars as lb
        seg = lb.build_seg(None, 0, 100, 200, 400, True, True, 10, 9, mid_y=300)
        r = seg.path.boundingRect()
        self.assertAlmostEqual(r.top(), 191, delta=0.01)             # dépasse de A au-dessus du début
        self.assertAlmostEqual(r.bottom(), 409, delta=0.01)          # et de A sous la fin
        self.assertAlmostEqual(r.right(), 119, delta=0.5)            # pointe à T + A (arrondie de A / 10)
        self.assertTrue(seg.path.contains(QPointF(118, 200)))        # pointe de début, sur l'heure de début
        self.assertTrue(seg.path.contains(QPointF(118, 400)))        # pointe de fin, sur l'heure de fin
        self.assertFalse(seg.path.contains(QPointF(118, 230)))       # sous le chevron : vide
        self.assertFalse(seg.path.contains(QPointF(100.2, 191.2)))   # coin haut gauche arrondi (A / 5)
        self.assertEqual([k for k, _r in seg.grips], ["s", "e", "m"])
        self.assertFalse(seg.light.isEmpty() or seg.dark.isEmpty())  # relief
        cont = lb.build_seg(None, 0, 100, 0, 300, False, False, 10, 9)
        self.assertEqual(cont.path.boundingRect().width(), 10)        # suite d'un jour à l'autre : bords droits

    def test_when_text_like_the_mockup(self):
        from fm_agenda.ui import longbars as lb
        self.assertEqual(lb.when_text(paris(2026, 11, 5, 6), paris(2026, 11, 6, 9), True), "jeu. 6:00 → ven. 9:00 · 27 h")
        self.assertEqual(lb.when_text(paris(2026, 11, 7, 10), paris(2026, 11, 7, 15), True), "10:00 – 15:00 · 5 h")
        self.assertEqual(lb.when_text(paris(2026, 11, 7, 18), paris(2026, 11, 8, 0), True), "18:00 – 0:00 · 6 h")


class LongBarsTest(PaneCase):
    def seg(self, title=TITLE):
        return next(s for s in self.pane.week.canvas.lines if s.occ.title == title)

    def test_long_event_is_a_bar_at_the_column_edge_and_blocks_stay(self):
        canvas = self.pane.week.canvas
        self.assertNotIn(TITLE, [o.title for _r, o, *_x in canvas.boxes])
        seg = self.seg()
        self.assertAlmostEqual(seg.x, self.pane.week.geom().x(seg.col) + 1)
        self.assertAlmostEqual(seg.top, self.pane.week.minute_y(10 * 60) - 9, delta=0.01)
        self.assertIn("Point équipe 3D", [o.title for _r, o, *_x in canvas.boxes])

    def test_settings_off_threshold_and_widths(self):
        p = self.pane
        p.apply_settings(dict(p.settings, agenda_long_bars=False))
        pump()
        self.assertEqual(p.week.canvas.lines, [])
        p.apply_settings(dict(p.settings, agenda_long_bars=True, agenda_long_threshold=2, agenda_bar_width=14,
                              agenda_arrow_width=12))
        pump()
        titles = {s.occ.title for s in p.week.canvas.lines}
        self.assertIn("Ferme de rendu — 26017", titles)              # 3 h : barre à partir de 2 h
        r = self.seg().path.boundingRect()
        self.assertAlmostEqual(r.width(), 14 + 12, delta=0.6)

    def test_hover_popover_follows_the_cursor_and_leaves_with_it(self):
        canvas = self.pane.week.canvas
        seg = self.seg()
        y = self.pane.week.minute_y(12 * 60)
        hover(canvas, QPointF(seg.x + 4, y))
        pops = canvas._popovers()
        self.assertEqual([pp.pinned for pp, _h in pops], [False])
        self.assertAlmostEqual(pops[0][0].lead_from.y(), y)
        hover(canvas, QPointF(seg.x + 4, y + 30))
        self.assertAlmostEqual(canvas._popovers()[0][0].lead_from.y(), y + 30)
        hover(canvas, QPointF(seg.x + 60, y))                       # hors de la barre
        self.assertEqual(canvas._popovers(), [])

    def test_click_pins_the_popover_and_reclick_removes_it(self):
        canvas = self.pane.week.canvas
        seg = self.seg()
        p = QPointF(seg.x + 4, self.pane.week.minute_y(12 * 60))
        hover(canvas, p)
        mouse(canvas, "press", p)
        mouse(canvas, "release", p)
        pump()
        pops = canvas._popovers()
        self.assertEqual([pp.pinned for pp, _h in pops], [True])
        self.assertTrue(pops[0][0].can_open)                         # vue Semaine : « Ouvrir la journée »
        hover(canvas, QPointF(seg.x + 60, p.y()))
        self.assertEqual(len(canvas._popovers()), 1)                 # le curseur part : il reste
        hover(canvas, p)
        mouse(canvas, "press", p)
        mouse(canvas, "release", p)
        pump()
        self.assertEqual(canvas._popovers(), [])
        hover(canvas, QPointF(p.x(), p.y() + 10))                    # toujours sur la barre : pas de survol
        self.assertEqual(canvas._popovers(), [])

    def test_end_grip_drag_changes_the_end_with_a_live_popover(self):
        canvas = self.pane.week.canvas
        r = next(z for k, z in self.seg().grips if k == "e")
        start, h = r.center(), self.pane.ctx.hour_h
        hover(canvas, start)
        mouse(canvas, "press", start)
        for i in range(1, 6):
            mouse(canvas, "move", QPointF(start.x(), start.y() + h * i / 5))
        self.assertEqual(canvas._gesture["kind"], "bar_e")
        self.assertIn("10:00 – 16:00", canvas._popovers()[-1][0].when)
        mouse(canvas, "release", QPointF(start.x(), start.y() + h))
        settle(self.service)
        pump()
        occ = self.seg().occ
        self.assertEqual((occ.start.hour, occ.end.hour), (10, 16))

    def test_middle_grip_moves_to_another_day_keeping_the_duration(self):
        canvas = self.pane.week.canvas
        r = next(z for k, z in self.seg().grips if k == "m")
        start, h, colw = r.center(), self.pane.ctx.hour_h, self.pane.week.geom().colw
        mouse(canvas, "press", start)
        for i in range(1, 6):
            mouse(canvas, "move", QPointF(start.x() - colw * i / 5, start.y() + h * i / 5))
        mouse(canvas, "release", QPointF(start.x() - colw, start.y() + h))
        settle(self.service)
        pump()
        occ = self.seg().occ
        self.assertEqual((occ.start.day, occ.start.hour, occ.end.hour), (6, 11, 16))

    def test_event_over_24h_is_a_bar_in_the_grid(self):
        self.new_event("Rendu long", paris(2026, 11, 4, 10), paris(2026, 11, 6, 9))
        settle(self.service)
        self.pane.refresh()
        pump()
        grid = self.pane.week
        self.assertNotIn("Rendu long", [o.title for o in grid.bars])
        segs = [s for s in grid.canvas.lines if s.occ.title == "Rendu long"]
        self.assertEqual([(s.is_start, s.is_end) for s in segs], [(True, False), (False, False), (False, True)])
        self.assertIn("m", [k for k, _r in segs[1].grips])            # milieu : jeudi 9:30


if __name__ == "__main__":
    unittest.main()
