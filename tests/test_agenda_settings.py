"""Réglages de l'agenda : défauts déclarés (load_settings les garde), fenêtre « Réglages : Agenda » construite
(chaque section, champs d'actions Google et Données compris), application en direct au panneau."""
import os as _os, sys as _sys  # jamais les vrais réglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import os
import shutil
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from _window_cleanup import WindowTestCase, track  # noqa: E402
import settings_store  # noqa: E402

app = QApplication.instance() or QApplication([])


class AgendaSettingsTest(WindowTestCase):
    def setUp(self):
        super().setUp()
        from fm_agenda import runtime
        from fm_agenda.services.agenda import AgendaService
        from fm_agenda.sync.manager import SyncManager
        self.tmp = Path(tempfile.mkdtemp(prefix="agenda_settings_"))
        self.service = AgendaService({"agenda_backup_daily": False}, path=self.tmp / "agenda.sqlite3")
        self.service.sync = SyncManager(self.service)
        runtime.set_service(self.service)

    def tearDown(self):
        from fm_agenda import runtime
        runtime.set_service(None)
        self.service.close()
        shutil.rmtree(self.tmp, ignore_errors=True)
        super().tearDown()

    def test_defaults_catalog_and_window(self):
        import settings_window_v2 as v2
        from fm_agenda.settings import AGENDA_TAB
        from fm_agenda.settings_defaults import AGENDA_DEFAULTS
        from fm_agenda.ui.settings_fields import DataField, GoogleAccountsField
        from settings_catalog import CATALOG
        for key, value in AGENDA_DEFAULTS.items():
            self.assertEqual(settings_store.DEFAULT_SETTINGS[key], value)
        specs = [spec for name, specs in CATALOG.items() if name.startswith("Agenda : ") for spec in specs]
        keys = {s.key for s in specs if not s.kind.startswith("agenda_")}       # champs d'actions : aucune valeur
        self.assertTrue(keys <= set(AGENDA_DEFAULTS), keys - set(AGENDA_DEFAULTS))
        self.assertEqual(v2.MODULE_SCOPES["agenda"], [(AGENDA_TAB, None)])
        window = track(v2.SettingsWindowV2(None, module="agenda"))
        for node in window.findChildren(v2._LazyNode):
            node.set_collapsed(False)
        app.processEvents()
        texts = {label.text() for label in window.findChildren(QLabel)}
        for label in ("Vue à l'ouverture", "Premier jour de la semaine", "Format des heures", "Rappels actifs",
                      "Fuseau horaire", "Synchronisation automatique", "Calendrier par défaut", "Aller à une date"):
            self.assertIn(label, texts)
        google = window.findChildren(GoogleAccountsField)
        self.assertEqual(len(google), 1)
        self.assertIn("Aucun compte connecté", google[0].status.text())
        self.assertTrue(google[0].b_connect.isHidden())              # identifiant OAuth pas encore importé
        data = window.findChildren(DataField)
        self.assertIn("agenda.sqlite3", data[0].info.text())

    def test_live_settings_reach_the_pane(self):
        from fm_agenda.ui.pane import AgendaPane
        pane = track(AgendaPane(self.service, settings={"agenda_theme": "sombre", "agenda_first_weekday": 0}))
        pane.resize(1100, 700)
        pane.show()
        pane.apply_settings({"agenda_theme": "clair", "agenda_first_weekday": 6, "agenda_time_format": "12"})
        QCoreApplication.processEvents()
        self.assertFalse(pane.holder.t.dark)
        self.assertEqual(pane.days_shown()[0].weekday(), 6)            # semaine du dimanche
        self.assertEqual(self.service.first_weekday, 6)
        self.assertFalse(pane.ctx.h24)
        pane.shutdown()


if __name__ == "__main__":
    unittest.main()
