"""Sonde visuelle du module CAD (vraie fenetre Windows, hors de l'ecran, polices reelles) : lignes de
plusieurs epaisseurs, extremites (coupe franche, arrondi, border radius), types de ligne, calques, selection
avec poignees, panneau Proprietes, LIGNE en cours (accrochage, saisie dynamique), gestionnaire de calques.

    QT_QPA_PLATFORM=windows python tests/_probe_cad.py [dossier_des_captures]

Ecrit cad_page.png, cad_zoom.png, cad_layers.png."""
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PySide6.QtCore import QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

APP = QApplication.instance() or QApplication([])
import app_style  # noqa: E402
import board  # noqa: E402
from board import cad_model  # noqa: E402
from board import ui as board_ui  # noqa: E402


def settle(seconds=0.1):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        APP.processEvents()


def main():
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.mkdtemp())
    out.mkdir(parents=True, exist_ok=True)
    app_style.apply_style(APP)
    from settings_store import DEFAULT_SETTINGS
    work = Path(tempfile.mkdtemp())
    path = board.create_board_file(work / "plan")
    host = QWidget()
    host.setAttribute(Qt.WA_DontShowOnScreen, False)
    host.resize(1500, 900)
    host.move(-4000, 100)                       # hors de l'ecran
    host.show()
    pane = board_ui.BoardPane(host, dict(DEFAULT_SETTINGS))
    pane.open(path)
    pane.show()
    pane.fit()
    pane.view.set_zoom(1.0)
    pane.view.center_on(QPointF(250, -120))
    pane.toggle_cad(True)
    ctl = pane.cad
    settle(0.3)
    cad = cad_model.copy_cad(ctl.cad_page())
    cad["layers"].append(dict(cad_model.LAYER_DEFAULTS, id="L1", name="Murs", color="#c0392b", lineweight=12.0))
    cad["layers"].append(dict(cad_model.LAYER_DEFAULTS, id="L2", name="Axes", color="#2d9bf0", linetype="center"))
    ctl.set_cad(cad, "calques")
    styles = [("flat", 0), ("round", 0), ("radius", 0), ("radius", 35), ("radius", 100)]
    for n, (style, radius) in enumerate(styles):
        y = 40 * n
        ctl.run("LINE", echo=False)
        ctl.submit(f"0,{y}")
        ctl.submit(f"@180,{n * 6}")
        ctl.submit("")
        item = ctl.cad_items()[-1]
        ctl.change_entities([item], {"layer": "L1", "end1": {"style": style, "radius": radius},
                                     "end2": {"style": "flat" if n % 2 else style, "radius": radius}}, "x")
    for n, linetype in enumerate(("dashed", "hidden", "center", "dashdot", "dot", "phantom")):
        ctl.run("LINE", echo=False)
        ctl.submit(f"260,{n * 28}")
        ctl.submit("@200,0")
        ctl.submit("")
        item = ctl.cad_items()[-1]
        ctl.change_entities([item], {"linetype": linetype, "lineweight": 3.0 if n % 2 else 0.0}, "x")
    ctl.run("LINE", echo=False)
    for text in ("520,0", "@120,0", "@0,120", "@-120,0", "C"):
        ctl.submit(text)
    axis = ctl.cad_items()[-2]
    ctl.change_entities([axis], {"layer": "L2"}, "x")
    ctl.cad_items()[2].setSelected(True)
    ctl.ui.show_properties()
    settle(0.3)
    ctl.run("LINE")
    ctl.submit("400,200")
    viewport = pane.view.viewport()
    target = ctl.doc_to_view((640, 118)).toPoint()
    QTest.mouseMove(viewport, target + QPoint(5, 5))
    QTest.mouseMove(viewport, target)
    ctl._move_cursor(QPointF(target))            # fenetre hors de l'ecran : le curseur n'y entre pas
    settle(0.4)
    ctl.overlay.repaint()
    settle(0.2)
    host.grab().save(str(out / "cad_page.png"))
    # (pas de mesure de peinture ici : une fenetre hors de l'ecran n'est pas repeinte par Windows ; mesures
    # dans tests/test_cad.py, PerformanceTest)
    pane.view.set_zoom(12.0, ctl.doc_to_view((180, 0)))
    settle(0.3)
    host.grab().save(str(out / "cad_zoom.png"))
    ctl.ui.open_layers()
    settle(0.4)
    ctl.ui._layers.grab().save(str(out / "cad_layers.png"))
    print("captures :", out)
    pane._autosave.stop()


if __name__ == "__main__":
    main()
