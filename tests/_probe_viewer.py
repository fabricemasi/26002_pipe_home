"""Sonde de la visionneuse du mode focus (offscreen, donnees reelles) : entree en focus sur un
fichier d'un dossier, crans de molette (temps BLOQUANT, a garder sous ~10 ms), ruban et pellicule
au repos, clavier (fleches, Fin, rebond, Echap), zoom Ctrl+molette, zoom « semantique » vers la
planche, taille des vignettes, choix d'une vignette, retour aux colonnes (inspecteur et colonne sur
la derniere image vue). Usage :
    python tests/_probe_viewer.py "F:\\PIPELINE\\un\\dossier\\d'images" [rang de depart]"""

from _probe_isolate import isolate as _isolate_probe, protected_modules as _probe_modules
_isolate_probe()
import os
import sys
import time
import traceback
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

import settings_store
import browser_core
import pipeline_browser as pb

from browser_core_parts import project_config as _core_project_config, settings as _core_settings
for module in (settings_store, pb, browser_core, _core_project_config, _core_settings, *_probe_modules()):
    for name in ("save_settings", "_save_window_geometry", "save_layout_settings", "_update_layout_setting"):
        if hasattr(module, name):
            setattr(module, name, lambda *a, **k: None)

FOLDER = Path(sys.argv[1] if len(sys.argv) > 1 else r"F:\PIPELINE\BIB\lut\images pour test")
ROW = int(sys.argv[2]) if len(sys.argv) > 2 else 1
settings = pb.load_settings()
settings["viewer_filmstrip_enabled"] = True        # la sonde suit la pellicule (coupee dans certains reglages)
pb.apply_all_settings(settings)
QApplication.setAttribute(Qt.AA_DontCreateNativeWidgetSiblings, True)
app = QApplication(sys.argv)
pb.apply_style(app)
win = pb.PipelineBrowser(Path(settings.get("root_path") or r"F:\PIPELINE"))
win._idle_preview_scheduler.timer.stop()
win.show()
win.resize(1700, 950)
errors = []
sys.excepthook = lambda *exc: (errors.append(exc), traceback.print_exception(*exc))


def pump(seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        time.sleep(0.003)


def timed(fn) -> float:
    start = time.perf_counter()
    fn()
    app.processEvents()
    return (time.perf_counter() - start) * 1000


def ctrl_wheel(widget, pos: QPointF, delta: int):
    QApplication.sendEvent(widget, QWheelEvent(pos, QPointF(widget.mapToGlobal(pos.toPoint())), QPoint(0, 0),
                                               QPoint(0, delta), Qt.NoButton, Qt.ControlModifier,
                                               Qt.NoScrollPhase, False))


pump(1.0)
win._navigate_to(FOLDER)
pump(2.0)
column = [c for c in [*win.columns, *win.group_columns] if c.directory == FOLDER][0]
column.list.setCurrentRow(ROW)
pump(1.5)
# Sans fenetre ACTIVE, aucun raccourci ne repond (offscreen : l'activation n'est pas automatique).
win.windowHandle().requestActivate()
QTest.qWaitForWindowActive(win, 2000)
print("fichier :", Path(win.detail._current_path).name)
print("masquage (ms bloquants) :", round(timed(lambda: win._set_columns_hidden(True))))
pump(1.2)
overlay = win._focus_overlay
print("visionneuse : rang", win._viewer_index, "/", len(win._viewer_paths), "| pellicule :",
      win._filmstrip is not None and win._filmstrip.isVisible(), "| raccourcis actifs :",
      sum(s.isEnabled() for s in win._viewer_keys), "| taille reelle :", overlay._natural,
      "| image pleine :", overlay._full is not None and overlay._full.size().toTuple())
steps = []
for _ in range(8):
    steps.append(timed(lambda: win._step_focus_image(1)))
    pump(0.05)
print("crans rapides (ms bloquants) :", [round(t, 1) for t in steps])
pump(1.0)
print("au repos : decalage", round(overlay.ribbon_offset(), 3), "| pellicule", round(win._filmstrip._pos, 2),
      "| rang", win._viewer_index, "| montre :", Path(win._focus_path).name,
      "| inspecteur :", Path(win.detail._current_path).name)
for key in (Qt.Key_Right, Qt.Key_Left, Qt.Key_End):
    QTest.keyClick(win, key)
    pump(0.6)
print("clavier : rang apres Droite/Gauche/Fin =", win._viewer_index, "/", len(win._viewer_paths) - 1)
QTest.keyClick(win, Qt.Key_Right)
pump(0.1)
print("rebond a l'extremite :", overlay._bump_dir != 0)
pump(0.5)
QTest.keyClick(win, Qt.Key_Home)
pump(0.7)
anchor = QPointF(overlay.width() / 2, overlay.height() / 3)
before = overlay._view_rect()
v = (anchor.y() - before.y()) / before.height()
ctrl_wheel(overlay, anchor, 240)
pump(0.6)
after = overlay._view_rect()
print("zoom Ctrl+molette : x", round(after.width() / before.width(), 2), "| ecart vertical du point vise :",
      round(after.y() + v * after.height() - anchor.y(), 1), "px")
QTest.keyClick(win, Qt.Key_Escape)
pump(0.6)
print("Echap : zoome ?", overlay.zoomed(), "| colonnes masquees ?", win._project_columns_hidden)
ctrl_wheel(overlay, anchor, -120)
pump(0.2)
gallery = win._focus_gallery
print("planche (Ctrl+molette arriere) :", gallery is not None, "| vague :", gallery is not None and gallery._ripple_origin is not None,
      "| pellicule cachee :", not win._filmstrip.isVisible(), "| raccourcis coupes :",
      not any(s.isEnabled() for s in win._viewer_keys))
pump(0.8)
if gallery is not None:
    size = gallery.TILE
    ctrl_wheel(gallery.viewport(), QPointF(200, 200), 120)
    print("planche Ctrl+molette : vignettes", size, "->", gallery.TILE)
    item = gallery.item(min(5, gallery.count() - 1))
    name = Path(item.data(Qt.UserRole)).name
    QTest.mouseClick(gallery.viewport(), Qt.LeftButton, Qt.NoModifier, gallery.visualItemRect(item).center())
    pump(0.8)
    print("vignette choisie :", name, "| montre :", Path(win._focus_path).name, "| planche fermee :",
          win._focus_gallery is None, "| pellicule revenue :", win._filmstrip.isVisible())
ms = timed(lambda: win._set_columns_hidden(False))
pump(1.0)
current = column.current_path() if not column.isHidden() else None
print("retour aux colonnes (ms bloquants) :", round(ms), "| inspecteur :", Path(win.detail._current_path).name,
      "| colonne :", current.name if current else None, "| pellicule cachee :", not win._filmstrip.isVisible(),
      "| image au centre retiree :", win._focus_overlay is None)
print("exceptions :", len(errors))
sys.stdout.flush()
os._exit(1 if errors else 0)
