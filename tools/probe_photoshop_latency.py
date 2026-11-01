"""Sonde de LATENCE VISIBLE du module Photoshop (établi seul, offscreen) : python tools/probe_photoshop_latency.py [petit|4k]

Pour chaque geste : N évènements souris réels envoyés à l'établi, chacun suivi de la peinture synchrone (`repaint`) ;
on rapporte la médiane et le p95 du temps « évènement + peinture » (ce que l'utilisateur attend entre deux images).
Gestes : trait, déplacement d'un calque (Ctrl + glisser), opacité du calque, zoom (cran de molette), déplacement de la vue,
affichage / masquage d'un calque, fusion de modes. `PROFILE=1` : cProfile du geste le plus lent."""
import cProfile
import os
import pstats
import statistics
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent, QWheelEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

APP = QApplication.instance() or QApplication([])

import bench_photoshop as B  # noqa: E402
from fm_photoshop import ops, render  # noqa: E402
from fm_photoshop.canvas import CanvasView  # noqa: E402
from fm_photoshop.session import Session  # noqa: E402

SIZES = {"petit": (1024, 768, 4, 1.0), "4k": (3840, 2160, 24, 0.25)}


def mouse(canvas, kind, x, y, mods=Qt.NoModifier):
    types = {"press": QMouseEvent.MouseButtonPress, "move": QMouseEvent.MouseMove, "release": QMouseEvent.MouseButtonRelease}
    pos = QPointF(x, y)
    buttons = Qt.NoButton if kind == "release" else Qt.LeftButton
    event = QMouseEvent(types[kind], pos, canvas.mapToGlobal(pos), Qt.LeftButton, buttons, mods)
    APP.sendEvent(canvas, event)


def measure(label, count, step, idle_ms: float = 0.0):
    """`idle_ms` : pause entre deux évènements (l'utilisateur n'envoie pas 1 000 évènements/s) ; les minuteries de
    l'établi (tuiles voisines) tournent pendant ce temps, hors mesure."""
    times = []
    for i in range(count):
        t = time.perf_counter()
        step(i)
        times.append((time.perf_counter() - t) * 1000)
        if idle_ms:
            end = time.perf_counter() + idle_ms / 1000.0
            while time.perf_counter() < end:
                APP.processEvents()
                time.sleep(0.002)
    times.sort()
    print(f"{label:<44} médiane {statistics.median(times):7.1f} ms   p95 {times[int(len(times) * 0.95)]:7.1f} ms   "
          f"max {times[-1]:7.1f} ms")
    return times


def run(name):
    width, height, count, share = SIZES[name]
    print(f"\n== {name} : {width} × {height}, {count} calques, fenêtre 1600 × 900 ==")
    doc = B.build(width, height, count, share)
    session = Session(doc)
    canvas = CanvasView(session)
    canvas.resize(1600, 900)
    canvas.show()
    session.zoom = 1.0
    session.center = (width / 2.0, height / 2.0)
    canvas.repaint()
    t = time.perf_counter()
    for _ in range(40):                                              # premier affichage : tuiles en tranches de temps
        canvas.repaint()
        APP.processEvents()
        if all(canvas.cache.is_ready(k) for k in canvas.cache.keys_for(canvas.visible_doc_rect())):
            break
    print(f"{'premier affichage complet (zoom 100 %)':<44} {(time.perf_counter() - t) * 1000:7.0f} ms")
    cx, cy = 800, 450
    layer = doc.layers[-1]
    session.select_layer(layer)
    # trait : tampon + tuiles recomposées + peinture
    session.tool = "brush"
    session.brush.size = 60.0
    mouse(canvas, "press", cx - 300, cy)
    measure("trait (taille 60, un évènement + peinture)", 80,
            lambda i: (mouse(canvas, "move", cx - 300 + i * 7, cy + (i % 9) * 6), canvas.repaint()))
    mouse(canvas, "release", cx + 260, cy)
    # déplacement de calque Ctrl + glisser
    session.tool = "move"
    session.select_layer(doc.layers[len(doc.layers) // 2])
    canvas.begin_move(*canvas.to_doc(QPointF(cx, cy)), True)      # (Ctrl tenu : les évènements synthétiques ne le disent pas)
    APP.processEvents()
    measure("déplacer un calque (Ctrl + glisser)", 40,
            lambda i: (mouse(canvas, "move", cx + i * 5, cy + i * 3, Qt.ControlModifier), canvas.repaint()))
    mouse(canvas, "release", cx + 200, cy + 120, Qt.ControlModifier)
    # opacité
    target = doc.layers[len(doc.layers) // 2]

    def opacity(i):
        target.opacity = 0.3 + 0.7 * ((i % 10) / 10.0)
        session.notify("structure", None)
        canvas.repaint()
    measure("opacité d'un calque (curseur, par cran)", 20, opacity)

    def toggle(i):
        target.visible = not target.visible
        session.notify("structure", None)
        canvas.repaint()
    measure("afficher / masquer un calque", 20, toggle)
    target.visible = True

    def wheel(i):
        anchor = QPointF(800, 450)
        event = QWheelEvent(anchor, canvas.mapToGlobal(anchor), QPoint(0, 0), QPoint(0, 120 if i % 2 == 0 else -120),
                            Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
        APP.sendEvent(canvas, event)
        canvas.repaint()
    measure("zoom (un cran de molette)", 16, wheel, 40)
    session.zoom = 1.0
    session.tool = "hand"
    mouse(canvas, "press", cx, cy)
    measure("déplacer la vue (main)", 40, lambda i: (mouse(canvas, "move", cx + i * 9, cy + i * 4), canvas.repaint()), 16)
    mouse(canvas, "release", cx, cy)
    if os.environ.get("PROFILE"):
        session.tool = "brush"
        mouse(canvas, "press", 200, 300)
        profiler = cProfile.Profile()
        profiler.enable()
        for i in range(60):
            mouse(canvas, "move", 200 + i * 9, 300 + (i % 5) * 8)
            canvas.repaint()
        profiler.disable()
        pstats.Stats(profiler).sort_stats("cumulative").print_stats(12)


if __name__ == "__main__":
    for case in sys.argv[1:] or ["petit", "4k"]:
        run(case)
