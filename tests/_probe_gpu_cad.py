"""Sonde du rendu GPU du CAD (board/cad_gpu.py) en VRAIE fenetre Windows, a l'ecran (interpreteur du projet : `.venv`, PyOpenGL) :
meme dessin peint par le rendu raster (lots du processeur) puis par le GPU, captures de l'ecran reel comparees pixel a
pixel (la capture d'un widget `grab()` ne montre pas le contenu d'un QOpenGLWidget tel qu'affiche).

    QT_QPA_PLATFORM=windows .venv/Scripts/python.exe tests/_probe_gpu_cad.py [dossier de sortie]

Affiche l'ecart moyen / le nombre de pixels qui different de plus de 8 et de 32 niveaux, et ecrit raster.png / gpu.png."""
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import numpy as np  # noqa: E402
from PySide6.QtCore import QPointF, QRect  # noqa: E402
from PySide6.QtGui import QGuiApplication, QImage  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

APP = QApplication.instance() or QApplication([])
import app_style  # noqa: E402
import board  # noqa: E402
from board import cad_model, model  # noqa: E402
from board import ui as board_ui  # noqa: E402
from settings_store import DEFAULT_SETTINGS  # noqa: E402

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.mkdtemp())


def settle(seconds):
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        APP.processEvents()


def grab(host) -> QImage:
    host.activateWindow()
    settle(0.8)
    return QGuiApplication.primaryScreen().grabWindow(host.winId()).toImage().copy(QRect(250, 220, 800, 480))


def pixels(image: QImage):
    image = image.convertToFormat(QImage.Format_RGB32)
    raw = np.frombuffer(image.constBits(), dtype=np.uint8)
    return raw.reshape(image.height(), image.bytesPerLine() // 4, 4)[:, :image.width(), 2].astype(int)


def main():
    app_style.apply_style(APP)
    path = board.create_board_file(Path(tempfile.mkdtemp()) / "plan")
    host = QWidget()
    host.resize(1300, 860)
    host.move(100, 60)
    host.show()
    pane = board_ui.BoardPane(host, dict(DEFAULT_SETTINGS, board_cad_unit="px"))
    pane.open(path)
    pane.show()
    pane.fit()
    pane.toggle_cad(True)
    ctl = pane.cad
    scene = pane.scene
    cad = ctl.cad_page()

    def add(kind, **geometry):
        data = model.new_item(kind, **cad_model.new_entity_values(cad, **geometry))
        return scene._add(data)

    thick = add("cad_line", p1=[-100.0, -60.0], p2=[100.0, -60.0], lineweight=10.0,
                end1={"style": "round", "radius": 50.0}, end2={"style": "radius", "radius": 60.0})
    dashed = add("cad_line", p1=[-100.0, -30.0], p2=[100.0, -10.0], lineweight=6.0, linetype="dashed")
    add("cad_circle", center=[0.0, 40.0], radius=30.0, lineweight=5.0)
    add("cad_arc", center=[-60.0, 40.0], radius=30.0, start=0.0, end=180.0)
    add("cad_pline", vertices=[[40.0, 20.0, 0.0], [100.0, 20.0, 1.0], [100.0, 70.0, 0.0], [40.0, 70.0, 0.0]],
        lineweight=8.0, end2={"style": "round", "radius": 50.0})
    del thick, dashed
    ctl.touch_index()
    pane.view.set_zoom(3.0)
    pane.view.center_on(QPointF(0, -20))
    results = {}
    for name, gpu in (("raster", False), ("gpu", True)):
        pane.apply_settings(dict(pane._settings, board_cad_gpu=gpu))
        settle(0.8)
        if gpu and getattr(pane.view, "gpu", None) is None:
            print("GPU indisponible (PyOpenGL / OpenGL 3.3) : rien a comparer")
            return
        results[name] = grab(host)
        results[name].save(str(OUT / f"{name}.png"))
    a, b = pixels(results["raster"]), pixels(results["gpu"])
    diff = np.abs(a - b)
    print(f"ecart moyen {diff.mean():.3f} niveaux ; pixels > 8 : {(diff > 8).sum()}, > 32 : {(diff > 32).sum()} "
          f"sur {diff.size} ; captures dans {OUT}")


main()
