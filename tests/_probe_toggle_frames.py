"""Fluidite de l'animation d'un toggle de la fenetre de reglages v2 (branchee sur la fenetre principale,
comme dans l'appli) : instants des images REELLEMENT peintes pendant la bascule, ecarts entre images,
et ce qui bloque le fil de l'interface pendant ce temps (apercu en direct). Affichage natif conseille :
QT_QPA_PLATFORM=windows python tests/_probe_toggle_frames.py. Jamais les reglages reels sur le disque."""
import copy, os, sys, tempfile, time
from pathlib import Path
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PySide6.QtCore import QCoreApplication, QElapsedTimer, QEvent, QObject, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
import settings_store, browser_core
import pipeline_browser as pb
import settings_window_v2 as v2
import settings_widgets as sw
for module in (settings_store, pb, browser_core, v2):
    for name in ("save_settings", "_save_window_geometry", "save_layout_settings", "_update_layout_setting"):
        if hasattr(module, name):
            setattr(module, name, lambda *a, **k: None)
settings = copy.deepcopy(settings_store.load_settings())      # vrais reglages LUS (jamais ecrits)
root = Path(tempfile.mkdtemp())
(root / "3d" / "images").mkdir(parents=True)
settings["root_path"] = str(root)
for module in (v2, pb):
    module.load_settings = lambda: copy.deepcopy(settings)
pb.apply_all_settings(settings)
QApplication.setAttribute(Qt.AA_DontCreateNativeWidgetSiblings, True)
app = QApplication(sys.argv)
pb.apply_style(app)
win = pb.PipelineBrowser(root); win._idle_preview_scheduler.timer.stop()
win.show(); win.resize(1400, 850)
clock = QElapsedTimer(); clock.start()


def pump(seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents(); QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete); time.sleep(0.001)


pump(0.5)
win.open_settings_v2(); pump(0.8)
dialog = win._settings_dialog_v2
page = dialog.stack.currentWidget()
for node in page.findChildren(v2._LazyNode):
    if node.node.title == "Visionneuse":
        node.set_collapsed(False)
pump(0.5)
toggle = next(w for st in dialog.stores.values() for sp, w in st.get("specs", ())
              if not isinstance(sp, str) and sp.key == "viewer_slide_enabled")
frames = []


class Spy(QObject):
    def eventFilter(self, obj, ev):
        if obj is toggle and ev.type() == QEvent.Paint:
            frames.append((clock.elapsed(), round(toggle._progress, 3)))
        return False


spy = Spy(); toggle.installEventFilter(spy)
# Ce qui tourne sur le fil de l'interface pendant l'animation
blocks = []
real_flush = dialog._flush_live


def timed_flush():
    t = clock.elapsed(); real_flush(); blocks.append(("_flush_live (apercu en direct)", t, clock.elapsed() - t))


dialog._live_timer.timeout.disconnect()
dialog._live_timer.timeout.connect(timed_flush)
for attempt in range(3):
    frames.clear(); blocks.clear()
    t0 = clock.elapsed()
    QTest.mouseClick(toggle, Qt.LeftButton)
    pump(0.6)
    shown = [(t - t0, p) for t, p in frames]
    gaps = [b[0] - a[0] for a, b in zip(shown, shown[1:]) if a[1] not in (0.0, 1.0) or b[1] not in (0.0, 1.0)]
    print(f"bascule {attempt + 1} : {len(shown)} images | ecarts (ms) {gaps} | max {max(gaps) if gaps else '-'}")
    print("   progression :", [p for _t, p in shown])
    for name, t, d in blocks:
        print(f"   {name} a +{t - t0} ms, duree {d} ms")
print("OK")
