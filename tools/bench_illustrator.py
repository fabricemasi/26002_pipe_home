"""Mesures de fluidité du module Illustrator (offscreen) : `python tools/bench_illustrator.py [N]`.

Board 2400 × 1300 avec N tracés (rectangles, ellipses, étoiles mêlés), module Illustrator actif, zoom 1 : création,
peinture d'une image entière, survol, cadre de sélection, Ctrl + glisser de 200 objets, mise à l'échelle de 200
objets, clic de plume, sélection de tout + dessin des points. Médianes en millisecondes (p95 entre parenthèses)."""
import os
import statistics
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QEvent, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

APP = QApplication.instance() or QApplication([])

from fm_board import model, serialization, ui as board_ui  # noqa: E402
from fm_illustrator import bezier as bz, model as im  # noqa: E402


def stats(values):
    values = sorted(values)
    p95 = values[min(len(values) - 1, int(len(values) * 0.95))]
    return f"{statistics.median(values) * 1000:7.2f} ms (p95 {p95 * 1000:.2f})"


def main(n=2000):
    tmp = Path(tempfile.mkdtemp(prefix="ill_bench_"))
    path = serialization.create_board_file(tmp / "bench.mro")
    host = QWidget()
    host.resize(2400, 1300)
    pane = board_ui.BoardPane(host)
    pane.open(path)
    pane.resize(2400, 1300)
    host.show()
    pane.show()
    pane.set_module("illustrator")
    ctl, scene, view = pane.illustrator, pane.scene, pane.view
    dicts = []
    for i in range(n):
        x, y = (i % 50) * 45.0, (i // 50) * 45.0
        kind = i % 3
        subs = bz.rect(0, 0, 36, 30) if kind == 0 else bz.ellipse(18, 18, 18, 14) if kind == 1 else \
            bz.star(18, 18, 18, 8, 5)
        dicts.append(model.new_item(im.PATH, x=x, y=y, z=float(i), subpaths=subs, fill="#3366cc", stroke="#000000"))
    t = time.perf_counter()
    scene.replace_items([], dicts, "bench")
    print(f"création de {n} tracés       : {(time.perf_counter() - t) * 1000:8.1f} ms")
    view.set_zoom(1.0)
    view.center_on(QPointF(1100, 600))
    APP.processEvents()

    def send(kind, pt, buttons=Qt.NoButton, mods=Qt.NoModifier, button=Qt.LeftButton):
        pos = QPointF(view.mapFromScene(pt))
        ev = QMouseEvent(kind, pos, QPointF(view.viewport().mapToGlobal(pos.toPoint())), button, buttons, mods)
        QApplication.sendEvent(view.viewport(), ev)

    def timed(fn, count=40, full=False):
        """Événement puis peinture de ce qui a changé (`processEvents`, zone sale seulement, comme à l'écran) ;
        `full` = toute l'image."""
        out = []
        for k in range(count):
            t0 = time.perf_counter()
            fn(k)
            if full:
                view.viewport().repaint()
            else:
                APP.processEvents()
            out.append(time.perf_counter() - t0)
        return stats(out)

    print("image entière (repaint)      :", timed(lambda k: None, 15, full=True))
    print("survol (mouvement + image)   :", timed(lambda k: send(QEvent.MouseMove, QPointF(300 + k * 7, 300))))
    ctl.set_tool("select")
    send(QEvent.MouseButtonPress, QPointF(5, 5))
    print("cadre de sélection           :", timed(lambda k: send(QEvent.MouseMove, QPointF(40 + k * 12, 40 + k * 9),
                                                                   Qt.LeftButton)))
    send(QEvent.MouseButtonRelease, QPointF(520, 400))
    print("   objets choisis :", len(ctl.selection()))
    sel = ctl.objects()[:200]
    ctl.select(sel)
    APP.processEvents()
    start = sel[0].geometry_rect().center()
    send(QEvent.MouseButtonPress, start, Qt.LeftButton, Qt.ControlModifier)
    print("Ctrl + glisser 200 objets    :", timed(lambda k: send(QEvent.MouseMove, start + QPointF(5 + k * 3, k * 2),
                                                                   Qt.LeftButton, Qt.ControlModifier)))
    t = time.perf_counter()
    send(QEvent.MouseButtonRelease, start + QPointF(200, 80), Qt.NoButton, Qt.ControlModifier)
    print(f"   fin du geste (annulation)  : {(time.perf_counter() - t) * 1000:8.1f} ms")
    rect = ctl.selection_rect()
    send(QEvent.MouseButtonPress, rect.bottomRight(), Qt.LeftButton)
    print("échelle 200 objets           :", timed(lambda k: send(QEvent.MouseMove, rect.bottomRight() +
                                                                   QPointF(k * 4, k * 3), Qt.LeftButton)))
    send(QEvent.MouseButtonRelease, rect.bottomRight() + QPointF(160, 120))
    ctl.set_tool("pen")
    print("clic de plume                :", timed(lambda k: (send(QEvent.MouseButtonPress,
                                                                    QPointF(100 + k * 20, 900), Qt.LeftButton),
                                                               send(QEvent.MouseButtonRelease,
                                                                    QPointF(100 + k * 20, 900))), 20))
    print("ligne élastique (survol)     :", timed(lambda k: send(QEvent.MouseMove, QPointF(600 + k * 5, 950))))
    ctl.tools["pen"].finish()
    ctl.set_tool("select")
    t = time.perf_counter()
    ctl.select(ctl.objects())
    APP.processEvents()
    view.viewport().repaint()
    print(f"tout choisir + image         : {(time.perf_counter() - t) * 1000:8.1f} ms")
    print("image, tout choisi           :", timed(lambda k: None, 10, full=True))
    t = time.perf_counter()
    data = scene.to_data()
    print(f"to_data (enregistrement)     : {(time.perf_counter() - t) * 1000:8.1f} ms ({len(data['items'])} éléments)")
    pane._autosave.stop()


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 2000)
