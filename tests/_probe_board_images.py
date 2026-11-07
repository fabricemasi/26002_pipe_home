"""Sonde de FLUIDITE d'un board d'images (ouverture, pan, zoom, selection), en vraie fenetre Windows A L'ECRAN.
Ne pas toucher la souris pendant la mesure. Le board est COPIE (avec son dossier d'images) dans un dossier
temporaire : l'original n'est jamais ouvert ni enregistre.

    QT_QPA_PLATFORM=windows python tests/_probe_board_images.py [fichier.mro] [scenarios]
    scenarios : open, pan, zoom, select (defaut : tous) ; fichier par defaut : _FM/recherches graphiques.mro
    ZOOM=<facteur>   pan et zoom a ce zoom (1 = 100 %) au lieu de celui du fichier
    PROFILE=1   profil cProfile de chaque scenario (20 lignes les plus couteuses, temps cumule)
    USER_SETTINGS=1   les reglages de l'utilisateur (copie isolee)
    BOARD_ROOT=<dossier>   y prendre d'abord les paquets (ex. fm_miro d'avant un changement : comparer)

Mesures par evenement (ms, p50 / p95 / max) : traitement de l'evenement (souris / molette / clic), rendu
(UpdateRequest de la fenetre : peinture + envoi a l'ecran), evt->img (de l'evenement a la fin du rendu qui le
montre) ; ouverture : `open` + premiere peinture complete."""
import cProfile
import io
import math
import os
import pstats
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
if os.environ.get("BOARD_ROOT"):            # BOARD_ROOT=<dossier> : y prendre d'abord les paquets (version a comparer)
    sys.path.insert(0, os.environ["BOARD_ROOT"])
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt, QTimer  # noqa: E402
from PySide6.QtGui import QMouseEvent, QWheelEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402


class ProbeApp(QApplication):
    host = None
    renders: list = []
    pending: list = []

    def notify(self, obj, event):
        if self.host is not None and event.type() == QEvent.UpdateRequest and obj is self.host:
            t0 = time.perf_counter()
            result = super().notify(obj, event)
            t1 = time.perf_counter()
            self.renders.append((t1 - t0) * 1000)
            for t in self.pending:
                LAT.append((t1 - t) * 1000)
            self.pending.clear()
            return result
        return super().notify(obj, event)


LAT: list = []
HANDLER: list = []
from fm_cad.cad_gpu import low_latency_format  # noqa: E402
low_latency_format()                        # comme l'appli (pipeline_browser.main) : echange sans attente du balayage
APP = QApplication.instance() or ProbeApp([])
import app_style  # noqa: E402
from fm_board import ui as board_ui  # noqa: E402
from fm_board import view as view_mod  # noqa: E402


def wrap(cls, name):
    original = getattr(cls, name)

    def wrapper(self, *args, **kwargs):
        t0 = time.perf_counter()
        APP.pending.append(t0)
        try:
            return original(self, *args, **kwargs)
        finally:
            HANDLER.append((time.perf_counter() - t0) * 1000)
    setattr(cls, name, wrapper)


for _name in ("mouseMoveEvent", "wheelEvent", "mousePressEvent", "mouseReleaseEvent"):
    wrap(view_mod.BoardView, _name)


BLOCKED = [0.0]                 # pire intervalle sans retour a la boucle d'evenements (figement), ms


def settle(seconds=0.1):
    end = time.monotonic() + seconds
    last = time.perf_counter()
    while time.monotonic() < end:
        APP.processEvents()
        now = time.perf_counter()
        BLOCKED[0] = max(BLOCKED[0], (now - last) * 1000)
        last = now


def stats(values):
    if not values:
        return "—"
    v = sorted(values)

    def q(p):
        return v[min(len(v) - 1, int(round(p * (len(v) - 1))))]
    return f"p50 {q(.5):7.2f}  p95 {q(.95):7.2f}  max {v[-1]:7.2f}  (n={len(v)})"


def reset():
    LAT.clear()
    HANDLER.clear()
    APP.renders.clear()
    APP.pending.clear()
    BLOCKED[0] = 0.0


def report(title):
    print(f"\n== {title}")
    print(f"  evenement {stats(HANDLER)}")
    print(f"  rendu     {stats(APP.renders)}")
    print(f"  evt->img  {stats(LAT)}")
    print(f"  bloque    {BLOCKED[0]:.1f} ms au pire")


def drive(seconds, step, rate_hz=250):
    """Appelle step(n) a rate_hz, un nouvel evenement seulement quand le precedent est montre (comme Windows)."""
    state = {"n": 0}
    end = time.perf_counter() + seconds

    def tick():
        if time.perf_counter() > end:
            timer.stop()
            return
        if APP.pending and time.perf_counter() - APP.pending[0] < 0.05:
            return
        APP.pending.clear()
        state["n"] += 1
        step(state["n"])
    timer = QTimer()
    timer.setTimerType(Qt.PreciseTimer)
    timer.timeout.connect(tick)
    timer.start(max(1, int(1000 / rate_hz)))
    settle(seconds + 0.3)


def profiled(fn):
    if not os.environ.get("PROFILE"):
        fn()
        return
    prof = cProfile.Profile()
    prof.enable()
    fn()
    prof.disable()
    out = io.StringIO()
    pstats.Stats(prof, stream=out).sort_stats("cumulative").print_stats(25)
    print(out.getvalue())


