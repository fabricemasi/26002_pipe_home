"""Fenetres de reglages construites par les tests : DETRUITES a la fin de leur test (ou de leur classe pour
celles de `setUpClass`). Une fenetre seulement fermee garde ses ~24 000 widgets vivants, inscrits dans les
listes globales des reglages (zones de saisie, arrondis, tableaux) que chaque restylage parcourt : les suites
`test_settings_cells` / `test_settings_window_v2` ralentissaient a chaque test (jusqu'a 90 s par test, la
suite complete ne finissait plus en 90 min).

    from _window_cleanup import WindowTestCase, track
    win = track(v2.SettingsWindowV2())      # dans les fonctions qui construisent une fenetre
    class MonTest(WindowTestCase): ...      # au lieu de unittest.TestCase
"""
import unittest

import shiboken6
from PySide6.QtCore import QCoreApplication, QEvent

_LIVE: list = []


def track(window):
    _LIVE.append(window)
    return window


def track_class(window_class):
    """Toute fenetre de cette classe creee pendant les tests est suivie (et detruite a la fin du test)."""
    if getattr(window_class, "_window_cleanup_tracked", False):
        return
    original = window_class.__init__

    def __init__(self, *args, **kwargs):
        original(self, *args, **kwargs)
        track(self)
    window_class.__init__ = __init__
    window_class._window_cleanup_tracked = True


def dispose(windows):
    """Detruites sans `close()` (qui pourrait demander une confirmation modale et bloquer le test)."""
    for window in windows:
        if shiboken6.isValid(window):
            window.hide()
            window.deleteLater()
    if windows:
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


class WindowTestCase(unittest.TestCase):
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        own_setup = cls.__dict__.get("setUpClass")
        own_teardown = cls.__dict__.get("tearDownClass")

        def setUpClass(klass):
            mark = len(_LIVE)
            if own_setup is not None:
                own_setup.__func__(klass)
            else:
                super(cls, klass).setUpClass()
            klass._class_windows = _LIVE[mark:]
            del _LIVE[mark:]

        def tearDownClass(klass):
            try:
                if own_teardown is not None:
                    own_teardown.__func__(klass)
                else:
                    super(cls, klass).tearDownClass()
            finally:
                dispose(klass.__dict__.get("_class_windows", []))

        cls.setUpClass = classmethod(setUpClass)
        cls.tearDownClass = classmethod(tearDownClass)

    def run(self, result=None):
        mark = len(_LIVE)
        try:
            return super().run(result)
        finally:
            windows = _LIVE[mark:]
            del _LIVE[mark:]
            dispose(windows)
