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
from PySide6.QtCore import QPointF, QRect, Qt  # noqa: E402
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
    pane = board_ui.BoardPane(host, dict(DEFAULT_SETTINGS, board_cad_unit="mm", board_cad_gpu=os.environ.get("GPU", "1") == "1",
                                          board_cad_dim_scale=int(os.environ.get("DIMSCALE", "100"))))
    pane.open(path)
    pane.resize(host.size()); pane.show()
    pane.toggle_cad(True)
    ctl, scene = pane.cad, pane.scene
    def run(*texts):
        from PySide6.QtTest import QTest
        for t in texts:
            for ch in t:
                QTest.keyClick(pane.view, ch)
            QTest.keyClick(pane.view, Qt.Key_Return)
        settle(0.05)
    k = ctl.unit()
    run("REC", "0,0", "120,80")
    run("C", "60,40", "20")
    run("REC", "150,0", "250,80")
    run("C", "300,40", "30")
    run("L", "330,0", "330,0")
    run("")
    run("REC", "0,110", "120,190")
    run("REC", "150,110", "250,190")
    pane.fit()
    pane.view.set_zoom(pane.view.zoom() * 0.5)
    ctl.touch_index()
    settle(0.3)
    def hatch(point, *opts):
        run("H", *opts)
        ctl.set_cursor_doc = None
        from PySide6.QtTest import QTest
        QTest.mouseClick(pane.view.viewport(), Qt.LeftButton, Qt.NoModifier, ctl.doc_to_view((point[0] * k, point[1] * k)).toPoint())
        settle(0.1)
        run("")
    hatch((10, 10))                                   # lignes, entre le carre et le cercle (trou)
    hatch((60, 40))                                   # dans le cercle
    hatch((160, 10), "M", "B")                        # briques
    hatch((300, 40), "M", "C")                        # croise, dans le cercle
    hatch((10, 120), "M", "PL")                       # plein
    hatch((160, 120), "M", "L", "A", "0", "E", "5")   # lignes 0 degres
    print("hachures", len([i for i in ctl.cad_items() if i.kind == "cad_hatch"]))
    settle(0.8)
    host.activateWindow(); settle(0.5)
    img = QGuiApplication.primaryScreen().grabWindow(host.winId()).toImage()
    img.save(str(OUT / "dims.png"))
    pane.view.viewport().grab().save(str(OUT / "dims_vp.png"))
    print("saved", OUT / "dims.png")


main()
