"""Vue du module PDF (Qt hors écran) : ouverture par la session, tuiles rendues dans le fil du moteur, zoom ancré
sous le curseur, navigation, et REMPLISSAGE d'un formulaire par de vrais évènements Qt (clic, frappe, Tab)."""
import os as _os, sys as _sys  # jamais les vrais réglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import os
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import _pdf_samples as S  # noqa: E402

APP = QApplication.instance() or QApplication([])


def wait_until(cond, timeout=10.0):
    end = time.perf_counter() + timeout
    while time.perf_counter() < end:
        APP.processEvents()
        if cond():
            return True
        time.sleep(0.005)
    APP.processEvents()
    return cond()


def type_char(widget, ch):
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QKeyEvent
    for kind in (QEvent.KeyPress, QEvent.KeyRelease):
        QApplication.sendEvent(widget, QKeyEvent(kind, 0, Qt.NoModifier, ch))


def move_to(widget, pos):
    """Survol déterministe (QTest.mouseMove n'atteint pas toujours un widget enfant hors écran)."""
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QMouseEvent
    p = QPointF(pos)
    QApplication.sendEvent(widget, QMouseEvent(QEvent.MouseMove, p, widget.mapToGlobal(p), Qt.NoButton,
                                               Qt.NoButton, Qt.NoModifier))


def make_view(data, size=(820, 900)):
    from fm_pdf.session import PdfSession
    from fm_pdf.view import PdfView
    session = PdfSession()
    view = PdfView(session, {"pdf_default_fit": "width"})
    view.resize(*size)
    view.show()
    session.open_bytes(data, "test.pdf")
    assert wait_until(lambda: session.info.get("page_count")), "ouverture"
    return session, view


def settle(view, timeout=10.0):
    """Attend que les tuiles visibles soient toutes rendues."""
    def done():
        view.viewport().repaint()
        gen, skey = view.session.generation, view._scale_key()
        return all(view._page_complete(i, skey) for i in view._visible_indexes()
                   if view.page_rect(i).intersects(view.viewport().rect())) and not view._zooming
    return wait_until(done, timeout)


class ViewTest(unittest.TestCase):
    def tearDown(self):
        from PySide6.QtCore import QEvent
        for attr in ("view", "session"):
            obj = getattr(self, attr, None)
            if obj is not None:
                obj.close()
                if attr == "view":
                    obj.deleteLater()
        wait_until(lambda: self.session.engine.pending() == 0, 10)
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)    # détruits AVANT la fin du processus
        APP.processEvents()

    def test_pages_render_and_zoom_keeps_the_point_under_the_cursor(self):
        self.session, self.view = make_view(S.text_pdf(5))
        v = self.view
        self.assertEqual(v.page_count(), 5)
        self.assertTrue(settle(v))
        img = v.viewport().grab().toImage()
        dark = sum(1 for y in range(0, img.height(), 3) for x in range(0, img.width(), 3)
                   if img.pixelColor(x, y).lightness() < 90)
        self.assertGreater(dark, 20)                                   # du texte est dessiné
        anchor = QPointF(300, 200)
        before = v.page_at(anchor)
        v.set_zoom(v.zoom * 2.0, anchor)
        after = v.page_at(anchor)
        self.assertEqual(before[0], after[0])
        self.assertAlmostEqual(before[1], after[1], delta=1.0)        # même point de la page sous le curseur
        self.assertAlmostEqual(before[2], after[2], delta=1.0)
        self.assertTrue(settle(v))
        v.go_to_page(3)
        self.assertEqual(v.current, 3)
        v.set_mode("two_continuous")
        self.assertEqual(v.page_rect(0).top(), v.page_rect(1).top())  # côte à côte
        v.history_back()
        self.assertTrue(v.stats()["tiles"] > 0)

    def test_fill_form_with_real_qt_events(self):
        self.session, self.view = make_view(S.sample_form())
        v = self.view
        self.assertTrue(settle(v))
        fields = {f["name"]: f for f in self.session.info["fields"]}

        def screen(name):
            x0, y0, x1, y1 = fields[name]["rect"]
            pr = v.page_rect(0)
            return QPoint(int(pr.left() + (x0 + x1) / 2 * v.zoom), int(pr.top() + (y0 + y1) / 2 * v.zoom))
        target = screen("nom")
        QTest.mouseMove(v.viewport(), target)
        self.assertTrue(wait_until(lambda: v._hover_field == 6))      # survol : champ texte reconnu
        QTest.mouseClick(v.viewport(), Qt.LeftButton, Qt.NoModifier, target)
        self.assertTrue(v.form_focus)
        QTest.keyClicks(v, "Zo")
        type_char(v, "é")                       # QTest.keyClicks("é") fait tomber PySide6 6.11 : vrai QKeyEvent
        QTest.keyClicks(v, " Martin")
        QTest.keyClick(v, Qt.Key_Tab)
        self.assertTrue(wait_until(lambda: self.session.engine.pending() == 0))
        self.assertEqual(self.session.call(lambda doc: doc.focused_field()), (0, "qte"))
        QTest.keyClicks(v, "4")
        QTest.keyClick(v, Qt.Key_Escape)        # Échap : sort du champ (valeur validée), le module reste ouvert
        self.assertFalse(v.form_focus)
        self.assertTrue(wait_until(lambda: self.session.engine.pending() == 0))
        values = self.session.call(lambda doc: {f["name"]: f["value"] for f in doc.fields()})
        self.assertEqual(values["nom"], "Zoé Martin")
        self.assertEqual(values["qte"], "4")
        self.assertTrue(self.session.form_dirty or wait_until(lambda: self.session.form_dirty))
        self.assertTrue(settle(v))                                    # tuiles du champ redessinées


if __name__ == "__main__":
    unittest.main()
