"""fm_agenda : interface (panneau seul, données de la maquette) — vues et navigation, gestes à la souris
(création au double-clic, tracé, glisser-déposer, redimensionnement, glisser dans le mois), clavier, recherche,
suppression et annulation, éditeur (validation), thème, fenêtre étroite."""
from _agenda_case import AgendaCase, paris, settle

import unittest
from datetime import date, datetime, timedelta
from unittest import mock

from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication

import _agenda_demo as demo
from fm_agenda.core import timeutil as tu


def pump(n=4):
    for _ in range(n):
        QCoreApplication.processEvents()


def mouse(widget, kind, pos, button=Qt.LeftButton, buttons=None):
    pos = QPointF(pos)
    types = {"press": QEvent.MouseButtonPress, "release": QEvent.MouseButtonRelease, "move": QEvent.MouseMove,
             "double": QEvent.MouseButtonDblClick}
    btns = buttons if buttons is not None else (Qt.NoButton if kind == "release" else button)
    if kind == "move" and buttons is None:
        btns = Qt.LeftButton
    event = QMouseEvent(types[kind], pos, widget.mapToGlobal(pos), button if kind != "move" else Qt.NoButton,
                        btns, Qt.NoModifier)
    QApplication.sendEvent(widget, event)


def key(widget, k, modifiers=Qt.NoModifier, text=""):
    for t in (QEvent.KeyPress, QEvent.KeyRelease):
        QApplication.sendEvent(widget, QKeyEvent(t, k, modifiers, text))


class PaneCase(AgendaCase):
    settings = dict(AgendaCase.settings, agenda_limit_hours=True, agenda_day_start=8, agenda_day_end=21,
                    agenda_confirm_delete=True)

    def setUp(self):
        super().setUp()
        demo.load(self.service)
        settle(self.service)
        from fm_agenda.ui.pane import AgendaPane
        self.pane = AgendaPane(self.service, settings=dict(self.settings))
        demo.freeze(self.pane.ctx)
        self.pane.resize(1280, 820)
        self.pane.show()
        self.pane.cur = demo.TODAY
        self.pane.set_view("semaine")
        self.pane.refresh()
        pump()

    def tearDown(self):
        self.pane.shutdown()
        self.pane.close()
        self.pane.deleteLater()
        pump()
        super().tearDown()

    def week_box(self, title):
        return next((r, o) for r, o, *_rest in self.pane.week.canvas.boxes if o.title == title)


