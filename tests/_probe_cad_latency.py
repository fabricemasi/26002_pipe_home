"""Sonde de LATENCE du module CAD (souris, accrochages, zoom), en vraie fenetre Windows A L'ECRAN (une fenetre
hors de l'ecran n'est jamais peinte : rien a mesurer). Ne pas toucher la souris pendant la mesure.

    QT_QPA_PLATFORM=windows python tests/_probe_cad_latency.py [N,N,...] [scenarios]
    scenarios : idle, line, line_nosnap, zoom, mixed, draw, pan (bouton du milieu tenu), pan_mixed, window (fenetre de selection)
    BOARD_ROOT=<dossier contenant un paquet board/>   (comparer avec une autre version du paquet)
    USER_SETTINGS=1   (les reglages de l'utilisateur, copie isolee, au lieu des defauts)
    RATE=<Hz>   (mouvements de souris par seconde, 250 par defaut ; une souris de jeu : 1000)
    FULL_CROSSHAIR=1   reticule jusqu'aux bords de la vue
    NOGRID=1          grille du board eteinte (mesure de ce que coute le fond raster)
    GPU=1             rendu GPU du CAD (fm_cad/cad_gpu.py ; interpreteur du projet : .venv, PyOpenGL)
    GL=1              viewport OpenGL (QOpenGLWidget) au lieu du viewport raster
    CURVES=N          N arcs et cercles en plus des lignes
    CURSOR_IN=0       la souris n'est PAS dans la vue au depart (defaut 1 : deja dedans, le reticule est affiche pendant pan / zoom)

Mouvements de souris POSTES dans la file comme un vrai pilote (250 Hz, un nouveau mouvement seulement quand le
precedent a ete traite : Windows fusionne lui aussi les WM_MOUSEMOVE), molette idem. Mesure, par evenement :
  - souris   : duree de BoardView.mouseMoveEvent (tout le traitement CAD synchrone) ;
  - osnap    : duree de SnapEngine.resolve ;
  - zoom     : duree de BoardView.wheelEvent ;
  - p.scene / p.overlay : peinture du viewport (scene) / de l'overlay CAD ;
  - rendu    : duree d'un UpdateRequest de la fenetre (peinture de TOUS les widgets salis + envoi a l'ecran) ;
  - evt->img : de la reception de l'evenement a la FIN du rendu qui le montre (latence INTERNE ; la suite —
               composition de Windows, balayage de l'ecran — demande une mesure externe) ;
  - bloque   : pire intervalle sans traitement d'evenement (figement du fil de l'interface).
Statistiques p50 / p95 / p99 / max en ms."""
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
if os.environ.get("BOARD_ROOT"):
    sys.path.insert(0, os.environ["BOARD_ROOT"])
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt, QTimer  # noqa: E402
from PySide6.QtGui import QMouseEvent, QWheelEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402


class ProbeApp(QApplication):
    host = None
    update_cb = None

    paints = None                                # PAINTS=1 : temps de peinture par classe de widget

    def notify(self, obj, event):
        if self.paints is not None and event.type() == QEvent.Paint:
            t0 = time.perf_counter()
            result = super().notify(obj, event)
            key = type(obj).__name__
            total, count = self.paints.get(key, (0.0, 0))
            self.paints[key] = (total + (time.perf_counter() - t0) * 1000, count + 1)
            return result
        if self.update_cb is not None and event.type() == QEvent.UpdateRequest and obj is self.host:
            t0 = time.perf_counter()
            result = super().notify(obj, event)
            self.update_cb(t0, time.perf_counter())
            return result
        return super().notify(obj, event)


APP = QApplication.instance() or ProbeApp([])
import app_style  # noqa: E402
import fm_board as board  # noqa: E402
from fm_cad import cad_model  # noqa: E402
from fm_board import model
from fm_board import ui as board_ui  # noqa: E402
from fm_cad import cad_snap  # noqa: E402
from fm_board import view as view_mod

print("paquet board :", os.path.dirname(board.__file__))


def settle(seconds=0.1):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        APP.processEvents()


def stats(values):
    if not values:
        return "—"
    v = sorted(values)

    def q(p):
        return v[min(len(v) - 1, int(round(p * (len(v) - 1))))]
    return f"p50 {q(.5):6.2f}  p95 {q(.95):6.2f}  p99 {q(.99):6.2f}  max {v[-1]:6.2f}  (n={len(v)})"


KEYS = ("souris", "osnap", "zoom", "p.scene", "p.overlay", "rendu", "evt->img", "bloque", "sans image")


