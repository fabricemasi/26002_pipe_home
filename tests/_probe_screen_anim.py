"""Compte les images REELLEMENT affichees a l'ecran pendant les repli/depli
(voir _screen_strip.py), reglages fermes puis ouverts."""
import os, sys, time, subprocess
sys.path.insert(0, os.getcwd())
from pathlib import Path
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QElapsedTimer, Qt
QApplication.setAttribute(Qt.AA_DontCreateNativeWidgetSiblings, True)   # comme main()
APP = QApplication.instance() or QApplication([])
import pipeline_browser as p, app_style
settings = p.load_settings(); p.apply_all_settings(settings); app_style.apply_style(APP)
w = p.PipelineBrowser(Path(settings["root_path"])); w._idle_preview_scheduler.timer.stop()
w.setGeometry(10, 10, 1700, 900); w.show()
def pump(ms):
    t = QElapsedTimer(); t.start()
    while t.elapsed() < ms: APP.processEvents()
pump(400)
for _ in range(3):
    cols = [c for c in w.columns if c.isVisible() and c.list.count() > 0]
    if not cols: break
    cols[-1].list.setCurrentRow(0); pump(600)
pump(500)
def scen(label, n=4):
    vp = w.scroll.viewport()
    g = vp.mapToGlobal(vp.rect().topLeft()); r = w.devicePixelRatioF()
    y = int((g.y() + 120) * r); x = int(g.x() * r); width = int(vp.width() * r)
    out = os.path.abspath(f"tests/_strip_{label}.txt")
    proc = subprocess.Popen([sys.executable, "tests/_screen_strip.py", str(x), str(y), str(width), out, str(n * 1.0 + 1.5)])
    pump(800)
    marks = []
    for _ in range(n):
        t = time.perf_counter(); w._toggle_project_columns(); pump(500); marks.append((t, time.perf_counter()))
    proc.wait()
    rows = [l.split() for l in open(out).read().splitlines()]
    rows = [(float(a), b) for a, b in rows]
    os.remove(out)
    res = []
    for t0, t1 in marks:
        seg = [(t, h) for t, h in rows if t0 <= t <= t0 + 0.35]
        changes = [seg[i][0] for i in range(1, len(seg)) if seg[i][1] != seg[i-1][1]]
        gaps = [b - a for a, b in zip(changes, changes[1:])]
        res.append(f"{len(changes)} img (max ecart {max(gaps)*1000:.0f}ms)" if gaps else f"{len(changes)} img")
    rate = len(rows) / (rows[-1][0] - rows[0][0])
    print(f"--- {label} (capture {rate:.0f}/s):", " | ".join(res), flush=True)
scen("fermes")
w.open_settings("visuel"); pump(1500)
scen("visuel_ouvert")
d = w._settings_dialog
d.move(w.x() + w.width() + 2000, d.y()); pump(500)
scen("visuel_hors_fenetre")
d.move(w.x() + 300, w.y() + 200); d.showMinimized(); pump(800)
scen("visuel_minimise")
d.showNormal(); pump(500); d.hide(); pump(800)
scen("visuel_cache")
