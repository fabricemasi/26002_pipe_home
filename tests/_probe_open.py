"""Mesure l'ouverture de la fenetre de reglages : 1re construction, puis
reouverture (fenetre gardee cachee, voir SettingsWindow.reopen).
Options : --prof (profil de la construction), --general (mode general)."""
import os, sys, time, cProfile, pstats, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
from PySide6.QtWidgets import QApplication
APP = QApplication([])
import app_style; app_style.apply_style(APP)
import pipeline_browser as p
win = p.PipelineBrowser(Path(tempfile.mkdtemp())); win._idle_preview_scheduler.timer.stop()
win.resize(1400, 800); win.show(); APP.processEvents()
mode = "general" if "--general" in sys.argv else "visuel"
attr = "_settings_dialog_general" if mode == "general" else "_settings_dialog"
pr = cProfile.Profile() if any(a.startswith("--prof") for a in sys.argv) else None
PROF_I = 1 if "--prof2" in sys.argv else 0
for i in range(3):
    t0 = time.perf_counter()
    if pr and i == PROF_I: pr.enable()
    win.open_settings(mode); APP.processEvents()
    if pr and i == PROF_I: pr.disable()
    print(f"ouverture {i + 1} : {1000 * (time.perf_counter() - t0):7.0f} ms")
    getattr(win, attr).reject(); APP.processEvents()
if pr:
    st = pstats.Stats(pr); st.sort_stats("cumulative").print_stats(40)
