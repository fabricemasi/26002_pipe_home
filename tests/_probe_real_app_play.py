"""Sonde de lecture dans l'appli TELLE QUE LANCÉE (comme `main()` : vrais réglages, vraie racine, QtWebEngine /
contextes OpenGL partagés, fenêtre de réglages et éditeur Markdown préchargés en fond), sans rien enregistrer.
Un CHIEN DE GARDE (fil Python) relève tout figement du fil de l'interface de plus de STALL ms et écrit la pile
EXACTE de ce fil à ce moment-là.

    QT_QPA_PLATFORM=windows python tests/_probe_real_app_play.py <vidéo> [secondes_de_lecture] [attente_avant]
    STALL=40 (ms)   LOG=<fichier de piles>
"""
import faulthandler, os, statistics, sys, threading, time
from pathlib import Path
os.environ.setdefault("QT_QPA_PLATFORM", "windows")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import settings_store, browser_core
import pipeline_browser as pb
for module in (settings_store, pb, browser_core):
    for name in ("save_settings", "_save_window_geometry", "save_layout_settings", "_update_layout_setting",
                 "save_live_state", "save_window_state"):
        if hasattr(module, name):
            setattr(module, name, lambda *a, **k: None)
pb.open_path = lambda path: None
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

VIDEO = Path(sys.argv[1])
PLAY = float(sys.argv[2]) if len(sys.argv) > 2 else 8.0
SETTLE = float(sys.argv[3]) if len(sys.argv) > 3 else 12.0     # laisse tourner les préchargements du démarrage
STALL = float(os.environ.get("STALL", "40")) / 1000.0
LOG = open(os.environ.get("LOG", os.path.join(os.environ.get("TEMP", "."), "real_stalls.txt")), "w", encoding="utf-8")

settings = settings_store.load_settings(startup=True)
pb.apply_all_settings(settings)
import config as _config
root = Path(settings["root_path"])
_config.ROOT = root
QApplication.setAttribute(Qt.AA_DontCreateNativeWidgetSiblings, True)
QApplication.setAttribute(Qt.AA_ShareOpenGLContexts, True)
app = QApplication(sys.argv)
pb.apply_style(app)
pb._install_context_menus()
win = pb.PipelineBrowser(root)
win.move(-3000, 0)
win.resize(1700, 950)
win.show()
QTimer = pb.QTimer
win._start_settings_idle_watch()
QTimer.singleShot(6000, win._preload_md_editor)
QTimer.singleShot(4500, win._preload_video)
QTimer.singleShot(1500, win._start_css_sync)

# ---- chien de garde : le fil de l'interface incrémente un compteur ; ce fil voit s'il n'avance plus ----
beat = [time.perf_counter()]
ui_ident = threading.get_ident()
stalls = []
running = [True]


def tick():
    beat[0] = time.perf_counter()


ticker = QTimer()
ticker.setInterval(5)
ticker.setTimerType(Qt.PreciseTimer)
ticker.timeout.connect(tick)
ticker.start()


def watchdog():
    import sys as _sys, traceback
    reported = 0.0
    while running[0]:
        time.sleep(0.004)
        late = time.perf_counter() - beat[0]
        if late > STALL and beat[0] != reported:
            frame = _sys._current_frames().get(ui_ident)
            stack = "".join(traceback.format_stack(frame)[-14:]) if frame else "?"
            stalls.append((time.perf_counter(), late, stack))
            reported = beat[0]
            time.sleep(0.02)


threading.Thread(target=watchdog, name="watchdog", daemon=True).start()


def pump(seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        time.sleep(0.001)


print(f"racine {root} ; attente {SETTLE:.0f} s (réglages / éditeur / vidéo préchargés)…", flush=True)
pump(SETTLE)
print(f"figements pendant le démarrage : {len(stalls)} (> {STALL * 1000:.0f} ms)", flush=True)
stalls.clear()

# Ouverture comme au double-clic : le dossier est affiché, la ligne cliquée deux fois.
win._navigate_to(VIDEO.parent) if str(VIDEO).startswith(str(root)) else None
pump(1.5)
opened = win._open_video(VIDEO)
pump(1.0)
pane = win._video
print("module ouvert :", bool(opened and pane), "moteur", getattr(pane, "_engine", None), flush=True)
stalls.clear()
shown = []
orig = pane.viewer.set_frame
pane.viewer.set_frame = lambda f: (shown.append(time.perf_counter()), orig(f))
if not pane._playing:
    pane.play()
t0 = time.perf_counter()
pump(PLAY)
elapsed = time.perf_counter() - t0
pane.pause()
gaps = sorted((b - a) * 1000 for a, b in zip(shown, shown[1:]))
fps = float(pane.source.fps)
print(f"lecture {elapsed:.1f} s à {fps:g} i/s : {len(shown)} images montrées (attendu ~{elapsed * fps:.0f}) ; "
      f"écart médian {statistics.median(gaps):.1f} ms, 95e {gaps[int(len(gaps) * .95)]:.1f}, max {gaps[-1]:.1f} ; "
      f">2 images d'écart : {sum(1 for g in gaps if g > 2000 / fps)}", flush=True)
print(f"FIGEMENTS du fil de l'interface (> {STALL * 1000:.0f} ms) pendant la lecture : {len(stalls)}", flush=True)
by_site = {}
for at, late, stack in stalls:
    last = [l for l in stack.splitlines() if l.strip().startswith("File")][-1:] or ["?"]
    by_site.setdefault(last[0].strip(), []).append(late)
for site, vals in sorted(by_site.items(), key=lambda kv: -sum(kv[1]))[:12]:
    print(f"  {len(vals):3d} × moy {statistics.mean(vals) * 1000:5.0f} ms  max {max(vals) * 1000:5.0f} ms  {site}")
for at, late, stack in stalls[:30]:
    LOG.write(f"=== figement {late * 1000:.0f} ms\n{stack}\n")
LOG.close()
dialog = getattr(win, "_settings_dialog_v2", None)
if dialog is not None:
    def built():
        return sum(1 for n in dialog.findChildren(__import__("settings_window_v2")._LazyNode) if n._built)
    before = built()
    pump(float(os.environ.get("RESUME", "6")))
    print(f"fenêtre de réglages : sections construites {before} -> {built()} après la pause "
          f"(la préparation {'reprend' if built() > before else 'NE reprend PAS'})", flush=True)
running[0] = False
win._close_video()
os._exit(0)
