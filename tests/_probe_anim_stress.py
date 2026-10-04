"""Usage : python tests/_probe_anim_stress.py [graine] [etapes] (racine root_path reelle).
Stress des animations de colonnes : clics rapides, repli/depli, masquage.
Verifie qu'aucun overlay ne reste bloque et que le fondu de selection marche encore."""
import os, sys, random, time, traceback
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.getcwd())
from pathlib import Path
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QElapsedTimer
APP = QApplication.instance() or QApplication([])
import pipeline_browser as p
import browser_core as bc
import app_style
import shiboken6

errors = []
def hook(t, v, tb):
    errors.append("".join(traceback.format_exception(t, v, tb)))
sys.excepthook = hook

settings = p.load_settings(); p.apply_all_settings(settings)
app_style.apply_style(APP)
root = Path(settings["root_path"])
w = p.PipelineBrowser(root)
w._idle_preview_scheduler.timer.stop()
w.setGeometry(10, 10, 1700, 900); w.show()

def pump(ms):
    t = QElapsedTimer(); t.start()
    while t.elapsed() < ms:
        APP.processEvents()

def overlays():
    vp = w.scroll.viewport()
    return [c for c in vp.children() if isinstance(c, (bc._FadeOverlay, bc._SlideOverlay)) and c.isVisible()]

def flags():
    out = {}
    for name in ("_columns_fade", "_select_fade", "_columns_slide"):
        o = getattr(w, name)
        if o is not None:
            out[name] = ("valid" if shiboken6.isValid(o) else "DELETED", o.running)
    return out

from collections import Counter
reasons = Counter()
orig = w._fade_before_select
def traced(column):
    if column in w.columns and w.columns.index(column) < len(w.columns) - 1:
        why = ("slide" if (w._columns_slide is not None and w._columns_slide.running) else
               "fade_masquer" if (w._columns_fade is not None and w._columns_fade.running) else
               "masque" if w._project_columns_hidden else None)
        res = orig(column)
        reasons["ok" if res is not None else (why or "autre")] += 1
        return res
    return orig(column)
w._fade_before_select = traced
pump(500)
rng = random.Random(int(sys.argv[1]) if len(sys.argv) > 1 else 1)
steps = int(sys.argv[2]) if len(sys.argv) > 2 else 300
stuck_at = None
for step in range(steps):
    r = rng.random()
    cols = [c for c in w.columns if c.isVisible() and c.list.count() > 0]
    try:
        if r < 0.75 and cols:
            c = rng.choice(cols[-3:])
            c.list.setCurrentRow(rng.randrange(c.list.count()))
        elif r < 0.87:
            w._toggle_project_columns()
        else:
            w._toggle_project_columns_hidden()
    except Exception:
        errors.append(traceback.format_exc())
    pump(rng.choice([0, 5, 20, 60, 120, 250, 400]))
    if step % 25 == 24:
        pump(1200)
        ov, fl = overlays(), flags()
        if ov or any(v[1] for v in fl.values()):
            print(f"[{step}] BLOQUE overlays={[type(o).__name__ for o in ov]} flags={fl}")
            if stuck_at is None: stuck_at = step
pump(1500)
print("overlays visibles en fin:", [type(o).__name__ for o in overlays()], "flags:", flags())
print("fondus de selection (ok / raison du saut):", dict(reasons))
print("exceptions:", len(errors))
uniq = {}
for e in errors:
    if "is not in list" not in e: uniq.setdefault(e.strip().splitlines()[-1], e)
for e in uniq.values(): print(e)
