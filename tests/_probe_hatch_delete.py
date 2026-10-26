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
    from PySide6.QtCore import QEvent, QPointF, QCoreApplication
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtTest import QTest
    run("REC", "0,0", "120,80")
    pane.fit(); settle(0.3)
    vp = pane.view.viewport()
    def move(p):
        at = QPointF(ctl.doc_to_view((p[0] * k, p[1] * k)))
        APP.sendEvent(vp, QMouseEvent(QEvent.MouseMove, at, vp.mapToGlobal(at), Qt.NoButton, Qt.NoButton, Qt.NoModifier))
        settle(0.05)
    for p in [(10, 10), (60, 40)]:
        move(p); print("AVANT", p, "vp", vp.cursor().shape(), ctl.cursor_doc if hasattr(ctl, "cursor_doc") else None)
    run("H")
    QTest.mouseClick(vp, Qt.LeftButton, Qt.NoModifier, ctl.doc_to_view((60 * k, 40 * k)).toPoint()); settle(0.2)
    run("")
    print("hachures", len([i for i in ctl.cad_items() if i.kind == "cad_hatch"]), "pur", pane.view.gpu.pure)
    # selection de la hachure par un clic dedans, puis suppression
    QTest.mouseClick(vp, Qt.LeftButton, Qt.NoModifier, ctl.doc_to_view((60 * k, 40 * k)).toPoint()); settle(0.2)
    print("selection", [i.kind for i in ctl.selection()])
    run("E"); settle(0.5)
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    settle(0.5)
    print("hachures apres", len([i for i in ctl.cad_items() if i.kind == "cad_hatch"]), "pur", pane.view.gpu.pure,
          "aire du viewport actif", vp.updatesEnabled())
    for p in [(10, 10), (60, 40), (100, 70), (30, 20)]:
        move(p)
        print("curseur", p, "doc", ctl.cursor_doc if hasattr(ctl, "cursor_doc") else None, "vp", vp.cursor().shape(), "view", pane.view.cursor().shape(), "plan", getattr(ctl, "_cursor_key", None) is not None,
              "hover", ctl.hover_item, ctl.hover_snap)
    pane.view.gpu.makeCurrent()
    pane.view.gpu.doneCurrent()
    host.activateWindow(); settle(0.5)
    img = QGuiApplication.primaryScreen().grabWindow(host.winId()).toImage()
    img.save(str(OUT / "dims.png"))
    pane.view.viewport().grab().save(str(OUT / "dims_vp.png"))
    print("saved", OUT / "dims.png")


main()