class Recorder:
    def __init__(self):
        self.reset()

    def reset(self):
        self.data = {k: [] for k in KEYS}
        self.pending = []                   # instants de reception des evenements pas encore montres
        self.last_beat = None

    def add(self, key, ms):
        self.data[key].append(ms)


REC = Recorder()


def wrap(cls, name, key=None, pending=False):
    original = getattr(cls, name)

    def wrapper(self, *args, **kwargs):
        t0 = time.perf_counter()
        if pending:
            REC.pending.append(t0)
        try:
            return original(self, *args, **kwargs)
        finally:
            if key:
                REC.add(key, (time.perf_counter() - t0) * 1000)
    setattr(cls, name, wrapper)


wrap(view_mod.BoardView, "mouseMoveEvent", "souris", pending=True)
wrap(view_mod.BoardView, "wheelEvent", "zoom", pending=True)
wrap(cad_snap.SnapEngine, "resolve", "osnap")
if "paintEvent" not in view_mod.BoardView.__dict__:
    from PySide6.QtWidgets import QGraphicsView
    view_mod.BoardView.paintEvent = lambda self, event: QGraphicsView.paintEvent(self, event)
wrap(view_mod.BoardView, "paintEvent", "p.scene")
from fm_cad import cad_overlay  # noqa: E402
wrap(cad_overlay.CadOverlay, "paintEvent", "p.overlay")


def on_update(t0, t1):
    REC.add("rendu", (t1 - t0) * 1000)
    for t in REC.pending:
        REC.add("evt->img", (t1 - t) * 1000)
    REC.pending.clear()


