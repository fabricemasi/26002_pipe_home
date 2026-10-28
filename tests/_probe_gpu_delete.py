"""Sonde du rendu GPU du CAD (fm_cad/cad_gpu.py) en VRAIE fenetre Windows, a l'ecran (interpreteur du projet : `.venv`, PyOpenGL) :
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
import fm_board as board  # noqa: E402
from fm_cad import cad_model  # noqa: E402
from fm_board import model
from fm_board import ui as board_ui  # noqa: E402
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
    import faulthandler, random
    faulthandler.enable()
    app_style.apply_style(APP)
    path = board.create_board_file(Path(tempfile.mkdtemp()) / "plan")
    host = QWidget()
    host.resize(1300, 860)
    host.move(100, 60)
    host.show()
    pane = board_ui.BoardPane(host, dict(DEFAULT_SETTINGS, board_cad_unit="px", board_cad_gpu=os.environ.get("GPU", "1") == "1"))
    pane.open(path)
    pane.show()
    pane.fit()
    pane.toggle_cad(True)
    ctl, scene = pane.cad, pane.scene
    cad = ctl.cad_page()
    print("gpu", getattr(pane.view, "gpu", None) is not None)
    rnd = random.Random(int(os.environ.get("SEED", "1")))
    kinds = ["cad_line", "cad_circle", "cad_arc", "cad_pline"]
    def make():
        k = rnd.choice(kinds)
        x, y = rnd.uniform(-200, 200), rnd.uniform(-150, 150)
        g = {"cad_line": dict(p1=[x, y], p2=[x + 40, y + 20]),
             "cad_circle": dict(center=[x, y], radius=15.0),
             "cad_arc": dict(center=[x, y], radius=15.0, start=0.0, end=120.0),
             "cad_pline": dict(vertices=[[x, y, 0.0], [x + 30, y, 0.5], [x + 30, y + 30, 0.0]])}[k]
        return scene._add(model.new_item(k, **cad_model.new_entity_values(cad, **g)))
    others = []
    def make_other():
        k = rnd.choice(["sticky", "shape", "text"])
        others.append(scene._add(model.new_item(k, x=rnd.uniform(-200, 200), y=rnd.uniform(-150, 150))))
    for _ in range(40):
        make()
    make_other()
    ctl.touch_index()
    settle(0.5)
    for n in range(int(os.environ.get("N", "300"))):
        items = list(ctl.cad_items())
        if not items:
            for _ in range(rnd.randint(1, 4)): make()
            items = list(ctl.cad_items())
        action = rnd.choice(["erase", "key", "key", "click", "undo", "redo", "make", "move", "other", "delother"])
        if action == "other":
            make_other(); continue
        if action == "delother":
            live = [o for o in others if o.scene() is scene]
            if live:
                scene.clearSelection(); rnd.choice(live).setSelected(True)
                pane.view.setFocus()
                from PySide6.QtTest import QTest
                QTest.keyClick(pane.view, Qt.Key_Delete)
            settle(rnd.choice([0.0, 0.02]))
            continue
        if action in ("key", "click"):
            from PySide6.QtCore import QPoint
            from PySide6.QtTest import QTest
            vp = pane.view.viewport()
            it = rnd.choice(items)
            c = pane.view.mapFromScene(it.sceneBoundingRect().center())
            QTest.mouseMove(vp, QPoint(c.x(), c.y()))
            settle(rnd.choice([0.0, 0.02, 0.4]))
            QTest.mouseClick(vp, Qt.LeftButton, Qt.NoModifier, QPoint(c.x(), c.y()))
            if action == "key":
                QTest.keyClick(pane.view, Qt.Key_Delete)
            continue
        if action == "erase":
            picks = rnd.sample(items, min(len(items), rnd.randint(1, 60)))
            scene.clearSelection()
            for it in picks: it.setSelected(True)
            ctl.run("ERASE", echo=False)
        elif action == "undo":
            pane.undo() if hasattr(pane, "undo") else scene.undo_stack.undo()
        elif action == "redo":
            pane.redo() if hasattr(pane, "redo") else scene.undo_stack.redo()
        elif action == "make":
            make()
        else:
            it = rnd.choice(items); it.setPos(it.pos().x() + 5, it.pos().y() + 3)
        settle(rnd.choice([0.0, 0.01, 0.03]))
    settle(0.5)
    print("fini sans plantage ; entites :", len(list(ctl.cad_items())))


main()
