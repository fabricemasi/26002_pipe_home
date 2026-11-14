"""Mixer : une tranche par piste, par bus et pour le master ; faders, pan, mute / solo,
vu-mètres RÉELS (télémétrie du moteur, crêtes par nœud et réduction de gain).

Fluidité : un fader envoie la valeur au moteur sans reconstruire le graphe ; le modèle n'est
modifié qu'au relâchement (une étape d'annulation). Les vu-mètres lisent la dernière télémétrie.
"""
from __future__ import annotations

import math

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QHBoxLayout, QScrollArea, QSlider, QVBoxLayout, QWidget

from .ui_kit import button, label, tok

FADER_MIN_DB = -60.0
FADER_MAX_DB = 12.0


def db_to_slider(db: float) -> int:
    return int(round((min(FADER_MAX_DB, max(FADER_MIN_DB, db)) - FADER_MIN_DB) * 10))


def slider_to_db(v: int) -> float:
    db = FADER_MIN_DB + v / 10.0
    return -120.0 if db <= FADER_MIN_DB + 0.01 else db


class Meter(QWidget):
    """Crêtes gauche / droite (dBFS), maintien de crête, réduction de gain."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(14)
        self.level = [0.0, 0.0]
        self.hold = [0.0, 0.0]
        self.gr = 0.0

    def feed(self, vals) -> None:
        for c in (0, 1):
            v = float(vals[c]) if len(vals) > c else 0.0
            self.level[c] = max(v, self.level[c] * 0.82)     # retombée visuelle
            self.hold[c] = max(v, self.hold[c] * 0.995)
        self.gr = float(vals[2]) if len(vals) > 2 else 0.0
        self.update()

    @staticmethod
    def frac(v: float) -> float:
        if v <= 1e-6:
            return 0.0
        return max(0.0, min(1.0, (20 * math.log10(v) - FADER_MIN_DB) / (6 - FADER_MIN_DB)))

    def paintEvent(self, _e) -> None:
        qp = QPainter(self)
        h, w = self.height(), self.width()
        qp.fillRect(self.rect(), tok("field_bg", "#141518"))
        bw = (w - 3) / 2
        for c in (0, 1):
            f = self.frac(self.level[c])
            col = tok("dirty_dot", "#e05050") if self.level[c] >= 0.999 else tok("accent", "#3d8bfd")
            qp.fillRect(QRectF(1 + c * (bw + 1), h * (1 - f), bw, h * f), col)
            hy = h * (1 - self.frac(self.hold[c]))
            qp.fillRect(QRectF(1 + c * (bw + 1), hy, bw, 1.5), tok("value_fg", "#ddd"))
        if self.gr < -0.1:
            g = min(1.0, -self.gr / 24)
            qp.fillRect(QRectF(0, 0, w, h * g), tok("dirty_border", "#c08030"))
        qp.end()


class Strip(QWidget):
    def __init__(self, mixer, node_id: str, name: str, parent=None):
        super().__init__(parent)
        self.m = mixer
        self.node_id = node_id
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(4)
        self.name = label(name, "row_label")
        self.name.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.name)
        self.pan = QSlider(Qt.Horizontal)
        self.pan.setRange(-100, 100)
        self.pan.setToolTip("Pan (double-clic : centre)")
        lay.addWidget(self.pan)
        mid = QHBoxLayout()
        self.fader = QSlider(Qt.Vertical)
        self.fader.setRange(0, db_to_slider(FADER_MAX_DB))
        self.fader.setMinimumHeight(140)
        self.meter = Meter()
        mid.addWidget(self.fader)
        mid.addWidget(self.meter)
        lay.addLayout(mid, 1)
        self.db = label("", "row_note")
        self.db.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.db)
        row = QHBoxLayout()
        self.mute = button("M", "Couper", checkable=True)
        self.solo = button("S", "Solo", checkable=True)
        row.addWidget(self.mute)
        row.addWidget(self.solo)
        lay.addLayout(row)
        self.fader.valueChanged.connect(self._live_gain)
        self.fader.sliderReleased.connect(self._commit)
        self.pan.valueChanged.connect(self._live_pan)
        self.pan.sliderReleased.connect(self._commit)
        self.mute.toggled.connect(lambda on: self._flag("mute", on))
        self.solo.toggled.connect(lambda on: self._flag("solo", on))
        self.setFixedWidth(84)

    def obj(self):
        p = self.m.s.project
        return p.track(self.node_id) or p.bus(self.node_id)

    def sync(self) -> None:
        o = self.obj()
        if o is None:
            return
        for w, v in ((self.fader, db_to_slider(o.gain_db)), (self.pan, int(round(o.pan * 100)))):
            w.blockSignals(True)
            w.setValue(v)
            w.blockSignals(False)
        self.db.setText(f"{o.gain_db:+.1f} dB" if o.gain_db > -119 else "-∞")
        for b, v in ((self.mute, getattr(o, "mute", False)), (self.solo, getattr(o, "solo", False))):
            b.blockSignals(True)
            b.setChecked(bool(v))
            b.blockSignals(False)
        self.solo.setVisible(hasattr(o, "solo"))

    def _live_gain(self, v: int) -> None:
        db = slider_to_db(v)
        self.db.setText(f"{db:+.1f} dB" if db > -119 else "-∞")
        self.m.s.set_node(self.node_id, "gain_db", db)
        if not self.fader.isSliderDown():
            self._commit()

    def _live_pan(self, v: int) -> None:
        self.m.s.set_node(self.node_id, "pan", v / 100.0)
        if not self.pan.isSliderDown():
            self._commit()

    def _commit(self) -> None:
        o = self.obj()
        if o is None:
            return
        db, pan = slider_to_db(self.fader.value()), self.pan.value() / 100.0
        if abs(o.gain_db - db) < 1e-6 and abs(o.pan - pan) < 1e-6:
            return
        p = self.m.s.project
        self.m.committing = True
        try:
            with p.edit("Mixer", *([self.node_id] if p.track(self.node_id) else []), structure=p.track(self.node_id) is None):
                o.gain_db, o.pan = db, pan
        finally:
            self.m.committing = False

    def _flag(self, attr: str, on: bool) -> None:
        o = self.obj()
        p = self.m.s.project
        with p.edit(f"Mixer : {attr}", *([self.node_id] if p.track(self.node_id) else []), structure=p.track(self.node_id) is None):
            setattr(o, attr, bool(on))
        self.m.s.set_node(self.node_id, attr, 1.0 if on else 0.0)

    # ---- routage (clic droit sur la tranche) : sortie, envois pré / post, sidechain
    def contextMenuEvent(self, e) -> None:
        from .ui_kit import menu
        p = self.m.s.project
        o = self.obj()
        if o is None or self.node_id == "master":
            return
        m = menu(self)
        acts = {}
        out = m.addMenu("Sortie")
        for bid, name in [("master", "Master")] + [(b.id, b.name) for b in p.buses if b.id != self.node_id]:
            a = out.addAction(name)
            a.setCheckable(True)
            a.setChecked(o.output == bid)
            acts[a] = ("output", bid)
        snd = m.addMenu("Envoi vers")
        for b in p.buses:
            if b.id != self.node_id:
                acts[snd.addAction(f"{b.name} (post-fader)")] = ("send", b.id, False)
                acts[snd.addAction(f"{b.name} (pré-fader)")] = ("send", b.id, True)
        for k, s in enumerate(o.sends):
            acts[m.addAction(f"Retirer l'envoi vers {s['target']}")] = ("unsend", k)
        comp = next((i for i, f in enumerate(o.fx) if f.type in ("compressor", "gate")), None)
        if comp is not None:
            sc = m.addMenu("Sidechain de " + o.fx[comp].type)
            for t in p.tracks:
                if t.id != self.node_id:
                    acts[sc.addAction(t.name)] = ("sidechain", comp, t.id)
            acts[sc.addAction("Aucun")] = ("sidechain", comp, "")
        what = acts.get(m.exec(e.globalPos()))
        if what:
            route(p, self.node_id, *what)

    def mouseDoubleClickEvent(self, e) -> None:
        if self.pan.geometry().contains(e.position().toPoint()):
            self.pan.setValue(0)
            self._commit()


class MixerPanel(QWidget):
    def __init__(self, session, parent=None):
        super().__init__(parent)
        self.s = session
        self.committing = False
        self.strips: dict[str, Strip] = {}
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.area = QScrollArea()
        self.area.setWidgetResizable(True)
        self.area.setFrameShape(QScrollArea.NoFrame)
        outer.addWidget(self.area)
        self.host = QWidget()
        self.row = QHBoxLayout(self.host)
        self.row.setContentsMargins(6, 6, 6, 6)
        self.row.setSpacing(6)
        self.area.setWidget(self.host)
        self.s.changed.connect(self.rebuild)
        self.s.tick.connect(self._meters)
        self.rebuild()

    def node_ids(self) -> list[tuple[str, str]]:
        p = self.s.project
        return [(t.id, t.name) for t in p.tracks] + [(b.id, b.name) for b in p.buses] + [("master", "Master")]

    def rebuild(self) -> None:
        ids = self.node_ids()
        if [k for k, _ in ids] != list(self.strips.keys()):
            for st in self.strips.values():
                st.setParent(None)
                st.deleteLater()
            self.strips.clear()
            while self.row.count():
                self.row.takeAt(0)
            for nid, name in ids:
                st = Strip(self, nid, name, self.host)
                self.strips[nid] = st
                self.row.addWidget(st)
            self.row.addStretch(1)
        for nid, name in ids:
            self.strips[nid].name.setText(name)
            if not self.committing:
                self.strips[nid].sync()

    def _meters(self, t: dict) -> None:
        if not self.isVisible():
            return
        meters = t.get("meters") or {}
        for nid, st in self.strips.items():
            vals = meters.get(nid)
            if vals is not None:
                st.meter.feed(vals)


def route(project, node_id: str, action: str, *args) -> None:
    """Routage d'une piste ou d'un bus (une étape d'annulation). Le moteur refuse les cycles :
    une sortie qui créerait une boucle est ignorée ici aussi."""
    is_track = project.track(node_id) is not None
    o = project.track(node_id) or project.bus(node_id)

    def creates_cycle(target: str) -> bool:
        seen, cur = set(), target
        while cur and cur != "master" and cur not in seen:
            if cur == node_id:
                return True
            seen.add(cur)
            b = project.bus(cur)
            cur = b.output if b else None
        return False
    with project.edit(f"Routage : {action}", *([node_id] if is_track else []), structure=not is_track):
        if action == "output":
            if not creates_cycle(args[0]):
                o.output = args[0]
        elif action == "send":
            if not creates_cycle(args[0]):
                o.sends.append({"target": args[0], "gain_db": -6.0, "pre": bool(args[1])})
        elif action == "unsend":
            del o.sends[args[0]]
        elif action == "sidechain":
            idx, src = args
            o.fx[idx].sidechain = src
            o.fx[idx].params["sidechain"] = 1 if src else 0