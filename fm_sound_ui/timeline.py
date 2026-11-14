"""Timeline commune (FM Audio : montage ; FM Music : arrangement) : pistes, clips audio avec
waveform, clips MIDI, règle (temps ou mesures), tête de lecture, sélection, gestes.

Fluidité : la peinture ne lit que des pyramides de pics déjà calculées (travail borné par la
largeur visible) et ne questionne jamais le moteur. Les gestes modifient un APERÇU ; le
modèle n'est modifié qu'au relâchement (une seule étape d'annulation).
Règles de l'appli : déplacer un clip exige Ctrl au départ du geste ; Échap annule (geste,
sélection) sans jamais quitter le module.
"""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QApplication, QWidget

from fm_audio_engine import edits
from fm_audio_engine.project import PPQ

from .ui_kit import fmt_time, tok

HEADER_W = 168
RULER_H = 26
TRACK_H = 84
EDGE = 6


class TimelineView(QWidget):
    selectionChanged = Signal()
    clipActivated = Signal(str, str)          # piste, clip (double-clic : piano roll / éditeur)
    trackSelected = Signal(str)

    def __init__(self, session, parent=None, music: bool = False):
        super().__init__(parent)
        self.s = session
        self.music = music
        self.spp = 1024.0                    # échantillons par pixel
        self.x0 = 0.0                        # échantillon au bord gauche
        self.y0 = 0                          # défilement vertical (px)
        self.track_h = TRACK_H
        self.sel: tuple[int, int] | None = None
        self.sel_tracks: set[str] = set()
        self.sel_clips: set[tuple[str, str]] = set()
        self.current_track: str | None = None
        self.clipboard: dict | None = None
        self._g: dict | None = None          # geste en cours
        self.snap_on = music
        self.auto_target: str | None = None    # couloir d'automation affiché sur la piste courante
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)
        self.setMinimumHeight(160)
        self.s.changed.connect(self.update)
        self.s.mediaReady.connect(self._media_ready)      # méthode liée : déconnectée à la destruction
        self.s.tick.connect(self._on_tick)

    # ---------------------------------------------------------------- géométrie
    @property
    def p(self):
        return self.s.project

    def lane_w(self) -> int:
        return max(1, self.width() - HEADER_W)

    def x_of(self, sample: float) -> float:
        return HEADER_W + (sample - self.x0) / self.spp

    def sample_at(self, x: float) -> int:
        return int(round(self.x0 + (x - HEADER_W) * self.spp))

    def track_at(self, y: float):
        if y < RULER_H:
            return None
        i = int((y - RULER_H + self.y0) // self.track_h)
        return self.p.tracks[i] if 0 <= i < len(self.p.tracks) else None

    def track_y(self, index: int) -> int:
        return RULER_H + index * self.track_h - self.y0

    def snap(self, sample: int, force: bool | None = None) -> int:
        on = self.snap_on if force is None else force
        if not on:
            return sample
        tm = self.p.tempo_map()
        grid = PPQ // 4                       # double croche
        tick = round(tm.sample_to_tick(sample) / grid) * grid
        return tm.tick_to_sample(int(tick))

    def zoom(self, factor: float, anchor_x: float | None = None) -> None:
        ax = anchor_x if anchor_x is not None else HEADER_W + self.lane_w() / 2
        at = self.x0 + (ax - HEADER_W) * self.spp
        self.spp = min(max(self.spp * factor, 0.05), 1 << 20)   # jusqu'à l'échantillon (et au-delà)
        self.x0 = max(0.0, at - (ax - HEADER_W) * self.spp)
        self.update()

    def zoom_fit(self) -> None:
        end = max(self.p.length_samples(), self.p.sample_rate * 10)
        self.spp = max(0.05, end / max(1, self.lane_w() - 20))
        self.x0 = 0
        self.update()

    def ensure_visible(self, sample: int) -> None:
        if not (self.x0 <= sample <= self.x0 + self.lane_w() * self.spp * 0.95):
            self.x0 = max(0.0, sample - self.lane_w() * self.spp * 0.1)

    def _media_ready(self, _path: str) -> None:
        self.update()

    def _on_tick(self, t: dict) -> None:
        if self.s.playing:
            self.ensure_visible(self.s.position)
            self.update()

    # ---------------------------------------------------------------- peinture
    def paintEvent(self, _e) -> None:
        qp = QPainter(self)
        qp.fillRect(self.rect(), tok("panel_bg", "#202226"))
        w, h = self.width(), self.height()
        lane0 = self.sample_at(HEADER_W)
        lane1 = self.sample_at(w)
        f = QFont(self.font())
        f.setPointSizeF(max(7.0, f.pointSizeF() * 0.9))
        qp.setFont(f)
        first = max(0, self.y0 // self.track_h)
        last = min(len(self.p.tracks), (self.y0 + h - RULER_H) // self.track_h + 1)
        for i in range(first, last):
            t = self.p.tracks[i]
            y = self.track_y(i)
            lane = QRectF(HEADER_W, y, w - HEADER_W, self.track_h)
            qp.fillRect(lane, tok("table_row_a" if i % 2 == 0 else "table_row_b", "#26282c"))
            for c in t.clips:
                self._paint_clip(qp, t, c, y, lane0, lane1)
            for m in t.midi_clips:
                self._paint_midi(qp, t, m, y, lane0, lane1)
            self._paint_header(qp, t, i, y)
            if self.auto_target and t.id == self.current_track:
                self._paint_auto(qp, t, y)
        # sélection
        if self.sel:
            a, b = self.sel
            x1, x2 = self.x_of(a), self.x_of(b)
            col = tok("accent", "#3d8bfd")
            col.setAlpha(50)
            for i, t in enumerate(self.p.tracks):
                if not self.sel_tracks or t.id in self.sel_tracks:
                    qp.fillRect(QRectF(x1, self.track_y(i), x2 - x1, self.track_h), col)
        self._paint_ruler(qp, lane0, lane1)
        # tête de lecture et curseur
        pos = self.s.position if self.s.playing else self.s.cursor
        x = self.x_of(pos)
        if HEADER_W <= x <= w:
            qp.setPen(QPen(tok("accent", "#3d8bfd"), 1.5))
            qp.drawLine(QPointF(x, 0), QPointF(x, h))
        if self.s.recording:
            qp.setPen(QPen(tok("dirty_dot", "#e05050"), 2))
            qp.drawRect(QRectF(1, 1, w - 2, h - 2))
        qp.end()

    def _clip_preview(self, t, c) -> tuple[int, int, int]:
        """(début, longueur, décalage de piste) affichés, geste en cours compris."""
        g = self._g
        start, length = c.start, c.length
        if g and (t.id, c.id) in g.get("items", ()):
            if g["kind"] == "move":
                start += g.get("delta", 0)
            elif g["kind"] == "trim_l":
                d = g.get("delta", 0)
                start, length = start + d, length - d
            elif g["kind"] == "trim_r":
                length += g.get("delta", 0)
        return start, max(1, length), 0

    def _paint_clip(self, qp, t, c, y, lane0, lane1) -> None:
        start, length, _ = self._clip_preview(t, c)
        if start > lane1 or start + length < lane0:
            return
        x1, x2 = self.x_of(start), self.x_of(start + length)
        r = QRectF(max(x1, HEADER_W), y + 2, min(x2, self.width()) - max(x1, HEADER_W), self.track_h - 4)
        if self._g and self._g["kind"] == "move" and (t.id, c.id) in self._g["items"] and self._g.get("track_shift"):
            r.translate(0, self._g["track_shift"] * self.track_h)
        sel = (t.id, c.id) in self.sel_clips
        bg = tok("track_bg", "#30343a")
        if c.mute:
            bg.setAlpha(110)
        qp.fillRect(r, bg)
        qp.setPen(QPen(tok("accent" if sel else "panel_border", "#556"), 1.5 if sel else 1))
        qp.drawRect(r)
        err = self.s.media_errors.get(c.path)
        pk = self.s.peaks.get(c.path)
        wave = tok("value_fg", "#c8ccd2")
        if pk is not None and r.width() > 1:
            n = pk.channels
            vis0 = max(start, lane0)
            px0 = int(self.x_of(vis0))
            width = int(r.width())
            mspp = self.spp * c.rate
            if c.reverse:   # lecture à l'envers : vue miroir du média
                mend = c.offset + (start + length - vis0) * c.rate
                mins, maxs = pk.view(mend - width * mspp, mspp, width)
                mins, maxs = mins[:, ::-1], maxs[:, ::-1]
            else:
                mins, maxs = pk.view(c.offset + (vis0 - start) * c.rate, mspp, width)
            g = 10 ** (c.gain_db / 20)
            ch_h = (r.height() - 14) / n
            qp.setPen(QPen(wave, 1))
            for ch in range(n):
                mid = r.top() + 14 + ch_h * (ch + 0.5)
                amp = ch_h / 2 * 0.95
                lines = []
                for k in range(width):
                    lo, hi = mins[ch, k], maxs[ch, k]
                    if lo != lo:          # NaN : hors média
                        continue
                    if c.polarity:
                        lo, hi = -hi, -lo
                    lines.append(QPointF(px0 + k, mid - min(1, hi * g) * amp))
                    lines.append(QPointF(px0 + k, mid - max(-1, lo * g) * amp))
                if lines:
                    qp.drawLines(lines)
        # fondus
        qp.setPen(QPen(tok("accent", "#3d8bfd"), 1))
        if c.fade_in:
            qp.drawLine(QPointF(x1, r.bottom()), QPointF(self.x_of(start + c.fade_in), r.top() + 14))
        if c.fade_out:
            qp.drawLine(QPointF(self.x_of(start + length - c.fade_out), r.top() + 14), QPointF(x2, r.bottom()))
        qp.setPen(tok("row_label", "#ddd"))
        name = c.name or (c.path.replace("\\", "/").rsplit("/", 1)[-1] if c.path else "clip")
        extra = f"  {c.gain_db:+.1f} dB" if abs(c.gain_db) > 0.05 else ""
        if err:
            extra += "  ⚠ " + ("média absent" if "absent" in err else "illisible")
        elif pk is None and c.path:
            extra += "  …"
        qp.drawText(QRectF(r.left() + 4, r.top() + 1, max(0, r.width() - 6), 13), Qt.AlignLeft | Qt.AlignVCenter, name + extra)

    def _paint_midi(self, qp, t, m, y, lane0, lane1) -> None:
        tm = self.p.tempo_map()
        s0, s1 = tm.tick_to_sample(m.start_tick), tm.tick_to_sample(m.end_tick)
        if s0 > lane1 or s1 < lane0:
            return
        x1, x2 = self.x_of(s0), self.x_of(s1)
        r = QRectF(max(x1, HEADER_W), y + 2, min(x2, self.width()) - max(x1, HEADER_W), self.track_h - 4)
        sel = (t.id, m.id) in self.sel_clips
        qp.fillRect(r, tok("track_bg", "#30343a"))
        qp.setPen(QPen(tok("accent" if sel else "panel_border", "#556"), 1.5 if sel else 1))
        qp.drawRect(r)
        from fm_audio_engine.project import pattern_notes
        notes = pattern_notes(self.p, m)
        if notes:
            lo = min(n.pitch for n in notes)
            hi = max(n.pitch for n in notes)
            span = max(12, hi - lo + 1)
            nh = max(1.5, (r.height() - 16) / span)
            qp.setPen(Qt.NoPen)
            qp.setBrush(tok("accent", "#3d8bfd"))
            for n in notes:            # borné : seules les notes du clip visible
                a = self.x_of(tm.tick_to_sample(m.start_tick + n.tick))
                b = self.x_of(tm.tick_to_sample(m.start_tick + n.tick + n.length))
                if b < HEADER_W or a > self.width():
                    continue
                yy = r.bottom() - 2 - (n.pitch - lo + 1) * nh
                qp.drawRect(QRectF(a, yy, max(1.0, b - a), max(1.0, nh - 0.5)))
        qp.setPen(tok("row_label", "#ddd"))
        label = m.name or (self.p.patterns.get(m.pattern, {}).get("name") if m.pattern else "") or "MIDI"
        qp.drawText(QRectF(r.left() + 4, r.top() + 1, max(0, r.width() - 6), 13), Qt.AlignLeft | Qt.AlignVCenter, label)

    def _header_buttons(self, y: int) -> list:
        from PySide6.QtCore import QRect
        size = 18
        return [(key, QRect(8 + k * (size + 4), y + self.track_h - size - 8, size, size))
                for k, key in enumerate(("M", "S", "R", "I"))]

    def _paint_header(self, qp, t, i, y) -> None:
        from fm_theme.style import painted_button_look
        rect = QRectF(0, y, HEADER_W, self.track_h)
        qp.fillRect(rect, tok("toolbar_bg", "#1c1d20"))
        sel = t.id == self.current_track
        qp.setPen(QPen(tok("accent" if sel else "panel_border", "#444"), 1))
        qp.drawLine(QPointF(0, y + self.track_h - 0.5), QPointF(self.width(), y + self.track_h - 0.5))
        qp.setPen(tok("row_label", "#ddd"))
        qp.drawText(QRectF(8, y + 4, HEADER_W - 12, 16), Qt.AlignLeft | Qt.AlignVCenter, t.name)
        qp.setPen(tok("label_dim", "#999"))
        info = f"{t.gain_db:+.1f} dB  pan {t.pan:+.2f}" + ("  " + (t.instrument or {}).get("type", "") if t.instrument else "")
        qp.drawText(QRectF(8, y + 20, HEADER_W - 12, 14), Qt.AlignLeft | Qt.AlignVCenter, info)
        states = {"M": t.mute, "S": t.solo, "R": t.armed, "I": t.monitor}
        for key, br in self._header_buttons(y):
            look = painted_button_look("checked" if states[key] else "standard")
            qp.setPen(QPen(look["line"], 1))
            qp.setBrush(look["bg"] if not (key == "R" and states[key]) else tok("dirty_dot", "#d04040"))
            qp.drawRoundedRect(br, look["radius"], look["radius"])
            qp.setPen(look["fg"])
            qp.drawText(br, Qt.AlignCenter, key)
        qp.setBrush(Qt.NoBrush)

    def _paint_ruler(self, qp, lane0, lane1) -> None:
        w = self.width()
        qp.fillRect(QRectF(0, 0, w, RULER_H), tok("titlebar_bg", "#18191b"))
        lp = self.p.loop
        if lp.get("end", 0) > lp.get("start", 0):
            col = tok("accent", "#3d8bfd")
            col.setAlpha(110 if lp.get("on") else 45)
            qp.fillRect(QRectF(self.x_of(lp["start"]), 0, self.x_of(lp["end"]) - self.x_of(lp["start"]), 6), col)
        qp.setPen(tok("label_dim", "#999"))
        sr = self.p.sample_rate
        if self.music:
            tm = self.p.tempo_map()
            t0, t1 = tm.sample_to_tick(max(0, lane0)), tm.sample_to_tick(max(0, lane1))
            bar = tm.bar_ticks(0)
            px_per_bar = (tm.tick_to_sample(bar) - tm.tick_to_sample(0)) / self.spp
            step = bar * max(1, 2 ** math.ceil(math.log2(max(1.0, 60 / max(px_per_bar, 1e-6)))))
            k = int(t0 // step) * step
            while k <= t1:
                x = self.x_of(tm.tick_to_sample(int(k)))
                b, _, _ = tm.bar_beat(int(k))
                qp.drawLine(QPointF(x, RULER_H - 8), QPointF(x, RULER_H))
                qp.drawText(QPointF(x + 3, RULER_H - 10), str(b))
                k += step
        else:
            secs_px = self.spp / sr
            steps = (0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1, 2, 5, 10, 30, 60, 300, 600)
            step = next((s for s in steps if s / secs_px >= 80), 600)
            k = math.floor(max(0, lane0) / sr / step) * step
            while k * sr <= lane1:
                x = self.x_of(k * sr)
                qp.drawLine(QPointF(x, RULER_H - 8), QPointF(x, RULER_H))
                qp.drawText(QPointF(x + 3, RULER_H - 10), fmt_time(int(k * sr), sr) if step < 1 else f"{int(k // 60)}:{int(k % 60):02d}")
                k += step
        qp.setPen(tok("panel_border", "#444"))
        qp.drawLine(QPointF(0, RULER_H - 0.5), QPointF(w, RULER_H - 0.5))

    # ---------------------------------------------------------------- souris
    def _hit_clip(self, t, x: float, y: float):
        s = self.sample_at(x)
        for c in reversed(t.clips):
            if c.start <= s <= c.end:
                x1, x2 = self.x_of(c.start), self.x_of(c.end)
                ty = self.track_y(self.p.tracks.index(t))
                zone = "body"
                if abs(x - x1) <= EDGE:
                    zone = "trim_l"
                elif abs(x - x2) <= EDGE:
                    zone = "trim_r"
                elif y - ty < 16 and x - x1 < 12:
                    zone = "fade_in"
                elif y - ty < 16 and x2 - x < 12:
                    zone = "fade_out"
                return c, zone
        return None, None

    def _hit_midi(self, t, x: float):
        tm = self.p.tempo_map()
        s = self.sample_at(x)
        for m in reversed(t.midi_clips):
            if tm.tick_to_sample(m.start_tick) <= s <= tm.tick_to_sample(m.end_tick):
                return m
        return None

    def mousePressEvent(self, e) -> None:
        self.setFocus()
        x, y = e.position().x(), e.position().y()
        ctrl = bool(QApplication.keyboardModifiers() & Qt.ControlModifier)   # Ctrl AU DÉPART du geste
        if e.button() != Qt.LeftButton:
            return
        if y < RULER_H:
            pos = self.snap(self.sample_at(x))
            if e.modifiers() & Qt.ShiftModifier:
                self._g = {"kind": "loop", "a": pos, "b": pos}
            else:
                self.s.seek(pos)
                self._g = {"kind": "scrub"}
            self.update()
            return
        t = self.track_at(y)
        if t is None:
            self.sel = None
            self.sel_clips.clear()
            self.update()
            return
        if x < HEADER_W:
            i = self.p.tracks.index(t)
            for key, br in self._header_buttons(self.track_y(i)):
                if br.contains(int(x), int(y)):
                    self._toggle_header(t, key)
                    return
            self.current_track = t.id
            self.trackSelected.emit(t.id)
            self.update()
            return
        self.current_track = t.id
        if self.auto_target and self._auto_press(t, x, y, e, ctrl):
            return
        c, zone = self._hit_clip(t, x, y)
        m = self._hit_midi(t, x) if c is None else None
        if c is not None:
            if not (e.modifiers() & Qt.ShiftModifier) and (t.id, c.id) not in self.sel_clips:
                self.sel_clips.clear()
            self.sel_clips.add((t.id, c.id))
            if ctrl and zone == "body":
                self._g = {"kind": "move", "x": x, "y": y, "items": set(self.sel_clips), "delta": 0, "track_shift": 0}
            elif zone in ("trim_l", "trim_r"):
                self._g = {"kind": zone, "x": x, "items": {(t.id, c.id)}, "delta": 0}
            elif zone in ("fade_in", "fade_out"):
                self._g = {"kind": zone, "x": x, "item": (t.id, c.id), "value": c.fade_in if zone == "fade_in" else c.fade_out}
            else:
                self._start_range(t, x)
        elif m is not None:
            self.sel_clips = {(t.id, m.id)}
            if ctrl:
                self._g = {"kind": "move_midi", "x": x, "item": (t.id, m.id), "delta": 0}
            else:
                self._start_range(t, x)
        else:
            self.sel_clips.clear()
            self._start_range(t, x)
        self.selectionChanged.emit()
        self.update()

    def _start_range(self, t, x: float) -> None:
        pos = self.snap(self.sample_at(x))
        self.s.seek(pos)
        self.sel = None
        self.sel_tracks = {t.id}
        self._g = {"kind": "range", "a": pos, "track": t.id}

    def _toggle_header(self, t, key: str) -> None:
        attr = {"M": "mute", "S": "solo", "R": "armed", "I": "monitor"}[key]
        with self.p.edit(f"Piste : {attr}", t.id):
            setattr(t, attr, not getattr(t, attr))
        if attr in ("mute", "solo", "monitor"):
            self.s.set_node(t.id, attr, 1.0 if getattr(t, attr) else 0.0)
        self.update()

    def mouseMoveEvent(self, e) -> None:
        g = self._g
        x, y = e.position().x(), e.position().y()
        if g is None:
            t = self.track_at(y)
            cur = Qt.ArrowCursor
            if t is not None and x > HEADER_W:
                c, zone = self._hit_clip(t, x, y)
                if zone in ("trim_l", "trim_r"):
                    cur = Qt.SizeHorCursor
                elif zone in ("fade_in", "fade_out"):
                    cur = Qt.PointingHandCursor
            self.setCursor(cur)
            return
        k = g["kind"]
        if k == "auto_move":
            g["t"] = max(0, self.snap(self.sample_at(x)))
            g["v"] = self._auto_value(g["y0"], y)
            self.update()
            return
        if k == "scrub":
            self.s.seek(self.snap(self.sample_at(x)))
        elif k == "loop":
            g["b"] = self.snap(self.sample_at(x))
            a, b = sorted((g["a"], g["b"]))
            self.p.loop = {"on": True, "start": a, "end": b}
        elif k == "range":
            b = self.snap(self.sample_at(x))
            a = g["a"]
            self.sel = (min(a, b), max(a, b)) if abs(b - a) > 0 else None
            t = self.track_at(y)
            if t is not None:
                ids = [tt.id for tt in self.p.tracks]
                i0, i1 = sorted((ids.index(g["track"]), ids.index(t.id)))
                self.sel_tracks = set(ids[i0:i1 + 1])
        elif k in ("move", "trim_l", "trim_r", "move_midi"):
            delta = int((x - g["x"]) * self.spp)
            if self.snap_on and k == "move":
                tid, cid = next(iter(g["items"]))
                c = next(cc for cc in self.p.track(tid).clips if cc.id == cid)
                delta = self.snap(c.start + delta) - c.start
            g["delta"] = delta
            if k == "move":
                g["track_shift"] = int(round((y - g["y"]) / self.track_h))
        elif k in ("fade_in", "fade_out"):
            tid, cid = g["item"]
            c = next(cc for cc in self.p.track(tid).clips if cc.id == cid)
            d = int((x - g["x"]) * self.spp)
            g["new"] = max(0, min(c.length, g["value"] + (d if k == "fade_in" else -d)))
        self.update()

    def mouseReleaseEvent(self, e) -> None:
        g, self._g = self._g, None
        if g is None:
            return
        k = g["kind"]
        if k == "auto_move" and "t" in g:
            from . import automation
            automation.move_point(self.p, g["track"], self.auto_target, g["index"], g["t"], g["v"])
        if k == "move" and (g["delta"] or g["track_shift"]):
            items = list(g["items"])
            target = None
            if g["track_shift"] and len({tid for tid, _ in items}) == 1:
                ids = [t.id for t in self.p.tracks]
                j = ids.index(items[0][0]) + g["track_shift"]
                if 0 <= j < len(ids):
                    target = ids[j]
            edits.move_clips(self.p, items, g["delta"], target)
            if target:
                self.sel_clips = {(target, cid) for _, cid in items}
        elif k in ("trim_l", "trim_r") and g["delta"]:
            (tid, cid), = g["items"]
            c = next(cc for cc in self.p.track(tid).clips if cc.id == cid)
            if k == "trim_l":
                edits.trim(self.p, tid, cid, new_start=c.start + g["delta"])
            else:
                edits.trim(self.p, tid, cid, new_end=c.end + g["delta"])
        elif k in ("fade_in", "fade_out") and "new" in g:
            tid, cid = g["item"]
            edits.set_fades(self.p, tid, cid, **({"fade_in": g["new"]} if k == "fade_in" else {"fade_out": g["new"]}))
        elif k == "move_midi" and g["delta"]:
            tid, mid = g["item"]
            tm = self.p.tempo_map()
            t = self.p.track(tid)
            m = next(mm for mm in t.midi_clips if mm.id == mid)
            s0 = tm.tick_to_sample(m.start_tick)
            new_tick = int(round(tm.sample_to_tick(max(0, self.snap(s0 + g["delta"], True)))))
            with self.p.edit("Déplacer le clip MIDI", tid):
                m.start_tick = max(0, new_tick)
        elif k == "loop":
            self.s.schedule_reload()
        self.selectionChanged.emit()
        self.update()

    def mouseDoubleClickEvent(self, e) -> None:
        x, y = e.position().x(), e.position().y()
        t = self.track_at(y)
        if t is None or x < HEADER_W:
            return
        c, _ = self._hit_clip(t, x, y)
        m = self._hit_midi(t, x) if c is None else None
        if c is not None or m is not None:
            self.clipActivated.emit(t.id, (c or m).id)

    def wheelEvent(self, e) -> None:
        d = e.angleDelta().y() or e.angleDelta().x()
        mods = e.modifiers()
        if mods & Qt.ControlModifier:
            self.zoom(0.8 if d > 0 else 1.25, e.position().x())
        elif mods & Qt.ShiftModifier or e.angleDelta().x():
            self.x0 = max(0.0, self.x0 - d / 120 * 80 * self.spp)
            self.update()
        else:
            total = len(self.p.tracks) * self.track_h
            self.y0 = int(max(0, min(max(0, total - (self.height() - RULER_H)), self.y0 - d / 120 * 40)))
            self.update()

    # ---------------------------------------------------------------- clavier / commandes
    def target_tracks(self) -> list[str]:
        if self.sel_tracks:
            return [t.id for t in self.p.tracks if t.id in self.sel_tracks]
        if self.current_track:
            return [self.current_track]
        return [t.id for t in self.p.tracks]

    def cmd_split(self) -> None:
        at = self.s.cursor
        clips = [(tid, cid) for tid, cid in self.sel_clips] or [
            (t.id, c.id) for t in self.p.tracks if t.id in self.target_tracks() for c in t.clips if c.start < at < c.end]
        with self.p.edit("Scinder", *{tid for tid, _ in clips}):
            for tid, cid in clips:
                edits.split(self.p, tid, cid, at)
        self.update()

    def cmd_delete(self, ripple: bool = False) -> None:
        if self.sel:
            edits.delete_range(self.p, self.target_tracks(), *self.sel, ripple=ripple)
            self.sel = None
        elif self.sel_clips:
            tids = {tid for tid, _ in self.sel_clips}
            with self.p.edit("Supprimer les clips", *tids):
                for tid in tids:
                    t = self.p.track(tid)
                    t.clips = [c for c in t.clips if (tid, c.id) not in self.sel_clips]
                    t.midi_clips = [m for m in t.midi_clips if (tid, m.id) not in self.sel_clips]
            self.sel_clips.clear()
        self.update()

    def cmd_copy(self, cut: bool = False) -> None:
        if self.sel:
            self.clipboard = edits.copy_range(self.p, self.target_tracks(), *self.sel)
            if cut:
                self.cmd_delete()
        elif self.sel_clips:
            a = min(c.start for tid, cid in self.sel_clips for c in self.p.track(tid).clips if c.id == cid)
            b = max(c.end for tid, cid in self.sel_clips for c in self.p.track(tid).clips if c.id == cid)
            self.clipboard = edits.copy_range(self.p, sorted({tid for tid, _ in self.sel_clips}), a, b)
            if cut:
                self.cmd_delete()

    def cmd_paste(self) -> None:
        if not self.clipboard:
            return
        n = len(self.clipboard["tracks"])
        ids = [t.id for t in self.p.tracks]
        start = ids.index(self.current_track) if self.current_track in ids else 0
        edits.paste(self.p, self.clipboard, self.s.cursor, ids[start:start + n])
        self.update()

    def cmd_crop(self) -> None:
        if self.sel:
            edits.crop(self.p, self.target_tracks(), *self.sel)
            self.update()

    def keyPressEvent(self, e) -> None:
        k, mods = e.key(), e.modifiers()
        ctrl = bool(mods & Qt.ControlModifier)
        if k == Qt.Key_Escape:                  # annule : geste, puis sélection ; ne quitte JAMAIS le module
            if self._g is not None:
                if self._g["kind"] == "loop":
                    self.p.loop = {"on": False, "start": 0, "end": 0}
                self._g = None
            else:
                self.sel = None
                self.sel_clips.clear()
            self.update()
        elif k == Qt.Key_Space:
            self.s.toggle_play()
        elif k == Qt.Key_Home:
            self.s.seek(0)
            self.x0 = 0
            self.update()
        elif ctrl and k == Qt.Key_Z:
            self.p.history.undo()
        elif ctrl and k == Qt.Key_Y:
            self.p.history.redo()
        elif ctrl and k == Qt.Key_C:
            self.cmd_copy()
        elif ctrl and k == Qt.Key_X:
            self.cmd_copy(cut=True)
        elif ctrl and k == Qt.Key_V:
            self.cmd_paste()
        elif ctrl and k == Qt.Key_A:
            self.sel = (0, self.p.length_samples())
            self.sel_tracks = {t.id for t in self.p.tracks}
            self.update()
        elif k in (Qt.Key_Delete, Qt.Key_Backspace):
            self.cmd_delete(ripple=bool(mods & Qt.ShiftModifier))
        elif k == Qt.Key_S and not ctrl:
            self.cmd_split()
        elif k in (Qt.Key_Plus, Qt.Key_Equal):
            self.zoom(0.5)
        elif k == Qt.Key_Minus:
            self.zoom(2.0)
        elif k == Qt.Key_A and not ctrl:                 # couloir de volume de la piste courante (A)
            self.auto_target = None if self.auto_target else "gain_db"
            self.update()
        elif k == Qt.Key_L and not ctrl:
            lp = self.p.loop
            if self.sel:
                self.p.loop = {"on": True, "start": self.sel[0], "end": self.sel[1]}
            else:
                lp["on"] = not lp.get("on")
            self.s.schedule_reload()
            self.update()
        else:
            super().keyPressEvent(e)

    # ---------------------------------------------------------------- automation
    def _lane_rect(self, y: float) -> QRectF:
        return QRectF(HEADER_W, y + 16, self.width() - HEADER_W, self.track_h - 22)

    def _auto_value(self, lane_top: float, y: float) -> float:
        from . import automation
        h = self.track_h - 22
        return automation.from_norm(self.auto_target, 1 - (y - lane_top) / max(1, h))

    def _auto_points_px(self, t, y):
        from . import automation
        ln = automation.lane(t, self.auto_target) or {"points": []}
        r = self._lane_rect(y)
        tm = self.p.tempo_map() if ln.get("unit") == "tick" else None
        out = []
        for k, (pt, v) in enumerate(ln["points"]):
            s = tm.tick_to_sample(int(pt)) if tm else pt
            out.append((k, QPointF(self.x_of(s), r.top() + (1 - automation.to_norm(self.auto_target, v)) * r.height())))
        return out, r

    def _paint_auto(self, qp, t, y) -> None:
        from . import automation
        pts, r = self._auto_points_px(t, y)
        col = tok("dirty_border", "#e0a040")
        qp.setPen(QPen(col, 1.5))
        if pts:
            line = [QPointF(HEADER_W, pts[0][1].y())] + [p for _, p in pts] + [QPointF(self.width(), pts[-1][1].y())]
            for a, b in zip(line, line[1:]):
                qp.drawLine(a, b)
            qp.setBrush(col)
            for _, p in pts:
                qp.drawEllipse(p, 3.5, 3.5)
            qp.setBrush(Qt.NoBrush)
        else:
            base = r.top() + (1 - automation.to_norm(self.auto_target, getattr(t, self.auto_target, 0.0)
                                                    if not self.auto_target.startswith("fx") else 0.5)) * r.height()
            qp.setPen(QPen(col, 1, Qt.DashLine))
            qp.drawLine(QPointF(HEADER_W, base), QPointF(self.width(), base))
        qp.setPen(col)
        qp.drawText(QRectF(r.left() + 4, r.bottom() - 13, 260, 13), Qt.AlignLeft | Qt.AlignVCenter,
                    f"automation : {self.auto_target} (clic : point, Ctrl+glisser : déplacer, Alt+clic : supprimer)")

    def _auto_press(self, t, x, y, e, ctrl) -> bool:
        from . import automation
        i = self.p.tracks.index(t)
        ty = self.track_y(i)
        pts, r = self._auto_points_px(t, ty)
        if not r.contains(QPointF(x, y)):
            return False
        hit = next((k for k, p in pts if abs(p.x() - x) <= 6 and abs(p.y() - y) <= 6), None)
        if hit is not None and (e.modifiers() & Qt.AltModifier):
            automation.remove_point(self.p, t.id, self.auto_target, hit)
        elif hit is not None and ctrl:
            self._g = {"kind": "auto_move", "track": t.id, "index": hit, "y0": r.top()}
        elif hit is None:
            automation.add_point(self.p, t.id, self.auto_target, max(0, self.snap(self.sample_at(x))), self._auto_value(r.top(), y))
        self.update()
        return True