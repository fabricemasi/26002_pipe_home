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
    import faulthandler, random
    faulthandler.enable()
    app_style.apply_style(APP)
    import shutil
    d = Path(tempfile.mkdtemp()); path = d / "nd.mro"; shutil.copy(r"C:/Users/fabrice/AppData/Local/Temp/nd.mro", path)
    host = QWidget()
    host.resize(1300, 860)
    host.move(100, 60)
    host.show()
    pane = board_ui.BoardPane(host, dict(DEFAULT_SETTINGS, board_cad_unit="px", board_cad_gpu=os.environ.get("GPU", "1") == "1"))
    pane.open(path)
    pane.show()
    pass
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
    others = []
    ctl.touch_index()
    settle(0.8)
    print('entites', len(list(ctl.cad_items())))
    if os.environ.get('PROPS') == '1':
        ctl.run('PROPERTIES', echo=False); settle(0.3)
    if os.environ.get('CADOFF') == '1':
        pane.toggle_cad(False); settle(0.3)
    import cProfile, pstats
    from PySide6.QtCore import QPoint
    from PySide6.QtTest import QTest
    vp = pane.view.viewport()
    def key(text):
        for ch in text:
            QTest.keyClick(pane.view, ch)
        QTest.keyClick(pane.view, Qt.Key_Return)
    items = [i for i in ctl.cad_items() if i.kind == "cad_line"]
    pane.view.set_zoom(0.0666)
    settle(0.5)
    # deux lignes qui se coupent (reperage par leurs milieux)
    def mid(i):
        a, b = i.points(); return ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
    import itertools
    pair = None
    from board import cad_geometry as geo
    for p, q in itertools.combinations(items, 2):
        a, b = p.points(); c, d = q.points()
        r = geo.line_intersection(a, b, c, d)
        if r is not None and 0 <= r[1] <= 1 and 0 <= r[2] <= 1:
            pair = (p, q); break
    print("paire", pair is not None)
    key("DAN")
    for item in pair:
        c = pane.view.mapFromScene(*[0, 0]) if False else ctl.doc_to_view(mid(item)).toPoint()
        QTest.mouseMove(vp, c); settle(0.05)
        QTest.mouseClick(vp, Qt.LeftButton, Qt.NoModifier, c); settle(0.1)
    print("pret", ctl.command.ready() if ctl.command else None, ctl.prompt().line() if ctl.command else None)
    base = ctl.doc_to_view(mid(pair[0])).toPoint()
    times = []
    pr = cProfile.Profile(); pr.enable()
    for n in range(60):
        pt = QPoint(base.x() + 30 + (n * 7) % 200, base.y() + 30 + (n * 11) % 160)
        from PySide6.QtCore import QEvent, QPointF
        from PySide6.QtGui import QMouseEvent
        at = QPointF(pt)
        t = time.perf_counter(); APP.sendEvent(vp, QMouseEvent(QEvent.MouseMove, at, vp.mapToGlobal(at), Qt.NoButton, Qt.NoButton, Qt.NoModifier)); APP.processEvents(); times.append((time.perf_counter() - t) * 1000)
    pr.disable()
    print("ms par mouvement : moy %.1f max %.1f" % (sum(times) / len(times), max(times)))
    pstats.Stats(pr).sort_stats("cumulative").print_stats(14)
    return


main()