def main():
    source = Path(sys.argv[1] if len(sys.argv) > 1 and sys.argv[1].endswith(".mro")
                  else os.path.join(ROOT, "_FM", "recherches graphiques.mro"))
    rest = [a for a in sys.argv[1:] if not a.endswith(".mro")]
    wanted = (rest[0] if rest else "open,pan,zoom,select").split(",")
    seconds = float(os.environ.get("SECONDS_PER", "3"))
    app_style.apply_style(APP)
    from settings_store import DEFAULT_SETTINGS, load_settings
    base = load_settings() if os.environ.get("USER_SETTINGS") else DEFAULT_SETTINGS
    work = Path(tempfile.mkdtemp())
    path = work / source.name
    shutil.copy(source, path)
    assets = source.with_name(source.stem + "_assets")
    if assets.is_dir():
        shutil.copytree(assets, work / assets.name)
    host = QWidget()
    host.setAttribute(Qt.WA_ShowWithoutActivating, True)
    screen = APP.primaryScreen().availableGeometry()
    host.resize(min(2400, screen.width() - 80), min(1300, screen.height() - 80))
    host.move(screen.left() + 40, screen.top() + 40)
    host.show()
    settle(0.3)
    overrides = {}
    if os.environ.get("GPU") is not None:              # GPU=0 / 1 : rendu GPU du board force
        overrides["board_cad_gpu"] = os.environ["GPU"] == "1"
    pane = board_ui.BoardPane(host, dict(base, **overrides))
    pane.setGeometry(host.rect())
    pane.show()
    APP.host = host
    reset()

    def do_open():
        t0 = time.perf_counter()
        pane.open(path)
        t1 = time.perf_counter()
        APP.renders.clear()
        BLOCKED[0] = (t1 - t0) * 1000
        while not APP.renders and time.perf_counter() - t1 < 5:
            APP.processEvents()
        t2 = time.perf_counter()
        first = APP.renders[0] if APP.renders else float("nan")
        settle(1.0)
        print(f"\n== ouverture : open {(t1 - t0) * 1000:.1f} ms, jusqu'a la premiere image {(t2 - t1) * 1000:.1f} ms "
              f"(rendu {first:.1f} ms) ; rendus de la seconde suivante : {stats(APP.renders[1:])} ; bloque {BLOCKED[0]:.1f} ms au pire")
    profiled(do_open)
    pane.set_module("miro")
    if os.environ.get("ZOOM"):                          # ZOOM=<facteur> : pan / zoom a ce zoom (1 = 100 %)
        pane.view.set_zoom(float(os.environ["ZOOM"]))
    settle(0.8)
    vp = pane.view.viewport()
    w, h = vp.width(), vp.height()

    if "pan" in wanted:
        def do_pan():
            start = QPointF(w * 0.5, h * 0.5)
            APP.sendEvent(vp, QMouseEvent(QEvent.MouseButtonPress, start, vp.mapToGlobal(start.toPoint()),
                                          Qt.MiddleButton, Qt.MiddleButton, Qt.NoModifier))

            def step(n):
                pos = QPointF(w * (0.5 + 0.35 * math.sin(n * 0.031)), h * (0.5 + 0.3 * math.sin(n * 0.047)))
                APP.postEvent(vp, QMouseEvent(QEvent.MouseMove, pos, vp.mapToGlobal(pos.toPoint()), Qt.NoButton,
                                              Qt.MiddleButton, Qt.NoModifier))
            reset()
            drive(seconds, step)
            APP.sendEvent(vp, QMouseEvent(QEvent.MouseButtonRelease, start, vp.mapToGlobal(start.toPoint()),
                                          Qt.MiddleButton, Qt.NoButton, Qt.NoModifier))
            report("pan (bouton du milieu)")
        for _ in range(int(os.environ.get("PAN_REPEAT", "1"))):     # PAN_REPEAT=N : N gestes (debut de geste)
            profiled(do_pan)
            settle(0.5)

    if "zoom" in wanted:
        def do_zoom():
            def step(n):
                direction = 1 if (n // 8) % 2 == 0 else -1
                pos = QPointF(w * 0.45, h * 0.55)
                APP.postEvent(vp, QWheelEvent(pos, vp.mapToGlobal(pos.toPoint()), QPoint(0, 0),
                                              QPoint(0, -120 * direction), Qt.NoButton, Qt.NoModifier,
                                              Qt.NoScrollPhase, False))
            reset()
            drive(seconds, step, rate_hz=60)
            report("zoom (molette, 8 crans dans chaque sens)")
            reset()
            settle(0.6)                                      # images gardees refaites 250 ms apres le dernier cran
            print(f"  fin du zoom : rendus {stats(APP.renders)} ; bloque {BLOCKED[0]:.1f} ms au pire")
        profiled(do_zoom)
        settle(0.5)

    if "select" in wanted:
        pane.view.fit_all()
        settle(0.5)
        items = [i for i in pane.scene.items() if getattr(i, "kind", None) == "image"]

        def do_select():
            reset()
            for item in items[:20]:
                at = pane.view.mapFromScene(item.sceneBoundingRect().center())
                pos = QPointF(at)
                if not vp.rect().contains(at):
                    continue
                APP.sendEvent(vp, QMouseEvent(QEvent.MouseButtonPress, pos, vp.mapToGlobal(at), Qt.LeftButton,
                                              Qt.LeftButton, Qt.NoModifier))
                APP.sendEvent(vp, QMouseEvent(QEvent.MouseButtonRelease, pos, vp.mapToGlobal(at), Qt.LeftButton,
                                              Qt.NoButton, Qt.NoModifier))
                settle(0.08)
            report("selection (clic sur 20 images)")
        profiled(do_select)
    APP.host = None
    pane.close_board() if hasattr(pane, "close_board") else None
    pane.deleteLater()
    host.deleteLater()
    settle(0.2)


if __name__ == "__main__":
    main()
