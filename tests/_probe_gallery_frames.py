"""Fluidite du passage image en focus -> planche (et retour) : instants des images REELLEMENT peintes
(image qui vole, planche), ecarts, et temps passe dans chaque peinture de la planche. Dossier temporaire de
40 images 1920 x 1080. Affichage natif : QT_QPA_PLATFORM=windows python tests/_probe_gallery_frames.py"""

from _probe_isolate import isolate as _isolate_probe, protected_modules as _probe_modules
_isolate_probe()
import copy, cProfile, os, pstats, sys, tempfile, time
from pathlib import Path
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PySide6.QtCore import QCoreApplication, QElapsedTimer, QEvent, QObject, Qt
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
import settings_store, browser_core
import pipeline_browser as pb
from browser_core_parts import project_config as _core_project_config, settings as _core_settings
for module in (settings_store, pb, browser_core, _core_project_config, _core_settings, *_probe_modules()):
    for name in ("save_settings", "_save_window_geometry", "save_layout_settings", "_update_layout_setting"):
        if hasattr(module, name):
            setattr(module, name, lambda *a, **k: None)
settings = copy.deepcopy(settings_store.load_settings())
root = Path(tempfile.mkdtemp())
folder = root / "3d" / "images"
folder.mkdir(parents=True)
for i in range(40):
    image = QImage(1920, 1080, QImage.Format_RGB32)
    p = QPainter(image)
    g = QLinearGradient(0, 0, 1920, 1080)
    g.setColorAt(0, QColor.fromHsv((i * 37) % 360, 160, 200)); g.setColorAt(1, QColor.fromHsv((i * 37 + 90) % 360, 200, 90))
    p.fillRect(image.rect(), g); p.end()
    image.save(str(folder / f"img_{i:02d}.jpg"), quality=90)
settings["root_path"] = str(root)
settings["viewer_gallery_ripple_enabled"] = os.environ.get("WAVE", "1") == "1"
pb.load_settings = lambda: copy.deepcopy(settings)
pb.apply_all_settings(settings)
QApplication.setAttribute(Qt.AA_DontCreateNativeWidgetSiblings, True)
app = QApplication(sys.argv)
pb.apply_style(app)
win = pb.PipelineBrowser(root); win._idle_preview_scheduler.timer.stop()
win.show(); win.resize(2540, 1380); win.move(0, 0)
clock = QElapsedTimer(); clock.start()


def pump(seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents(); QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete); time.sleep(0.001)


pump(0.5)
win._navigate_to(folder); pump(1.5)
column = [c for c in [*win.columns, *win.group_columns] if c.directory == folder][0]
column.list.setCurrentRow(5); pump(1.5)
win.windowHandle().requestActivate(); QTest.qWaitForWindowActive(win, 2000)
win._set_columns_hidden(True); pump(2.5)                 # images voisines decodees, au repos
frames, paints = [], []


class Spy(QObject):
    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Paint:
            name = type(obj).__name__
            if name in ("FocusOverlay", "Spy") or (obj.parent() is not None and type(obj.parent()).__name__ == "FocusGallery"):
                t = clock.elapsed()
                frames.append((t, "planche" if name not in ("FocusOverlay",) else "image"))
        return False


spy = Spy(); app.installEventFilter(spy)
real_paint = pb.FocusGallery.paintEvent


def timed_paint(self, event):
    t = time.perf_counter(); real_paint(self, event); paints.append((time.perf_counter() - t) * 1000)


pb.FocusGallery.paintEvent = timed_paint


def report(label, t0, seconds=0.8):
    shown = sorted({t for t, _k in frames if t >= t0})
    gaps = [b - a for a, b in zip(shown, shown[1:])]
    print(f"{label} : {len(shown)} images en {seconds} s | ecart max {max(gaps) if gaps else '-'} ms "
          f"| ecarts > 20 ms : {[g for g in gaps if g > 20]}")
    if paints:
        print(f"   peinture planche : {len(paints)} fois, moyenne {sum(paints) / len(paints):.1f} ms, max {max(paints):.1f} ms")


costs = {"tile_pixmap": [], "_on_proxy": []}
for name in costs:
    real = getattr(pb.FocusGallery, name)
    def timed(self, *a, _real=real, _name=name):
        t = time.perf_counter(); r = _real(self, *a); costs[_name].append((time.perf_counter() - t) * 1000); return r
    setattr(pb.FocusGallery, name, timed)
from fm_visionneuse import focus
profile = cProfile.Profile()
for attempt in range(2):
    frames.clear(); paints.clear()
    focus._PROXIES.clear(); focus._CELLS.clear()   # comme une premiere ouverture sur ce dossier
    for v in costs.values(): v.clear()
    t0 = clock.elapsed()
    t = time.perf_counter()
    if attempt == 0:
        profile.enable()
    win._open_focus_gallery()
    opening = (time.perf_counter() - t) * 1000
    pump(0.9)
    if attempt == 0:
        profile.disable()
    print(f"ouverture de la planche (appel bloquant) : {opening:.0f} ms")
    report(f"image -> planche {attempt + 1}", t0)
    for name, v in costs.items():
        if v:
            print(f"   {name} : {len(v)} appels, total {sum(v):.0f} ms, max {max(v):.1f} ms")
    frames.clear(); paints.clear()
    t0 = clock.elapsed()
    win._close_focus_gallery(); pump(0.9)
    report(f"planche -> image {attempt + 1}", t0)
    pump(0.5)

print("OK")
