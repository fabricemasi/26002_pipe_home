"""Fenetres « Changement de style a la volee » (overrides) : redimensionnement par le bord, a l'ecran.
Pour chaque pas : temps de traitement, tailles reellement prises par la fenetre (aller-retour = elle se
redimensionne contre le geste, ce qui clignote), changements de hauteur. Jamais les reglages reels.
Lancer : QT_QPA_PLATFORM=windows python tests/_probe_quick_style_resize.py"""
import copy, os, sys, time
os.environ.setdefault("QT_QPA_PLATFORM", "windows")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv)
import settings_quick_style as qs
import settings_window_v2 as v2
import settings_element_style as es
from settings_store import DEFAULT_SETTINGS
qs.save_settings = lambda *a, **k: None
qs.load_settings = lambda: copy.deepcopy(DEFAULT_SETTINGS)
settings = copy.deepcopy(DEFAULT_SETTINGS)


def table_specs():
    return es.TableTarget.specs(es.TableTarget.__new__(es.TableTarget))


WINDOWS = {
    "Override Tableau": table_specs,
    "Titre de ligne": lambda: list(qs.font_padding_specs("item_title")),
    "Visionneuse : Tableau": lambda: list(v2.CATALOG["Visionneuse : Tableau"]),
}


class Sizes(QObject):
    def __init__(self):
        super().__init__()
        self.log = []

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Resize:
            self.log.append((event.size().width(), event.size().height()))
        return False


def pump_idle(limit=0.5):
    end = time.perf_counter() + limit
    while time.perf_counter() < end:
        app.processEvents()
        if not app.hasPendingEvents() if hasattr(app, "hasPendingEvents") else False:
            break


for name, make in WINDOWS.items():
    win = qs.QuickStyleWindow(f"sonde {name}", make(), settings, settings=settings)
    win.show()
    for _ in range(20):
        app.processEvents()
    spy = Sizes()
    win.installEventFilter(spy)
    start_w, start_h = win.width(), win.height()
    times, back, heights = [], 0, set()
    for step in range(60):
        target = start_w - 4 * step if step < 30 else start_w - 120 + 4 * (step - 30)
        spy.log.clear()
        t = time.perf_counter()
        win.resize(target, win.height())
        for _ in range(4):
            app.processEvents()
        times.append((time.perf_counter() - t) * 1000)
        widths = [w for w, _h in spy.log]
        heights.update(h for _w, h in spy.log)
        if len(set(widths)) > 1 or (widths and widths[-1] != max(target, win.minimumWidth())):
            back += 1
    times.sort()
    print(f"{name:22} : pas median {times[len(times) // 2]:.1f} ms, max {times[-1]:.1f} ms | "
          f"aller-retours {back} | hauteurs {sorted(heights)}")
    win.close()
    for _ in range(5):
        app.processEvents()
print("OK")
