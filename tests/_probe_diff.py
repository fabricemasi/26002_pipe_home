"""Compare tests/_shots_before et _shots_after : tailles, pixels differents, zones."""
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtGui import QImage, QColor, QPainter
from PySide6.QtWidgets import QApplication
APP = QApplication.instance() or QApplication([])
b_dir, a_dir = "tests/_shots_before", "tests/_shots_after"
for name in sorted(os.listdir(b_dir)):
    a = QImage(os.path.join(a_dir, name)).convertToFormat(QImage.Format_RGB32)
    b = QImage(os.path.join(b_dir, name)).convertToFormat(QImage.Format_RGB32)
    if a.size() != b.size():
        print(name, "TAILLE", b.size().toTuple(), "->", a.size().toTuple()); continue
    w, h = a.width(), a.height()
    out = QImage(b)
    p = QPainter(out); p.fillRect(out.rect(), QColor(0, 0, 0, 170)); p.end()
    n = 0; rows = set()
    ab = a.constBits(); bb = b.constBits()
    am = memoryview(ab).cast("I"); bm = memoryview(bb).cast("I")
    for y in range(h):
        base = y * w
        if am[base:base + w] == bm[base:base + w]:
            continue
        for x in range(w):
            if am[base + x] != bm[base + x]:
                n += 1; rows.add(y); out.setPixelColor(x, y, QColor(255, 40, 40))
    out.save(os.path.join(a_dir, "DIFF_" + name))
    print(f"{name}: {n} px differents sur {len(rows)} lignes")
