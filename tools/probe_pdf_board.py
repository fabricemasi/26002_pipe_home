"""Sonde de fluidité de l'élément PDF DANS le Board (mesures RÉELLES, vraie fenêtre 1600 × 1000).

    QT_QPA_PLATFORM=windows python tools/probe_pdf_board.py [rapport.json]

Mesure, pour un AcroForm, un XFA (ACIA) et l'IMM 1344 de l'IRCC (XFA lourd, si la fixture est là), et un PDF de
300 pages : ouverture du document de l'élément jusqu'à l'aperçu peint ; clic (module actif) -> édition sur place,
puis tuiles nettes ; FRAPPE dans un champ embarqué (touche -> champ redessiné à l'écran) ; peinture du Board (image
d'un pan / d'un zoom) avec le document en aperçu et en édition ; cran de zoom du Board avec le document édité (image,
puis net après la pause) ; pleine page, pleine largeur, plein écran (clic -> net). Réglages et presets : copies
temporaires (`tests/_isolate.py`)."""
from __future__ import annotations

import json
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import _isolate  # noqa: E402,F401  (jamais les vrais réglages de l'utilisateur)

from PySide6.QtCore import QPointF, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

APP = QApplication.instance() or QApplication(sys.argv)


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


def big_text_pdf(pages=300) -> bytes:
    import io
    import pymupdf
    doc = pymupdf.open()
    for i in range(pages):
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 100), "Page %d — texte de contrôle" % (i + 1), fontsize=14)
    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


