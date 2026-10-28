"""Planche, molette avec « Scrolling anime » : mesure A L'ECRAN (affichage natif) la regularite du
glissement — intervalle entre deux images peintes et duree de chaque peinture. Dossier temporaire,
jamais les reglages reels. Lancer : QT_QPA_PLATFORM=windows python tests/_probe_gallery_scroll.py"""
import copy, os, sys, tempfile, time
from pathlib import Path
os.environ.setdefault("QT_QPA_PLATFORM", "windows")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QImage, QWheelEvent
from PySide6.QtWidgets import QApplication, QWidget
app = QApplication(sys.argv)
from fm_visionneuse import focus
import ui_state
from settings_store import DEFAULT_SETTINGS
ui_state.APPLIED_SETTINGS = copy.deepcopy(DEFAULT_SETTINGS)
ui_state.APPLIED_SETTINGS["viewer_scroll_animated"] = True
folder = Path(tempfile.mkdtemp())
paths = []
for i in range(90):
    image = QImage(800, 600, QImage.Format_RGB32)
    image.fill(QColor.fromHsv((i * 23) % 360, 150, 180))
    path = folder / f"i{i:02d}.png"
    image.save(str(path))
    paths.append(path)
host = QWidget()
screen = app.primaryScreen().availableGeometry()
host.setGeometry(screen)
host.show()
gallery = focus.FocusGallery(host, paths, str(paths[0]))
gallery.setGeometry(host.rect())
gallery.show()
gallery.reveal_current()


def pump(seconds, until=None):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        if until is not None and until():
            return
        time.sleep(0.002)


pump(float(os.environ.get("SETTLE", "3")))   # vignettes decodees (SETTLE=s : planche au repos avant)
stamps, durations = [], []


class Meter(QObject):
    def eventFilter(self, obj, event):
        if event.type() == QEvent.Paint and gallery._scroll_goal is not None:
            start = time.perf_counter()
            obj.removeEventFilter(self)
            app.sendEvent(obj, event)
            obj.installEventFilter(self)
            durations.append((time.perf_counter() - start) * 1000)
            stamps.append(time.perf_counter())
            return True
        return False


meter = Meter()
gallery.viewport().installEventFilter(meter)
print("ecran", screen.size(), "| planche", gallery._cols, "x", gallery._visible_rows, "visibles sur", gallery._rows, "lignes")
for delta in (-120, -120, 120, -360, 360, -120, -120, 120, 120):
    stamps.clear(); durations.clear()
    viewport = gallery.viewport()
    pos = QPointF(400, 300)
    app.sendEvent(viewport, QWheelEvent(pos, QPointF(viewport.mapToGlobal(pos.toPoint())), QPoint(0, 0), QPoint(0, delta),
                                        Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False))
    pump(1.0, lambda: gallery._scroll_goal is None)
    pump(float(os.environ.get("PAUSE", "0.1")))
    busy = gallery._proxy_pool.activeThreadCount()
    gaps = [round((b - a) * 1000, 1) for a, b in zip(stamps, stamps[1:])]
    print(f"cran {delta:+d} : {len(stamps)} images, ecarts max {max(gaps or [0])} ms, mediane "
          f"{sorted(gaps)[len(gaps) // 2] if gaps else 0} ms | peinture max {max(durations or [0]):.1f} ms | decodages en cours {busy} | ecarts {gaps}")
host.close()
pump(0.2)
