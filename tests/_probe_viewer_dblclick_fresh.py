"""Double-clic sur une ligne PAS ENCORE selectionnee (l'inspecteur ne la montre pas encore) : la visionneuse
doit montrer CE fichier en grand (pleine definition, a sa taille au centre), jamais la seule miniature de la
ligne. Plusieurs lignes, double-clics a la suite, avec ou sans pause. Dossier temporaire, jamais les
reglages reels."""

from _probe_isolate import isolate as _isolate_probe, protected_modules as _probe_modules
_isolate_probe()
import copy, os, sys, tempfile, time
from pathlib import Path
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PySide6.QtCore import QCoreApplication, QEvent, Qt
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
root = Path(tempfile.mkdtemp())
folder = root / "3d" / "images"
folder.mkdir(parents=True)
for i in range(8):
    image = QImage(2000, 1500, QImage.Format_RGB32)
    image.fill(QColor.fromHsv(i * 40, 160, 190))
    image.save(str(folder / f"i{i}.png"))
LAUNCHED = []          # jamais de logiciel externe ouvert par la sonde
pb.PipelineBrowser.on_activated = lambda self, path: LAUNCHED.append(path)
QApplication.setAttribute(Qt.AA_DontCreateNativeWidgetSiblings, True)
app = QApplication(sys.argv)


def pump(seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents(); QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete); time.sleep(0.003)


settings = copy.deepcopy(settings_store.DEFAULT_SETTINGS)
settings["root_path"] = str(root)
pb.apply_all_settings(settings)
pb.apply_style(app)
win = pb.PipelineBrowser(root); win._idle_preview_scheduler.timer.stop()
win.show(); win.resize(1400, 850)
pump(0.5)
win._navigate_to(folder); pump(1.0)
column = [c for c in [*win.columns, *win.group_columns] if c.directory == folder][0]
win.windowHandle().requestActivate(); QTest.qWaitForWindowActive(win, 2000)
bad = 0
CASES = [(3, 0.0, 1.2), (5, 0.05, 1.2), (1, 0.6, 1.2), (6, 0.0, 1.2), (2, 0.15, 1.2), (7, 0.3, 1.2), (4, 0.02, 1.2),
         (0, 0.1, 1.2), (3, 1.0, 1.2), (5, 2.0, 1.2), (1, 0.8, 1.2)]   # pause longue : ligne DEJA selectionnee
# Double-clic juste apres le retour aux colonnes (`back` = temps laisse au retour, animation encore en cours).
CASES += [(2, 0.0, 0.1), (6, 0.05, 0.05), (4, 0.1, 0.3), (4, 0.0, 0.1), (7, 0.6, 0.2), (7, 0.0, 0.15), (0, 0.0, 1.2)]
for row, settle, back in CASES:
    pass                                      # la ligne precedente reste selectionnee (cas reel)
    pump(0.3)
    item = column.list.item(row)
    rect = column.list.visualItemRect(item)
    # Vrai double-clic : 1er clic (selection : l'inspecteur se met a jour, en differe), 2e clic presque
    # aussitot. `settle` = temps entre les deux.
    QTest.mouseClick(column.list.viewport(), Qt.LeftButton, Qt.NoModifier, rect.center())
    pump(settle)
    QTest.mouseDClick(column.list.viewport(), Qt.LeftButton, Qt.NoModifier, rect.center())
    pump(1.5)
    overlay = win._focus_overlay
    target = overlay._target if overlay is not None else None
    shown = win._focus_path
    ok = (win._project_columns_hidden and overlay is not None and shown is not None
          and Path(shown).name == item.text() and target.width() > 300)
    bad += not ok
    print(f"ligne {row} ({item.text()}, pause {settle}s, retour {back}s) : masque {win._project_columns_hidden} | montre "
          f"{Path(shown).name if shown else None} | taille au centre {target.size().toSize() if target else None} | "
          f"image {overlay._base.size() if overlay else None} -> {'OK' if ok else 'MINIATURE'}")
    win._set_columns_hidden(False); pump(back)
    if back >= 1.0:                          # retour termine : la colonne a repris l'image montree
        selected = column.current_path()
        if selected is None or selected.name != item.text():
            bad += 1
            print("   retour : colonne sur", selected)
win.close(); pump(0.3)
print("logiciel externe demande :", LAUNCHED)
print("OK" if not bad and not LAUNCHED else f"ECHECS : {bad}")
