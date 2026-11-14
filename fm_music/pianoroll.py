"""Piano roll de FM Music : notes d'un clip MIDI (ou de son pattern), vélocités, grille.

Gestes : clic dans le vide = nouvelle note (longueur de grille) ; Ctrl + glisser une note = la
déplacer (Ctrl AU DÉPART, règle de l'appli) ; glisser le bord droit = longueur ; clic = choisir
(Maj : ajouter) ; zone basse = vélocités (glisser). Clavier : Q quantifier, Maj+Q annuler la
quantification, Haut / Bas transposer (Maj : octave), Suppr, Ctrl+A, Échap (annule le geste puis
la sélection, ne quitte jamais le module). Peinture bornée aux notes visibles du clip.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import QApplication, QWidget

from fm_audio_engine import midi
from fm_audio_engine.project import PPQ, Note
from fm_sound_ui.ui_kit import tok

KEYS_W = 46
VEL_H = 56
BLACK = {1, 3, 6, 8, 10}
NAMES = ("do", "do#", "ré", "ré#", "mi", "fa", "fa#", "sol", "sol#", "la", "la#", "si")


class PianoRoll(QWidget):
    edited = Signal()

    def __init__(self, session, parent=None):
        super().__init__(parent)
        self.s = session
        self.track_id: str | None = None
        self.clip_id: str | None = None
        self.tpp = PPQ / 48            # ticks par pixel
        self.t0 = 0.0
        self.row_h = 12
        self.top_pitch = 96
        self.grid = PPQ // 4
        self.sel: set[int] = set()     # indices des notes
        self._g = None
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)
        self.setMinimumHeight(180)
        self.s.changed.connect(self.update)

    # ---------------------------------------------------------------- données
    def set_clip(self, track_id: str, clip_id: str) -> None:
        self.track_id, self.clip_id = track_id, clip_id
        self.sel.clear()
        notes = self.notes()
        if notes:
            mid = sorted(n.pitch for n in notes)[len(notes) // 2]
            self.top_pitch = min(127, mid + max(6, (self.height() - VEL_H) // self.row_h // 2))
        self.t0 = 0
        self.update()

    def clip(self):
        t = self.s.project.track(self.track_id) if self.track_id else None
        if t is None:
            return None, None
        return t, next((m for m in t.midi_clips if m.id == self.clip_id), None)

    def notes(self) -> list:
        t, m = self.clip()
        if m is None:
            return []
        if m.pattern:
            p = self.s.project.patterns.get(m.pattern)
            return p["notes"] if p else []
        return m.notes

    def length(self) -> int:
        t, m = self.clip()
        if m is None:
            return 0
        if m.pattern:
            return int(self.s.project.patterns.get(m.pattern, {}).get("length_tick", m.length_tick))
        return m.length_tick

    def edit(self, label: str):
        return self.s.project.edit(label, self.track_id, structure=bool(self.clip()[1] and self.clip()[1].pattern))

    # ---------------------------------------------------------------- géométrie
    def x_of(self, tick: float) -> float:
        return KEYS_W + (tick - self.t0) / self.tpp

    def tick_at(self, x: float) -> float:
        return self.t0 + (x - KEYS_W) * self.tpp

    def y_of(self, pitch: int) -> float:
        return (self.top_pitch - pitch) * self.row_h

    def pitch_at(self, y: float) -> int:
        return int(self.top_pitch - y // self.row_h)

    def snap(self, tick: float) -> int:
        return int(round(tick / self.grid) * self.grid)

    def roll_h(self) -> int:
        return self.height() - VEL_H

    def hit(self, x: float, y: float):
        tk, p = self.tick_at(x), self.pitch_at(y)
        for i, n in reversed(list(enumerate(self.notes()))):
            if n.pitch == p and n.tick <= tk <= n.tick + n.length:
                edge = abs(self.x_of(n.tick + n.length) - x) <= 5
                return i, ("resize" if edge else "body")
        return None, None

    # ---------------------------------------------------------------- peinture
    def paintEvent(self, _e) -> None:
        qp = QPainter(self)
        w, rh = self.width(), self.roll_h()
        qp.fillRect(self.rect(), tok("panel_bg", "#202226"))
        t, m = self.clip()
        if m is None:
            qp.setPen(tok("label_dim", "#999"))
            qp.drawText(self.rect(), Qt.AlignCenter, "Double-clic sur un clip MIDI de l'arrangement pour l'éditer ici")
            qp.end()
            return
        rows = rh // self.row_h + 1
        for k in range(rows):
            p = self.top_pitch - k
            y = k * self.row_h
            qp.fillRect(QRectF(KEYS_W, y, w - KEYS_W, self.row_h), tok("table_row_b" if p % 12 in BLACK else "table_row_a", "#26282c"))
            qp.fillRect(QRectF(0, y, KEYS_W, self.row_h), tok("field_bg" if p % 12 in BLACK else "value_fg", "#ccc"))
            if p % 12 == 0:
                qp.setPen(tok("panel_bg", "#222"))
                qp.drawText(QRectF(2, y, KEYS_W - 4, self.row_h), Qt.AlignRight | Qt.AlignVCenter, f"do{p // 12 - 1}")
        # grille
        L = self.length()
        tm = self.s.project.tempo_map()
        bar = tm.bar_ticks(0)
        k = int(self.t0 // self.grid) * self.grid
        end_tick = self.tick_at(w)
        while k <= end_tick:
            x = self.x_of(k)
            col = tok("panel_border" if k % bar else "label_dim", "#444")
            qp.setPen(QPen(col, 1))
            qp.drawLine(QPointF(x, 0), QPointF(x, rh))
            k += self.grid
        qp.fillRect(QRectF(self.x_of(L), 0, max(0, w - self.x_of(L)), rh), tok("toolbar_bg", "#151515"))
        # notes visibles
        acc = tok("accent", "#3d8bfd")
        sel_col = tok("dirty_border", "#e0a040")
        g = self._g
        for i, n in enumerate(self.notes()):
            tick, length, pitch = n.tick, n.length, n.pitch
            if g and i in g.get("idx", ()):
                if g["kind"] == "move":
                    tick, pitch = max(0, tick + g["dt"]), max(0, min(127, pitch + g["dp"]))
                elif g["kind"] == "resize":
                    length = max(self.grid // 4, length + g["dt"])
            x1, x2 = self.x_of(tick), self.x_of(tick + length)
            if x2 < KEYS_W or x1 > w:
                continue
            y = self.y_of(pitch)
            if y < -self.row_h or y > rh:
                continue
            col = sel_col if i in self.sel else acc
            c2 = col.lighter(100 + int(n.vel / 127 * 40))
            qp.fillRect(QRectF(x1, y + 1, max(2.0, x2 - x1), self.row_h - 2), c2)
            if n.orig_tick is not None:          # quantifiée : origine rappelée
                qp.setPen(QPen(tok("label_dim", "#999"), 1, Qt.DotLine))
                ox = self.x_of(n.orig_tick)
                qp.drawLine(QPointF(ox, y + 2), QPointF(ox, y + self.row_h - 2))
        # vélocités
        vy = rh
        qp.fillRect(QRectF(0, vy, w, VEL_H), tok("toolbar_bg", "#18191b"))
        qp.setPen(tok("label_dim", "#999"))
        qp.drawText(QRectF(2, vy, KEYS_W - 4, VEL_H), Qt.AlignCenter, "vél.")
        for i, n in enumerate(self.notes()):
            x = self.x_of(n.tick)
            if KEYS_W <= x <= w:
                hgt = (VEL_H - 6) * n.vel / 127
                qp.fillRect(QRectF(x, vy + VEL_H - 3 - hgt, 3, hgt), sel_col if i in self.sel else acc)
        if self.s.playing:
            t_, m_ = self.clip()
            pos = self.s.project.tempo_map().sample_to_tick(self.s.position) - m_.start_tick
            if m_.pattern and L:
                pos %= L
            x = self.x_of(pos)
            qp.setPen(QPen(tok("accent", "#3d8bfd"), 1.5))
            qp.drawLine(QPointF(x, 0), QPointF(x, self.height()))
        qp.end()

    # ---------------------------------------------------------------- souris
    def mousePressEvent(self, e) -> None:
        self.setFocus()
        if self.clip()[1] is None or e.button() != Qt.LeftButton:
            return
        x, y = e.position().x(), e.position().y()
        ctrl = bool(QApplication.keyboardModifiers() & Qt.ControlModifier)
        if y >= self.roll_h():
            self._g = {"kind": "vel"}
            self._set_vel(x, y)
            return
        if x < KEYS_W:
            self.audition(self.pitch_at(y))
            return
        i, zone = self.hit(x, y)
        if i is None:
            tick = max(0, int(self.tick_at(x) // self.grid) * self.grid)      # case de grille cliquée
            p = self.pitch_at(y)
            if tick >= self.length():
                return
            with self.edit("Ajouter une note"):
                self.notes().append(Note(tick, self.grid, p, 100))
            self.sel = {len(self.notes()) - 1}
            self.audition(p)
            self._g = {"kind": "resize", "idx": set(self.sel), "x": x, "dt": 0}
            self.update()
            return
        if not (e.modifiers() & Qt.ShiftModifier) and i not in self.sel:
            self.sel = set()
        self.sel.add(i)
        if zone == "resize":
            self._g = {"kind": "resize", "idx": set(self.sel), "x": x, "dt": 0}
        elif ctrl:
            self._g = {"kind": "move", "idx": set(self.sel), "x": x, "y": y, "dt": 0, "dp": 0}
        self.audition(self.notes()[i].pitch)
        self.update()

    def _set_vel(self, x: float, y: float) -> None:
        v = int(max(1, min(127, (self.height() - 3 - y) / (VEL_H - 6) * 127)))
        tk = self.tick_at(x)
        notes = self.notes()
        best = min(range(len(notes)), key=lambda k: abs(notes[k].tick - tk), default=None)
        if best is None or abs(self.x_of(notes[best].tick) - x) > 6:
            return
        targets = self.sel if best in self.sel else {best}
        g = self._g
        g.setdefault("before", {k: notes[k].vel for k in targets})
        for k in targets:
            notes[k].vel = v
        self.update()

    def mouseMoveEvent(self, e) -> None:
        g = self._g
        if g is None:
            x, y = e.position().x(), e.position().y()
            i, zone = self.hit(x, y) if y < self.roll_h() else (None, None)
            self.setCursor(Qt.SizeHorCursor if zone == "resize" else Qt.ArrowCursor)
            return
        x, y = e.position().x(), e.position().y()
        if g["kind"] == "vel":
            self._set_vel(x, y)
        elif g["kind"] == "move":
            g["dt"] = int(round((x - g["x"]) * self.tpp / self.grid)) * self.grid
            g["dp"] = int(round((g["y"] - y) / self.row_h))
        elif g["kind"] == "resize":
            g["dt"] = int(round((x - g["x"]) * self.tpp / self.grid)) * self.grid
        self.update()

    def mouseReleaseEvent(self, e) -> None:
        g, self._g = self._g, None
        if g is None:
            return
        notes = self.notes()
        if g["kind"] == "vel" and "before" in g:
            after = {k: notes[k].vel for k in g["before"]}
            for k, v in g["before"].items():
                notes[k].vel = v           # état d'origine rétabli, puis modification enregistrée
            with self.edit("Vélocité"):
                for k, v in after.items():
                    notes[k].vel = v
        elif g["kind"] == "move" and (g["dt"] or g["dp"]):
            with self.edit("Déplacer des notes"):
                for k in g["idx"]:
                    n = notes[k]
                    n.tick = max(0, n.tick + g["dt"])
                    n.pitch = max(0, min(127, n.pitch + g["dp"]))
                    n.orig_tick = n.orig_length = None
        elif g["kind"] == "resize" and g["dt"]:
            with self.edit("Longueur des notes"):
                for k in g["idx"]:
                    notes[k].length = max(self.grid // 4, notes[k].length + g["dt"])
                    notes[k].orig_length = None
        self.edited.emit()
        self.update()

    def wheelEvent(self, e) -> None:
        d = e.angleDelta().y()
        if e.modifiers() & Qt.ControlModifier:
            at = self.tick_at(e.position().x())
            self.tpp = min(max(self.tpp * (0.8 if d > 0 else 1.25), 0.5), PPQ)
            self.t0 = max(0.0, at - (e.position().x() - KEYS_W) * self.tpp)
        elif e.modifiers() & Qt.ShiftModifier:
            self.t0 = max(0.0, self.t0 - d / 120 * 40 * self.tpp)
        else:
            self.top_pitch = int(max(12, min(127, self.top_pitch + d / 120 * 3)))
        self.update()

    def keyPressEvent(self, e) -> None:
        k, mods = e.key(), e.modifiers()
        notes = self.notes()
        targets = [notes[i] for i in sorted(self.sel)] or notes
        if k == Qt.Key_Escape:
            if self._g is not None:
                g, self._g = self._g, None
                if g["kind"] == "vel" and "before" in g:
                    for i, v in g["before"].items():
                        notes[i].vel = v
            else:
                self.sel.clear()
            self.update()
        elif k == Qt.Key_Q:
            with self.edit("Annuler la quantification" if mods & Qt.ShiftModifier else "Quantifier"):
                if mods & Qt.ShiftModifier:
                    midi.unquantize(targets)
                else:
                    swing = float((self.s.settings() or {}).get("music_swing", 0.0))
                    midi.quantize(targets, self.grid, swing=swing)
        elif k in (Qt.Key_Up, Qt.Key_Down) and self.sel:
            step = (12 if mods & Qt.ShiftModifier else 1) * (1 if k == Qt.Key_Up else -1)
            with self.edit("Transposer"):
                midi.transpose(targets, step)
        elif k in (Qt.Key_Delete, Qt.Key_Backspace) and self.sel:
            with self.edit("Supprimer des notes"):
                keep = [n for i, n in enumerate(notes) if i not in self.sel]
                notes[:] = keep
            self.sel.clear()
        elif (mods & Qt.ControlModifier) and k == Qt.Key_A:
            self.sel = set(range(len(notes)))
            self.update()
        elif (mods & Qt.ControlModifier) and k == Qt.Key_Z:
            self.s.project.history.undo()
        elif (mods & Qt.ControlModifier) and k == Qt.Key_Y:
            self.s.project.history.redo()
        elif k == Qt.Key_Space:
            self.s.toggle_play()
        else:
            super().keyPressEvent(e)

    def audition(self, pitch: int) -> None:
        """Écoute de la note (instrument de la piste) si le moteur est déjà actif ; jamais d'ouverture
        de périphérique imposée par un simple clic."""
        eng = self.s.engine
        if eng is None or not eng.alive() or self.s.device is None:
            return
        ids = [t.id for t in self.s.project.tracks]
        if self.track_id not in ids:
            return
        node = ids.index(self.track_id)
        try:
            eng.request("note", node=node, pitch=int(pitch), vel=100)
            from PySide6.QtCore import QTimer
            QTimer.singleShot(250, lambda: eng.alive() and eng.request("note", node=node, pitch=int(pitch), vel=0))
        except Exception:
            pass
