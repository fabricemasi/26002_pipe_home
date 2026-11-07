"""Module PDF DANS le Board : bouton de la barre des modules, barres flottantes, élément `pdf_doc` lié au fichier
(enregistré dans le .brd, relu), APERÇU de toutes les pages par le document de l'élément (XFA compris : jamais la
page de repli « Please wait… »), ÉDITION SUR PLACE quand le module est actif (clic, saisie au clavier, Tab, Ctrl+S
dans le fichier lié), pleine page / pleine largeur / plein écran, éditeur plein cadre au-dessus du Board."""
import os as _os, sys as _sys  # jamais les vrais réglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import json
import time
import unittest

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from _lent import lent  # noqa: E402
from _photoshop_case import APP, PsCase, settle  # noqa: E402
import _pdf_samples as S  # noqa: E402


def wait_until(cond, timeout=15.0):
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
    from PySide6.QtWidgets import QApplication
    for kind in (QEvent.KeyPress, QEvent.KeyRelease):
        QApplication.sendEvent(widget, QKeyEvent(kind, 0, Qt.NoModifier, ch))


class PdfBoardTest(PsCase):
    def tearDown(self):
        from fm_pdf import board_docs
        for pane in [self.pane]:
            try:
                board_docs.close_scene(pane.scene)                     # documents du moteur fermés
            except RuntimeError:
                pass
        super().tearDown()

    def _ready(self, item):
        self.pane.view.viewport().grab()                               # peinture réelle : ouvre le document
        return wait_until(lambda: item.entry() is not None and item.entry().ready())

    def _paint_until_images(self, item):
        from fm_pdf import board_docs
        entry = item.entry()

        def has_images():
            self.pane.view.viewport().grab()
            return any(k[0] is entry for k in board_docs._IMAGES)
        return wait_until(has_images)

    def _click_body(self, item, x=60.0, y=80.0):
        v = self.pane.view
        pos = v.mapFromScene(item.mapToScene(QPointF(x, y)))
        QTest.mouseClick(v.viewport(), Qt.LeftButton, Qt.NoModifier, pos)
        settle(0.05)

    def test_module_item_preview_editor_and_reload(self):
        from fm_board import modulebar
        from fm_pdf.board_item import PdfItem
        self.assertIn("pdf", modulebar.MODULE_NAMES)
        pdf = self.tmp / "plan.pdf"
        pdf.write_bytes(S.sample_form())
        self.pane.set_module("pdf")
        self.assertEqual(self.pane.module, "pdf")
        ctl = self.pane.pdf
        self.assertTrue(ctl.active)
        item = ctl.insert(pdf)
        self.assertIsInstance(item, PdfItem)
        self.assertEqual(item.pdf_path().resolve(), pdf.resolve())
        self.assertEqual(item.data["rel"], "plan.pdf")
        w, h = item.size()
        self.assertGreater(h, w)                                       # proportions de la page A4
        self.assertTrue(self._ready(item))
        self.assertTrue(self._paint_until_images(item), "aperçu jamais rendu")
        editor = item.open_editor()
        self.assertIs(ctl.editor, editor)
        self.assertEqual(editor.parent(), self.pane)
        settle(0.3)
        self.assertEqual(editor.session.path, pdf)
        editor.request_close()                                         # non modifié : fermeture directe
        settle(0.05)
        self.assertIsNone(ctl.editor)
        self.assertTrue(self.pane.save())
        data = json.loads(self.path.read_text(encoding="utf-8"))
        kinds = [i["type"] for i in data["items"]]
        self.assertIn("pdf_doc", kinds)
        self.pane.set_module(None)
        self.assertFalse(ctl.active)
        again = self.make_pane(self.path)                              # relu depuis le .brd
        items = [i for i in again.scene.board_items() if isinstance(i, PdfItem)]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].pdf_path().resolve(), pdf.resolve())

    def test_xfa_preview_is_the_real_form_not_the_fallback_page(self):
        """Signalé (imm5707f de l'IRCC) : l'aperçu ouvrait le fichier SANS JavaScript, PDFium montrait alors la page
        de repli « Please wait… ». Le document de l'élément charge le XFA (comme l'éditeur)."""
        pdf = self.tmp / "acia.pdf"
        pdf.write_bytes(S.fixture("xfa_fish_licence.pdf"))
        self.pane.set_module("pdf")
        item = self.pane.pdf.insert(pdf)
        self.assertTrue(self._ready(item))
        info = item.entry().info
        self.assertTrue(info["is_xfa"])
        self.assertTrue(info["xfa_loaded"], "XFA non chargé : page de repli « Please wait… »")
        self.assertTrue(self._paint_until_images(item))

    def test_live_edit_shows_every_page_with_fit_and_fullscreen(self):
        pdf = self.tmp / "texte.pdf"
        pdf.write_bytes(S.text_pdf(4))
        self.pane.set_module("pdf")
        ctl = self.pane.pdf
        item = ctl.insert(pdf)
        self.assertTrue(self._ready(item))
        self.assertFalse(item.is_live())
        self._click_body(item)                                         # module actif : un clic = édition
        self.assertTrue(item.is_live())
        live = item.live
        self.assertIs(ctl.live(), live)
        self.assertEqual(live.view.page_count(), 4)                    # TOUTES les pages
        self.assertEqual(live.view.mode, "continuous")
        self.assertIs(item._proxy.widget(), live)
        for key in ("fit_page", "fit_width", "fullscreen", "zoom_in", "zoom_out", "save", "fill", "hand"):
            self.assertIsNotNone(ctl.bars.manager.bar_of(key), key)   # dans les barres du module
        item.data["w"] = 900.0                                         # élément plus large qu'une page
        item.sync()
        settle(0.05)
        ctl.buttons["fit_width"].click()
        self.assertEqual(live.view.fit, "width")
        z_width = live.view.zoom
        ctl.buttons["fit_page"].click()
        self.assertEqual(live.view.fit, "page")
        self.assertLess(live.view.zoom, z_width)                       # une page entière : plus petit
        self.assertTrue(ctl.buttons["fit_page"].active)
        # « Pleine page » recentre la page EN COURS de manière à remplir l'écran (demande de l'utilisateur 2026-11-06)
        pr = live.view.page_rect(live.view.current)
        page = item._proxy.mapRectToScene(QRectF(live.view.viewport().mapTo(live, pr.topLeft()), pr.size()))
        seen = self.pane.view.mapFromScene(page).boundingRect()
        area = self.pane.view.viewport().rect()
        self.assertTrue(area.adjusted(-2, -2, 2, 2).contains(seen), (seen, area))
        self.assertLessEqual(min(abs(seen.width() - area.width()), abs(seen.height() - area.height())), 2)
        self.assertLessEqual((seen.center() - area.center()).manhattanLength(), 3)
        ctl.buttons["fit_width"].click()
        self.assertAlmostEqual(live.view.zoom, z_width, places=3)
        # « Pleine largeur » : le document en pleine largeur À L'ÉCRAN, le haut de la page en cours en haut
        pr = live.view.page_rect(live.view.current)
        page = item._proxy.mapRectToScene(QRectF(live.view.viewport().mapTo(live, pr.topLeft()), pr.size()))
        seen = self.pane.view.mapFromScene(page).boundingRect()
        self.assertLessEqual(abs(seen.left() - area.left()) + abs(seen.right() - area.right()), 3, (seen, area))
        self.assertLessEqual(abs(seen.top() - area.top()), 2)
        ctl.buttons["fullscreen"].click()                              # plein écran : tout le Board
        settle(0.05)
        self.assertTrue(live.fullscreen)
        self.assertIs(live.parent(), self.pane)
        self.assertEqual(live.geometry(), self.pane.rect())
        self.assertTrue(ctl.buttons["fullscreen"].active)
        QTest.keyClick(live.view, Qt.Key_Escape)                       # Échap : sortie du plein écran seulement
        settle(0.05)
        self.assertFalse(live.fullscreen)
        self.assertIs(item._proxy.widget(), live)
        self.assertEqual(self.pane.module, "pdf")                      # le module reste actif
        live.view.next_page(2)
        page = live.view.current
        self.pane.set_module(None)                                     # module quitté : aperçu, endroit retenu
        self.assertFalse(item.is_live())
        self.assertEqual(item.data["fit"], "width")
        self.assertEqual(item.data["page"], page)
        self.assertTrue(self.pane.save())
        saved = [i for i in json.loads(self.path.read_text(encoding="utf-8"))["items"] if i["type"] == "pdf_doc"]
        self.assertEqual(saved[0]["fit"], "width")

    def test_fill_a_form_in_the_board_tab_and_save_to_the_linked_file(self):
        from fm_pdf import acroform
        pdf = self.tmp / "formulaire.pdf"
        pdf.write_bytes(S.sample_form())
        self.pane.set_module("pdf")
        ctl = self.pane.pdf
        item = ctl.insert(pdf)
        self.assertTrue(self._ready(item))
        self._click_body(item, 10, 40)
        live = item.live
        self.assertIsNotNone(live)
        v = self.pane.view
        fields = {f["name"]: f for f in item.entry().info["fields"]}
        x0, y0, x1, y1 = fields["nom"]["rect"]
        pr = live.view.page_rect(0)
        local = QPointF(pr.left() + (x0 + x1) / 2 * live.view.zoom, pr.top() + (y0 + y1) / 2 * live.view.zoom)
        target = v.mapFromScene(item.mapToScene(local))
        QTest.mouseClick(v.viewport(), Qt.LeftButton, Qt.NoModifier, target)   # vrai clic dans le Board
        self.assertTrue(wait_until(lambda: live.view.form_focus))
        self.assertTrue(v.editing_text())                              # le Board laisse le clavier au document
        QTest.keyClicks(v, "Zo")
        type_char(v, "é")
        QTest.keyClick(v, Qt.Key_Tab)                                  # Tab : champ suivant (pas le focus du Board)
        self.assertTrue(wait_until(lambda: item.session.engine.pending() == 0))
        self.assertEqual(item.session.call(lambda doc: doc.focused_field()), (0, "qte"))
        QTest.keyClicks(v, "4")
        QTest.keyClick(v, Qt.Key_Escape)                               # sort du champ ; le module reste
        self.assertTrue(wait_until(lambda: item.session.dirty))
        self.assertEqual(self.pane.module, "pdf")
        QTest.keyClick(v, Qt.Key_S, Qt.ControlModifier)                # Ctrl+S : le PDF lié
        self.assertTrue(wait_until(lambda: not item.session.dirty))
        values = {f.name: f.value for f in acroform.read_fields(pdf.read_bytes())}
        self.assertEqual(values["nom"], "Zoé")
        self.assertEqual(values["qte"], "4")

    def test_pages_touch_the_frame_and_old_frames_are_fitted_once(self):
        """Demande de l'utilisateur (capture annotée) : « pas d'écart entre le bord de la page et le cadre »."""
        from fm_pdf import board_item
        pdf = self.tmp / "texte.pdf"
        pdf.write_bytes(S.text_pdf(3))
        self.pane.set_module("pdf")
        item = self.pane.pdf.insert(pdf)
        w, h = item.size()
        self.assertAlmostEqual(h / w, 842 / 595, places=2)               # cadre = la page
        self.assertTrue(self._ready(item))
        zoom, rects, cw, _ch = board_item.layout_pages(item.entry().info["sizes"], "width", 1.0, w, h)
        self.assertEqual((rects[0][0], rects[0][1]), (0.0, 0.0))        # aperçu : page au bord du cadre
        self.assertAlmostEqual(cw * zoom, w, places=3)
        self._click_body(item)
        pr = item.live.view.page_rect(0)
        self.assertAlmostEqual(pr.left(), 0.0, delta=0.5)               # édition : pareil
        self.assertAlmostEqual(pr.top(), 0.0, delta=0.5)
        self.assertAlmostEqual(pr.width(), item.live.view.viewport().width(), delta=1.0)
        self.pane.set_module(None)
        old = self.pane.pdf.insert(pdf)                                   # élément d'avant : marges, titre
        old.data.update({"framed": False, "h": h + 60})
        old.sync()
        board_docs = __import__("fm_pdf.board_docs", fromlist=["x"])
        board_docs.close_scene(self.pane.scene)                          # documents rouverts : recalage
        self.assertTrue(self._ready(old))
        self.assertTrue(wait_until(lambda: old.data["framed"]))
        self.assertAlmostEqual(old.size()[1], round(w * 842 / 595, 1), delta=0.6)

    def test_click_while_opening_starts_editing_once_ready(self):
        """Gros XFA : quelques secondes d'ouverture ; le clic fait pendant ce temps n'est pas perdu."""
        pdf = self.tmp / "texte.pdf"
        pdf.write_bytes(S.text_pdf(2))
        self.pane.set_module("pdf")
        item = self.pane.pdf.insert(pdf)
        self.assertIsNone(item.go_live())                              # document pas encore ouvert
        self.assertTrue(wait_until(item.is_live))
        self.assertIs(self.pane.pdf.live_item, item)

    def test_unsaved_document_is_asked_for_when_the_board_closes(self):
        from fm_pdf import ui_kit
        pdf = self.tmp / "formulaire.pdf"
        pdf.write_bytes(S.sample_form())
        self.pane.set_module("pdf")
        item = self.pane.pdf.insert(pdf)
        self.assertTrue(self._ready(item))
        item.session.form_dirty = True                                 # saisie non enregistrée
        asked = []
        original = ui_kit.choose
        ui_kit.choose = lambda *a, **k: asked.append(a[2]) or None     # « Annuler »
        try:
            self.assertFalse(self.pane.confirm_leave())
            ui_kit.choose = lambda *a, **k: asked.append(a[2]) or "discard"
            self.assertTrue(self.pane.confirm_leave())
        finally:
            ui_kit.choose = original
        self.assertEqual(len(asked), 2)
        self.assertIn("formulaire.pdf", asked[0])

    @lent
    def test_ircc_xfa_shows_all_its_pages_in_the_board(self):
        """IRCC IMM 1344 (même famille que l'imm5707f signalé) : 14 pages après mise en page XFA, toutes dans
        l'élément ; sans JavaScript PDFium n'en montrait qu'UNE (la page de repli)."""
        pdf = self.tmp / "imm1344e.pdf"
        pdf.write_bytes(S.fixture("xfa_filled_imm1344e.pdf"))
        self.pane.set_module("pdf")
        item = self.pane.pdf.insert(pdf)
        self.pane.view.viewport().grab()
        self.assertTrue(wait_until(lambda: item.entry().ready(), 60))
        self.assertTrue(item.entry().info["xfa_loaded"])
        self.assertEqual(item.entry().info["page_count"], 14)
        self._click_body(item)
        self.assertEqual(item.live.view.page_count(), 14)


if __name__ == "__main__":
    unittest.main()