class Probe:
    def __init__(self):
        from fm_board import serialization, ui as board_ui
        self.tmp = Path(tempfile.mkdtemp(prefix="probe_pdf_board_"))
        path = serialization.create_board_file(self.tmp / "sonde.brd")
        self.host = QWidget()
        self.host.resize(1600, 1000)
        self.pane = board_ui.BoardPane(self.host)
        self.pane.open(path)
        self.pane.resize(1600, 1000)
        self.host.show()
        self.pane.show()
        pump_until(lambda: False, 0.3)
        self.pane.set_module("pdf")
        self.ctl = self.pane.pdf
        self.v = self.pane.view

    def repaint(self):
        t = time.perf_counter()
        self.v.viewport().repaint()
        return (time.perf_counter() - t) * 1000

    def live_sharp(self, live) -> bool:
        self.v.viewport().repaint()
        lv = live.view
        if lv._zooming or lv._pending:
            return False
        skey = lv._scale_key()
        area = lv._view_area()
        return all(lv._page_complete(i, skey) for i in lv._visible_indexes() if lv.page_rect(i).intersects(area))

    def insert(self, name, data, offset):
        from fm_pdf import board_docs
        pdf = self.tmp / name
        pdf.write_bytes(data)
        t0 = time.perf_counter()
        item = self.ctl.insert(pdf)
        item.setPos(item.pos() + QPointF(offset, 0))
        entry_ready = pump_until(lambda: (self.v.viewport().repaint() or True) and item.entry() is not None
                                 and item.entry().ready(), 60)
        entry = item.entry()
        first = pump_until(lambda: (self.v.viewport().repaint() or True)
                           and any(k[0] is entry for k in board_docs._IMAGES), 30)
        return item, {"open_ms": None if entry_ready is None else round(entry_ready, 1),
                      "preview_painted_ms": round((time.perf_counter() - t0) * 1000, 1) if first is not None else None,
                      "pages": entry.info.get("page_count"), "xfa_loaded": entry.info.get("xfa_loaded")}

    def click(self, item, x, y):
        pos = self.v.mapFromScene(item.mapToScene(QPointF(x, y)))
        QTest.mouseClick(self.v.viewport(), Qt.LeftButton, Qt.NoModifier, pos)

    def measure(self, item, report, field=None, chars="abcdefgh"):
        preview = [self.repaint() for _ in range(15)]
        t0 = time.perf_counter()
        self.click(item, 40, 60)
        live = item.live
        report["click_to_live_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        ms = pump_until(lambda: self.live_sharp(live), 20)
        report["click_to_sharp_ms"] = None if ms is None else round((time.perf_counter() - t0) * 1000, 1)
        report["board_frame_preview"] = stats(preview)
        report["board_frame_live"] = stats([self.repaint() for _ in range(15)])
        center = QPointF(self.v.viewport().width() / 2, self.v.viewport().height() / 2)
        steps = []
        for k in range(8):
            t = time.perf_counter()
            self.v.zoom_by(1.1 if k < 4 else 1 / 1.1, center)
            self.v.viewport().repaint()
            steps.append((time.perf_counter() - t) * 1000)
        t0 = time.perf_counter()
        ms = pump_until(lambda: self.live_sharp(live), 10)
        report["board_zoom_step"] = stats(steps)
        report["board_zoom_sharp_after_ms"] = None if ms is None else round((time.perf_counter() - t0) * 1000, 1)
        for key in ("fit_page", "fit_width"):
            t0 = time.perf_counter()
            self.ctl.buttons[key].click()
            ms = pump_until(lambda: self.live_sharp(live), 10)
            report[key + "_sharp_ms"] = None if ms is None else round((time.perf_counter() - t0) * 1000, 1)
        t0 = time.perf_counter()
        self.ctl.buttons["fullscreen"].click()
        ms = pump_until(lambda: (live.repaint() or True) and not live.view._zooming and not live.view._pending
                        and all(live.view._page_complete(i, live.view._scale_key()) for i in live.view._visible_indexes()
                                if live.view.page_rect(i).intersects(live.view.viewport().rect())), 10)
        report["fullscreen_sharp_ms"] = None if ms is None else round((time.perf_counter() - t0) * 1000, 1)
        t0 = time.perf_counter()
        QTest.keyClick(live.view, Qt.Key_Escape)
        ms = pump_until(lambda: self.live_sharp(live), 10)
        report["fullscreen_exit_sharp_ms"] = None if ms is None else round((time.perf_counter() - t0) * 1000, 1)
        if field is not None:
            report["typing"] = self.typing(item, field, chars)

    def typing(self, item, field, chars):
        """Touche (envoyée à la VUE DU BOARD, comme au clavier) -> zone du champ redessinée à l'écran."""
        live = item.live
        lv = live.view
        if isinstance(field, tuple):                         # XFA : point d'un champ texte (points de la page 1)
            lv.go_to_page(0, record=False)
            pump_until(lambda: self.live_sharp(live), 10)
            dx, dy = lv.from_engine(0, *field)
            pr = lv.page_rect(0)
            local = QPointF(pr.left() + dx * lv.zoom, pr.top() + dy * lv.zoom)
        else:
            f = next(x for x in item.entry().info["fields"] if x["name"] == field)
            x0, y0, x1, y1 = f["rect"]
            pr = lv.page_rect(0)
            local = QPointF(pr.left() + (x0 + x1) / 2 * lv.zoom, pr.top() + (y0 + y1) / 2 * lv.zoom)
        self.click(item, local.x(), local.y())
        pump_until(lambda: lv.form_focus and item.session.engine.pending() == 0, 5)
        pump_until(lambda: self.live_sharp(live), 10)
        out = []
        for ch in chars:
            tiles = lv.timings["tiles"]
            t0 = time.perf_counter()
            QTest.keyClick(self.v, ch)
            ms = pump_until(lambda: lv.timings["tiles"] > tiles and self.live_sharp(live)
                            and item.session.engine.pending() == 0, 5)
            out.append(None if ms is None else (time.perf_counter() - t0) * 1000)
        return stats(out)


def main(argv):
    import _pdf_samples as S
    probe = Probe()
    report = {"window": [1600, 1000]}
    item, r = probe.insert("acroform.pdf", S.sample_form(), -700)
    probe.measure(item, r, "nom")
    report["acroform"] = r
    item, r = probe.insert("pages300.pdf", big_text_pdf(300), -300)
    probe.measure(item, r)
    report["text_300_pages"] = r
    item, r = probe.insert("acia.pdf", S.fixture("xfa_fish_licence.pdf"), 100)
    probe.measure(item, r, (100.0, 190.0), "abcd")            # « Company Name » (comme tools/probe_pdf_latency.py)
    report["xfa_acia"] = r
    if S.has_fixture("xfa_filled_imm1344e.pdf"):
        item, r = probe.insert("imm1344e.pdf", S.fixture("xfa_filled_imm1344e.pdf"), 500)
        probe.measure(item, r, (66.7, 220.0), "abcd")
        report["xfa_imm1344"] = r
    text = json.dumps(report, indent=2, ensure_ascii=False)
    print(text)
    if len(argv) > 1:
        Path(argv[1]).write_text(text, encoding="utf-8")
    from fm_pdf import board_docs
    board_docs.close_scene(probe.pane.scene)


if __name__ == "__main__":
    main(sys.argv)
