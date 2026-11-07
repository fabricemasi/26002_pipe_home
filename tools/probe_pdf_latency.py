"""Sonde de fluidité du module PDF (mesures RÉELLES, pas d'impression subjective).

    QT_QPA_PLATFORM=windows python tools/probe_pdf_latency.py [rapport.json]

Mesure, dans une vraie fenêtre 1600 × 1000 : ouverture (300 pages de texte, AcroForm, XFA ACIA, XFA IMM 1344),
premier rendu net, changement de page (jusqu'aux tuiles nettes), latence de FRAPPE dans un champ AcroForm et XFA
(touche -> tuile du champ redessinée), zoom (cran -> image ; rendu net après la pause), défilement (durée des
images peintes), mémoire du processus. Chaque mesure : médiane et pire cas sur plusieurs essais.
"""
from __future__ import annotations

import ctypes
import json
import os
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
os.environ.setdefault("FM_PDF_RECOVERY_DIR", str(ROOT / "tmp_shot" / "pdf_recovery"))

from PySide6.QtCore import QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

APP = QApplication.instance() or QApplication(sys.argv)


def rss_mb() -> float:
    class PMC(ctypes.Structure):
        _fields_ = [("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong), ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t), ("a", ctypes.c_size_t), ("b", ctypes.c_size_t),
                    ("c", ctypes.c_size_t), ("d", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t)]
    pmc = PMC()
    pmc.cb = ctypes.sizeof(PMC)
    k32 = ctypes.windll.kernel32
    k32.GetCurrentProcess.restype = ctypes.c_void_p
    k32.K32GetProcessMemoryInfo.argtypes = (ctypes.c_void_p, ctypes.POINTER(PMC), ctypes.c_ulong)
    k32.K32GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb)
    return pmc.WorkingSetSize / 1048576


def pump_until(cond, timeout=30.0):
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < timeout:
        APP.processEvents()
        if cond():
            return (time.perf_counter() - t0) * 1000
        time.sleep(0.001)
    return None


def stats(values):
    values = [v for v in values if v is not None]
    if not values:
        return None
    return {"median_ms": round(statistics.median(values), 1), "max_ms": round(max(values), 1), "n": len(values)}


def sharp(view):
    view.viewport().repaint()
    skey = view._scale_key()
    return not view._zooming and all(view._page_complete(i, skey) for i in view._visible_indexes()
                                     if view.page_rect(i).intersects(view.viewport().rect()))


def big_text_pdf(pages=300) -> bytes:
    import io
    import pymupdf
    doc = pymupdf.open()
    for i in range(pages):
        p = doc.new_page(width=595, height=842)
        y = 60
        for k in range(45):
            p.insert_text((50, y), "Page %d ligne %d : texte de contrôle pour mesurer le rendu et le défilement" %
                          (i + 1, k + 1), fontsize=10)
            y += 16
    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


def open_pane(data, name):
    from fm_pdf.pane import PdfPane
    tmp = ROOT / "tmp_shot" / "probe"
    tmp.mkdir(parents=True, exist_ok=True)
    path = tmp / name
    path.write_bytes(data)
    pane = PdfPane(None, {"pdf_default_fit": "width", "pdf_autosave_recovery_s": 0})
    pane.resize(1600, 1000)
    pane.show()
    t0 = time.perf_counter()
    pane.open_path(path)
    opened = pump_until(lambda: pane.session.info.get("page_count"), 60)
    first = pump_until(lambda: sharp(pane.view), 60)
    return pane, {"open_ms": round(opened, 1) if opened else None,
                  "first_sharp_ms": round((time.perf_counter() - t0) * 1000, 1) if first is not None else None,
                  "engine_open_ms": round(pane.session.info.get("open_ms", 0), 1),
                  "xfa_ms": round(pane.session.info.get("xfa_ms", 0), 1)}


def close(pane):
    pane.session.form_dirty = pane.session.struct_dirty = False
    pane.shutdown()
    pane.close()
    pane.deleteLater()
    APP.processEvents()


