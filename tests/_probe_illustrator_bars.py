"""Sonde de fluidité des barres flottantes d'Illustrator (hors écran ; pas un test) : médiane et pire cas, en ms, de
`sync`, d'un clic d'outil, de la repeinture des barres, de l'apparition de la barre « Texte » et des déplacements.
Lancer : `python tests/_probe_illustrator_bars.py` (venv : skia-pathops). Les seuils vérifiés sont dans
`test_illustrator_bars.FluidityTest` ; chiffres relevés : docs/agents/fm_illustrator.md, « Mesures »."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import statistics
import tempfile
import time
from pathlib import Path

_os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

from PySide6.QtCore import QPoint, QPointF
from PySide6.QtWidgets import QApplication, QWidget

APP = QApplication.instance() or QApplication([])
import app_style  # noqa: E402

app_style.apply_style(APP)
from fm_board import serialization, ui as board_ui  # noqa: E402


def settle(seconds=0.05):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        APP.processEvents()
        time.sleep(0.002)


def measure(label, fn, runs=40):
    times = []
    for _ in range(runs):
        start = time.perf_counter()
        fn()
        times.append((time.perf_counter() - start) * 1000)
    print(f"{label:<44} médiane {statistics.median(times):6.2f} ms   pire {max(times):6.2f} ms")


def main():
    folder = Path(tempfile.mkdtemp(prefix="ill_bars_probe_"))
    path = serialization.create_board_file(folder / "essai.mro")
    host = QWidget()
    host.resize(1400, 900)
    pane = board_ui.BoardPane(host)
    pane.open(path)
    pane.resize(1400, 900)
    host.show()
    pane.show()
    pane.set_module("illustrator")
    ctl = pane.illustrator
    ui = ctl.ui
    manager = ui.bars.manager
    settle()
    names = ["select", "pen", "rect", "hand", "zoom"]
    state = {"n": 0}

    def click_tool():
        ui._tool_buttons[names[state["n"] % len(names)]].click()
        state["n"] += 1
        ui.sync()

    def repaint():
        for bar in manager.bars:
            bar.update()
        APP.processEvents()

    def text_in_out():
        text = ctl.new_text(QPointF(100, 300), text="x")
        ctl.select([text])
        ui.sync()
        APP.processEvents()
        ctl.discard(text)
        ctl.select([])
        ui.sync()
        APP.processEvents()

    def move_bar():
        bar = manager.bar("b5")
        manager.begin_bar_drag(bar, bar.mapToGlobal(QPoint(30, 10)))
        for dx in range(0, 200, 20):
            manager.bar_drag_to(bar, bar.mapToGlobal(QPoint(30 + dx, 10 + dx // 2)))
        manager.end_bar_drag(bar)

    def move_item():
        bar = manager.bar_of("pen")
        item = bar._items["pen"]
        manager.begin_item_drag(bar, item, bar.mapToGlobal(item.widget.geometry().center()))
        for dx in range(0, 200, 20):
            manager.item_drag_to(pane.mapToGlobal(QPoint(300 + dx, 400)))
        manager.end_item_drag()

    measure("sync (rien ne change)", ui.sync)
    measure("clic sur un outil + sync", click_tool)
    measure("repeindre les barres", repaint)
    measure("grab de toutes les barres", lambda: [bar.grab() for bar in manager.bars], 20)
    measure("choisir puis quitter un texte (barre Texte)", text_in_out, 15)
    measure("déplacer une barre (10 pas)", move_bar, 10)
    measure("déplacer un outil vers une autre barre (10 pas)", move_item, 5)


if __name__ == "__main__":
    main()
