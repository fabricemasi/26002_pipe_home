"""Couloirs de prises de la piste courante (sous la timeline) : une ligne par prise (waveform), le
comp en surbrillance. Glisser horizontalement sur une prise = la choisir sur cette plage (comping,
fondus enchaînés aux transitions) ; « Superposer » = looper (toutes les prises jouent ensemble).
Les prises restent des sources indépendantes ; chaque choix = une étape d'annulation."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from fm_audio_engine.project import set_comp, stack_loop_takes

from .timeline import HEADER_W
from .ui_kit import button, label, tok

LANE_H = 44


class TakeLanes(QWidget):
    def __init__(self, timeline, parent=None):
        super().__init__(parent)
        self.tl = timeline
        self.s = timeline.s
        self._g = None
        self.setMinimumHeight(LANE_H)
        self.setMouseTracking(True)
        self.s.changed.connect(self._refresh)
        self.s.mediaReady.connect(self._media)
        timeline.trackSelected.connect(lambda _t: self._refresh())

    def _media(self, _p: str) -> None:
        self.update()

    def track(self):
        return self.s.project.track(self.tl.current_track) if self.tl.current_track else None

    def _refresh(self) -> None:
        t = self.track()
        self.setFixedHeight(max(LANE_H, LANE_H * len(t.takes) if t else LANE_H))
        self.update()

    def paintEvent(self, _e) -> None:
        qp = QPainter(self)
        qp.fillRect(self.rect(), tok("panel_bg", "#202226"))
        t = self.track()
        if t is None or not t.takes:
            qp.setPen(tok("label_dim", "#999"))
            qp.drawText(self.rect(), Qt.AlignCenter, "Aucune prise sur la piste courante (armer R puis Enreg. ; une prise par passe de boucle)")
            qp.end()
            return
        comp = {s["take"]: [] for s in t.comp}
        for s in t.comp:
            comp[s["take"]].append((s["start"], s["end"]))
        for i, k in enumerate(t.takes):
            y = i * LANE_H
            qp.fillRect(QRectF(0, y, HEADER_W, LANE_H), tok("toolbar_bg", "#1c1d20"))
            qp.setPen(tok("row_label", "#ddd"))
            qp.drawText(QRectF(8, y, HEADER_W - 10, LANE_H), Qt.AlignLeft | Qt.AlignVCenter, k.get("name") or k["id"])
            lane = QRectF(HEADER_W, y + 2, self.width() - HEADER_W, LANE_H - 4)
            qp.fillRect(lane, tok("table_row_a" if i % 2 == 0 else "table_row_b", "#26282c"))
            hi = tok("accent", "#3d8bfd")
            hi.setAlpha(70)
            for a, b in comp.get(k["id"], []):
                qp.fillRect(QRectF(self.tl.x_of(a), lane.top(), self.tl.x_of(b) - self.tl.x_of(a), lane.height()), hi)
            for c in k["clips"]:
                x1, x2 = max(HEADER_W, self.tl.x_of(c.start)), min(self.width(), self.tl.x_of(c.end))
                if x2 <= x1:
                    continue
                qp.setPen(QPen(tok("panel_border", "#556"), 1))
                qp.drawRect(QRectF(x1, lane.top(), x2 - x1, lane.height()))
                pk = self.s.peaks.get(c.path)
                if pk is not None:
                    w = int(x2 - x1)
                    mins, maxs = pk.view(c.offset + (self.tl.sample_at(x1) - c.start) * c.rate, self.tl.spp * c.rate, w)
                    mid, amp = lane.center().y(), lane.height() / 2 * 0.9
                    qp.setPen(QPen(tok("value_fg", "#ccc"), 1))
                    pts = []
                    for kx in range(w):
                        lo, hv = mins[:, kx].min(), maxs[:, kx].max()
                        if lo == lo:
                            pts += [QPointF(x1 + kx, mid - hv * amp), QPointF(x1 + kx, mid - lo * amp)]
                    if pts:
                        qp.drawLines(pts)
        if self._g and "b" in self._g:
            col = tok("dirty_border", "#e0a040")
            col.setAlpha(90)
            y = self._g["lane"] * LANE_H
            a, b = sorted((self._g["a"], self._g["b"]))
            qp.fillRect(QRectF(self.tl.x_of(a), y, self.tl.x_of(b) - self.tl.x_of(a), LANE_H), col)
        qp.end()

    def mousePressEvent(self, e) -> None:
        t = self.track()
        if t is None or e.position().x() < HEADER_W:
            return
        i = int(e.position().y() // LANE_H)
        if 0 <= i < len(t.takes):
            s = self.tl.snap(self.tl.sample_at(e.position().x()))
            self._g = {"lane": i, "a": s, "b": s}

    def mouseMoveEvent(self, e) -> None:
        if self._g is not None:
            self._g["b"] = self.tl.snap(self.tl.sample_at(e.position().x()))
            self.update()

    def mouseReleaseEvent(self, e) -> None:
        g, self._g = self._g, None
        t = self.track()
        if g is None or t is None:
            return
        a, b = sorted((g["a"], g["b"]))
        if b - a > 0:
            set_comp(self.s.project, t.id, t.takes[g["lane"]]["id"], a, b, xfade=self.s.project.sample_rate // 100)
        self.update()

    def keyPressEvent(self, e) -> None:
        if e.key() == Qt.Key_Escape:            # annule le geste, ne quitte pas le module
            self._g = None
            self.update()
            return
        super().keyPressEvent(e)


class TakesPanel(QWidget):
    def __init__(self, timeline, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        bar.addWidget(label("Prises", "row_label"))
        self.lanes = TakeLanes(timeline)
        bar.addWidget(button("Superposer (looper)", "Toutes les prises jouent ensemble", self.stack))
        bar.addWidget(button("Vider le comp", "Revenir à la dernière prise posée sur la piste", self.clear))
        bar.addStretch(1)
        lay.addLayout(bar)
        lay.addWidget(self.lanes)

    def stack(self) -> None:
        t = self.lanes.track()
        if t is not None and t.takes:
            stack_loop_takes(self.lanes.s.project, t.id)

    def clear(self) -> None:
        t = self.lanes.track()
        if t is None or not t.takes:
            return
        p = self.lanes.s.project
        with p.edit("Vider le comp", t.id):
            t.comp = []
            from fm_audio_engine.project import Clip
            last = t.takes[-1]["clips"][0]
            t.clips = [c for c in t.clips if not c.take] + [Clip.from_dict(last.to_dict())]
