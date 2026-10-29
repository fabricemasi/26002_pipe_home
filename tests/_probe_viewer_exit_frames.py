"""Retour aux colonnes depuis la visionneuse : instants des images PEINTES (fondu des colonnes, image qui
repart vers l'inspecteur), ecarts, et ce qui prend du temps (cProfile du retour). Fenetre native, dossier
temporaire, jamais les reglages reels. Lancer : QT_QPA_PLATFORM=windows python tests/_probe_viewer_exit_frames.py"""

from _probe_isolate import isolate as _isolate_probe, protected_modules as _probe_modules
_isolate_probe()
import copy, cProfile, os, pstats, sys, tempfile, time
from pathlib import Path
os.environ.setdefault("QT_QPA_PLATFORM", "windows")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PySide6.QtCore import QCoreApplication, QEvent, QObject, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
import settings_store, browser_core
import pipeline_browser as pb
from browser_core_parts import project_config as _core_project_config, settings as _core_settings
for module in (settings_store, pb, browser_core, _core_project_config, _core_settings, *_probe_modules()):
    for name in ("save_settings", "_save_window_geometry", "save_layout_settings", "_update_layout_setting"):
        if hasattr(module, name):
            setattr(module, name, lambda *a, **k: None)
# FOLDER=<dossier reel> : mesure sur un vrai dossier (lecture seule ; racine = son disque de projets).
REAL_FOLDER = os.environ.get("FOLDER")
root = Path(os.environ.get("ROOT", r"F:\PIPELINE")) if REAL_FOLDER else Path(tempfile.mkdtemp())
folder = Path(REAL_FOLDER) if REAL_FOLDER else root / "3d" / "images"
if not REAL_FOLDER:
    folder.mkdir(parents=True)
for i in range(0 if REAL_FOLDER else 6):
    image = QImage(1600, 1000, QImage.Format_RGB32); image.fill(QColor(40 * i, 120, 200 - 30 * i))
    image.save(str(folder / f"i{i}.png"))
QApplication.setAttribute(Qt.AA_DontCreateNativeWidgetSiblings, True)
app = QApplication(sys.argv)


def pump(seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents(); QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete); time.sleep(0.002)


settings = copy.deepcopy(settings_store.DEFAULT_SETTINGS if not os.environ.get("REAL") else settings_store.load_settings())
settings["root_path"] = str(root)
pb.apply_all_settings(settings)
pb.apply_style(app)
win = pb.PipelineBrowser(root); win._idle_preview_scheduler.timer.stop()
win.setGeometry(40, 40, 1600, 900); win.show(); win.raise_(); win.activateWindow()
pump(0.8)
win._navigate_to(folder); pump(1.2)
column = [c for c in [*win.columns, *win.group_columns] if c.directory == folder][0]
pump(3.0 if REAL_FOLDER else 0)                      # vignettes du vrai dossier
frames = []


class Spy(QObject):
    def eventFilter(self, obj, event):
        if event.type() == QEvent.Paint and type(obj).__name__ in ("_FadeOverlay", "FocusOverlay", "QWidget")                 and (type(obj).__name__ != "QWidget" or type(obj.parent()).__name__ == "FocusGallery"):
            frames.append((time.perf_counter(), type(obj).__name__))
        return False


spy = Spy()
app.installEventFilter(spy)
for attempt in range(3):
    lst = column.list
    files = [i for i in range(lst.count()) if not lst.item(i).data(pb.ROLE_ISDIR)]
    item = lst.item(files[1 + attempt])
    lst.setCurrentItem(item); pump(0.8)
    win._view_in_viewer(Path(item.data(pb.ROLE_PATH)), column); pump(1.5)
    assert win._project_columns_hidden
    # STEPS=n : comme en vrai, on parcourt n images puis on revient AUSSITOT (synchro colonne / inspecteur et
    # decodages d'apercus en cours pendant le retour).
    steps = int(os.environ.get("STEPS", "0"))
    for _ in range(steps):
        win._step_focus_image(1); pump(0.12)
    pump(float(os.environ.get("WAIT", "0")))   # WAIT=s : on regarde la derniere image avant de revenir
    if os.environ.get("GALLERY"):              # GALLERY=1 : retour depuis la PLANCHE
        win._open_focus_gallery(); pump(1.5)
    frames.clear()
    profile = cProfile.Profile()
    vp = win.scroll.viewport()
    t0 = time.perf_counter()
    profile.enable()
    win._last_return_target = None
    real_start = win._start_focus_overlay

    def spy_start(end, _real=real_start):
        _real(end)
        if win._focus_overlay is not None:
            win._last_return_target = win._focus_overlay._source.toRect()
    win._start_focus_overlay = spy_start
    QTest.mousePress(vp, Qt.BackButton, Qt.NoModifier, vp.rect().center())
    QTest.mouseRelease(vp, Qt.BackButton, Qt.NoModifier, vp.rect().center())
    click = (time.perf_counter() - t0) * 1000
    end = time.perf_counter() + 0.9
    while time.perf_counter() < end:
        app.processEvents(); time.sleep(0.001)
    profile.disable()
    pump(0.3)
    landing = getattr(win, "_last_return_target", None)
    home = win._focus_source()
    print(f"   arrivee de l'image : {landing} | apercu de l'inspecteur : {home[1] if home else None}")
    shown = sorted({round((t - t0) * 1000) for t, _k in frames})
    gaps = [b - a for a, b in zip(shown, shown[1:])]
    print(f"retour {attempt + 1} : clic bloquant {click:.0f} ms | premiere image {shown[0] if shown else '-'} ms | "
          f"{len(shown)} images | ecart max {max(gaps) if gaps else '-'} ms | ecarts > 20 : {[g for g in gaps if g > 20]}")
    if attempt == 0:
        pstats.Stats(profile).sort_stats("cumulative").print_stats(int(os.environ.get("TOP", "22")))
    pump(0.6)
win.close(); pump(0.3)
print("OK")
