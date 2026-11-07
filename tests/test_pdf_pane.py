"""Éditeur PDF complet (Qt hors écran) : ouverture, CONCEPTION d'un champ (mode distinct), passage en
REMPLISSAGE, saisie au clavier dans ce champ, enregistrement sur disque (écriture vérifiée), réouverture ; outils
Pages (rotation annulable) et Commentaires (surlignage persistant) ; Échap ne ferme pas le module."""
import os as _os, sys as _sys  # jamais les vrais réglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("FM_PDF_RECOVERY_DIR", tempfile.mkdtemp(prefix="pdf_recovery_"))

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

import _pdf_samples as S  # noqa: E402
from test_pdf_view import APP, move_to, settle, wait_until  # noqa: E402


class PaneTest(unittest.TestCase):
    def setUp(self):
        from fm_pdf.pane import PdfPane
        self.tmp = Path(tempfile.mkdtemp(prefix="pdf_pane_"))
        self.path = self.tmp / "formulaire.pdf"
        self.path.write_bytes(S.sample_form())
        self.pane = PdfPane(None, {"pdf_default_fit": "width", "pdf_autosave_recovery_s": 0,
                                   "pdf_show_thumbnails": True, "pdf_javascript": True})
        self.pane.resize(1400, 950)
        self.pane.show()
        self.assertTrue(self.pane.open_path(self.path))
        self.assertTrue(wait_until(lambda: self.pane.session.info.get("page_count") == 1))

    def tearDown(self):
        from PySide6.QtCore import QEvent
        from PySide6.QtWidgets import QApplication
        self.pane.shutdown()
        self.pane.close()
        self.pane.deleteLater()
        self.assertTrue(wait_until(lambda: self.pane.session.engine.pending() == 0, 10))
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)    # détruits AVANT la fin du processus
        APP.processEvents()

    def _idle(self):
        return wait_until(lambda: self.pane.session.engine.pending() == 0 and not self.pane.session._callbacks, 15)

    def test_design_then_fill_then_save_and_reopen(self):
        pane = self.pane
        pane.set_mode("design")
        self.assertTrue(pane.right.isVisible())
        self.assertTrue(wait_until(lambda: len(pane.designer.specs) == 12))
        pane.designer.create("text", 0, (300, 500, 480, 520))
        self.assertTrue(wait_until(lambda: any(s.name == "Texte" for s in pane.designer.specs)))
        new = next(s for s in pane.designer.specs if s.name == "Texte")
        self.assertEqual(pane.designer.overlay.selected, [new.xref])      # le champ créé est choisi
        prop = pane.designer.panel.table.fields["required"]               # propriété : obligatoire
        prop.setText("oui")
        pane.designer.panel._commit("required", "oui")
        self.assertTrue(wait_until(lambda: next((s for s in pane.designer.specs if s.name == "Texte"),
                                                new).required))
        self.assertTrue(pane.session.can_undo())
        pane.set_mode("fill")                                              # test immédiat
        self.assertIsNone(pane.view.overlay)
        self.assertTrue(settle(pane.view))
        v = pane.view
        pr = v.page_rect(0)
        target = QPoint(int(pr.left() + 390 * v.zoom), int(pr.top() + 510 * v.zoom))
        move_to(v.viewport(), target)
        self.assertTrue(wait_until(lambda: v._hover_field == 6))
        QTest.mouseClick(v.viewport(), Qt.LeftButton, Qt.NoModifier, target)
        QTest.keyClicks(v, "Valeur saisie")
        QTest.keyClick(v, Qt.Key_Escape)
        self.assertTrue(self._idle())
        pane.save()
        self.assertTrue(wait_until(lambda: not pane.session.dirty, 15))
        import pymupdf
        doc = pymupdf.open(self.path)
        widgets = {w.field_name: w for w in doc[0].widgets()}
        self.assertEqual(widgets["Texte"].field_value, "Valeur saisie")
        self.assertTrue(widgets["Texte"].field_flags & 2)                 # obligatoire
        self.assertEqual(len(widgets), 11)                                # 10 + nouveau (radios groupés : 1 nom)
        doc.close()
        pane.open_path(self.path)                                          # réouverture : valeur modifiable
        self.assertTrue(wait_until(lambda: any(f["name"] == "Texte" and f["value"] == "Valeur saisie"
                                               for f in pane.session.info.get("fields", []))))

    def test_page_rotation_is_undoable_and_comments_persist(self):
        pane = self.pane
        from fm_pdf import page_actions
        page_actions.rotate(pane, 1, [0])
        self.assertTrue(wait_until(lambda: pane.session.info["sizes"][0][0] > pane.session.info["sizes"][0][1]))
        pane.session.undo()
        self.assertTrue(wait_until(lambda: pane.session.info["sizes"][0][0] < pane.session.info["sizes"][0][1]))
        ctl = pane._ensure_annot()
        ctl.add(0, "rect", {"rect": (60, 600, 200, 680)})
        self.assertTrue(wait_until(lambda: pane.comments_panel.tree.topLevelItemCount() == 1))
        pane.save()
        self.assertTrue(wait_until(lambda: not pane.session.dirty, 15))
        from fm_pdf import annots
        items = annots.list_all(self.path.read_bytes())
        self.assertEqual([a["kind"] for a in items], ["rect"])

    def test_digital_signature_by_a_simple_click(self):
        """Parcours réel : Protéger > Signer numériquement > certificat personnel > SIMPLE CLIC sur la page (taille
        standard) > document signé enregistré, intact, rouvert."""
        from unittest import mock
        from fm_pdf import protect_actions, security
        pane = self.pane
        signed = self.tmp / "formulaire_signé.pdf"
        answers = iter(["Fabrice Test", "phrase", "Approuvé"])
        with mock.patch.object(protect_actions.ui_kit, "choose", return_value="self"),                 mock.patch.object(protect_actions.ui_kit, "ask_text", side_effect=lambda *a, **k: next(answers)),                 mock.patch.object(protect_actions.ui_kit, "confirm", return_value=True) as confirm,                 mock.patch.object(protect_actions.QFileDialog, "getSaveFileName",
                                  side_effect=[("", ""), (str(signed), "")]):
            pane.set_mode("protect")
            protect_actions.digital_signature(pane)
            self.assertTrue(pane.banner.isVisible())                       # consigne bien visible
            v = pane.view
            pr = v.page_rect(0)
            QTest.mouseClick(v.viewport(), Qt.LeftButton, Qt.NoModifier,
                             QPoint(int(pr.left() + 320 * v.zoom), int(pr.top() + 700 * v.zoom)))
            self.assertTrue(wait_until(lambda: signed.exists() and confirm.called, 30))
        self.assertFalse(pane.banner.isVisible())
        (state,) = security.verify(signed.read_bytes())
        self.assertTrue(state["intact"] and state["valid"], state)
        self.assertIn("Fabrice Test", state["signer"])
        self.assertTrue(wait_until(lambda: pane.session.path == signed, 15))   # le document signé est rouvert

    def test_escape_never_closes_the_module(self):
        closed = []
        self.pane.closeRequested.connect(lambda: closed.append(True))
        self.pane.set_mode("design")
        QTest.keyClick(self.pane, Qt.Key_Escape)
        QTest.keyClick(self.pane.view, Qt.Key_Escape)
        APP.processEvents()
        self.assertEqual(closed, [])
        self.assertTrue(self.pane.isVisible())


if __name__ == "__main__":
    unittest.main()