def measure_navigation(pane, report):
    v = pane.view
    pages = []
    for target in (10, 150, 299, 3, 200):
        if target >= v.page_count():
            continue
        t0 = time.perf_counter()
        v.go_to_page(target)
        ms = pump_until(lambda: sharp(v), 20)
        pages.append(None if ms is None else (time.perf_counter() - t0) * 1000)
    report["page_change_to_sharp"] = stats(pages)
    frames = []
    orig = v.paintEvent

    def timed(event):
        t = time.perf_counter()
        orig(event)
        frames.append((time.perf_counter() - t) * 1000)
    v.paintEvent = timed
    bar = v.verticalScrollBar()
    for _ in range(120):
        bar.setValue(bar.value() + 25)
        v.viewport().repaint()
        APP.processEvents()
    v.paintEvent = orig
    report["scroll_frame_paint"] = stats(frames)
    zooms, settle = [], []
    for factor in (1.15, 1.15, 1.15, 0.87, 0.87):
        t0 = time.perf_counter()
        v.zoom_by(factor, QPointF(500, 400))
        v.viewport().repaint()
        zooms.append((time.perf_counter() - t0) * 1000)
    t0 = time.perf_counter()
    ms = pump_until(lambda: sharp(v), 20)
    report["zoom_step_frame"] = stats(zooms)
    report["zoom_sharp_after_last_step_ms"] = None if ms is None else round((time.perf_counter() - t0) * 1000, 1)
    report["tile_render"] = {"avg_ms": round(v.stats()["tile_ms_avg"], 1), "tiles": v.stats()["tiles"],
                             "cache_mb": round(v.stats()["cache_mb"], 1)}


def type_latency(pane, point, chars="abcdefghij"):
    """Touche -> zones invalidées redessinées (tuiles nettes)."""
    from PySide6.QtTest import QTest
    v = pane.view
    QTest.mouseClick(v.viewport(), Qt.LeftButton, Qt.NoModifier, point)
    pump_until(lambda: pane.session.engine.pending() == 0, 5)
    pump_until(lambda: sharp(v), 10)
    out = []
    for ch in chars:
        gen_tiles = v.timings["tiles"]
        t0 = time.perf_counter()
        QTest.keyClick(v, ch)
        ms = pump_until(lambda: v.timings["tiles"] > gen_tiles and sharp(v) and pane.session.engine.pending() == 0,
                        5)
        out.append(None if ms is None else (time.perf_counter() - t0) * 1000)
    return stats(out)


def field_point(pane, name):
    f = next(x for x in pane.session.info["fields"] if x["name"] == name)
    pr = pane.view.page_rect(0)
    z = pane.view.zoom
    return QPoint(int(pr.left() + (f["rect"][0] + f["rect"][2]) / 2 * z),
                  int(pr.top() + (f["rect"][1] + f["rect"][3]) / 2 * z))


def main(argv):
    import _pdf_samples as S
    report = {"platform": APP.platformName(), "rss_start_mb": round(rss_mb(), 1)}
    pane, r = open_pane(big_text_pdf(), "300_pages.pdf")
    report["texte_300_pages"] = r
    measure_navigation(pane, r)
    r["rss_mb"] = round(rss_mb(), 1)
    close(pane)

    pane, r = open_pane(S.sample_form(), "formulaire.pdf")
    report["acroform"] = r
    r["typing"] = type_latency(pane, field_point(pane, "nom"))
    close(pane)

    for name, point in (("xfa_fish_licence.pdf", (100.0, 190.0)), ("xfa_filled_imm1344e.pdf", (66.7, 220.0))):
        if not S.has_fixture(name):
            continue
        pane, r = open_pane(S.fixture(name), name)
        report[name] = r
        pr = pane.view.page_rect(0)
        z = pane.view.zoom
        r["typing"] = type_latency(pane, QPoint(int(pr.left() + point[0] * z), int(pr.top() + point[1] * z)))
        r["rss_mb"] = round(rss_mb(), 1)
        close(pane)
    report["rss_end_mb"] = round(rss_mb(), 1)
    text = json.dumps(report, ensure_ascii=False, indent=1)
    if argv:
        Path(argv[0]).write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
