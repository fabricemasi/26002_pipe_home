"""Outils communs des tests de fm_agenda : service sur une base temporaire, attente du fil d'écriture."""
import _isolate  # noqa: F401

import shutil
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication

from fm_agenda.core import timeutil as tu

PARIS = "Europe/Paris"
SETTINGS = {"agenda_timezone": PARIS, "agenda_backup_daily": False, "agenda_default_duration": 60}


def app():
    return QApplication.instance() or QApplication([])


def paris(y, m, d, h=0, mi=0):
    return tu.localize(datetime(y, m, d, h, mi), tu.get_tz(PARIS))


def settle(service, rounds: int = 3):
    """Écritures terminées ET leurs rappels délivrés dans le fil de l'interface."""
    for _ in range(rounds):
        service.flush()
        QCoreApplication.processEvents()


class AgendaCase(unittest.TestCase):
    settings = SETTINGS

    @classmethod
    def setUpClass(cls):
        app()

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="agenda_test_"))
        self.path = self.tmp / "agenda.sqlite3"
        self.service = self.open_service()

    def open_service(self):
        from fm_agenda.services.agenda import AgendaService
        return AgendaService(dict(self.settings), path=self.path)

    def reopen(self):
        settle(self.service)
        self.service.close()
        self.service = self.open_service()
        return self.service

    def tearDown(self):
        try:
            settle(self.service)
            self.service.close()
        finally:
            shutil.rmtree(self.tmp, ignore_errors=True)

    def cal(self, name="Projets et revues"):
        return next(c for c in self.service.calendars() if c.name == name)

    def new_event(self, title, start, end, **fields):
        draft = self.service.new_draft(start, end, calendar_id=self.cal().id)
        draft.title = title
        for k, v in fields.items():
            setattr(draft, k, v)
        return self.service.create(draft)
