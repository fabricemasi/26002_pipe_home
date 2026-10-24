"""Sonde de l'onglet « Markdown » de la fenetre de reglages v2 : construit l'onglet, deplie une partie et enregistre
une capture (fenetre native hors ecran ; valeurs par defaut, jamais les reglages reels).

    python tests/_probe_md_settings_tab.py sortie.png [titre de la partie a deplier]"""
import copy
import os
import sys
import time
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PySide6.QtWidgets import QApplication  # noqa: E402

APP = QApplication.instance() or QApplication(sys.argv)

import settings_store  # noqa: E402
import settings_window_v2 as v2  # noqa: E402


def settle(seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        APP.processEvents()
        time.sleep(0.01)


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "md_tab.png"
    wanted = sys.argv[2] if len(sys.argv) > 2 else "Titres H1-H6"
    settings = copy.deepcopy(settings_store.DEFAULT_SETTINGS)
    with mock.patch.object(v2, "load_settings", lambda: copy.deepcopy(settings)), mock.patch.object(v2, "AUTOSAVE", False):
        window = v2.SettingsWindowV2()
    window.resize(1500, 1100)
    window.move(-3000, 0)
    window.show()
    index = [label for label, _t in v2.SCOPES].index(v2.MARKDOWN_TAB)
    window.tabs.changed.emit(index)
    t0 = time.perf_counter()
    window._show_page(index)
    print(f"onglet construit : {(time.perf_counter() - t0) * 1000:.0f} ms")
    settle(0.3)
    nodes = [n for n in window.findChildren(v2._LazyNode) if n._values.name == v2.MARKDOWN_TAB]
    target = next(n for n in nodes if n.node.title == wanted)
    t0 = time.perf_counter()
    target._head.set_collapsed(False)
    for child in getattr(target, "_child_nodes", [])[:1]:
        child._head.set_collapsed(False)
    settle(0.5)
    print(f"« {wanted} » deplie : {(time.perf_counter() - t0) * 1000:.0f} ms ; widgets : {window.widget_count()}")
    window.grab().save(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
