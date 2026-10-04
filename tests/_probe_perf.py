"""Mesure le cout reel d'un cran de slider (fenetre principale + reglages ouverts)."""
import os, sys, time, cProfile, pstats, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
from PySide6.QtWidgets import QApplication
APP = QApplication([])
import app_style; app_style.apply_style(APP)
import pipeline_browser as p
import settings_window as sw
work = tempfile.mkdtemp()
win = p.PipelineBrowser(Path(work)); win._idle_preview_scheduler.timer.stop()
win.resize(1400, 800); win.show(); APP.processEvents()
dlg = sw.SettingsWindow(win)
dlg.settingsChanged.connect(win._apply_settings)
dlg.show(); APP.processEvents()
def settle():
    for _ in range(4):
        APP.processEvents(); time.sleep(0.04)
def tick(field, delta=1):
    field.setValue(field.value() + delta)
    s = time.perf_counter(); settle0 = time.perf_counter()
    # attend la fin du debounce + application
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < 0.15:
        APP.processEvents()
    return
def cost(name, field, n=6):
    # mesure le temps CPU passe dans la boucle d'evenements, hors attente
    total = 0
    for i in range(n):
        field.setValue(field.value() + (1 if i % 2 == 0 else -1) * 2)
        s = time.perf_counter()
        t0 = s
        busy = 0
        while time.perf_counter() - t0 < 0.2:
            b = time.perf_counter(); APP.processEvents(); busy += time.perf_counter() - b if time.perf_counter() - b > 0.002 else 0
        total += busy
    print(f"{name:34s} {total/n*1000:8.1f} ms / cran")
for attr in ("header_height_field", "header_padding_field", "scale_field", "title_level1_indent_field"):
    f = getattr(dlg, attr, None)
    if f is not None: cost(attr, f)
if len(sys.argv) > 1:
    pr = cProfile.Profile(); pr.enable()
    for i in range(6):
        dlg.header_height_field.setValue(dlg.header_height_field.value() + 2)
        t0 = time.perf_counter()
        while time.perf_counter() - t0 < 0.2: APP.processEvents()
    pr.disable(); pstats.Stats(pr).sort_stats("cumulative").print_callers("setStyleSheet")
