"""PIPE FMZ COMPLET avec le module PDF (lent : fenêtre principale entière, réglages isolés) : démarrage, bouton
« PDF » de la barre, ouverture d'un .pdf (comme le double-clic), cadre « PDF » de la barre de navigation, autre
module qui ferme l'éditeur, fermeture de la fenêtre sans plantage."""
import os as _os, sys as _sys  # jamais les vrais réglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import os
import tempfile
import time
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("FM_PDF_RECOVERY_DIR", tempfile.mkdtemp(prefix="pdf_recovery_"))

from _lent import lent  # noqa: E402
import _pdf_samples as S  # noqa: E402


@lent
class PdfAppTest(unittest.TestCase):
    def test_main_window_opens_and_closes_the_pdf_editor(self):
        from PySide6.QtCore import QEvent
        from PySide6.QtWidgets import QApplication
        from settings_store import load_settings
        import pipeline_browser as pb
        settings = load_settings()
        pb.apply_all_settings(settings)
        app = QApplication.instance() or QApplication([])
        pb.apply_style(app) if hasattr(pb, "apply_style") else None
        tmp = Path(tempfile.mkdtemp(prefix="pdf_app_"))
        pdf = tmp / "formulaire.pdf"
        pdf.write_bytes(S.sample_form())
        root = tmp / "racine"
        (root / "PROJET").mkdir(parents=True)
        win = pb.PipelineBrowser(root)
        win.resize(1500, 950)
        win.show()

        def pump(seconds):
            end = time.perf_counter() + seconds
            while time.perf_counter() < end:
                app.processEvents()
                time.sleep(0.005)
        pump(0.5)
        self.assertTrue(hasattr(win, "btn_pdf"))
        self.assertTrue(win._pdf_claims(pdf))
        self.assertTrue(win._open_pdf(pdf))                            # = double-clic sur le .pdf
        pane = win._pdf
        self.assertIsNotNone(pane)
        end = time.perf_counter() + 15
        while not pane.session.info.get("page_count") and time.perf_counter() < end:
            pump(0.02)
        self.assertEqual(pane.session.info.get("page_count"), 1)
        win._layout_pdf_buttons()
        self.assertTrue(win.titlebar.pdf_group().isVisible())          # cadre « PDF » de la barre
        self.assertEqual(len(win._pdf_buttons), 6)
        win._sync_mode_buttons()
        self.assertFalse(win.scroll.widget().isVisible())              # colonnes masquées sous l'éditeur
        self.assertTrue(win._leave_pdf())                              # un autre module le ferme (non modifié)
        self.assertIsNone(win._pdf)
        self.assertFalse(win.titlebar.pdf_group().isVisible())
        self.assertTrue(win._open_pdf(pdf))
        pump(0.3)
        win.close()                                                     # fermeture : l'éditeur est fermé AVANT
        self.assertIsNone(win._pdf)
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        win.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        pump(0.2)


if __name__ == "__main__":
    unittest.main()
