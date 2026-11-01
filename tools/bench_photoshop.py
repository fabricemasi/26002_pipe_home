"""Mesures du module Photoshop (reproductibles, offscreen) : python tools/bench_photoshop.py [petit|4k|grand ...]

Distingue : temps de calcul (compose, trait), latence visible (un point de brosse jusqu'à la tuile recomposée prête à
peindre), chargement / enregistrement, mémoire (pixels des calques et pic du processus)."""
import os
import statistics
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np  # noqa: E402

from PySide6.QtWidgets import QApplication  # noqa: E402

APP = QApplication.instance() or QApplication([])

from fm_photoshop import brush as B, compose as C, container, model as M, render  # noqa: E402
from fm_photoshop.session import Session  # noqa: E402

CASES = {"petit": (1024, 768, 4, 1.0), "4k": (3840, 2160, 24, 0.25), "grand": (8000, 6000, 8, 0.25)}


def rss_mb() -> float:
    import ctypes
    from ctypes import wintypes

    class Counters(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t), ("a", ctypes.c_size_t), ("b", ctypes.c_size_t),
                    ("c", ctypes.c_size_t), ("d", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t)]
    counters = Counters()
    counters.cb = ctypes.sizeof(Counters)
    ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(counters),
                                             counters.cb)
    return counters.WorkingSetSize / 1e6


def build(width, height, count, share):
    doc = M.new_document(width, height, "Bench")
    rng = np.random.default_rng(1)
    for i in range(count - 1):
        layer = M.Layer(f"L{i}")
        w, h = int(width * share ** 0.5), int(height * share ** 0.5)
        x, y = int(rng.integers(0, width - w + 1)), int(rng.integers(0, height - h + 1))
        data = rng.integers(0, 255, (h, w, 4), dtype=np.uint8)
        data[..., 3] = rng.integers(60, 255, (h, w), dtype=np.uint8)
        layer.pix.set_all(x, y, data)
        layer.opacity = 0.8
        layer.blend = ("normal", "multiply", "screen", "overlay")[i % 4]
        doc.layers.append(layer)
    return doc


def ms(fn, repeat=5):
    times = []
    for _ in range(repeat):
        t = time.perf_counter()
        fn()
        times.append((time.perf_counter() - t) * 1000)
    return statistics.median(times), max(times)


def run(name):
    width, height, count, share = CASES[name]
    print(f"\n== {name} : {width} × {height}, {count} calques ==")
    before = rss_mb()
    doc = build(width, height, count, share)
    session = Session(doc)
    print(f"pixels des calques : {doc.nbytes() / 1e6:.0f} Mo ; processus +{rss_mb() - before:.0f} Mo")
    tile = (1024, 1024, 1280, 1280)
    print("composition d'une tuile 256 × 256 : médiane %.1f ms, max %.1f ms" % ms(lambda: C.compose(doc.layers, tile)))
    if name != "grand":
        print("composition COMPLÈTE : médiane %.0f ms, max %.0f ms" % ms(lambda: C.compose(doc.layers, doc.rect()), 2))
    # trait : un point de brosse + recomposition de la zone touchée (ce que la peinture exige)
    layer = doc.layers[-1]
    cache = render.cache_for(session)
    cache.pump(cache.keys_for((0, 0, 1024, 1024)), 1e9)
    brush = B.Brush(size=60, hardness=0.5, color=(255, 0, 0))
    stroke = B.Stroke(layer, "pixels", brush, doc.rect())
    stroke.begin(300, 300)
    times, stamps = [], []
    for i in range(1, 60):
        t = time.perf_counter()
        dirty = stroke.move(300 + i * 6, 300 + (i % 7) * 4)
        stamps.append((time.perf_counter() - t) * 1000)
        if dirty:
            session.notify("paint", dirty)
            for key in cache.keys_for(dirty):
                cache.tile(key)
        times.append((time.perf_counter() - t) * 1000)
    times.sort()
    print("trait, tampon seul : médiane %.2f ms ; tampon + tuiles recomposées : médiane %.2f ms, p95 %.2f ms" % (
        statistics.median(stamps), statistics.median(times), times[int(len(times) * 0.95)]))
    command = stroke.end()
    print("fin de trait (étape d'annulation, %.1f Mo) " % (command.nbytes() / 1e6 if command else 0))
    session.do(command, notified=True)
    t = time.perf_counter(); session.undo(); print("annuler : %.1f ms" % ((time.perf_counter() - t) * 1000))
    t = time.perf_counter(); payload = container.dumps(doc); first = (time.perf_counter() - t) * 1000
    layer.pix.write((0, 0, 8, 8), np.zeros((8, 8, 4), np.uint8))
    t = time.perf_counter(); container.dumps(doc); again = (time.perf_counter() - t) * 1000
    t = time.perf_counter(); container.loads(payload); load = (time.perf_counter() - t) * 1000
    print(f"conteneur {len(payload) / 1e6:.0f} Mo : 1re écriture {first:.0f} ms, écriture après un seul calque modifié "
          f"{again:.0f} ms, ouverture {load:.0f} ms")
    print(f"mémoire du processus : {rss_mb():.0f} Mo")


if __name__ == "__main__":
    for case in sys.argv[1:] or ["petit", "4k"]:
        run(case)
