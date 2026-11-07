"""Réglages du module PDF : défauts déclarés (load_settings les garde), fenêtre « Réglages : PDF » construite (chaque
section), onglet PDF aussi dans « Réglages : Board », et cible des menus / boutons de la fenêtre principale."""
import os as _os, sys as _sys  # jamais les vrais réglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import os
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from _window_cleanup import WindowTestCase, track  # noqa: E402
import settings_store  # noqa: E402

app = QApplication.instance() or QApplication([])


class PdfSettingsTest(WindowTestCase):
    def test_defaults_catalog_and_window(self):
        import settings_window_v2 as v2
        from fm_pdf.settings import PDF_TAB
        from fm_pdf.settings_defaults import PDF_DEFAULTS
        from settings_catalog import CATALOG
        for key, value in PDF_DEFAULTS.items():
            self.assertEqual(settings_store.DEFAULT_SETTINGS[key], value)
        keys = {spec.key for name, specs in CATALOG.items() if name.startswith("PDF : ") for spec in specs}
        self.assertTrue(keys <= set(PDF_DEFAULTS), keys - set(PDF_DEFAULTS))
        self.assertIn("pdf_javascript", keys)
        self.assertEqual(v2.MODULE_SCOPES["pdf"], [(PDF_TAB, None)])
        self.assertIn((PDF_TAB, None), v2.MODULE_SCOPES["board"])          # intégré au Board
        window = track(v2.SettingsWindowV2(None, module="pdf"))
        for node in window.findChildren(v2._LazyNode):
            node.set_collapsed(False)
        app.processEvents()
        texts = {label.text() for label in window.findChildren(QLabel)}
        for label in ("Zoom à l'ouverture", "Surbrillance des champs interactifs", "Mémoire des pages rendues",
                      "Double-clic sur un .pdf : éditeur PDF", "Résolution d'impression"):
            self.assertIn(label, texts)

    def test_module_targets(self):
        from main_window.module_targets import MODULES, OPENERS, module_targets
        self.assertIn("pdf", module_targets(Path("x/plan.PDF"), False))
        self.assertNotIn("pdf", module_targets(Path("x/plan.pdf"), True))
        self.assertEqual(OPENERS["pdf"], "_open_pdf")
        self.assertEqual(MODULES["pdf"][1], "btn_pdf")


if __name__ == "__main__":
    unittest.main()