class ViewsTest(PaneCase):
    def test_titles_and_navigation_like_the_mockup(self):
        p = self.pane
        self.assertEqual(p.header.title.title, "Novembre 2026")
        self.assertEqual(p.header.title.sub, "Semaine 45")
        p.set_view("jour")
        self.assertEqual(p.header.title.title, "Vendredi 6 novembre 2026")
        self.assertEqual(p.details.title.text(), "Livraison V2 — 26014 Teaser")   # prochain après 14:20
        p.step(1)
        self.assertEqual(p.cur, date(2026, 11, 7))
        p.set_view("mois")
        self.assertEqual(p.header.title.title, "Novembre 2026")
        self.assertEqual(len(p.month.weeks), 6)
        p.set_view("annee")
        self.assertEqual(p.header.title.title, "2026")
        p.year.monthActivated.emit(date(2026, 3, 1))
        self.assertEqual((p.view, p.cur), ("mois", date(2026, 3, 1)))
        p.set_view("travail")
        self.assertEqual([d.weekday() for d in p.days_shown()], [0, 1, 2, 3, 4])
        p.go_today()
        self.assertEqual(p.cur, p.ctx.today())

    def test_week_shows_bars_lanes_and_now_line(self):
        grid = self.pane.week
        self.assertEqual(sorted(o.title for o in grid.bars), ["Congés — Léa", "Jalon : V2 Teaser 26014"])
        lanes = {o.title: rect for rect, o, *_r in grid.canvas.boxes}
        self.assertLess(lanes["Ferme de rendu — 26017"].width(), lanes["Point équipe 3D"].width())
        self.assertIn(demo.TODAY, grid.days)

    def test_keyboard_navigation(self):
        canvas = self.pane.week.canvas
        canvas.setFocus()
        key(canvas, Qt.Key_Right)
        self.assertEqual(self.pane.cur, demo.TODAY + timedelta(days=7))
        key(canvas, Qt.Key_T, text="t")
        self.assertEqual(self.pane.cur, demo.TODAY)
        key(canvas, Qt.Key_4, text="4")
        self.assertEqual(self.pane.view, "mois")
        key(self.pane, Qt.Key_2, text="2")
        self.assertEqual(self.pane.view, "semaine")

    def test_search_results_and_escape(self):
        p = self.pane
        p.header.search.edit.setText("teaser")
        p._run_search()
        titles = {r[2].title for r in p.results.rows if r[1] == "item"}
        self.assertIn("Livraison V2 — 26014 Teaser", titles)
        self.assertIs(p.stack.currentWidget(), p.results_area)
        p.clear_search()
        self.assertIs(p.stack.currentWidget(), p.week)

    def test_theme_toggle_and_narrow_window(self):
        p = self.pane
        self.assertTrue(p.holder.t.dark)
        p.toggle_theme()
        self.assertFalse(p.holder.t.dark)
        self.assertEqual(p.holder.t.hexc("bg"), "#f7f8f9")
        p.resize(840, 700)
        pump()
        self.assertEqual(p.header.new_btn.text(), "")
        self.assertEqual(p.header.seg.items[0][1], "J")
        p.resize(640, 600)
        pump()
        self.assertFalse(p.sidebar.isVisible())                     # panneau latéral rangé en fenêtre étroite

    def test_width_percent_centers_the_agenda(self):
        """Curseur « Largeur de l'agenda » (barre d'état) : contenu centré, jamais sous MIN_CONTENT, réglage aussi
        appliqué depuis Réglages : Agenda > Affichage."""
        p = self.pane
        p.resize(1400, 800)
        pump()
        self.assertEqual(p.content_width(), 1400)
        p.set_width_percent(60)
        pump()
        self.assertEqual(p.content_width(), 840)
        self.assertEqual(p.layout().contentsMargins().left(), 280)
        self.assertEqual(p.layout().contentsMargins().right(), 280)
        self.assertEqual(p.splitter.geometry().x(), 280)
        self.assertEqual(p.header.width(), 840)
        self.assertTrue(p.sidebar.isVisible())
        p.set_width_percent(30)                                     # 420 px : MIN_CONTENT gardé
        pump()
        self.assertEqual(p.content_width(), p.MIN_CONTENT)
        self.assertFalse(p.sidebar.isVisible())                     # même règle qu'une fenêtre étroite
        p.resize(1000, 800)                                         # fenêtre redimensionnée : le % suit
        pump()
        self.assertEqual(p.content_width(), p.MIN_CONTENT)
        p.apply_settings(dict(p.settings, agenda_width=100))        # fenêtre de réglages
        pump()
        self.assertEqual(p.content_width(), 1000)
        self.assertEqual(p.layout().contentsMargins().left(), 0)
        self.assertTrue(p.sidebar.isVisible())