def build(pane, count, mixed):
    scene = pane.scene
    ctl = pane.cad
    cad = ctl.cad_page()
    side = max(1, int(count ** 0.5))
    for n in range(count):
        x = (n % side) * 20.0
        y = (n // side) * 20.0
        values = cad_model.new_line_values(cad, (x, y), (x + 15.0, y + 9.0 + (n % 7)))
        scene._add(model.new_item("cad_line", **values))
    for n in range(int(os.environ.get("CURVES", "0"))):        # CURVES=N : N cercles et arcs en plus des lignes
        x = (n % side) * 20.0 + 7.0
        y = (n // side) * 20.0 + 5.0
        kind = "cad_circle" if n % 2 else "cad_arc"
        geometry = {"center": [x, y], "radius": 4.0 + n % 5}
        if kind == "cad_arc":
            geometry.update(start=float(n % 360), end=float((n * 7) % 360))
        scene._add(model.new_item(kind, **cad_model.new_entity_values(cad, **geometry)))
    if mixed:
        for n in range(150):
            kind = ("sticky", "shape", "text")[n % 3]
            data = model.new_item(kind, x=(n % 15) * 40.0, y=-(n // 15) * 40.0 - 400)
            if kind != "shape":
                data["text"] = f"note {n}"
            scene._add(data)
    ctl.touch_index()


def run_moves(pane, seconds, rate_hz=int(os.environ.get("RATE", 250)), draw=None, pan=False):
    vp = pane.view.viewport()
    w, h = vp.width(), vp.height()
    state = {"n": 0, "busy": False}
    end = time.perf_counter() + seconds

    def tick():
        if time.perf_counter() > end:
            timer.stop()
            return
        if REC.pending:                      # le precedent n'est pas encore traite + montre : fusionne (OS)
            if time.perf_counter() - REC.pending[0] < 0.05:
                return
            REC.add("sans image", 0.0)       # traite sans rien a repeindre (rien n'a change a l'ecran)
            REC.pending.clear()
        n = state["n"] = state["n"] + 1
        import math
        if draw is not None and n % 25 == 0:
            draw(n)                              # une ligne tracee (scenario « draw »)
        x = w * (0.5 + 0.42 * math.sin(n * 0.031))
        y = h * (0.5 + 0.40 * math.sin(n * 0.047 + 1.0))
        pos = QPointF(x, y)
        held = Qt.MiddleButton if pan else Qt.NoButton
        ev = QMouseEvent(QEvent.MouseMove, pos, vp.mapToGlobal(pos), Qt.NoButton, held, Qt.NoModifier)
        APP.postEvent(vp, ev)
    if pan:                                      # bouton du milieu tenu : deplacement du board
        import math
        start = QPointF(w * 0.5, h * (0.5 + 0.40 * math.sin(1.0)))
        APP.sendEvent(vp, QMouseEvent(QEvent.MouseButtonPress, start, vp.mapToGlobal(start), Qt.MiddleButton,
                                      Qt.MiddleButton, Qt.NoModifier))
    timer = QTimer()
    timer.setTimerType(Qt.PreciseTimer)
    timer.timeout.connect(tick)
    timer.start(int(1000 / rate_hz))
    beat(seconds + 0.3)
    if pan:
        APP.sendEvent(vp, QMouseEvent(QEvent.MouseButtonRelease, QPointF(w / 2, h / 2), vp.mapToGlobal(QPoint(w // 2, h // 2)),
                                      Qt.MiddleButton, Qt.NoButton, Qt.NoModifier))


def run_wheel(pane, seconds, rate_hz=60):
    vp = pane.view.viewport()
    state = {"n": 0}
    end = time.perf_counter() + seconds

    def tick():
        if time.perf_counter() > end:
            timer.stop()
            return
        if REC.pending:
            return
        n = state["n"] = state["n"] + 1
        direction = 1 if (n // 6) % 2 == 0 else -1          # 6 crans, puis demi-tour immediat
        pos = QPointF(vp.width() * 0.45, vp.height() * 0.55)
        ev = QWheelEvent(pos, vp.mapToGlobal(pos), QPoint(0, 0), QPoint(0, 120 * direction), Qt.NoButton,
                         Qt.NoModifier, Qt.NoScrollPhase, False)
        APP.postEvent(vp, ev)
    timer = QTimer()
    timer.setTimerType(Qt.PreciseTimer)
    timer.timeout.connect(tick)
    timer.start(int(1000 / rate_hz))
    beat(seconds + 0.3)


def beat(seconds):
    """Boucle d'evenements + plus long intervalle sans retour a la boucle (figement)."""
    end = time.perf_counter() + seconds
    last = time.perf_counter()
    worst = 0.0
    while time.perf_counter() < end:
        APP.processEvents()
        now = time.perf_counter()
        worst = max(worst, now - last)
        last = now
    REC.add("bloque", worst * 1000)


SWAPS: list = []
SCROLLS: list = []
GPU_MS: list = []


def report(title):
    print(f"\n== {title}")
    if len(SWAPS) > 3:
        gaps = sorted((b - a) * 1000 for a, b in zip(SWAPS, SWAPS[1:]))
        print(f"  images GPU : {len(SWAPS)} presentees, intervalle p50 {gaps[len(gaps) // 2]:.1f}  "
              f"p95 {gaps[int(len(gaps) * 0.95)]:.1f}  max {gaps[-1]:.1f} ms ; paintGL processeur p50 "
              f"{sorted(GPU_MS)[len(GPU_MS) // 2]:.2f} ms")
    if os.environ.get("SERIES") and len(SWAPS) > 3:
        t0 = SWAPS[0]
        prev = SCROLLS[0]
        rows = []
        for i in range(1, len(SWAPS)):
            d = abs(SCROLLS[i][1] - prev[1]) + abs(SCROLLS[i][0] - prev[0])
            rows.append(f"{(SWAPS[i]-SWAPS[i-1])*1000:5.1f}/{d}")
            prev = SCROLLS[i]
        print("  intervalle ms / deplacement px :", " ".join(rows[:120]))
    SWAPS.clear()
    SCROLLS.clear()
    GPU_MS.clear()
    for key in KEYS:
        if REC.data[key]:
            print(f"  {key:9s} {stats(REC.data[key])}")


def main():
    counts = [int(c) for c in (sys.argv[1] if len(sys.argv) > 1 else "0,1000,5000").split(",")]
    wanted = (sys.argv[2] if len(sys.argv) > 2 else "idle,line,line_nosnap,zoom,mixed").split(",")
    seconds = float(os.environ.get("SECONDS_PER", "3"))
    app_style.apply_style(APP)
    from settings_store import DEFAULT_SETTINGS
    for count in counts:
        for scenario in wanted:
            mixed = scenario in ("mixed", "pan_mixed")
            work = Path(tempfile.mkdtemp())
            path = board.create_board_file(work / "plan")
            host = QWidget()
            host.setAttribute(Qt.WA_ShowWithoutActivating, True)
            screen = APP.primaryScreen().availableGeometry()
            host.resize(min(2400, screen.width() - 80), min(1300, screen.height() - 80))
            host.move(screen.left() + 40, screen.top() + 40)       # A L'ECRAN : hors ecran, Windows ne peint rien
            host.show()
            APP.host = host
            base = DEFAULT_SETTINGS
            if os.environ.get("USER_SETTINGS"):           # USER_SETTINGS=1 : les reglages de l'utilisateur (copie, _isolate)
                from settings_store import load_settings
                base = load_settings()
            pane = board_ui.BoardPane(host, dict(base, board_opengl=bool(os.environ.get("GL")), board_cad_gpu=bool(os.environ.get("GPU"))))
            if os.environ.get("FILE"):                    # FILE=<.mro> : un vrai dessin au lieu des lignes generees
                import shutil
                shutil.copy(os.environ["FILE"], path)
            pane.open(path)
            if os.environ.get("NOGRID"):
                pane.scene.set_page({"grid": False}, record=False)
            pane.show()
            pane.fit()                          # comme l'appli : le panneau (et la vue) a la taille de la fenetre
            pane.toggle_cad(True)
            ctl = pane.cad
            settings = dict(ctl.settings, board_cad_dyn=True)
            if os.environ.get("USER_SETTINGS"):
                settings = dict(ctl.settings)
            if scenario == "line_nosnap":
                settings["board_cad_osnap"] = False
            else:
                settings.update(board_cad_osnap=True, board_cad_osnap_end=True, board_cad_osnap_mid=True,
                                board_cad_osnap_int=True, board_cad_osnap_appint=True, board_cad_osnap_per=True,
                                board_cad_osnap_nea=True, board_cad_otrack=True)
            if os.environ.get("FULL_CROSSHAIR"):             # reticule jusqu'aux bords de la vue
                settings["board_cad_crosshair_full"] = True
            ctl.apply_settings(settings)
            if not os.environ.get("FILE"):
                build(pane, count, mixed)
            pane.view.fit_all()
            settle(0.6)
            if scenario in ("line", "line_nosnap", "mixed", "zoom", "draw"):
                ctl.run("LINE", echo=False)
                ctl.submit("3,4")
            settle(0.4)
            if os.environ.get("CURSOR_IN", "1") == "1":          # la souris est deja dans la vue (reticule affiche)
                vp = pane.view.viewport()
                at = QPointF(vp.width() * 0.45, vp.height() * 0.55)
                APP.sendEvent(vp, QMouseEvent(QEvent.MouseMove, at, vp.mapToGlobal(at), Qt.NoButton, Qt.NoButton,
                                              Qt.NoModifier))
                settle(0.3)
            if scenario == "window":                    # fenetre de selection ouverte depuis un coin, balayee
                vp = pane.view.viewport()
                ctl.window = {"start": ctl.view_to_doc(QPointF(vp.width() * 0.03, vp.height() * 0.03))}
                ctl._apply_cursor()
                settle(0.2)
            SWAPS.clear()
            if getattr(pane.view, "gpu", None) is not None:           # rendu GPU : images reellement presentees
                pane.view.gpu.frameSwapped.connect(lambda: (SWAPS.append(time.perf_counter()), GPU_MS.append(pane.view.gpu.frame_ms), SCROLLS.append((pane.view.horizontalScrollBar().value(), pane.view.verticalScrollBar().value()))))
            if getattr(pane.view, "gpu", None) is not None and os.environ.get("GPU_LOG"):   # GPU_LOG=1 : pires temps de _sync
                layer = pane.view.gpu
                original = layer._sync
                SYNCS = []
                def timed(scene, original=original):
                    t = time.perf_counter()
                    dirty = sum(1 for c in layer.store.chunks if c.dirty)
                    original(scene)
                    SYNCS.append(((time.perf_counter() - t) * 1000.0, dirty))
                layer._sync = timed
                APP.syncs = SYNCS
            APP.update_cb = on_update
            if os.environ.get("PAINTS"):
                APP.paints = {}
            REC.reset()
            if scenario == "zoom":
                run_wheel(pane, seconds)
            elif scenario == "draw":
                run_moves(pane, seconds, draw=lambda n: ctl.create_line((n * 0.37 % 900, n * 0.53 % 700),
                                                                         (n * 0.37 % 900 + 40, n * 0.53 % 700 + 25)))
            elif scenario.startswith("pan"):
                print("mode GPU pur :", getattr(getattr(pane.view, "gpu", None), "pure", None))
                pane.view.set_zoom(pane.view.zoom() * 2.0)      # une partie du dessin : il y a de quoi deplacer
                settle(0.3)
                REC.reset()
                if APP.paints is not None:
                    APP.paints.clear()
                run_moves(pane, seconds, pan=True)
            else:
                run_moves(pane, seconds)
            APP.update_cb = None
            if getattr(APP, "syncs", None):
                worst = sorted(APP.syncs, reverse=True)[:5]
                print("  _sync GPU, pires :", ", ".join(f"{ms:.0f} ms ({n} lots)" for ms, n in worst))
                APP.syncs = None
            report(f"{count} lignes CAD — {scenario}")
            ctl.escape() if hasattr(ctl, "escape") else None
            pane.close_board() if hasattr(pane, "close_board") else None
            pane.deleteLater()
            host.deleteLater()
            settle(0.2)


if __name__ == "__main__":
    main()
