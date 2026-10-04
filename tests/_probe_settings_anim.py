"""Usage : python tests/_probe_settings_anim.py [offscreen|native] [profile]
Compare la duree des images des animations de colonnes sans puis avec la
fenetre de reglages ouverte (et apres sa fermeture)."""
import os, sys, time, cProfile, pstats
if (sys.argv[1] if len(sys.argv) > 1 else "offscreen") == "offscreen":
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.getcwd())
from pathlib import Path
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QElapsedTimer
APP = QApplication.instance() or QApplication([])
import pipeline_browser as p
import browser_core as bc
import app_style
settings = p.load_settings(); p.apply_all_settings(settings)
app_style.apply_style(APP)
w = p.PipelineBrowser(Path(settings["root_path"]))
w._idle_preview_scheduler.timer.stop()
w.setGeometry(10, 10, 1700, 900); w.show()

def pump(ms):
    t = QElapsedTimer(); t.start()
    while t.elapsed() < ms:
        APP.processEvents()

# instrumentation des ticks et des paints
stats = {"tick": [], "gap": [], "paint": []}
last = [None]
for cls in (bc._FadeOverlay, bc._SlideOverlay):
    orig_tick, orig_paint = cls._tick, cls.paintEvent
    def tick(self, _o=orig_tick):
        now = time.perf_counter()
        if last[0] is not None: stats["gap"].append(now - last[0])
        last[0] = now
        s = time.perf_counter(); _o(self); stats["tick"].append(time.perf_counter() - s)
    def paint(self, e, _o=orig_paint):
        s = time.perf_counter(); _o(self, e); stats["paint"].append(time.perf_counter() - s)
    cls._tick, cls.paintEvent = tick, paint

created = []
for cls in (bc._FadeOverlay, bc._SlideOverlay):
    oi = cls.__init__
    def init(self, *a, _o=oi, _n=cls.__name__, **k):
        created.append((cur[0], _n)); _o(self, *a, **k)
    cls.__init__ = init
cur = ["?"]
of = w._fade_before_select
def fbs(column):
    r = of(column)
    if 0:
        print("  fade_before_select ->", r is not None, "visible", w.isVisible(), "hidden", w._project_columns_hidden,
              "fade", p._anim_running(w._columns_fade), w._columns_fade, "col", column is not None and column.isVisible(),
              "slide", w._columns_slide)
    return r
w._fade_before_select = fbs
def navigate():
    pump(400)
    for _ in range(3):
        cols = [c for c in w.columns if c.isVisible() and c.list.count() > 0]
        if not cols: break
        c = cols[-1]; c.list.setCurrentRow(0); pump(600)

def scenario(label):
    for k in stats: stats[k].clear()
    created.clear()
    last[0] = None
    t0 = time.perf_counter(); n = 0
    for i in range(4):
        cols = [c for c in w.columns if c.isVisible() and c.list.count() > 1]
        if 0: print("  cols", [(c.column_title, c.isVisible(), c.list.count(), c.width()) for c in w.columns], "hidden", w._project_columns_hidden, "collapsed", w._project_columns_collapsed)
        if True:
            cur[0]="select"; c = w.columns[0]; c.list.setCurrentRow((c.list.currentRow() + 1) % c.list.count()); last[0] = None; pump(700)
        cur[0]="collapse"; w._toggle_project_columns(); last[0] = None; pump(700)
        cur[0]="expand"; w._toggle_project_columns(); last[0] = None; pump(700)
        cur[0]="hide"; w._toggle_project_columns_hidden(); last[0] = None; pump(700)
        cur[0]="show"; w._toggle_project_columns_hidden(); last[0] = None; pump(700)
    def fmt(v):
        if not v: return "-"
        v = sorted(v); return f"n={len(v)} med={v[len(v)//2]*1000:.1f}ms p90={v[int(len(v)*.9)]*1000:.1f}ms max={v[-1]*1000:.1f}ms"
    from collections import Counter
    print(f"--- {label}", dict(Counter(created)))
    for k in stats: print(f"  {k:5s} {fmt(stats[k])}")

navigate()
scenario("sans reglages")
for mode in ("visuel", "general"):
    s = time.perf_counter(); w.open_settings(mode); pump(1500)
    print(f"ouverture {mode}: {time.perf_counter()-s:.2f}s")
prof = len(sys.argv) > 2
if prof:
    pr = cProfile.Profile(); pr.enable()
scenario("reglages ouverts")
if prof:
    pr.disable(); pstats.Stats(pr).sort_stats("tottime").print_stats(25)
w._settings_dialog.close(); w._settings_dialog_general.close(); pump(800)
scenario("reglages fermes")