class GesturesTest(PaneCase):
    def test_double_click_on_empty_slot_opens_the_editor_then_creates(self):
        canvas = self.pane.week.canvas
        g = self.pane.week.geom()
        x = g.x(2) + g.colw / 2                                     # mercredi 4
        y = self.pane.week.minute_y(17 * 60 + 10)
        captured = {}

        def fake_edit(occ, draft, is_new):
            captured["draft"] = draft
            draft.title = "Créé au double-clic"
            self.pane._editor.action = "save"
            return draft
        editor = self.pane._editor_window()
        with mock.patch.object(editor, "edit", side_effect=fake_edit):
            mouse(canvas, "double", QPointF(x, y))
        settle(self.service)
        draft = captured["draft"]
        self.assertEqual((draft.start.day, draft.start.hour, draft.start.minute), (4, 17, 0))
        self.assertEqual(draft.end - draft.start, timedelta(minutes=60))
        titles = [o.title for o in self.service.occurrences(date(2026, 11, 4), date(2026, 11, 5))]
        self.assertIn("Créé au double-clic", titles)

    def test_drag_moves_to_another_day_and_time(self):
        canvas = self.pane.week.canvas
        rect, occ = self.week_box("Point équipe 3D")                # mercredi 15:00 – 16:00
        start = rect.center()
        g = self.pane.week.geom()
        dx = g.colw                                                 # + 1 jour
        dy = self.pane.ctx.hour_h                                   # + 1 heure
        mouse(canvas, "press", start)
        for i in range(1, 6):
            mouse(canvas, "move", QPointF(start.x() + dx * i / 5, start.y() + dy * i / 5))
        mouse(canvas, "release", QPointF(start.x() + dx, start.y() + dy))
        settle(self.service)
        moved = [o for o in self.service.occurrences(date(2026, 11, 5), date(2026, 11, 6)) if o.title == "Point équipe 3D"]
        self.assertEqual(len(moved), 1)
        self.assertEqual((moved[0].start.hour, moved[0].end.hour), (16, 17))
        self.service.undo()
        back = [o for o in self.service.occurrences(date(2026, 11, 4), date(2026, 11, 5)) if o.title == "Point équipe 3D"]
        self.assertEqual(back[0].start.hour, 15)

    def test_resize_bottom_edge_changes_duration(self):
        canvas = self.pane.week.canvas
        rect, occ = self.week_box("Revue lookdev — 26017 Packshot")   # 11:00 – 12:30
        start = QPointF(rect.center().x(), rect.bottom() - 2)
        mouse(canvas, "press", start)
        for i in range(1, 4):
            mouse(canvas, "move", QPointF(start.x(), start.y() + self.pane.ctx.hour_h * i / 3))
        mouse(canvas, "release", QPointF(start.x(), start.y() + self.pane.ctx.hour_h))
        settle(self.service)
        occ = next(o for o in self.service.occurrences(date(2026, 11, 4), date(2026, 11, 5)) if "lookdev" in o.title)
        self.assertEqual((occ.start.hour, occ.start.minute, occ.end.hour, occ.end.minute), (11, 0, 13, 30))

    def test_drag_on_empty_area_creates_the_drawn_range(self):
        canvas = self.pane.week.canvas
        g = self.pane.week.geom()
        x = g.x(6) + g.colw / 2                                     # dimanche 8
        y0, y1 = self.pane.week.minute_y(10 * 60 + 5), self.pane.week.minute_y(12 * 60 + 20)
        got = []
        self.pane.week.createRequested.disconnect()
        self.pane.week.createRequested.connect(lambda s, e, a: got.append((s, e, a)))
        mouse(canvas, "press", QPointF(x, y0))
        for i in range(1, 5):
            mouse(canvas, "move", QPointF(x, y0 + (y1 - y0) * i / 4))
        mouse(canvas, "release", QPointF(x, y1))
        (s, e, all_day), = got
        self.assertEqual((s.day, s.hour, s.minute, e.hour, e.minute, all_day), (8, 10, 0, 12, 30, False))

    def test_recurring_move_asks_the_scope(self):
        canvas = self.pane.week.canvas
        rect, occ = self.week_box("Point de prod hebdo")            # lundi 9:30
        self.assertTrue(occ.recurring)
        with mock.patch("fm_agenda.ui.kit.choose", return_value="this") as choose:
            mouse(canvas, "press", rect.center())
            for i in range(1, 4):
                mouse(canvas, "move", QPointF(rect.center().x(), rect.center().y() + self.pane.ctx.hour_h * i / 3))
            mouse(canvas, "release", QPointF(rect.center().x(), rect.center().y() + self.pane.ctx.hour_h))
        self.assertTrue(choose.called)
        settle(self.service)
        mondays = [o.start.hour for o in self.service.occurrences(date(2026, 11, 1), date(2026, 12, 1))
                   if o.title == "Point de prod hebdo"]
        self.assertEqual(mondays, [10, 9, 9, 9, 9])

    def test_month_chip_drag_moves_the_event(self):
        p = self.pane
        p.set_view("mois")
        pump()
        m = p.month
        rect, occ, day = next((r, o, d) for r, o, d in m.chips if o.title.startswith("Livraison images"))
        target_day = day + timedelta(days=1)
        r = next(i for i, row in enumerate(m.weeks) if target_day in row)
        c = m.weeks[r].index(target_day)
        target = m.cell_rect(r, c).center()
        mouse(m, "press", rect.center())
        mouse(m, "move", QPointF((rect.center().x() + target.x()) / 2, rect.center().y()))
        mouse(m, "move", target)
        mouse(m, "release", target)
        settle(self.service)
        moved = [o for o in self.service.occurrences(target_day, target_day + timedelta(days=1))
                 if o.title.startswith("Livraison images")]
        self.assertEqual(len(moved), 1)
        self.assertEqual(moved[0].start.hour, 16)

    def test_month_click_opens_the_day_like_the_mockup(self):
        p = self.pane
        p.set_view("mois")
        pump()
        m = p.month
        target = m.cell_rect(2, 3).center()                          # jeudi 12
        mouse(m, "press", target)
        mouse(m, "release", target)
        self.assertEqual((p.view, p.cur), ("jour", date(2026, 11, 12)))

    def test_delete_with_confirmation_then_undo_shortcut(self):
        p = self.pane
        rect, occ = self.week_box("Revue client — 26009 Configurateur")
        p._select(occ)
        with mock.patch("fm_agenda.ui.kit.confirm", return_value=True):
            p._delete_selected()
        settle(self.service)
        self.assertNotIn(occ.title, [o.title for o in self.service.occurrences(date(2026, 11, 3), date(2026, 11, 4))])
        key(p.week.canvas, Qt.Key_Z, Qt.ControlModifier)
        settle(self.service)
        self.assertIn(occ.title, [o.title for o in self.service.occurrences(date(2026, 11, 3), date(2026, 11, 4))])

    def test_task_checkbox_toggles_done(self):
        canvas = self.pane.week.canvas
        rect, occ = self.week_box("Exporter les caches Alembic")
        mouse(canvas, "press", QPointF(rect.left() + 12, rect.center().y()))
        settle(self.service)
        occ = next(o for o in self.service.occurrences(date(2026, 11, 4), date(2026, 11, 5)) if "Alembic" in o.title)
        self.assertTrue(occ.done)


