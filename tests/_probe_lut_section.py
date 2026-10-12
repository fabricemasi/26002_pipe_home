"""Usage : python tests/_probe_lut_section.py [image] [sortie.png]
Ouvre Parametres generaux, deplie la section LUT avec l'image donnee et capture la fenetre."""
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.getcwd())
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QElapsedTimer
APP = QApplication.instance() or QApplication([])
import app_style
app_style.apply_style(APP)
import browser_core
import settings_layout as sl
import settings_window as sw

browser_core._register_settings_hooks()
image = sys.argv[1] if len(sys.argv) > 1 else ""
out = sys.argv[2] if len(sys.argv) > 2 else "lut_section.png"


def pump(ms):
    t = QElapsedTimer(); t.start()
    while t.elapsed() < ms:
        APP.processEvents()


win = sw.SettingsWindow(mode="general")
win.resize(900, 1700)
win.show()
pump(300)
for section in win.findChildren(sl._Section):
    if section._name_label.text() == "LUT":
        section.set_collapsed(False)
pump(300)
if image:
    win.lut_images_field.set_values([image], image, {image: "slog3"})
    pump(1500)
win.grab().save(out)
print("saved", out, "curves", win.lut_images_field.curves())
