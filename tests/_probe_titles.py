import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication
APP = QApplication([])
import app_style; app_style.apply_style(APP)
import settings_window as sw, settings_layout as sl
w = sw.SettingsWindow(); w.resize(1100, 900); w.show()
for x in w.findChildren(sl._Section): x.set_collapsed(False)
for x in w.findChildren(sl._SubSection): x.set_collapsed(False)
APP.processEvents()
for lvl in range(1, 6):
    getattr(w, f"title_level{lvl}_indent_field").setValue(0)
APP.processEvents()
xs = {}
for x in w.findChildren(sl._Section):
    xs.setdefault(("1", x._name_label.mapTo(w, x._name_label.rect().topLeft()).x()), []).append(x._name_label.text())
for x in w.findChildren(sl._SubSection):
    if x.isVisible():
        xs.setdefault((str(x._level), x._name_label.mapTo(w, x._name_label.rect().topLeft()).x()), []).append(x._name_label.text())
for (lvl, px), names in sorted(xs.items()):
    print(lvl, px, len(names), names[:2])