class EditorTest(PaneCase):
    def test_editor_fill_collect_and_validation(self):
        p = self.pane
        occ = next(o for o in self.service.occurrences(demo.TODAY, demo.TODAY + timedelta(days=1))
                   if o.title.startswith("Livraison V2"))
        editor = p._editor_window()
        editor.fill(occ, self.service.draft_for(occ), False)
        draft, error = editor.collect()
        self.assertEqual(error, "")
        self.assertEqual((draft.start.hour, draft.end.hour, draft.project), (15, 16, "26014 Teaser"))
        editor.f_end.time.setText("14:00")                           # fin avant le début
        draft, error = editor.collect()
        self.assertIsNone(draft)
        self.assertIn("fin", error)
        editor.f_end.time.setText("17:30")
        editor.f_attendees.setPlainText("Léa Martin <lea@example.com>\nclient@example.com")
        editor.f_reminders.set_values([15, 60])
        draft, error = editor.collect()
        self.assertEqual([a.email for a in draft.attendees], ["lea@example.com", "client@example.com"])
        self.assertEqual(draft.reminders, [15, 60])
        editor.f_start.time.setText("16:00")                         # la fin suit le début (durée gardée)
        editor.f_start._normalize()
        self.assertEqual(editor.f_end.time.text(), "18:30")

    def test_all_day_draft_switched_to_timed_gets_a_valid_end(self):
        editor = self.pane._editor_window()
        draft = self.service.new_draft(date(2026, 11, 12), date(2026, 11, 13), all_day=True)
        draft.title = "Bascule"
        editor.fill(None, draft, True)
        editor.f_all_day.setChecked(False)
        pump()
        result, error = editor.collect()
        self.assertEqual(error, "")
        self.assertFalse(result.all_day)
        self.assertGreater(result.end, result.start)
        self.assertEqual(result.start.date(), date(2026, 11, 12))


if __name__ == "__main__":
    unittest.main()
